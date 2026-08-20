import gpxpy
import numpy as np
import pandas as pd
from haversine import Unit, haversine_vector

from .stats_fun import compute_gpx_stats


def _add_distance_and_grade(df):

    coords = df[["lat", "lon"]].to_numpy()

    distances_segment = np.zeros(len(df))
    distances_segment[1:] = haversine_vector(coords[:-1], coords[1:], unit=Unit.METERS)

    df["distance"] = np.cumsum(distances_segment)

    elev_diff = np.diff(df["ele"], prepend=df["ele"].iloc[0])
    with np.errstate(divide="ignore", invalid="ignore"):
        df["grade"] = np.where(
            distances_segment > 0, (elev_diff / distances_segment) * 100, 0
        )

    return df


def parse_gpx(gpx_filepath, max_points_per_km: int = 20):
    with open(gpx_filepath, 'r') as gpx_content:
        gpx = gpxpy.parse(gpx_content)

    data = []

    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                data.append(
                    {
                        "lat": point.latitude,
                        "lon": point.longitude,
                        "ele": point.elevation,
                        "time": point.time,
                    }
                )

    df = pd.DataFrame(data)
    if len(df) < 2:
        raise ValueError("GPX file too short")

    df = _add_distance_and_grade(df)

    df = reduce_points_by_density(df, max_points_per_km)

    df = _add_distance_and_grade(df)

    time_deltas = pd.to_datetime(df["time"]).diff().dt.total_seconds().fillna(0)
    df["duration_sec"] = np.where(time_deltas < 3600, time_deltas, 0)

    stats = compute_gpx_stats(df)
    return df, stats


def reduce_points_by_density(df, max_points_per_km: int = 20):
    total_km = df["distance"].iloc[-1] / 1000
    if total_km == 0:
        return df

    max_points = int(total_km * max_points_per_km)
    if len(df) <= max_points or max_points == 0:
        return df

    step = max(1, len(df) // max_points)
    return df.iloc[::step].reset_index(drop=True)
