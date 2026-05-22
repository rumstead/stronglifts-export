from __future__ import annotations

import json
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


def generate_all_exercises_page(
    connection: sqlite3.Connection,
    output_path: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """Generate a single HTML page with a dropdown to select exercises.

    Exercises are ordered by most recent workout date (descending).
    Default drag mode is pan instead of zoom.
    """
    # Get exercises ordered by most recent data (respecting date filters)
    exercise_filters = ["(reps > 0 OR weight > 0)"]
    exercise_values: list[object] = []
    if start_date:
        exercise_filters.append("workout_date >= ?")
        exercise_values.append(start_date)
    if end_date:
        exercise_filters.append("workout_date <= ?")
        exercise_values.append(end_date)

    exercise_where = " AND ".join(exercise_filters)
    exercises_query = f"""
    SELECT exercise_name, MAX(workout_date) AS last_date
    FROM sets
    WHERE {exercise_where}
    GROUP BY exercise_name
    ORDER BY last_date DESC, exercise_name ASC
    """
    exercises = connection.execute(exercises_query, exercise_values).fetchall()
    if not exercises:
        raise ValueError("No exercise data found in the database")

    exercise_names = [row["exercise_name"] for row in exercises]

    # Build chart data for all exercises in a single query
    filters = ["(reps > 0 OR weight > 0)"]
    values: list[object] = []
    if start_date:
        filters.append("workout_date >= ?")
        values.append(start_date)
    if end_date:
        filters.append("workout_date <= ?")
        values.append(end_date)

    where_clause = " AND ".join(filters)
    query = f"""
    SELECT
      exercise_name,
      workout_date,
      MAX(weight) AS top_weight,
      MAX(estimated_1rm) AS top_estimated_1rm,
      SUM(volume) AS total_volume
    FROM sets
    WHERE {where_clause}
    GROUP BY exercise_name, workout_date
    ORDER BY exercise_name, workout_date
    """
    rows = connection.execute(query, values).fetchall()

    # Group rows by exercise, preserving the most-recent-first ordering
    all_chart_data: dict[str, dict] = {}
    for row in rows:
        name = row["exercise_name"]
        if name not in all_chart_data:
            all_chart_data[name] = {
                "dates": [],
                "top_weights": [],
                "top_estimated": [],
                "total_volumes": [],
            }
        all_chart_data[name]["dates"].append(row["workout_date"])
        all_chart_data[name]["top_weights"].append(row["top_weight"])
        all_chart_data[name]["top_estimated"].append(row["top_estimated_1rm"])
        all_chart_data[name]["total_volumes"].append(row["total_volume"])

    # Re-order to match the most-recent-first exercise ordering
    all_chart_data = {name: all_chart_data[name] for name in exercise_names if name in all_chart_data}

    if not all_chart_data:
        raise ValueError("No exercise data found for the selected date range")

    # Generate self-contained HTML with dropdown
    # Escape JSON for safe embedding in <script> tags
    def _json_default(obj: object) -> object:
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if hasattr(obj, "__float__"):
            return float(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    chart_data_json = json.dumps(all_chart_data, default=_json_default).replace("</", "<\\/").replace("<!--", "<\\!--")
    exercise_names_json = json.dumps(list(all_chart_data.keys()), default=_json_default).replace("</", "<\\/").replace("<!--", "<\\!--")

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lifting Progress</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0;
      padding: 20px;
      background: #fafafa;
    }}
    .controls {{
      max-width: 900px;
      margin: 0 auto 16px auto;
    }}
    select {{
      font-size: 16px;
      padding: 8px 12px;
      border-radius: 6px;
      border: 1px solid #ccc;
      min-width: 300px;
    }}
    #chart {{
      max-width: 900px;
      margin: 0 auto;
      background: white;
      border-radius: 8px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      padding: 10px;
    }}
  </style>
</head>
<body>
  <div class="controls">
    <label for="exercise-select">Exercise:</label>
    <select id="exercise-select" onchange="renderChart()">
    </select>
  </div>
  <div id="chart"></div>
  <script>
    var chartData = {chart_data_json};
    var exerciseNames = {exercise_names_json};

    var select = document.getElementById('exercise-select');
    exerciseNames.forEach(function(name) {{
      var opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    }});

    function renderChart() {{
      var name = select.value;
      var data = chartData[name];
      if (!data) return;

      var traceWeight = {{
        x: data.dates,
        y: data.top_weights,
        mode: 'lines+markers',
        name: 'Top Weight',
        yaxis: 'y'
      }};
      var trace1RM = {{
        x: data.dates,
        y: data.top_estimated,
        mode: 'lines+markers',
        name: 'Top Est. 1RM',
        yaxis: 'y'
      }};
      var traceVolume = {{
        x: data.dates,
        y: data.total_volumes,
        type: 'bar',
        name: 'Total Volume',
        opacity: 0.35,
        yaxis: 'y2'
      }};

      var layout = {{
        title: name + ' Progress',
        xaxis: {{ title: 'Workout Date' }},
        yaxis: {{ title: 'Weight / Estimated 1RM', side: 'left' }},
        yaxis2: {{ title: 'Volume', side: 'right', overlaying: 'y' }},
        legend: {{ title: {{ text: 'Metrics' }} }},
        template: 'plotly_white',
        dragmode: 'pan',
        margin: {{ t: 50, b: 50 }}
      }};

      var config = {{
        scrollZoom: true,
        displayModeBar: true,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
      }};

      Plotly.react('chart', [traceWeight, trace1RM, traceVolume], layout, config);
    }}

    // Render the first exercise on load
    if (exerciseNames.length > 0) {{
      renderChart();
    }}
  </script>
</body>
</html>"""

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html_content, encoding="utf-8")
    return len(all_chart_data)
