# Project Context

## Purpose
Provide a reliable local pipeline for ingesting Strong workout CSV exports, deduplicating set records in SQLite, and generating progress charts as shareable HTML output.

## Tech Stack
- Python 3.11+
- SQLite
- Plotly
- Pytest
- GitHub Actions
- Docker/Podman for container build and publish

## Project Conventions

### Code Style
- Prefer clear, small functions and dataclasses for value objects/results.
- Keep modules focused by responsibility: parsing, ingestion, charting, email ingestion, CLI.
- Use type hints consistently and keep APIs simple.
- Favor explicit behavior over magic defaults; validate and fail loudly on invalid state.

### Architecture Patterns
- CLI entrypoint in `src/lifting_data/cli.py` orchestrates operations.
- Data flow is parse -> ingest -> dedupe -> query -> chart.
- Dedupe is enforced at the database level with UNIQUE constraints.
- Gmail automation is additive and uses `email_imports` tracking for attachment-level dedupe.

### Testing Strategy
- Use pytest with tmp-path SQLite databases for realistic integration-style tests.
- Cover parser behavior, ingestion dedupe behavior, and email-ingestion helper logic.
- Prefer regression tests when fixing bugs (dedupe logic, dry-run behavior, parsing edge-cases).

### Git Workflow
- Pull request workflow runs tests and container build without push.
- Tag workflow runs tests and publishes image to GHCR.
- Keep changes focused and incremental; include tests for behavior changes.

## Domain Context
- Source data comes from Strong CSV exports and may contain imperfect values (duration formats, set order anomalies).
- The canonical training history is the `sets` table.
- Re-import safety is a core requirement: duplicate sets must be skipped, not duplicated.
- Email ingestion handles unread mailbox items, validates sender/subject/attachment type, then ingests CSV attachments.

## Important Constraints
- Python support baseline is 3.11.
- Database is SQLite; schema constraints are relied on for correctness.
- Avoid silent data loss or silent corruption; unexpected integrity issues should raise errors.
- Dry-run paths should be side-effect free.

## External Dependencies
- Plotly for HTML chart rendering.
- Gmail IMAP (with app password) for optional email ingestion automation.
- GitHub Container Registry (GHCR) for image publication.
