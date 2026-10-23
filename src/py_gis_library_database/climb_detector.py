import numpy as np
import pandas as pd


def get_color(grade) -> str:
    if grade >= 18:
        return "#8B0000"  # Dark Red
    elif grade >= 10:
        return "#FF8C00"  # Dark Orange
    elif grade >= 2:
        return "#FFFF00"  # Yellow
    elif grade >= 0:
        return "#ADFF2F"  # GreenYellow
    elif grade >= -2:
        return "#ADD8E6"  # LightBlue
    elif grade >= -10:
        return "#0000FF"  # Blue
    else:
        return "#00008B"  # Dark Blue


def get_color_from_palette(grade):

    palette = [
        "#0d0887",  # Morado/Azul oscuro (Bajada > 12%)
        "#0000FF",  # Azul (Bajada 6-12%)
        "#ADD8E6",  # Azul claro (Bajada 0-6%)
        "#E0E0E0",  # Gris claro (Llano -1% a 1%)
        "#FFFF00",  # Amarillo (Subida 1-4%)
        "#FFA500",  # Naranja (Subida 4-8%)
        "#FF4500",  # Rojo-Naranja (Subida 8-12%)
        "#B22222",  # Ladrillo (Subida 12-16%)
        "#8B0000",  # Rojo Oscuro (Subida > 16%)
    ]
    grade_bins = np.array([-15, -8, -3, -1, 1, 4, 8, 12, 20])
    idx = np.interp(grade, grade_bins, range(len(palette)))

    color_idx = round(idx)

    return palette[color_idx]


def apply_slope_smoothing(df, target_meters: int = 300):
    meters_per_point = df["distance"].iloc[-1] / len(df)

    if meters_per_point == 0:
        return df

    window = max(3, int(target_meters / meters_per_point))

    if window % 2 == 0:
        window += 1

    df["plot_grade"] = (
        df["grade"].rolling(window=window, center=True, min_periods=1).mean()
    )
    return df


def classify_climb_category(length_m, avg_slope) -> str:
    length_km = length_m / 1000
    if length_km >= 10 and avg_slope >= 6:
        return "Hors Catégorie"
    elif length_km >= 8 and avg_slope >= 5:
        return "Category 1"
    elif length_km >= 5 and avg_slope >= 4:
        return "Category 2"
    elif length_km >= 3 and avg_slope >= 3:
        return "Category 3"
    elif length_km >= 2 and avg_slope >= 3:
        return "Category 4"
    elif length_km >= 1 and avg_slope >= 2:
        return "Category 5"
    elif length_km >= 0.5 and avg_slope >= 1:
        return "Category 6"
    else:
        return "Uncategorized"


def detect_significant_segments(
    df,
    kind: str = "climb",
    start_threshold_slope: float = 2.0,
    end_threshold_slope: float = 1.0,
    max_pause_length_m: int = 200,
    max_pause_descent_m: int = 10,
):

    df = apply_slope_smoothing(df, target_meters=300)
    segments = []
    state = "SEARCHING"

    slope_sign = 1 if kind == "climb" else -1

    start_idx = 0
    current_segment_points = []

    for i in range(1, len(df)):
        point_data = df.iloc[i]
        slope = point_data["plot_grade"] * slope_sign
        elev_diff = (df["elevation"].iloc[i] - df["elevation"].iloc[i - 1]) * slope_sign
        dist_diff = point_data["distance"] - df["distance"].iloc[i - 1]

        if state == "SEARCHING":
            if slope >= start_threshold_slope:
                state = "IN_CLIMB"
                start_idx = i - 1
                current_segment_points = [
                    df.iloc[i - 1].to_dict(),
                    point_data.to_dict(),
                ]

        elif state == "IN_CLIMB":
            if slope < end_threshold_slope:
                state = "EVALUATING_PAUSE"
                pause_start_idx = i - 1
                pause_length = 0
                pause_descent = 0
            current_segment_points.append(point_data.to_dict())
        elif state == "EVALUATING_PAUSE":
            current_segment_points.append(point_data.to_dict())
            pause_length += dist_diff
            if elev_diff < 0:
                pause_descent += abs(elev_diff)

            if slope >= end_threshold_slope:
                state = "IN_CLIMB"

            elif (
                pause_length > max_pause_length_m or pause_descent > max_pause_descent_m
            ):
                final_segment_df = pd.DataFrame(
                    current_segment_points[: -(i - pause_start_idx)]
                )
                _validate_and_append_segment(
                    segments, final_segment_df, kind, start_idx
                )

                state = "SEARCHING"
                current_segment_points = []

    if state in ["IN_CLIMB", "EVALUATING_PAUSE"] and current_segment_points:
        _validate_and_append_segment(
            segments, pd.DataFrame(current_segment_points), kind, start_idx
        )

    return pd.DataFrame(segments)


def _validate_and_append_segment(
    segments_list,
    segment_df,
    kind,
    start_idx,
    min_gain: int = 20,
    min_length: int = 300,
) -> None:
    if segment_df.empty or len(segment_df) < 2:
        return

    length = segment_df["distance"].iloc[-1] - segment_df["distance"].iloc[0]

    if kind == "climb":
        gain = segment_df[segment_df["elevation"].diff() > 0]["elevation"].diff().sum()
    else:  # descent
        gain = abs(
            segment_df[segment_df["elevation"].diff() < 0]["elevation"].diff().sum()
        )

    if length > min_length and gain > min_gain:
        avg_slope = (gain / length) * 100 if length > 0 else 0
        end_idx = start_idx + len(segment_df) - 1

        segments_list.append(
            {
                "type": kind,
                "start_km": segment_df["distance"].iloc[0] / 1000,
                "end_km": segment_df["distance"].iloc[-1] / 1000,
                "elev_gain" if kind == "climb" else "elev_loss": gain,
                "length_m": length,
                "avg_slope": avg_slope if kind == "climb" else -avg_slope,
                "start_idx": start_idx,
                "end_idx": end_idx,
            }
        )
