import os
from typing import Any

import elevation
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from dem_stitcher import stitch_dem
from general_fun import rounddown, roundup
from haversine import Unit, haversine_vector
from pandas.core.frame import DataFrame
from scipy import ndimage
from scipy.signal import savgol_filter
from stats_fun import compute_gpx_stats
from twonav_trk_fun import trk_to_geodataframe


def clean_gpx_track(
    gdf: gpd.GeoDataFrame,
    max_speed_mps: float = 5.0,
    elevation_window: int = 11,
    elevation_polyorder: int = 2,
) -> gpd.GeoDataFrame:
    """Remove GPS noise from a track and smooth its elevation profile.

    Drops duplicate timestamps, discards points implying a physically
    unrealistic speed (GPS jumps/teleports), then applies a Savitzky-Golay
    filter to the elevation column.

    Args:
        gdf: GeoDataFrame with "geometry", "time" and "elevation" columns.
        max_speed_mps: Points implying a higher speed than this (m/s) are dropped.
        elevation_window: Window length (points) for the elevation smoothing filter.
        elevation_polyorder: Polynomial order for the elevation smoothing filter.

    Returns:
        A cleaned copy of the GeoDataFrame with a reset index.
    """
    gdf = gdf.drop_duplicates(subset="time").reset_index(drop=True)

    coordinates = np.column_stack((gdf["geometry"].y.values, gdf["geometry"].x.values))
    distances_segment = np.zeros(len(gdf))
    distances_segment[1:] = haversine_vector(
        coordinates[:-1], coordinates[1:], unit=Unit.METERS
    )
    time_deltas = gdf["time"].diff().dt.total_seconds().to_numpy()

    with np.errstate(divide="ignore", invalid="ignore"):
        speed_mps = distances_segment / time_deltas
    speed_mps[0] = 0  # no previous point to compare the first row against

    gdf = gdf[speed_mps <= max_speed_mps].reset_index(drop=True)

    window = min(elevation_window, len(gdf) - (1 - len(gdf) % 2))
    if window >= elevation_polyorder + 1 and window % 2 == 1 and len(gdf) >= window:
        gdf["elevation"] = savgol_filter(
            gdf["elevation"].to_numpy(),
            window_length=window,
            polyorder=elevation_polyorder,
        )

    return gdf


