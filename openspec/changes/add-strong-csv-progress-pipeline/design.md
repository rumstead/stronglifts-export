## Context
Strong exports workout data as CSV and does not provide a robust unattended sync. The implementation must therefore treat CSV files as the system boundary and prioritize safe repeated imports.

## Goals / Non-Goals
- Goals:
  - Provide reliable CSV ingestion for Strong exports.
  - Make re-imports idempotent.
  - Generate progress charts from stored data.
  - Keep deployment portable across local machine and homelab.
- Non-Goals:
  - Direct Strong API integration.
  - Real-time background sync from iPhone.
  - Multi-user authentication for initial release.

## Decisions
- Decision: Use Python for data ingestion and chart generation.
  - Alternatives considered: Node.js ETL stack; rejected for slower iteration for data tooling.
- Decision: Use SQLite as the first storage backend.
  - Alternatives considered: PostgreSQL; deferred to keep deployment simple.
- Decision: Use content-hash based uniqueness for set-level deduplication.
  - Alternatives considered: file-level dedupe only; rejected because users may upload combined exports.
- Decision: Generate standalone HTML charts using Plotly.
  - Alternatives considered: server-rendered charts only; rejected because static output is easier to share.

## Risks / Trade-offs
- Risk: CSV format drift from Strong updates.
  - Mitigation: validate required columns and fail with actionable errors.
- Risk: inferred duplicate keys may collide for rare edge cases.
  - Mitigation: include multiple fields in hash and keep raw rows for debugging.
- Risk: user-provided weight units may vary.
  - Mitigation: preserve source values and document assumptions.

## Migration Plan
1. Implement schema and ingest tooling.
2. Backfill from exported historical CSV files.
3. Generate baseline charts for core lifts.
4. Add optional scheduled runs around manual export drop-ins.

## Open Questions
- Should first-host deployment target be Talos homelab or local-only?
- Which metrics are highest priority for chart defaults beyond volume and estimated 1RM?
