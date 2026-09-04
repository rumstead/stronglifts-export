from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path


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


def _build_exercise_payload(
    dates: list[str],
    top_weights: list[float | None],
    top_estimated: list[float | None],
    total_volumes: list[float | None],
    max_reps: list[int | None],
) -> dict[str, object]:
    """Build the per-exercise chart payload: raw series, PR progression, summary.

    The PR progression is the running max of the per-session best Est. 1RM.
    The summary is a short human-readable line with trend and stall detection.
    """
    pr_dates: list[str] = []
    pr_values: list[float] = []
    summary = ""

    points = [(d, e) for d, e in zip(dates, top_estimated) if e is not None]
    if points:
        # Running best (PR progression) and the sessions that set a new all-time best.
        running_max: float | None = None
        pr_marker_dates: list[str] = []
        for d, e in points:
            if running_max is None or e > running_max:
                running_max = e
                pr_marker_dates.append(d)
            pr_dates.append(d)
            pr_values.append(running_max)

        # Linear trend over the valid Est. 1RM points.
        ordinals = [_to_date(d).toordinal() for d, _ in points]
        values = [e for _, e in points]
        trend = _linear_trend(ordinals, values)

        direction = ""
        if trend is not None:
            slope, _intercept = trend
            per_month = slope * 30.44
            if per_month > 0.1:
                direction = f"\u25b2 +{per_month:.1f}/mo"
            elif per_month < -0.1:
                direction = f"\u25bc {per_month:.1f}/mo"
            else:
                direction = "\u25ac holding steady"

        # Stall detection: days between the last PR and the most recent session.
        days_since_pr = (_to_date(points[-1][0]) - _to_date(pr_marker_dates[-1])).days
        stall = ""
        if len(points) >= 4 and days_since_pr >= 42:
            stall = f"  \u00b7  \u26a0 no new PR in {days_since_pr}d"

        summary_parts = [f"Best Est. 1RM {max(values):.0f} lb"]
        if direction:
            summary_parts.append(direction)
        summary = "   ".join(summary_parts) + stall

    return {
        "dates": dates,
        "top_weights": top_weights,
        "top_estimated": top_estimated,
        "total_volumes": total_volumes,
        "max_reps": max_reps,
        "pr_dates": pr_dates,
        "pr_values": pr_values,
        "summary": summary,
    }


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lifting Progress</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0;
      padding: 12px;
      background: #fafafa;
    }
    .container { max-width: 720px; margin: 0 auto; }
    .controls { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
    select {
      font-size: 16px;
      padding: 10px 12px;
      border-radius: 6px;
      border: 1px solid #ccc;
      flex: 1;
      min-width: 0;
    }
    .summary { color: #4a5568; font-size: 14px; margin: 0 2px 10px; min-height: 1em; }
    .range-buttons { display: flex; gap: 6px; margin-bottom: 12px; }
    .range-buttons button {
      flex: 1;
      padding: 7px 0;
      font-size: 13px;
      border: 1px solid #ccc;
      background: #fff;
      border-radius: 6px;
      color: #4a5568;
    }
    .range-buttons button.active { background: #6b46c1; border-color: #6b46c1; color: #fff; }
    .card {
      background: #fff;
      border-radius: 8px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      padding: 10px 6px 2px;
      margin-bottom: 14px;
    }
    .card h3 { margin: 0 0 2px 8px; font-size: 15px; font-weight: 600; color: #1a202c; }
  </style>
</head>
<body>
  <div class="container">
    <div class="controls">
      <label for="exercise-select">Exercise:</label>
      <select id="exercise-select"></select>
    </div>
    <div class="summary" id="summary"></div>
    <div class="range-buttons" id="range-buttons">
      <button data-months="1">1M</button>
      <button data-months="3">3M</button>
      <button data-months="6">6M</button>
      <button data-months="12">1Y</button>
      <button data-months="0" class="active">All</button>
    </div>
    <div id="charts"></div>
  </div>
  <script>
    const chartData = __CHART_DATA__;
    const exerciseNames = __EXERCISE_NAMES__;

    const PURPLE = '#7c3aed';
    const GREEN = '#38a169';

    // One simple chart per metric, like the Strong app.
    const CHART_DEFS = [
      { title: 'Best Set (Est. 1RM, lb)', kind: 'line', x: d => d.dates, y: d => d.top_estimated },
      { title: 'Best Set (Max Weight, lb)', kind: 'line', x: d => d.dates, y: d => d.top_weights },
      { title: 'Total Volume (lb-reps)', kind: 'bar', x: d => d.dates, y: d => d.total_volumes },
      { title: 'PR Progression (as 1RM, lb)', kind: 'step', x: d => d.pr_dates, y: d => d.pr_values },
      { title: 'Max Consecutive Reps', kind: 'line', x: d => d.dates, y: d => d.max_reps }
    ];

    const select = document.getElementById('exercise-select');
    exerciseNames.forEach(function(name) {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    });
    select.addEventListener('change', renderCharts);

    // Build one card per chart.
    const chartsRoot = document.getElementById('charts');
    CHART_DEFS.forEach(function(def, i) {
      const card = document.createElement('div');
      card.className = 'card';
      const heading = document.createElement('h3');
      heading.textContent = def.title;
      card.appendChild(heading);
      const chartDiv = document.createElement('div');
      chartDiv.id = 'chart-' + i;
      card.appendChild(chartDiv);
      chartsRoot.appendChild(card);
    });

    // Global time-range toggle applied to every chart.
    let currentMonths = 0;
    const rangeButtons = document.querySelectorAll('#range-buttons button');
    rangeButtons.forEach(function(btn) {
      btn.addEventListener('click', function() {
        rangeButtons.forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        currentMonths = parseInt(btn.dataset.months, 10);
        renderCharts();
      });
    });

    function rangeCutoff() {
      if (!currentMonths) return null;
      const dt = new Date();
      dt.setMonth(dt.getMonth() - currentMonths);
      return dt.toISOString().slice(0, 10);
    }

    function filterXY(x, y, cutoff) {
      if (!cutoff) return [x, y];
      const fx = [], fy = [];
      for (let i = 0; i < x.length; i++) {
        if (x[i] >= cutoff) { fx.push(x[i]); fy.push(y[i]); }
      }
      return [fx, fy];
    }

    function makeTrace(kind, x, y) {
      if (kind === 'bar') {
        return {
          x: x, y: y, type: 'bar',
          marker: { color: PURPLE, opacity: 0.75 },
          hovertemplate: '%{x|%b %d, %Y}<br>%{y}<extra></extra>'
        };
      }
      if (kind === 'step') {
        return {
          x: x, y: y, mode: 'lines',
          line: { color: GREEN, width: 2, shape: 'hv' },
          hovertemplate: '%{x|%b %d, %Y}<br>%{y}<extra></extra>'
        };
      }
      return {
        x: x, y: y, mode: 'lines+markers',
        line: { color: PURPLE, width: 2 },
        marker: { size: 5, color: PURPLE },
        hovertemplate: '%{x|%b %d, %Y}<br>%{y}<extra></extra>'
      };
    }

    function baseLayout() {
      return {
        height: 230,
        margin: { t: 8, b: 32, l: 46, r: 10 },
        showlegend: false,
        xaxis: { fixedrange: true, tickfont: { size: 11 }, gridcolor: '#eee' },
        yaxis: { fixedrange: true, tickfont: { size: 11 }, gridcolor: '#eee' },
        plot_bgcolor: '#fff',
        paper_bgcolor: '#fff',
        bargap: 0.4
      };
    }

    const CONFIG = { displayModeBar: false, responsive: true };

    function renderCharts() {
      const data = chartData[select.value];
      if (!data) return;
      document.getElementById('summary').textContent = data.summary || '';
      const cutoff = rangeCutoff();
      CHART_DEFS.forEach(function(def, i) {
        const filtered = filterXY(def.x(data) || [], def.y(data) || [], cutoff);
        Plotly.react('chart-' + i, [makeTrace(def.kind, filtered[0], filtered[1])], baseLayout(), CONFIG);
      });
    }

    if (exerciseNames.length > 0) {
      renderCharts();
    }
  </script>
</body>
</html>"""


def _render_page(chart_data: dict[str, dict[str, object]], output_path: str) -> None:
    """Write the self-contained multi-chart HTML page for the given exercises."""

    def _json_default(obj: object) -> object:
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if hasattr(obj, "__float__"):
            return float(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    def _escape(payload: object) -> str:
        # Escape JSON for safe embedding in <script> tags
        return json.dumps(payload, default=_json_default).replace("</", "<\\/").replace("<!--", "<\\!--")

    html_content = _PAGE_TEMPLATE.replace("__CHART_DATA__", _escape(chart_data)).replace(
        "__EXERCISE_NAMES__", _escape(list(chart_data.keys()))
    )

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html_content, encoding="utf-8")


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
      SUM(volume) AS total_volume,
      MAX(reps) AS max_reps
    FROM sets
    WHERE {where_clause}
    GROUP BY workout_date
    ORDER BY workout_date
    """

    rows = connection.execute(query, values).fetchall()
    if not rows:
        raise ValueError(f"No data found for exercise: {exercise_name}")

    payload = _build_exercise_payload(
        [row["workout_date"] for row in rows],
        [row["top_weight"] for row in rows],
        [row["top_estimated_1rm"] for row in rows],
        [row["total_volume"] for row in rows],
        [row["max_reps"] for row in rows],
    )

    _render_page({exercise_name: payload}, output_path)
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
      SUM(volume) AS total_volume,
      MAX(reps) AS max_reps
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
                "max_reps": [],
            }
        all_chart_data[name]["dates"].append(row["workout_date"])
        all_chart_data[name]["top_weights"].append(row["top_weight"])
        all_chart_data[name]["top_estimated"].append(row["top_estimated_1rm"])
        all_chart_data[name]["total_volumes"].append(row["total_volume"])
        all_chart_data[name]["max_reps"].append(row["max_reps"])

    # Re-order to match the most-recent-first exercise ordering
    all_chart_data = {name: all_chart_data[name] for name in exercise_names if name in all_chart_data}

    if not all_chart_data:
        raise ValueError("No exercise data found for the selected date range")

    # Build per-exercise payloads (raw series, PR progression, summary).
    payloads = {
        name: _build_exercise_payload(
            data["dates"],
            data["top_weights"],
            data["top_estimated"],
            data["total_volumes"],
            data["max_reps"],
        )
        for name, data in all_chart_data.items()
    }

    _render_page(payloads, output_path)
    return len(payloads)
