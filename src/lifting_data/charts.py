from __future__ import annotations

import sqlite3
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def generate_exercise_progress_chart(
    connection: sqlite3.Connection,
    exercise_name: str,
    output_path: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    filters = ["exercise_name = ?"]
    values: list[object] = [exercise_name]

    if start_date:
        filters.append("workout_date >= ?")
        values.append(start_date)
    if end_date:
        filters.append("workout_date <= ?")
        values.append(end_date)

    where_clause = " AND ".join(filters)

    query = f"""
    SELECT
      workout_date,
      MAX(weight) AS top_weight,
      MAX(estimated_1rm) AS top_estimated_1rm,
      SUM(volume) AS total_volume
    FROM sets
    WHERE {where_clause}
    GROUP BY workout_date
    ORDER BY workout_date
    """

    rows = connection.execute(query, values).fetchall()
    if not rows:
        raise ValueError(f"No data found for exercise: {exercise_name}")

    dates = [row["workout_date"] for row in rows]
    top_weights = [row["top_weight"] for row in rows]
    top_estimated = [row["top_estimated_1rm"] for row in rows]
    total_volumes = [row["total_volume"] for row in rows]

    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(
        go.Scatter(x=dates, y=top_weights, mode="lines+markers", name="Top Weight"),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(x=dates, y=top_estimated, mode="lines+markers", name="Top Est. 1RM"),
        secondary_y=False,
    )
    figure.add_trace(
        go.Bar(x=dates, y=total_volumes, name="Total Volume", opacity=0.35),
        secondary_y=True,
    )

    figure.update_layout(
        title=f"{exercise_name} Progress",
        xaxis_title="Workout Date",
        yaxis_title="Weight",
        legend_title="Metrics",
        template="plotly_white",
    )
    figure.update_yaxes(title_text="Weight / Estimated 1RM", secondary_y=False)
    figure.update_yaxes(title_text="Volume", secondary_y=True)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(str(destination), include_plotlyjs="cdn", full_html=True)
    return len(rows)
