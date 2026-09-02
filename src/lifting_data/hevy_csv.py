from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

REQUIRED_COLUMNS = {
    "title",
    "start_time",
    "exercise_title",
    "set_index",
    "set_type",
    "reps",
}
WEIGHT_COLUMNS = {"weight_kg", "weight_lbs"}
LB_TO_KG = Decimal("0.45359237")
MILES_TO_KM = Decimal("1.609344")


@dataclass(frozen=True)
class HevySet:
    workout_date: str
    workout_name: str
    duration_seconds: int | None
    exercise_name: str
    set_order: int
    set_type: str
    weight: float | None
    reps: int | None
    distance: float | None
    seconds: float | None
    rpe: float | None
    volume: float | None
    estimated_1rm: float | None
    dedupe_key: str


def _cell(row: dict[str, str | None], key: str) -> str:
    return (row.get(key) or "").strip()


def _parse_decimal(value: str, field: str, row_number: int) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(
            f"Row {row_number} has invalid {field} value: {value!r}"
        ) from exc


def _parse_float(value: str, field: str, row_number: int) -> float | None:
    parsed = _parse_decimal(value, field, row_number)
    return float(parsed) if parsed is not None else None


def _parse_int(value: str, field: str, row_number: int) -> int | None:
    parsed = _parse_decimal(value, field, row_number)
    if parsed is None:
        return None
    if parsed != parsed.to_integral_value():
        raise ValueError(f"Row {row_number} has non-integer {field} value: {value!r}")
    return int(parsed)


def _parse_timestamp(value: str, field: str, row_number: int) -> datetime:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Row {row_number} is missing required field: {field}")

    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        pass

    for date_format in ("%d %b %Y, %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(normalized, date_format)
        except ValueError:
            continue

    raise ValueError(
        f"Row {row_number} has unsupported {field} value: {value!r}"
    )


def _canonical_num(value: int | float | None) -> str:
    return "" if value is None else repr(value)


def _build_dedupe_key(
    workout_date: str,
    workout_name: str,
    exercise_name: str,
    set_order: int,
    set_type: str,
    weight: float | None,
    reps: int | None,
    distance: float | None,
    seconds: float | None,
    rpe: float | None,
) -> str:
    fields = [
        workout_date,
        workout_name,
        exercise_name,
        str(set_order),
        set_type,
        _canonical_num(weight),
        _canonical_num(reps),
        _canonical_num(distance),
        _canonical_num(seconds),
        _canonical_num(rpe),
    ]
    return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()


def _weight_kg(row: dict[str, str | None], row_number: int) -> float | None:
    weight_kg = _parse_decimal(_cell(row, "weight_kg"), "weight_kg", row_number)
    weight_lbs = _parse_decimal(
        _cell(row, "weight_lbs"), "weight_lbs", row_number
    )
    if weight_kg is not None and weight_lbs is not None:
        raise ValueError(
            f"Row {row_number} populates both weight_kg and weight_lbs"
        )
    if weight_kg is not None:
        return float(weight_kg)
    if weight_lbs is not None:
        return float(weight_lbs * LB_TO_KG)
    return None


def _distance_km(row: dict[str, str | None], row_number: int) -> float | None:
    distance_km = _parse_decimal(
        _cell(row, "distance_km"), "distance_km", row_number
    )
    distance_miles = _parse_decimal(
        _cell(row, "distance_miles"), "distance_miles", row_number
    )
    if distance_km is not None and distance_miles is not None:
        raise ValueError(
            f"Row {row_number} populates both distance_km and distance_miles"
        )
    if distance_km is not None:
        return float(distance_km)
    if distance_miles is not None:
        return float(distance_miles * MILES_TO_KM)
    return None


def parse_hevy_csv(csv_path: str) -> Iterable[HevySet]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS.difference(columns)
        if missing:
            raise ValueError(
                f"Missing required Hevy columns: {', '.join(sorted(missing))}"
            )
        if not WEIGHT_COLUMNS.intersection(columns):
            raise ValueError("Missing required Hevy weight column: weight_kg or weight_lbs")

        for row_number, row in enumerate(reader, start=2):
            workout_name = _cell(row, "title")
            exercise_name = _cell(row, "exercise_title")
            if not workout_name or not exercise_name:
                raise ValueError(
                    f"Row {row_number} is missing title or exercise_title"
                )

            start_time = _parse_timestamp(
                _cell(row, "start_time"), "start_time", row_number
            )
            end_value = _cell(row, "end_time")
            end_time = (
                _parse_timestamp(end_value, "end_time", row_number)
                if end_value
                else None
            )
            duration_seconds = (
                int((end_time - start_time).total_seconds())
                if end_time is not None
                else None
            )
            if duration_seconds is not None and duration_seconds < 0:
                raise ValueError(f"Row {row_number} has end_time before start_time")

            set_index = _parse_int(_cell(row, "set_index"), "set_index", row_number)
            if set_index is None or set_index < 0:
                raise ValueError(f"Row {row_number} has invalid set_index")
            set_order = set_index + 1
            set_type = _cell(row, "set_type") or "normal"
            weight = _weight_kg(row, row_number)
            reps = _parse_int(_cell(row, "reps"), "reps", row_number)
            distance = _distance_km(row, row_number)
            seconds = _parse_float(
                _cell(row, "duration_seconds"), "duration_seconds", row_number
            )
            rpe = _parse_float(_cell(row, "rpe"), "rpe", row_number)
            volume = weight * reps if weight is not None and reps is not None else None
            estimated_1rm = (
                weight * (1 + reps / 30.0)
                if weight is not None and reps is not None and reps > 0
                else None
            )
            workout_date = start_time.strftime("%Y-%m-%d %H:%M:%S")

            yield HevySet(
                workout_date=workout_date,
                workout_name=workout_name,
                duration_seconds=duration_seconds,
                exercise_name=exercise_name,
                set_order=set_order,
                set_type=set_type,
                weight=weight,
                reps=reps,
                distance=distance,
                seconds=seconds,
                rpe=rpe,
                volume=volume,
                estimated_1rm=estimated_1rm,
                dedupe_key=_build_dedupe_key(
                    workout_date,
                    workout_name,
                    exercise_name,
                    set_order,
                    set_type,
                    weight,
                    reps,
                    distance,
                    seconds,
                    rpe,
                ),
            )
