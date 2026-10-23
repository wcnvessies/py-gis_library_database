"""twonav_trk.py

Reader/converter for TwoNav ``*.trk`` track files (as produced by TwoNav /
CompeGPS devices and apps, e.g. "TwoNav Aventura+").

The record format implemented here mirrors the reference implementation of
``TwoNavParser`` from the GPXSee project
(``GPXSee/src/data/twonavparser.cpp`` / ``twonavparser.h``), so that this
Python module reads exactly the records that GPXSee itself understands.

File format overview
--------------------
A ``.trk`` file is a plain text file, one record per line. Each line starts
with a single letter that identifies the record type:

``B``   Text encoding of the file (e.g. ``UTF-8``). Only present when the
        file does not start with a UTF-8 BOM.
``G``   Geodetic datum used for the coordinates (e.g. ``WGS 84``).
``U``   Coordinate system identifier. Must be ``1`` (geographic lat/lon).
``L``   UTC offset used by the recording device, e.g. ``-02:00:00``.
``P``   Recording program/device name and version (informational).
``Q``   Device serial number/identifier (informational).
``C``   Track colour/style (informational, vendor specific).
``V``   Vendor specific track flags (informational).
``E``   Vendor specific "activity/session" summary block (informational).
``X``   Vendor specific numeric block (informational).
``f``   Free-text field, e.g. the owner's e-mail address (informational).
``c``   Vendor specific key:value block (informational).
``z``   Track summary: bounding box, start/end unix timestamps, distance,
        min/max elevation, average/max speed (informational).
``m``   Track summary: max speed, activity id, activity name, etc.
        (informational).
``T``   A track point: fix type, latitude, longitude, date, time,
        (separator), elevation, plus additional vendor specific fields.
``x``   Extra per-trackpoint accuracy data following a ``T`` line
        (informational, ignored).
``W``   A waypoint (or, once a route has been started with an ``R`` record,
        a route point): name, fix type, latitude, longitude, date, time,
        elevation, description.
``w``   The symbol/icon name of the *last* waypoint read so far.
``R``   Starts a new route. All ``W`` records that follow (for the rest of
        the file) are added to the current route instead of the top level
        waypoint list.

Of these, only ``B``, ``G``, ``U``, ``T``, ``W``, ``w`` and ``R`` are
actually interpreted by GPXSee/this module; the rest are recorded as raw,
un-parsed metadata (see :attr:`TwoNavTrack.metadata`) because their exact
binary/vendor semantics are not required to reconstruct the geometry and
timestamps of the recorded track.

Timestamps
----------
Per the file's own documentation the date/time recorded in ``T`` and ``W``
records is UTC. Timestamps are therefore parsed as timezone-aware
``datetime`` objects with ``tzinfo=UTC``.

Coordinate reference system
----------------------------
Only the ``WGS 84`` datum with coordinate system ``1`` (plain geographic
latitude/longitude) is supported, which corresponds to ``EPSG:4326``. Files
using another datum raise :class:`NotImplementedError`, since reprojecting
other datums would require the same datum-transformation tables used
internally by GPXSee/CompeGPS.

Public API
----------
``parse_trk(path)``
    Parse a ``.trk`` file into a :class:`TwoNavTrack` container.
``trk_to_geodataframe(path, track_index=0)``
    Read a ``.trk`` file and return a ``geopandas.GeoDataFrame`` of the
    track points (``crs="EPSG:4326"``, UTC timestamps).
``trk_to_gpx(trk_path, gpx_path=None)``
    Convert a ``.trk`` file to a GPX 1.1 file.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

__all__ = [
    "Route",
    "TrackPoint",
    "TwoNavTrack",
    "Waypoint",
    "parse_trk",
    "trk_to_geodataframe",
    "trk_to_gpx",
]

# CRS of all coordinates produced by this module (WGS 84 lat/lon).
WGS84_CRS = "EPSG:4326"

# TwoNav uses the masculine ordinal indicator (U+00BA, "º") as the degree
# sign in coordinates, e.g. "68.20993412ºN".
_DEGREE_SIGN = "\u00ba"

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

_GPX_NS = "http://www.topografix.com/GPX/1/1"

PathLike = str | Path


# --------------------------------------------------------------------------
# Data containers
# --------------------------------------------------------------------------


@dataclass
class TrackPoint:
    """A single recorded track point ("T" record)."""

    lat: float
    lon: float
    timestamp: datetime | None = None
    elevation: float | None = None


@dataclass
class Waypoint:
    """A waypoint or route point ("W" record)."""

    lat: float
    lon: float
    name: str = ""
    timestamp: datetime | None = None
    elevation: float | None = None
    description: str = ""
    symbol: str | None = None


@dataclass
class Route:
    """A route ("R" record) made of an ordered list of :class:`Waypoint`."""

    name: str = ""
    points: list[Waypoint] = field(default_factory=list)


@dataclass
class TwoNavTrack:
    """Parsed contents of a TwoNav ``.trk`` file.

    ``tracks`` is a list of tracks, each a list of :class:`TrackPoint`
    (in practice a ``.trk`` file contains at most one track).
    """

    tracks: list[list[TrackPoint]] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    waypoints: list[Waypoint] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    source_file: str | None = None


# --------------------------------------------------------------------------
# Low level helpers
# --------------------------------------------------------------------------


def _parse_lat(token: str) -> float | None:
    if _DEGREE_SIGN not in token:
        return None
    value_str, _, hemisphere = token.partition(_DEGREE_SIGN)
    try:
        value = float(value_str)
    except ValueError:
        return None
    if hemisphere == "S":
        return -value
    if hemisphere == "N":
        return value
    return None


def _parse_lon(token: str) -> float | None:
    if _DEGREE_SIGN not in token:
        return None
    value_str, _, hemisphere = token.partition(_DEGREE_SIGN)
    try:
        value = float(value_str)
    except ValueError:
        return None
    if hemisphere == "W":
        return -value
    if hemisphere == "E":
        return value
    return None


def _parse_date(date_str: str) -> tuple[int, int, int] | None:
    """Parse a ``dd-MMM-yy`` or ``dd-MMM-yyyy`` date, English month names."""
    parts = date_str.split("-")
    if len(parts) != 3:
        return None
    day_str, mon_str, year_str = parts
    month = _MONTHS.get(mon_str.upper())
    if month is None:
        return None
    try:
        day = int(day_str)
        year = int(year_str)
    except ValueError:
        return None
    if len(year_str) == 2:
        # Matches the reference parser: a 2-digit year is parsed as
        # 19yy and then shifted forward by 100 years -> 20yy.
        year += 2000
    return year, month, day


def _parse_time(time_str: str) -> tuple[int, int, int, int] | None:
    """Parse a ``H:M:S`` or ``H:M:S.mmm`` time."""
    main, _, frac = time_str.partition(".")
    hms = main.split(":")
    if len(hms) != 3:
        return None
    try:
        hour, minute, second = (int(x) for x in hms)
        microsecond = int(frac.ljust(6, "0")[:6]) if frac else 0
    except ValueError:
        return None
    return hour, minute, second, microsecond


def parse_timestamp(date_str: str, time_str: str) -> datetime | None:
    """Parse a TwoNav ``date time`` pair into a UTC-aware ``datetime``.

    Returns ``None`` if either part cannot be parsed (matching the
    reference parser, which silently drops an unparsable timestamp instead
    of failing the whole file).
    """
    date_parts = _parse_date(date_str)
    time_parts = _parse_time(time_str)
    if date_parts is None or time_parts is None:
        return None
    year, month, day = date_parts
    hour, minute, second, microsecond = time_parts
    try:
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            tzinfo=UTC,
        )
    except ValueError:
        return None


def _parse_trackpoint(text: str, lineno: int) -> TrackPoint:
    # `text` includes the leading "T"; strip it before splitting fields.
    fields = text[1:].split()
    if len(fields) < 3:
        raise ValueError(f"Line {lineno}: malformed T (track point) record")

    lat = _parse_lat(fields[1])
    lon = _parse_lon(fields[2])
    if lat is None or lon is None:
        raise ValueError(f"Line {lineno}: invalid coordinates in T record")

    point = TrackPoint(lat=lat, lon=lon)

    if len(fields) > 4:
        point.timestamp = parse_timestamp(fields[3], fields[4])
    if len(fields) > 6:
        try:
            point.elevation = float(fields[6])
        except ValueError:
            raise ValueError(f"Line {lineno}: invalid elevation in T record")

    return point


def _parse_waypoint(text: str, lineno: int) -> Waypoint:
    # `text` includes the leading "W"; strip it before splitting fields.
    fields = text[1:].split()
    if len(fields) < 4:
        raise ValueError(f"Line {lineno}: malformed W (waypoint) record")

    name = fields[0].replace("_", " ").strip()
    lat = _parse_lat(fields[2])
    lon = _parse_lon(fields[3])
    if lat is None or lon is None:
        raise ValueError(f"Line {lineno}: invalid coordinates in W record")

    wpt = Waypoint(lat=lat, lon=lon, name=name)

    if len(fields) > 5:
        wpt.timestamp = parse_timestamp(fields[4], fields[5])
    if len(fields) > 6:
        try:
            wpt.elevation = float(fields[6])
        except ValueError:
            raise ValueError(f"Line {lineno}: invalid elevation in W record")
    if len(fields) > 7:
        wpt.description = " ".join(fields[7:])

    return wpt


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def parse_trk(path: PathLike) -> TwoNavTrack:
    """Parse a TwoNav ``.trk`` file and return a :class:`TwoNavTrack`.

    Raises ``ValueError`` for structurally invalid records and
    ``NotImplementedError`` for unsupported datums/coordinate systems.
    """
    path = Path(path)
    raw = path.read_bytes()

    encoding = "cp1252"
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
        encoding = "utf-8"

    result = TwoNavTrack(source_file=str(path))
    result.metadata["headers"] = defaultdict(list)
    in_route = False

    for lineno, raw_line in enumerate(raw.split(b"\n"), start=1):
        line = raw_line.strip(b"\r\n")
        if not line:
            continue

        tag = chr(line[0])

        if tag == "B":
            enc_name = line[1:].strip().decode("ascii", errors="replace")
            if enc_name == "UTF-8":
                encoding = "utf-8"
            else:
                raise ValueError(
                    f"Line {lineno}: invalid/unknown encoding {enc_name!r}"
                )
            continue

        text = line.decode(encoding, errors="replace")

        if tag == "G":
            datum = text[1:].strip()
            result.metadata["datum"] = datum
            if datum != "WGS 84":
                raise NotImplementedError(
                    f"Line {lineno}: datum {datum!r} is not supported "
                    "(only 'WGS 84' is implemented)"
                )
        elif tag == "U":
            coord_system = text[1:].strip()
            result.metadata["coordinate_system"] = coord_system
            if coord_system != "1":
                raise NotImplementedError(
                    f"Line {lineno}: unsupported coordinate system "
                    f"{coord_system!r} (only '1' is implemented)"
                )
        elif tag == "L":
            result.metadata["utc_offset"] = text[1:].strip()
        elif tag == "P":
            result.metadata["program"] = text[1:].strip()
        elif tag == "Q":
            result.metadata["device_id"] = text[1:].strip()
        elif tag == "T":
            point = _parse_trackpoint(text, lineno)
            if not result.tracks:
                result.tracks.append([])
            result.tracks[-1].append(point)
        elif tag == "W":
            wpt = _parse_waypoint(text, lineno)
            if in_route and result.routes:
                result.routes[-1].points.append(wpt)
            else:
                result.waypoints.append(wpt)
        elif tag == "w":
            symbol = text[1:].split(",", 1)[0].strip()
            # Matches the reference parser: the symbol always applies to
            # the last *top level* waypoint, even while inside a route.
            if result.waypoints:
                result.waypoints[-1].symbol = symbol
        elif tag == "R":
            parts = text[1:].split(",")
            route = Route(name=parts[0].strip() if parts and parts[0].strip() else "")
            result.routes.append(route)
            in_route = True
        else:
            # Informational/vendor-specific record: keep the raw line so
            # it can be inspected, but it is not otherwise interpreted.
            result.metadata["headers"][tag].append(text[1:].strip())

    if not (result.waypoints or result.routes or result.tracks):
        raise ValueError(f"{path}: no valid track, route or waypoint data found")

    return result


def trk_to_geodataframe(path: PathLike, track_index: int = 0) -> gpd.GeoDataFrame:
    """Read a ``.trk`` file's track points into a ``GeoDataFrame``.

    Parameters
    ----------
    path:
        Path to the ``.trk`` file.
    track_index:
        Which track to convert if the file contains more than one
        (defaults to the first/only track).

    Returns
    -------
    geopandas.GeoDataFrame
        One row per track point, with columns:

        - ``geometry``: ``shapely.Point(lon, lat)``
        - ``time``: timezone-aware UTC timestamp (``datetime64[ns, UTC]``)
        - ``elevation``: elevation in meters (``float``, may be ``NaN``)
        - ``seq``: 0-based point sequence number within the track

        The GeoDataFrame's CRS is set to ``EPSG:4326`` (WGS 84 lat/lon).
    """
    data = parse_trk(path)
    if not data.tracks:
        raise ValueError(f"{path}: no track data found")
    if track_index >= len(data.tracks):
        raise IndexError(
            f"track_index={track_index} out of range "
            f"(file has {len(data.tracks)} track(s))"
        )

    points = data.tracks[track_index]
    records = [
        {
            "geometry": Point(p.lon, p.lat),
            "time": p.timestamp,
            "elevation": p.elevation,
            "seq": i,
        }
        for i, p in enumerate(points)
    ]

    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=WGS84_CRS)
    gdf["time"] = pd.to_datetime(gdf["time"], utc=True)
    return gdf


def _element(tag: str, attrib: dict | None = None) -> ET.Element:
    return ET.Element(f"{{{_GPX_NS}}}{tag}", attrib or {})


def _sub_element(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, f"{{{_GPX_NS}}}{tag}")
    if text is not None:
        el.text = text
    return el


def _format_time(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _trackpoint_element(point: TrackPoint) -> ET.Element:
    el = _element("trkpt", {"lat": f"{point.lat:.8f}", "lon": f"{point.lon:.8f}"})
    if point.elevation is not None:
        _sub_element(el, "ele", f"{point.elevation}")
    if point.timestamp is not None:
        _sub_element(el, "time", _format_time(point.timestamp))
    return el


def _waypoint_element(tag: str, wpt: Waypoint) -> ET.Element:
    el = _element(tag, {"lat": f"{wpt.lat:.8f}", "lon": f"{wpt.lon:.8f}"})
    if wpt.elevation is not None:
        _sub_element(el, "ele", f"{wpt.elevation}")
    if wpt.timestamp is not None:
        _sub_element(el, "time", _format_time(wpt.timestamp))
    if wpt.name:
        _sub_element(el, "name", wpt.name)
    if wpt.description:
        _sub_element(el, "desc", wpt.description)
    if wpt.symbol:
        _sub_element(el, "sym", wpt.symbol)
    return el


def trk_to_gpx(trk_path: PathLike, gpx_path: PathLike | None = None) -> Path:
    """Convert a TwoNav ``.trk`` file to a GPX 1.1 file.

    Parameters
    ----------
    trk_path:
        Path to the source ``.trk`` file.
    gpx_path:
        Destination path. Defaults to ``trk_path`` with its suffix
        replaced by ``.gpx``.

    Returns
    -------
    pathlib.Path
        The path the GPX file was written to.
    """
    trk_path = Path(trk_path)
    data = parse_trk(trk_path)

    if gpx_path is None:
        gpx_path = trk_path.with_suffix(".gpx")
    gpx_path = Path(gpx_path)

    ET.register_namespace("", _GPX_NS)
    gpx = _element(
        "gpx",
        {"version": "1.1", "creator": "py-read_twonav_files (twonav_trk.py)"},
    )

    for wpt in data.waypoints:
        gpx.append(_waypoint_element("wpt", wpt))

    for route in data.routes:
        rte = _sub_element(gpx, "rte")
        if route.name:
            _sub_element(rte, "name", route.name)
        for wpt in route.points:
            rte.append(_waypoint_element("rtept", wpt))

    for track in data.tracks:
        trk = _sub_element(gpx, "trk")
        trkseg = _sub_element(trk, "trkseg")
        for point in track:
            trkseg.append(_trackpoint_element(point))

    tree = ET.ElementTree(gpx)
    ET.indent(tree, space="  ")
    tree.write(gpx_path, encoding="UTF-8", xml_declaration=True)
    return gpx_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert a TwoNav .trk file to GPX")
    parser.add_argument("trk_file", type=Path, help="Input .trk file")
    parser.add_argument(
        "-o", "--output", type=Path, default=None, help="Output .gpx file"
    )
    args = parser.parse_args()

    out_path = trk_to_gpx(args.trk_file, args.output)
    print(f"Wrote {out_path}")
