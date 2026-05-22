# Change: Add Strong CSV Progress Pipeline

## Why
Strong does not provide a reliable background sync path, so progress tracking depends on CSV exports. We need a repeatable ingestion and visualization workflow that is safe to re-run and easy to host locally or on a homelab.

## What Changes
- Add a CSV ingestion capability for Strong exports.
- Add idempotent storage and deduplication requirements for repeated imports.
- Add visualization requirements for lift trends and progress metrics over time.
- Add a minimal automation workflow for command-line import and chart generation.

## Impact
- Affected specs: strong-ingestion, strong-visualization
- Affected code: new Python ingestion and chart generation tooling, storage schema, and documentation
