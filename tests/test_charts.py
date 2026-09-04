from __future__ import annotations

from pathlib import Path

from lifting_data.charts import generate_all_exercises_page, generate_exercise_progress_chart
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
    assert "est. 1rm, lb" in full_html

    filtered_chart = tmp_path / "output" / "bench-press-filtered.html"
    filtered_points = generate_exercise_progress_chart(
        connection,
        exercise_name="Bench Press",
        output_path=str(filtered_chart),
        start_date="2026-05-02",
    )

    assert filtered_points == 1
    assert filtered_chart.exists()


def _write_multi_exercise_csv(path: Path) -> None:
    path.write_text(
        "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
        "2026-05-01,Push Day,3600,Bench Press,1,100,5,,,8\n"
        "2026-05-02,Push Day,3600,Bench Press,1,105,4,,,9\n"
        "2026-05-03,Pull Day,3600,Barbell Row,1,80,8,,,7\n"
        "2026-05-04,Pull Day,3600,Barbell Row,1,82.5,7,,,8\n"
        "2026-05-01,Leg Day,3600,Squat,1,0,0,,,\n",
        encoding="utf-8",
    )


def test_plot_all_creates_html_with_dropdown(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_multi_exercise_csv(csv_path)

    db_path = tmp_path / "lifts.db"
    connection = connect(str(db_path))
    init_db(connection)
    ingest_csv(connection, str(csv_path))

    output = tmp_path / "output" / "index.html"
    count = generate_all_exercises_page(connection, output_path=str(output))

    assert output.exists()
    html = output.read_text(encoding="utf-8")
    assert "exercise-select" in html
    assert "Bench Press" in html
    assert "Barbell Row" in html
    # Barbell Row has more recent data (05-04) than Bench Press (05-02),
    # so it should appear first in the JSON array
    assert html.index("Barbell Row") < html.index("Bench Press")
    assert count == 2  # Squat excluded (0 reps, 0 weight)


def test_plot_all_date_filter_limits_dataset(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_multi_exercise_csv(csv_path)

    db_path = tmp_path / "lifts.db"
    connection = connect(str(db_path))
    init_db(connection)
    ingest_csv(connection, str(csv_path))

    output = tmp_path / "output" / "filtered.html"
    count = generate_all_exercises_page(
        connection, output_path=str(output), start_date="2026-05-03"
    )

    assert output.exists()
    html = output.read_text(encoding="utf-8")
    # Only Barbell Row has data on or after 05-03
    assert "Barbell Row" in html
    assert "Bench Press" not in html
    assert count == 1


def test_plot_all_empty_date_range_raises(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_multi_exercise_csv(csv_path)

    db_path = tmp_path / "lifts.db"
    connection = connect(str(db_path))
    init_db(connection)
    ingest_csv(connection, str(csv_path))

    import pytest

    with pytest.raises(ValueError, match="No exercise data"):
        generate_all_exercises_page(
            connection,
            output_path=str(tmp_path / "empty.html"),
            start_date="2099-01-01",
        )
