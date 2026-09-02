from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .csv_format import CsvFormat, detect_csv_format
from .hevy_csv import parse_hevy_csv
from .strong_csv import parse_strong_csv


@dataclass(frozen=True)
class IngestResult:
    inserted: int
    skipped: int


def ingest_csv(
    connection: sqlite3.Connection,
    csv_path: str,
    csv_format: CsvFormat = "auto",
) -> IngestResult:
    inserted = 0
    skipped = 0
    source_file = Path(csv_path).name
    resolved_format = detect_csv_format(csv_path, csv_format)
    parser = parse_strong_csv if resolved_format == "strong" else parse_hevy_csv
    items = list(parser(csv_path))

    sql = """
    INSERT INTO sets (
        workout_date,
        workout_name,
        duration_seconds,
        exercise_name,
        set_order,
        set_type,
        weight,
        reps,
        distance,
        seconds,
        rpe,
        volume,
        estimated_1rm,
        source_file,
        dedupe_key
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(dedupe_key) DO NOTHING
    """

    with connection:
        for item in items:
            cursor = connection.execute(
                sql,
                (
                    item.workout_date,
                    item.workout_name,
                    item.duration_seconds,
                    item.exercise_name,
                    item.set_order,
                    getattr(item, "set_type", "normal"),
                    item.weight,
                    item.reps,
                    item.distance,
                    item.seconds,
                    item.rpe,
                    item.volume,
                    item.estimated_1rm,
                    source_file,
                    item.dedupe_key,
                ),
            )
            if cursor.rowcount == 1:
                inserted += 1
            else:
                skipped += 1

    return IngestResult(inserted=inserted, skipped=skipped)
