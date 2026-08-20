def compute_gpx_stats(df):
    total_distance = df["distance"].iloc[-1]
    elev_diff = df["ele"].diff()

    gain = elev_diff[elev_diff > 0].sum()
    loss = -elev_diff[elev_diff < 0].sum()
    duration = df["duration_sec"]

    num_points = len(df)
    density_per_km = num_points / (total_distance / 1000)
    density_per_100m = num_points / (total_distance / 100)

    stats = {
        "total_distance_km": total_distance / 1000,
        "elevation_gain": gain,
        "elevation_loss": loss,
        "min_elevation": df["ele"].min(),
        "max_elevation": df["ele"].max(),
        "average_grade": df["grade"].mean(),
        "max_grade": df["grade"].max(),
        "moving_time_min": duration[duration < 300].sum() / 60,
        "total_time_min": duration.sum() / 60,
        "num_points": num_points,
        "point_density_km": density_per_km,
        "point_density_100m": density_per_100m,
        "precision_score": min(100.0, (density_per_km / 20) * 100),
    }

    return stats