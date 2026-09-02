from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from lifting_data.db import connect, init_db
from lifting_data import ingest as ingest_module
from lifting_data.ingest import ingest_csv
from lifting_data.strong_csv import _parse_duration_seconds, parse_strong_csv


def _write_sample_csv(path: Path) -> None:
    path.write_text(
        "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
        "2026-05-01,Push Day,3600,Bench Press,1,100,5,,,8\n"
        "2026-05-01,Push Day,3600,Bench Press,2,102.5,5,,,9\n",
        encoding="utf-8",
    )


def test_parse_strong_csv_derives_metrics(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_sample_csv(csv_path)

    rows = list(parse_strong_csv(str(csv_path)))

    assert len(rows) == 2
    assert rows[0].volume == 500.0
    assert rows[0].estimated_1rm is not None
    assert rows[0].dedupe_key


def test_ingest_is_duplicate_safe(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    _write_sample_csv(csv_path)

    db_path = tmp_path / "lifts.db"
    connection = connect(str(db_path))
    init_db(connection)

    first = ingest_csv(connection, str(csv_path))
    second = ingest_csv(connection, str(csv_path))

    assert first.inserted == 2
    assert first.skipped == 0
    assert second.inserted == 0
    assert second.skipped == 2

    count = connection.execute("SELECT COUNT(*) AS c FROM sets").fetchone()["c"]
    assert count == 2


def test_parse_duration_seconds_supports_human_readable_formats() -> None:
    assert _parse_duration_seconds("3600") == 3600
    assert _parse_duration_seconds("48m") == 2880
    assert _parse_duration_seconds("1h 5m") == 3900
    assert _parse_duration_seconds("42s") == 42


def test_parse_strong_csv_tolerates_non_numeric_set_order(tmp_path: Path) -> None:
    csv_path = tmp_path / "export.csv"
    csv_path.write_text(
        "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
        "2026-05-01,Push Day,48m,Bench Press,D,100,5,,,8\n",
        encoding="utf-8",
    )

    rows = list(parse_strong_csv(str(csv_path)))

    assert len(rows) == 1
    assert rows[0].set_order == 0
    assert rows[0].duration_seconds == 2880


def test_ingest_reraises_non_dedupe_integrity_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass(frozen=True)
    class FakeSet:
        workout_date: str
        workout_name: str | None
        duration_seconds: int
        exercise_name: str
        set_order: int
        weight: float
        reps: int
        distance: float | None
        seconds: float | None
        rpe: float | None
        volume: float
        estimated_1rm: float
        dedupe_key: str

    def fake_parse_strong_csv(_csv_path: str):
        yield FakeSet(
            workout_date="2026-05-01",
            workout_name=None,
            duration_seconds=3600,
            exercise_name="Bench Press",
            set_order=1,
            weight=100.0,
            reps=5,
            distance=None,
            seconds=None,
            rpe=8.0,
            volume=500.0,
            estimated_1rm=112.5,
            dedupe_key="bad-row",
        )

    monkeypatch.setattr(ingest_module, "parse_strong_csv", fake_parse_strong_csv)

    db_path = tmp_path / "lifts.db"
    connection = connect(str(db_path))
    init_db(connection)

    csv_path = tmp_path / "unused.csv"
    _write_sample_csv(csv_path)

    with pytest.raises(sqlite3.IntegrityError):
        ingest_module.ingest_csv(connection, str(csv_path))
