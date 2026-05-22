from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REQUIRED_COLUMNS = {
    "Date",
    "Workout Name",
    "Duration",
    "Exercise Name",
    "Set Order",
    "Weight",
    "Reps",
    "Distance",
    "Seconds",
    "RPE",
}


@dataclass(frozen=True)
class StrongSet:
    workout_date: str
    workout_name: str
    duration_seconds: int | None
    exercise_name: str
    set_order: int
    weight: float | None
    reps: int | None
    distance: float | None
    seconds: float | None
    rpe: float | None
    volume: float | None
    estimated_1rm: float | None
    dedupe_key: str


def _parse_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _parse_duration_seconds(value: str) -> int | None:
    raw = value.strip().lower()
    if not raw:
        return None

    # Supports numeric seconds and human-readable strings like "48m", "1h 05m", "42s".
    try:
        return int(float(raw))
    except ValueError:
        pass

    total = 0
    matched = False
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", raw):
        matched = True
        number = float(amount)
        if unit == "h":
            total += int(number * 3600)
        elif unit == "m":
            total += int(number * 60)
        elif unit == "s":
            total += int(number)

    if matched:
        return total

    raise ValueError(f"Unsupported duration format: {value}")


def _parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _estimate_1rm(weight: float | None, reps: int | None) -> float | None:
    if weight is None or reps is None or reps <= 0:
        return None
    return weight * (1 + reps / 30.0)


def _cell(row: dict[str, str | None], key: str) -> str:
    """Return a stripped string, treating missing/None cells as empty."""
    return (row.get(key) or "").strip()


def _canonical_num(value: int | float | None) -> str:
    """Canonical string representation of a parsed numeric value."""
    if value is None:
        return ""
    return repr(value)


def _build_dedupe_key(
    workout_date: str,
    workout_name: str,
    exercise_name: str,
    set_order: int,
    weight: float | None,
    reps: int | None,
    distance: float | None,
    seconds: float | None,
    rpe: float | None,
) -> str:
    key_fields = [
        workout_date,
        workout_name,
        exercise_name,
        str(set_order),
        _canonical_num(weight),
        _canonical_num(reps),
        _canonical_num(distance),
        _canonical_num(seconds),
        _canonical_num(rpe),
    ]
    payload = "|".join(key_fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_strong_csv(csv_path: str) -> Iterable[StrongSet]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS.difference(columns)
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(f"Missing required columns: {missing_list}")

        for row in reader:
            workout_date = _cell(row, "Date")
            workout_name = _cell(row, "Workout Name")
            exercise_name = _cell(row, "Exercise Name")
            if not workout_date or not workout_name or not exercise_name:
                raise ValueError(
                    f"Row is missing required string fields: {dict(row)!r}"
                )
            set_order = _parse_int(_cell(row, "Set Order")) or 0
            weight = _parse_float(_cell(row, "Weight"))
            reps = _parse_int(_cell(row, "Reps"))
            distance = _parse_float(_cell(row, "Distance"))
            seconds = _parse_float(_cell(row, "Seconds"))
            rpe = _parse_float(_cell(row, "RPE"))
            volume = weight * reps if weight is not None and reps is not None else None
            yield StrongSet(
                workout_date=workout_date,
                workout_name=workout_name,
                duration_seconds=_parse_duration_seconds(_cell(row, "Duration")),
                exercise_name=exercise_name,
                set_order=set_order,
                weight=weight,
                reps=reps,
                distance=distance,
                seconds=seconds,
                rpe=rpe,
                volume=volume,
                estimated_1rm=_estimate_1rm(weight, reps),
                dedupe_key=_build_dedupe_key(
                    workout_date=workout_date,
                    workout_name=workout_name,
                    exercise_name=exercise_name,
                    set_order=set_order,
                    weight=weight,
                    reps=reps,
                    distance=distance,
                    seconds=seconds,
                    rpe=rpe,
                ),
            )
