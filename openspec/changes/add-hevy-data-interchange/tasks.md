## 1. One-Time Strong Migration
- [x] 1.1 Hash and inspect the attached Strong source before conversion.
- [x] 1.2 Generate `output/strong_workouts_for_hevy.csv`, converting populated pounds to kilograms with `Decimal`.
- [x] 1.3 Verify source immutability, headers, row counts, non-weight fields, and representative round-trip values.
- [x] 1.4 Manually import into Hevy and verify representative lifts.

## 2. Hevy Parsing
- [x] 2.1 Add format detection and `--format auto|strong|hevy`.
- [x] 2.2 Add a native Hevy parser supporting `weight_kg` and `weight_lbs` headers.
- [x] 2.3 Normalize Hevy timestamps, numeric values, optional fields, and stable dedupe keys.
- [x] 2.4 Parse a complete file before insertion so malformed exports are atomic.

## 3. Ingestion Surfaces
- [x] 3.1 Route local ingestion through the selected parser without changing existing Strong behavior.
- [x] 3.2 Generalize email attachment validation to accept Strong and Hevy signatures.
- [x] 3.3 Update CLI output and help text for supported formats.

## 4. Tests and Documentation
- [x] 4.1 Add fixtures for kilogram, pound, duplicate, cumulative, optional-column, and malformed Hevy exports.
- [x] 4.2 Add local and email dry-run regression tests.
- [x] 4.3 Document the clean Hevy database baseline, backup/rollback, and warning against mixing legacy Strong rows.
- [x] 4.4 Run focused tests, the complete pytest suite, and strict OpenSpec validation.
