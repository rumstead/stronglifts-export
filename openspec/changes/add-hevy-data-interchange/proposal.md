# Change: Add Hevy Export Ingestion

## Approved Scope
This change has two deliverables: generate one corrected Strong CSV for the initial Hevy migration, then support idempotent native Hevy export ingestion. Hevy becomes the source of truth after migration, and the local database is rebuilt from the first Hevy export. Persistent conversion tooling, legacy-row migration, canonical mixed-source storage, and cross-source reconciliation are excluded.

## Product Summary
Perform one non-destructive conversion of the current Strong history from pounds to kilogram-valued Strong CSV for Hevy's one-time import. After migration, treat native Hevy workout exports as the source of truth and ingest repeated Hevy exports idempotently.

## Why
Strong CSV exports label the load column only as `Weight`; they do not encode whether values are pounds or kilograms. Hevy can therefore interpret pound values as kilograms during its one-time Strong import. Native Hevy exports use a different snake_case schema and encode their weight unit in the column name, which the current parser rejects.

The attached `strong_workouts.csv` is structurally valid Strong data and is known by the user to contain pounds. If Hevy interprets that file as kilograms, a 60 lb set becomes 60 kg instead of approximately 27.2155 kg. Editing the numbers manually is unsafe, difficult to audit, and easy to repeat accidentally.

## Goals
- Generate one Hevy-importable copy of the attached Strong CSV without modifying the original.
- Preserve the Strong header, row count, column order, and all non-weight logical values.
- Detect Strong and Hevy workout exports by header signature, with an explicit format override.
- Support the unit-bearing `weight_kg` and `weight_lbs` Hevy variants.
- Preserve idempotent re-import behavior for overlapping cumulative Hevy exports.
- Support both local-file and existing email-attachment ingestion paths.
- Establish the first Hevy export as a clean database baseline.

## Non-Goals
- A permanent Strong-to-Hevy conversion command or general conversion framework.
- Cross-source Strong/Hevy deduplication.
- Migrating existing Strong database rows into a mixed-source canonical schema.
- Uploading data directly to Hevy or using the Hevy API.
- Importing a native Hevy export back into Hevy; Hevy accepts Strong-format imports, not its own workout export format.
- Migrating Hevy routines, measurements, profile data, or progress photos.

## User Flow
1. Generate `output/strong_workouts_for_hevy.csv`, converting only populated `Weight` values with $weight_{kg} = weight_{lb} \times 0.45359237$.
2. Verify row counts, source immutability, non-weight fields, and representative conversions.
3. Import the generated file through Hevy's `Import Strong CSV` flow and verify sample lifts.
4. Export all workouts from Hevy after migration.
5. Back up any existing local database and initialize a clean database from that first native Hevy export.
6. Ingest later cumulative Hevy exports; already-seen sets are skipped.

## Success Criteria
- The original Strong CSV remains byte-for-byte unchanged.
- The generated migration CSV preserves header, row count, column order, and non-weight logical values.
- Populated weights round-trip through converted kilograms within 0.01 lb.
- A representative generated file imports through Hevy's documented Strong CSV workflow and displays agreed sample weights correctly in pounds.
- Native Hevy fixtures using either `weight_kg` or `weight_lbs` ingest correctly.
- Re-importing identical or cumulative overlapping Hevy exports inserts only new sets.
- Invalid rows cause no partial database writes for their file.

## Rollout
1. Back up the original CSV and any existing SQLite database.
2. Generate and validate the one-time migration CSV.
3. Import it into Hevy and inspect representative lifts; revert the Hevy import if values are wrong.
4. Add local native Hevy parsing and idempotent ingestion.
5. Add Hevy email attachment detection after local-file tests pass.
6. Rebuild the local database from the first post-migration Hevy export.

## Confirmed Inputs
- The attached Strong export records its `Weight` values in pounds.
- The user's current Hevy import flow interprets those unitless `Weight` values as kilograms.
- The migration output must therefore convert populated weights from pounds to kilograms while retaining the Strong CSV schema.

## Open Questions
- Does a current Hevy export use `weight_kg` unconditionally or choose between `weight_kg` and `weight_lbs` based on account settings? The parser will support both signatures.

## What Changes
- Generate and validate one converted migration CSV in `output/`.
- Add Strong and Hevy format detection plus an explicit format override.
- Add a native Hevy CSV parser mapped into the existing set model.
- Add stable Hevy deduplication for cumulative exports.
- Update local and email ingestion, CLI help, documentation, and tests.

## Impact
- Affected specs: hevy-ingestion (new).
- Affected code: CSV parsing, ingestion orchestration, CLI, email header validation, tests, and README.
- Operational change: rebuild the local database from the first post-migration Hevy export before later Hevy imports.
- External dependency: Hevy's documented Strong import and workout CSV export formats.
