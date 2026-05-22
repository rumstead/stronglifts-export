from __future__ import annotations

from pathlib import Path

from lifting_data.charts import generate_exercise_progress_chart
from lifting_data.db import connect, init_db
from lifting_data.ingest import ingest_csv


def _write_chart_sample_csv(path: Path) -> None:
    path.write_text(
        "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
        "2026-05-01,Push Day,3600,Bench Press,1,100,5,,,8\n"
        "2026-05-02,Push Day,3600,Bench Press,1,105,4,,,9\n",
        encoding="utf-8",
    )


def test_generate_exercise_progress_chart_writes_html_and_returns_point_count(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_chart_sample_csv(csv_path)

    db_path = tmp_path / "lifts.db"
    connection = connect(str(db_path))
    init_db(connection)
    ingest_csv(connection, str(csv_path))

    full_chart = tmp_path / "output" / "bench-press.html"
    full_points = generate_exercise_progress_chart(
        connection,
        exercise_name="Bench Press",
        output_path=str(full_chart),
    )

    assert full_points == 2
    assert full_chart.exists()
    full_html = full_chart.read_text(encoding="utf-8").lower()
    assert "<html" in full_html
    assert "plotly" in full_html

    filtered_chart = tmp_path / "output" / "bench-press-filtered.html"
    filtered_points = generate_exercise_progress_chart(
        connection,
        exercise_name="Bench Press",
        output_path=str(filtered_chart),
        start_date="2026-05-02",
    )

    assert filtered_points == 1
    assert filtered_chart.exists()
