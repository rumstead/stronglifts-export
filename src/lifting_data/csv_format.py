from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Literal

from .hevy_csv import REQUIRED_COLUMNS as HEVY_REQUIRED_COLUMNS
from .hevy_csv import WEIGHT_COLUMNS as HEVY_WEIGHT_COLUMNS
from .strong_csv import REQUIRED_COLUMNS as STRONG_REQUIRED_COLUMNS

CsvFormat = Literal["auto", "strong", "hevy"]
ResolvedCsvFormat = Literal["strong", "hevy"]


def _matches_hevy(columns: set[str]) -> bool:
    return HEVY_REQUIRED_COLUMNS.issubset(columns) and bool(
        HEVY_WEIGHT_COLUMNS.intersection(columns)
    )


def detect_csv_format_from_columns(
    fieldnames: Iterable[str], requested_format: CsvFormat = "auto"
) -> ResolvedCsvFormat:
    columns = set(fieldnames)
    found = ", ".join(sorted(columns)) or "<none>"
    matches_strong = STRONG_REQUIRED_COLUMNS.issubset(columns)
    matches_hevy = _matches_hevy(columns)

    if requested_format == "strong":
        if not matches_strong:
            missing = ", ".join(sorted(STRONG_REQUIRED_COLUMNS.difference(columns)))
            raise ValueError(
                f"CSV does not match Strong format; missing: {missing}; found: {found}"
            )
        return "strong"

    if requested_format == "hevy":
        if not matches_hevy:
            missing = HEVY_REQUIRED_COLUMNS.difference(columns)
            details = ", ".join(sorted(missing)) or "weight_kg or weight_lbs"
            raise ValueError(
                f"CSV does not match Hevy format; missing: {details}; found: {found}"
            )
        return "hevy"

    if matches_strong == matches_hevy:
        reason = "ambiguous" if matches_strong else "unknown"
        raise ValueError(f"CSV format is {reason}; found headers: {found}")
    return "strong" if matches_strong else "hevy"


def detect_csv_format(
    csv_path: str, requested_format: CsvFormat = "auto"
) -> ResolvedCsvFormat:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        fieldnames = next(reader, [])
    return detect_csv_format_from_columns(fieldnames, requested_format)
