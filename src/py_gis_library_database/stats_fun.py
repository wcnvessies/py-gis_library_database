from typing import Any

from pandas.core.frame import DataFrame
from pandas.core.series import Series


def _compute_elevation_gain_loss(df: DataFrame) -> tuple[float, float]:
    """Compute total elevation gain and loss from a GPX-derived dataframe.

    This helper analyzes the elevation series to separate positive and negative
    changes and aggregates them into overall ascent and descent values.

    Args:
        df: Dataframe containing at least an "ele" column with elevation values.

    Returns:
        A tuple with two floats: total elevation gain and total elevation loss.
    """
    elev_diff = df["elevation"].diff()
    gain = elev_diff[elev_diff > 0].sum()
    loss = -elev_diff[elev_diff < 0].sum()
    return gain, loss


def _compute_point_densities(
    num_points: int, total_distance: float
) -> tuple[float, float]:
    """Compute sampling point densities along the GPX track distance.

    This helper estimates how densely points are distributed by calculating
    counts per kilometer and per 100 meters.

    Args:
        num_points: Total number of recorded points in the track.
        total_distance: Total track distance in meters.

    Returns:
        A tuple containing the point density per kilometer and per 100 meters.
    """
    density_per_km = num_points / (total_distance / 1000)
    density_per_100m = num_points / (total_distance / 100)
    return density_per_km, density_per_100m


def _compute_total_distance_km(total_distance: float) -> float:
    """Convert a total track distance in meters to kilometers.

    This helper provides a convenient way to express GPX track length
    in kilometers for summary statistics and user-facing metrics.

    Args:
        total_distance: Total track distance in meters.

    Returns:
        The total track distance converted to kilometers.
    """
    return total_distance / 1000


def _compute_times_minutes(duration_series: Series) -> tuple[float, float]:
    """Compute moving and total time in minutes from a duration series.

    This helper derives both the actively moving time and overall elapsed time
    from per-point durations, returning them in a convenient minute-based form.

    Args:
        duration_series: Series of per-point durations in seconds.

    Returns:
        A tuple containing moving time in minutes and total time in minutes.
    """
    mask = duration_series < 300
    moving_time_min = duration_series[mask].sum() / 60
    total_time_min = duration_series.sum() / 60
    return moving_time_min, total_time_min


def _compute_precision_score(density_per_km: float) -> float:
    """Compute a precision score based on track point density per kilometer.

    This helper translates how densely points are sampled into a bounded
    quality score, making it easier to assess GPX recording reliability.

    Args:
        density_per_km: Number of recorded points per kilometer of track.

    Returns:
        A precision score between 0 and 100 representing sampling quality.
    """
    value = (density_per_km / 20) * 100
    return min(100.0, value)


def _build_stats_dict(
    df: DataFrame,
    total_distance: float,
    gain: float,
    loss: float,
    duration: Series,
    num_points: int,
    density_per_km: float,
    density_per_100m: float,
) -> dict[str, Any]:
    """Build a dictionary of summary statistics for a GPX-derived dataframe.

    This helper aggregates distance, elevation, timing, and density metrics
    into a single mapping that can be used for reporting or further analysis.

    Args:
        df: Dataframe containing track data such as distance, elevation and grade.
        total_distance: Total track distance in meters.
        gain: Total elevation gain in meters.
        loss: Total elevation loss in meters.
        duration: Series of per-point durations in seconds.
        num_points: Total number of recorded points in the track.
        density_per_km: Number of recorded points per kilometer.
        density_per_100m: Number of recorded points per 100 meters.

    Returns:
        A dictionary with computed summary statistics for the GPX track.
    """
    tdk = _compute_total_distance_km(total_distance)
    mtm, ttm = _compute_times_minutes(duration)
    p_score = _compute_precision_score(density_per_km)

    return {
        "total_distance_km": tdk,
        "elevation_gain": gain,
        "elevation_loss": loss,
        "min_elevation": df["elevation"].min(),
        "max_elevation": df["elevation"].max(),
        "average_grade": df["grade"].mean(),
        "max_grade": df["grade"].max(),
        "moving_time_min": mtm,
        "total_time_min": ttm,
        "num_points": num_points,
        "point_density_km": density_per_km,
        "point_density_100m": density_per_100m,
        "precision_score": p_score,
    }


def compute_gpx_stats(df: DataFrame) -> dict[str, Any]:
    """Compute summary statistics for a GPX-derived track dataframe.

    This function consolidates distance, elevation, timing, and sampling
    density information into a single, easy-to-use statistics dictionary.

    Args:
        df: Dataframe containing GPX track data, including distance, elevation,
            grade, and per-point duration columns.

    Returns:
        A dictionary with aggregated statistics describing the GPX track.
    """
    total_distance = df["distance"].iloc[-1]
    gain, loss = _compute_elevation_gain_loss(df)
    duration = df["duration_sec"]

    num_points = len(df)
    density_per_km, density_per_100m = _compute_point_densities(
        num_points, total_distance
    )

    return _build_stats_dict(
        df=df,
        total_distance=total_distance,
        gain=gain,
        loss=loss,
        duration=duration,
        num_points=num_points,
        density_per_km=density_per_km,
        density_per_100m=density_per_100m,
    )
