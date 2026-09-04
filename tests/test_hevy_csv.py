from __future__ import annotations

from pathlib import Path

import pytest

from lifting_data.csv_format import detect_csv_format
from lifting_data.db import connect, init_db
from lifting_data.hevy_csv import parse_hevy_csv
from lifting_data.ingest import ingest_csv


HEADER = (
    "title,start_time,end_time,description,exercise_title,superset_id,"
    "exercise_notes,set_index,set_type,weight_kg,weight_lbs,reps,"
    "distance_km,duration_seconds,rpe\n"
)


def test_parse_hevy_csv_converts_kg_to_lbs(tmp_path: Path) -> None:
    csv_path = tmp_path / "hevy.csv"
    csv_path.write_text(
        HEADER
        + 'Push Day,"20 Aug 2024, 19:10","20 Aug 2024, 20:10",,Bench Press,,,'
        "0,normal,100,,5,,,8\n",
        encoding="utf-8",
    )

    rows = list(parse_hevy_csv(str(csv_path)))

    assert len(rows) == 1
    assert rows[0].workout_date == "2024-08-20 19:10:00"
    assert rows[0].duration_seconds == 3600
    assert rows[0].set_order == 1
    assert rows[0].set_type == "normal"
    assert rows[0].weight == pytest.approx(220.46226218487757)
    assert rows[0].volume == pytest.approx(1102.3113109243879)


def test_parse_hevy_csv_preserves_lbs(tmp_path: Path) -> None:
    csv_path = tmp_path / "hevy.csv"
    csv_path.write_text(
        HEADER
        + "Push Day,2024-08-20T19:10:00Z,2024-08-20T20:10:00Z,,Bench Press,,,"
        "0,normal,,60,5,,,8\n",
        encoding="utf-8",
    )

    row = list(parse_hevy_csv(str(csv_path)))[0]

    assert row.weight == 60.0
    assert row.volume == 300.0


def test_parse_hevy_csv_converts_miles_to_km(tmp_path: Path) -> None:
    csv_path = tmp_path / "hevy.csv"
    csv_path.write_text(
        HEADER.replace("distance_km", "distance_miles")
        + "Cardio,2024-08-20 19:10,2024-08-20 20:10,,Running,,,"
        "0,normal,0,,0,1,,\n",
        encoding="utf-8",
    )

    row = list(parse_hevy_csv(str(csv_path)))[0]

    assert row.distance == pytest.approx(1.609344)


def test_parse_hevy_csv_rejects_populated_weight_units(tmp_path: Path) -> None:
    csv_path = tmp_path / "hevy.csv"
    csv_path.write_text(
        HEADER
        + "Push Day,2024-08-20 19:10,2024-08-20 20:10,,Bench Press,,,"
        "0,normal,27.2,60,5,,,8\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="both weight_kg and weight_lbs"):
        list(parse_hevy_csv(str(csv_path)))


def test_parse_hevy_csv_rejects_invalid_numeric_value(tmp_path: Path) -> None:
    csv_path = tmp_path / "hevy.csv"
    csv_path.write_text(
        HEADER
        + "Push Day,2024-08-20 19:10,2024-08-20 20:10,,Bench Press,,,"
        "0,normal,100,,five,,,8\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Row 2 has invalid reps"):
        list(parse_hevy_csv(str(csv_path)))


def test_detect_and_ingest_cumulative_hevy_exports(tmp_path: Path) -> None:
    first_path = tmp_path / "hevy-first.csv"
    first_path.write_text(
        HEADER
        + "Push Day,2024-08-20 19:10,2024-08-20 20:10,,Bench Press,,,"
        "0,warmup,20,,10,,,\n",
        encoding="utf-8",
    )
    cumulative_path = tmp_path / "hevy-cumulative.csv"
    cumulative_path.write_text(
        first_path.read_text(encoding="utf-8")
        + "Push Day,2024-08-20 19:10,2024-08-20 20:10,,Bench Press,,,"
        "1,normal,100,,5,,,8\n",
        encoding="utf-8",
    )
    connection = connect(str(tmp_path / "lifts.db"))
    init_db(connection)

    assert detect_csv_format(str(first_path)) == "hevy"
    first = ingest_csv(connection, str(first_path))
    cumulative = ingest_csv(connection, str(cumulative_path), csv_format="hevy")

    assert (first.inserted, first.skipped) == (1, 0)
    assert (cumulative.inserted, cumulative.skipped) == (1, 1)
    stored = connection.execute(
        "SELECT set_order, set_type FROM sets ORDER BY set_order"
    ).fetchall()
    assert [(row["set_order"], row["set_type"]) for row in stored] == [
        (1, "warmup"),
        (2, "normal"),
    ]


def test_hevy_ingest_is_atomic_when_later_row_is_invalid(tmp_path: Path) -> None:
    csv_path = tmp_path / "hevy.csv"
    csv_path.write_text(
        HEADER
        + "Push Day,2024-08-20 19:10,2024-08-20 20:10,,Bench Press,,,"
        "0,normal,100,,5,,,8\n"
        + "Push Day,2024-08-20 19:10,2024-08-20 20:10,,Bench Press,,,"
        "1,normal,105,,five,,,8\n",
        encoding="utf-8",
    )
    connection = connect(str(tmp_path / "lifts.db"))
    init_db(connection)

    with pytest.raises(ValueError, match="Row 3 has invalid reps"):
        ingest_csv(connection, str(csv_path))

    count = connection.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
    assert count == 0
