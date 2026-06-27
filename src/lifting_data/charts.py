from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _to_date(value: str) -> date:
    """Parse a workout date that may include a time component."""
    return date.fromisoformat(value.split("T")[0].split(" ")[0])


def _linear_trend(x_ordinals: list[int], y_values: list[float]) -> tuple[float, float] | None:
    n = len(x_ordinals)
    if n < 2:
        return None
    mean_x = sum(x_ordinals) / n
    mean_y = sum(y_values) / n
    denom = sum((x - mean_x) ** 2 for x in x_ordinals)
    if denom == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_ordinals, y_values)) / denom
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _compute_progress_overlays(
    dates: list[str],
    estimated: list[float | None],
) -> dict[str, object]:
    """Derive progressive-overload overlays from per-session best Est. 1RM.

    Every value here is computed across all sets in each session (the caller
    passes the session's strongest set, chosen from all sets via the 1RM
    formula). Produces a rolling-best (PR) envelope, new-PR markers, a linear
    trend line, and a short human-readable summary with stall detection.
    """
    overlay: dict[str, object] = {
        "pr_dates": [],
        "pr_envelope": [],
        "pr_marker_dates": [],
        "pr_marker_values": [],
        "trend_dates": [],
        "trend_values": [],
        "summary": "",
    }

    points = [(d, e) for d, e in zip(dates, estimated) if e is not None]
    if not points:
        return overlay

    # Rolling best (PR envelope) and the sessions that set a new all-time best.
    running_max: float | None = None
    for d, e in points:
        if running_max is None or e > running_max:
            running_max = e
            overlay["pr_marker_dates"].append(d)  # type: ignore[union-attr]
            overlay["pr_marker_values"].append(e)  # type: ignore[union-attr]
        overlay["pr_dates"].append(d)  # type: ignore[union-attr]
        overlay["pr_envelope"].append(running_max)  # type: ignore[union-attr]

    # Linear trend over the valid Est. 1RM points.
    ordinals = [_to_date(d).toordinal() for d, _ in points]
    values = [e for _, e in points]
    trend = _linear_trend(ordinals, values)

    direction = ""
    if trend is not None:
        slope, intercept = trend
        overlay["trend_dates"] = [points[0][0], points[-1][0]]
        overlay["trend_values"] = [
            slope * ordinals[0] + intercept,
            slope * ordinals[-1] + intercept,
        ]
        per_month = slope * 30.44
        if per_month > 0.1:
            direction = f"\u25b2 +{per_month:.1f}/mo"
        elif per_month < -0.1:
            direction = f"\u25bc {per_month:.1f}/mo"
        else:
            direction = "\u25ac holding steady"

    # Stall detection: days between the last PR and the most recent session.
    marker_dates = overlay["pr_marker_dates"]  # type: ignore[assignment]
    last_pr = _to_date(marker_dates[-1])  # type: ignore[index]
    last_session = _to_date(points[-1][0])
    days_since_pr = (last_session - last_pr).days
    stall = ""
    if len(points) >= 4 and days_since_pr >= 42:
        stall = f"  \u00b7  \u26a0 no new PR in {days_since_pr}d"

    summary_parts = [f"Best Est. 1RM {max(values):.0f}"]
    if direction:
        summary_parts.append(direction)
    overlay["summary"] = "   ".join(summary_parts) + stall
    return overlay


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

    overlay = _compute_progress_overlays(dates, top_estimated)

    figure = make_subplots(specs=[[{"secondary_y": True}]])
    # Raw per-session strength signal (best set of the day), de-emphasized.
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=top_estimated,
            mode="lines+markers",
            name="Est. 1RM (best set)",
            line={"color": "#9fb3c8", "width": 1},
            marker={"size": 5, "color": "#9fb3c8"},
        ),
        secondary_y=False,
    )
    # Best-to-date (PR) envelope: clean, monotonic "is it stepping up?" line.
    figure.add_trace(
        go.Scatter(
            x=overlay["pr_dates"],
            y=overlay["pr_envelope"],
            mode="lines",
            name="Best to date",
            line={"color": "#38a169", "width": 2, "shape": "hv"},
        ),
        secondary_y=False,
    )
    # Linear trend line: the headline direction.
    figure.add_trace(
        go.Scatter(
            x=overlay["trend_dates"],
            y=overlay["trend_values"],
            mode="lines",
            name="Trend",
            line={"color": "#2b6cb0", "width": 3, "dash": "dash"},
            hoverinfo="skip",
        ),
        secondary_y=False,
    )
    # Sessions that set a new all-time best.
    figure.add_trace(
        go.Scatter(
            x=overlay["pr_marker_dates"],
            y=overlay["pr_marker_values"],
            mode="markers",
            name="New PR",
            marker={"size": 11, "color": "#dd6b20", "symbol": "star", "line": {"color": "#fff", "width": 1}},
        ),
        secondary_y=False,
    )
    # Noisy single-set max; available via legend but hidden by default.
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=top_weights,
            mode="lines+markers",
            name="Top Weight",
            marker={"size": 6},
            visible="legendonly",
        ),
        secondary_y=False,
    )
    # Total volume across all sets; available via legend but hidden by default.
    figure.add_trace(
        go.Bar(x=dates, y=total_volumes, name="Total Volume", opacity=0.35, visible="legendonly"),
        secondary_y=True,
    )

    title_text = f"{exercise_name} Progress"
    if overlay["summary"]:
        title_text += f'<br><span style="font-size:13px;color:#4a5568">{overlay["summary"]}</span>'

    figure.update_layout(
        title=title_text,
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

    # Derive progressive-overload overlays (PR envelope, trend, summary) per exercise.
    for data in all_chart_data.values():
        data["overlay"] = _compute_progress_overlays(data["dates"], data["top_estimated"])

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

    mobile_breakpoint = 600
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
      padding: 12px;
      background: #fafafa;
    }}
    .controls {{
      max-width: 900px;
      margin: 0 auto 12px auto;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    select {{
      font-size: 16px;
      padding: 10px 12px;
      border-radius: 6px;
      border: 1px solid #ccc;
      flex: 1;
      min-width: 0;
      max-width: 500px;
    }}
    #chart {{
      max-width: 900px;
      margin: 0 auto;
      background: white;
      border-radius: 8px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      padding: 8px;
    }}
    @media (max-width: {mobile_breakpoint}px) {{
      body {{ padding: 8px; }}
      .controls {{
        flex-direction: column;
        align-items: stretch;
      }}
      select {{
        max-width: 100%;
        font-size: 18px;
        padding: 12px;
      }}
      #chart {{ padding: 4px; border-radius: 4px; }}
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
    const MOBILE_QUERY = window.matchMedia('(max-width: {mobile_breakpoint}px)');
    const chartData = {chart_data_json};
    const exerciseNames = {exercise_names_json};

    const select = document.getElementById('exercise-select');
    exerciseNames.forEach(function(name) {{
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    }});

    function getChartHeight() {{
      return Math.max(350, window.innerHeight - 150);
    }}

    function renderChart() {{
      const name = select.value;
      const data = chartData[name];
      if (!data) return;

      const isMobile = MOBILE_QUERY.matches;
      const overlay = data.overlay || {{}};

      // Raw per-session strength signal (best set of the day), de-emphasized.
      const traceEst = {{
        x: data.dates,
        y: data.top_estimated,
        mode: 'lines+markers',
        name: 'Est. 1RM (best set)',
        line: {{ color: '#9fb3c8', width: 1 }},
        marker: {{ size: 5, color: '#9fb3c8' }},
        yaxis: 'y'
      }};
      // Best-to-date (PR) envelope: a clean, monotonic "is it stepping up?" line.
      const tracePR = {{
        x: overlay.pr_dates || [],
        y: overlay.pr_envelope || [],
        mode: 'lines',
        name: 'Best to date',
        line: {{ color: '#38a169', width: 2, shape: 'hv' }},
        yaxis: 'y'
      }};
      // Linear trend line: the headline direction.
      const traceTrend = {{
        x: overlay.trend_dates || [],
        y: overlay.trend_values || [],
        mode: 'lines',
        name: 'Trend',
        line: {{ color: '#2b6cb0', width: 3, dash: 'dash' }},
        hoverinfo: 'skip',
        yaxis: 'y'
      }};
      // Sessions that set a new all-time best.
      const tracePRMarkers = {{
        x: overlay.pr_marker_dates || [],
        y: overlay.pr_marker_values || [],
        mode: 'markers',
        name: 'New PR',
        marker: {{ size: 11, color: '#dd6b20', symbol: 'star', line: {{ color: '#fff', width: 1 }} }},
        yaxis: 'y'
      }};
      // Noisy single-set max; available via legend but hidden by default.
      const traceWeight = {{
        x: data.dates,
        y: data.top_weights,
        mode: 'lines+markers',
        name: 'Top Weight',
        marker: {{ size: 6 }},
        visible: 'legendonly',
        yaxis: 'y'
      }};
      // Total volume across all sets; available via legend but hidden by default.
      const traceVolume = {{
        x: data.dates,
        y: data.total_volumes,
        type: 'bar',
        name: 'Total Volume',
        opacity: 0.35,
        visible: 'legendonly',
        yaxis: 'y2'
      }};

      const titleText = name + ' Progress'
        + (overlay.summary
            ? '<br><span style="font-size:' + (isMobile ? 11 : 13) + 'px;color:#4a5568">' + overlay.summary + '</span>'
            : '');

      const layout = {{
        title: {{ text: titleText, font: {{ size: isMobile ? 14 : 17 }} }},
        xaxis: {{
          title: isMobile ? '' : 'Workout Date',
          rangeselector: {{
            buttons: [
              {{ count: 1, label: '1M', step: 'month', stepmode: 'backward' }},
              {{ count: 3, label: '3M', step: 'month', stepmode: 'backward' }},
              {{ count: 6, label: '6M', step: 'month', stepmode: 'backward' }},
              {{ count: 1, label: '1Y', step: 'year', stepmode: 'backward' }},
              {{ step: 'all', label: 'All' }}
            ],
            font: {{ size: isMobile ? 11 : 13 }},
            y: 1.18
          }},
          rangeslider: {{ visible: true, thickness: isMobile ? 0.08 : 0.06 }}
        }},
        yaxis: {{ title: isMobile ? '' : 'Weight / Est. 1RM', side: 'left', fixedrange: true }},
        yaxis2: {{ title: isMobile ? '' : 'Volume', side: 'right', overlaying: 'y', fixedrange: true }},
        legend: {{
          orientation: isMobile ? 'h' : 'v',
          x: isMobile ? 0.5 : 0.01,
          y: isMobile ? -0.25 : 0.99,
          xanchor: isMobile ? 'center' : 'left',
          yanchor: isMobile ? 'top' : 'top'
        }},
        template: 'plotly_white',
        dragmode: 'pan',
        height: getChartHeight(),
        margin: {{ t: 95, b: isMobile ? 40 : 50, l: isMobile ? 40 : 60, r: isMobile ? 40 : 80 }}
      }};

      const config = {{
        scrollZoom: true,
        displayModeBar: !isMobile,
        responsive: true,
        modeBarButtonsToRemove: ['lasso2d', 'select2d']
      }};

      Plotly.react('chart', [traceEst, tracePR, traceTrend, tracePRMarkers, traceWeight, traceVolume], layout, config);
    }}

    // Re-render when crossing the mobile breakpoint or resizing
    MOBILE_QUERY.addEventListener('change', renderChart);
    window.addEventListener('resize', renderChart);

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
