# Strong CSV Lift Tracking

This project ingests CSV exports from Strong, stores deduplicated set history in SQLite, and generates exercise progress charts as HTML files.

## Why this workflow
Strong exports CSV, but does not provide reliable unattended sync from iPhone. This pipeline assumes manual export from the app and automates everything after that.

## Setup
1. Create and activate a virtual environment.
2. Install dependencies and the project in editable mode.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Why no `PYTHONPATH=src`: editable install (`pip install -e .`) registers `lifting_data` directly in your venv.

## Commands
Initialize database:

```bash
python3 -m lifting_data.cli --db data/lifts.db init-db
```

Ingest a Strong CSV export:

```bash
python3 -m lifting_data.cli --db data/lifts.db ingest --csv path/to/strong-export.csv
```

List ingested exercises:

```bash
python3 -m lifting_data.cli --db data/lifts.db list-exercises
```

Generate an exercise chart:

```bash
python3 -m lifting_data.cli --db data/lifts.db plot --exercise "Bench Press" --output output/bench-press.html
```

Use date range filters:

```bash
python3 -m lifting_data.cli --db data/lifts.db plot --exercise "Bench Press" --start 2026-01-01 --end 2026-12-31 --output output/bench-press-2026.html
```

## One-command pipeline

```bash
./scripts/run_pipeline.sh path/to/strong-export.csv "Bench Press" output/bench-press.html
```

## Container build and GHCR push

Build an image locally:

```bash
make image-build
```

Use Podman instead of Docker:

```bash
make image-build CONTAINER_RUNTIME=podman
```

Run a pre-push smoke test inside the built container:

```bash
make image-smoke TAG=localtest IMAGE_REPO=ghcr.io/<your-github-user>/lifting-data CONTAINER_RUNTIME=podman
```

Build and push with an explicit tag:

```bash
make image-publish TAG=2026-05-19-1 IMAGE_REPO=ghcr.io/<your-github-user>/lifting-data CONTAINER_RUNTIME=podman
```

Run the CLI inside the container (example: initialize DB in a mounted data dir):

```bash
podman run --rm -v "$PWD/data:/app/data" ghcr.io/<your-github-user>/lifting-data:2026-05-19-1 --db /app/data/lifts.db init-db
```

If Podman is on your remote host (`<your-build-host-ip>`), run build/test/push there:

```bash
ssh <your-build-host-ip> 'cd /path/to/lifting-data && make image-build TAG=2026-05-19-1 IMAGE_REPO=ghcr.io/<your-github-user>/lifting-data CONTAINER_RUNTIME=podman && make image-smoke TAG=2026-05-19-1 IMAGE_REPO=ghcr.io/<your-github-user>/lifting-data CONTAINER_RUNTIME=podman && make image-publish TAG=2026-05-19-1 IMAGE_REPO=ghcr.io/<your-github-user>/lifting-data CONTAINER_RUNTIME=podman'
```

## GitHub Actions image publish on tag

This repo includes a workflow that runs on pushed tags matching `v*` and publishes to GHCR.

Workflow file:

`/.github/workflows/publish-image-on-tag.yml`

Required GitHub repository settings:

- Workflow permissions must allow `packages: write`.
- No custom registry secrets are required for GHCR publish in the workflow.

Release flow:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Published image tags:

- `ghcr.io/<your-github-user>/lifting-data:v0.1.0`
- `ghcr.io/<your-github-user>/lifting-data:latest`

## Automation options
- Local scheduler: run `scripts/run_pipeline.sh` via cron after you export a CSV from your iPhone.
- Homelab (Talos): run this in a container and expose generated HTML via a simple web server.
- iPhone Shortcut: optional manual trigger to upload exported CSV to your host, then run ingest/plot.

## Gmail ingestion automation

This option keeps Strong export manual in the iPhone app, then automates everything after the email send.

1. In Gmail, create a filter that tags incoming Strong export emails.
2. Enable IMAP in Gmail settings.
3. Enable 2-step verification and create an app password.
4. Export your app password at runtime (never commit it):

```bash
export GMAIL_APP_PASSWORD='your-app-password'
```

5. Run secure email ingestion:

```bash
python3 -m lifting_data.cli --db data/lifts.db ingest-email \
  --imap-user your-email@example.com \
  --source-mailbox Strong \
  --processed-mailbox Strong/Processed \
  --allow-sender your-email@example.com
```

The command reads unread messages from the selected mailbox/label, validates sender and attachment type, ingests valid CSV files, deduplicates by message/attachment hash, and moves processed messages into `Strong/Processed`.

Sender safety: pass one or more `--allow-sender` values to restrict ingestion. If you intentionally want to allow all senders, add `--allow-all-senders` explicitly.

Optional extra guardrail for subject matching:

```bash
python3 -m lifting_data.cli --db data/lifts.db ingest-email \
  --imap-user your-email@example.com \
  --source-mailbox Strong \
  --processed-mailbox Strong/Processed \
  --allow-sender your-email@example.com \
  --subject-contains "Strong lifts"
```

Dry-run mode (validation without ingest/move):

```bash
python3 -m lifting_data.cli --db data/lifts.db ingest-email \
  --imap-user your-email@example.com \
  --allow-sender your-email@example.com \
  --dry-run
```

Hourly automation example via cron:

```bash
0 * * * * cd /path/to/lifting-data && /bin/bash -lc 'source .venv/bin/activate && export GMAIL_APP_PASSWORD="..." && python3 -m lifting_data.cli --db data/lifts.db ingest-email --imap-user your-email@example.com --source-mailbox Strong --processed-mailbox Strong/Processed --allow-sender your-email@example.com'
```

## Notes
- Re-importing the same CSV is safe. Duplicate sets are skipped automatically.
- Current schema stores derived metrics such as set volume and estimated 1RM.