def reduce_points_by_density(df: DataFrame, max_points_per_km: int) -> DataFrame:
    """Reduce GPX track points to respect a maximum density per kilometer.

    This function downsamples the track by keeping regularly spaced points so
    the overall number of samples does not exceed the requested density limit.

    Args:
        df: DataFrame containing GPX track points with a "distance" column in meters.
        max_points_per_km: Maximum allowed number of points per kilometer of track.

    Returns:
        A downsampled DataFrame that meets the desired point density, or the
        original DataFrame if no reduction is required.
    """
    total_km = df["distance"].iloc[-1] / 1000
    if total_km == 0:
        return df

    max_points = int(total_km * max_points_per_km)
    if len(df) <= max_points or max_points == 0:
        return df

    step = max(1, len(df) // max_points)
    return df.iloc[::step].reset_index(drop=True)


def calculate_distance(df: DataFrame, coordinates) -> tuple[DataFrame, np.ndarray]:
    distances_segment = np.zeros(len(df))
    distances_segment[1:] = haversine_vector(
        coordinates[:-1], coordinates[1:], unit=Unit.METERS
    )

    df["distance"] = np.cumsum(distances_segment)

    return df, distances_segment


def calculate_grade(
    df: DataFrame,
    distances_segment: np.ndarray,
    column_ele_name: str = "elevation",
    column_name: str = "grade",
) -> DataFrame:
    elev_diff = np.diff(df[column_ele_name], prepend=df[column_ele_name].iloc[0])
    with np.errstate(divide="ignore", invalid="ignore"):
        df[column_name] = np.where(
            distances_segment > 0, (elev_diff / distances_segment) * 100, 0
        )
    return df


def _add_time_distance_and_grade(df: DataFrame) -> DataFrame:

    if "lat" in df.columns and "lon" in df.columns:
        coordinates = df[["lat", "lon"]].to_numpy()

    if "geometry" in df.columns:
        coordinates = np.column_stack(
            (df["geometry"].y.values, df["geometry"].x.values)
        )

    df, distances_segment = calculate_distance(df, coordinates)

    df = calculate_grade(
        df, distances_segment, column_ele_name="elevation", column_name="grade"
    )

    df["duration"] = df["time"].diff().fillna(0)

    time_deltas = pd.to_datetime(df["time"]).diff().dt.total_seconds().fillna(0)
    df["duration_sec"] = np.where(time_deltas < 3600, time_deltas, 0)

    return df


def read_trk_file_add_additional_properties(
    gpx_filepath: str,
    max_speed_mps: float = 5.0,
    elevation_window: int = 11,
    elevation_polyorder: int = 2,
) -> tuple[DataFrame, dict[str, Any]]:

    gdf = trk_to_geodataframe(gpx_filepath)

    gdf = clean_gpx_track(
        gdf,
        max_speed_mps=max_speed_mps,
        elevation_window=elevation_window,
        elevation_polyorder=elevation_polyorder,
    )

    gdf = _add_time_distance_and_grade(gdf)

    stats = compute_gpx_stats(gdf)
    return gdf, stats


def get_bounds_from_gdf(
    gdf: gpd.GeoDataFrame, bound_value: float = 0.01
) -> tuple[float, float, float, float]:

    minx, miny, maxx, maxy = gdf.dissolve().bounds.loc[0]

    bounds = (
        rounddown(minx, bound_value) - bound_value,
        rounddown(miny, bound_value) - bound_value,
        roundup(maxx, bound_value) + bound_value,
        roundup(maxy, bound_value) + bound_value,
    )
    return bounds


def smooth_dem_model(dem_data):
    dem_array = dem_data.read(1)
    dem_array_float = dem_array.astype(float)

    dem_array_float = ndimage.gaussian_filter(dem_array_float, sigma=0.33)

    upscale_factor = 10

    dem_array_float = ndimage.zoom(dem_array_float, upscale_factor).round(decimals=1)

    transform = dem_data.transform * dem_data.transform.scale(
        (dem_data.width / dem_array_float.shape[-1]),
        (dem_data.height / dem_array_float.shape[-2]),
    )
    return dem_array_float, transform


def use_dem_model(
    gdf: gpd.GeoDataFrame,
    dem_model_tool_use: str = "dem_stitcher",
    dem_name: str = "glo_30",
    dem_folder: str = "dem",
) -> tuple[gpd.GeoDataFrame, np.ndarray]:

    bounds = get_bounds_from_gdf(gdf, bound_value=0.01)

    match dem_model_tool_use:
        case "elevation":
            elevation.clip(
                bounds=bounds, output=os.path.join(dem_folder, "dem_elevation.tif")
            )
            elevation.clean()

            dem_file_path = os.path.join(dem_folder, "dem_elevation.tif")

        case "dem_stitcher":
            # Global Copernicus 30 meter resolution DEM

            X, p = stitch_dem(
                bounds,
                dem_name=dem_name,  # Global Copernicus 30 meter resolution DEM
                dst_ellipsoidal_height=False,
                dst_area_or_point="Point",
            )
            with rasterio.open(
                os.path.join(dem_folder, f"dem_{dem_name}.tif"), "w", **p
            ) as ds:
                ds.write(X, 1)
                ds.update_tags(AREA_OR_POINT="Point")

            dem_file_path = os.path.join(dem_folder, f"dem_{dem_name}.tif")

    dem_data = rasterio.open(dem_file_path)

    dem_array, transform = smooth_dem_model(dem_data)

    gdf["elevation_dem"] = dem_array[
        rasterio.transform.rowcol(transform, gdf["geometry"].x, gdf["geometry"].y)
    ]

    coordinates = np.column_stack((gdf["geometry"].y.values, gdf["geometry"].x.values))

    _, distances_segment = calculate_distance(gdf, coordinates)

    gdf = calculate_grade(
        gdf, distances_segment, column_ele_name="elevation_dem", column_name="grade_dem"
    )
    return gdf, dem_array, transform
