from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .strong_csv import parse_strong_csv


@dataclass(frozen=True)
class IngestResult:
    inserted: int
    skipped: int


def ingest_csv(connection: sqlite3.Connection, csv_path: str) -> IngestResult:
    inserted = 0
    skipped = 0
    source_file = Path(csv_path).name

    sql = """
    INSERT INTO sets (
        workout_date,
        workout_name,
        duration_seconds,
        exercise_name,
        set_order,
        weight,
        reps,
        distance,
        seconds,
        rpe,
        volume,
        estimated_1rm,
        source_file,
        dedupe_key
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    with connection:
        for item in parse_strong_csv(csv_path):
            try:
                connection.execute(
                    sql,
                    (
                        item.workout_date,
                        item.workout_name,
                        item.duration_seconds,
                        item.exercise_name,
                        item.set_order,
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
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1

    return IngestResult(inserted=inserted, skipped=skipped)
