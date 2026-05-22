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
    return float(value)


def _estimate_1rm(weight: float | None, reps: int | None) -> float | None:
    if weight is None or reps is None or reps <= 0:
        return None
    return weight * (1 + reps / 30.0)


def _build_dedupe_key(row: dict[str, str]) -> str:
    key_fields = [
        row.get("Date", "").strip(),
        row.get("Workout Name", "").strip(),
        row.get("Exercise Name", "").strip(),
        row.get("Set Order", "").strip(),
        row.get("Weight", "").strip(),
        row.get("Reps", "").strip(),
        row.get("Distance", "").strip(),
        row.get("Seconds", "").strip(),
        row.get("RPE", "").strip(),
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
            weight = _parse_float(row["Weight"])
            reps = _parse_int(row["Reps"])
            volume = weight * reps if weight is not None and reps is not None else None
            yield StrongSet(
                workout_date=row["Date"].strip(),
                workout_name=row["Workout Name"].strip(),
                duration_seconds=_parse_duration_seconds(row["Duration"]),
                exercise_name=row["Exercise Name"].strip(),
                set_order=_parse_int(row["Set Order"]) or 0,
                weight=weight,
                reps=reps,
                distance=_parse_float(row["Distance"]),
                seconds=_parse_float(row["Seconds"]),
                rpe=_parse_float(row["RPE"]),
                volume=volume,
                estimated_1rm=_estimate_1rm(weight, reps),
                dedupe_key=_build_dedupe_key(row),
            )
