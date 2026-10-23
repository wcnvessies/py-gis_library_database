from climb_detector import get_color_from_palette


def draw_detailed_colored_profile(
    ax, df, climbs_df, descents_df, color_by_slope, show_markers, color_mode
) -> None:
    if color_mode == "Detailed Slope":
        for i in range(1, len(df)):
            x = df["distance"].iloc[i - 1 : i + 1] / 1000
            y = df["elevation"].iloc[i - 1 : i + 1]
            color = (
                get_color_from_palette(df["plot_grade"].iloc[i])
                if color_by_slope
                else "#999999"
            )
            ax.fill_between(x, 0, y, color=color, alpha=0.8)

    else:
        ax.fill_between(
            df["distance"] / 1000, 0, df["elevation"], color="#E0E0E0", alpha=0.6
        )

        for segment_df in [climbs_df, descents_df]:
            if segment_df is not None and not segment_df.empty:
                for _, row in segment_df.iterrows():
                    avg_slope_color = get_color_from_palette(row["avg_slope"])

                    segment_data = df.iloc[row["start_idx"] : row["end_idx"] + 1]

                    ax.fill_between(
                        segment_data["distance"] / 1000,
                        0,
                        segment_data["elevation"],
                        color=avg_slope_color,
                        alpha=0.9,
                    )

    if show_markers:
        for segment_df, color, label in [
            (climbs_df, "black", "climbs"),
            (descents_df, "blue", "descents"),
        ]:
            if segment_df is not None and not segment_df.empty:
                row = segment_df.iloc[0]
                style = "--" if color == "black" else ":"
                ax.axvline(
                    x=row["start_km"],
                    color=color,
                    linestyle=style,
                    alpha=0.6,
                    label=label,
                )
                ax.axvline(x=row["end_km"], color=color, linestyle=style, alpha=0.6)

                for _, row in segment_df.iloc[1:].iterrows():
                    ax.axvline(
                        x=row["start_km"], color=color, linestyle=style, alpha=0.6
                    )
                    ax.axvline(x=row["end_km"], color=color, linestyle=style, alpha=0.6)

        if (climbs_df is not None and not climbs_df.empty) or (
            descents_df is not None and not descents_df.empty
        ):
            ax.legend(loc="upper right")
