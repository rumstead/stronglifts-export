# Change: Add Secure Gmail Ingestion Automation

## Why
Manual file movement after Strong export still adds friction. A Gmail-driven intake path can preserve the required manual export trigger while automating retrieval, ingest, and chart refresh. Because personal email is involved, security controls must be explicit from the first release.

## What Changes
- Add secure IMAP-based Gmail attachment ingestion as an optional source for Strong CSV files.
- Add secret-management and mailbox-safety requirements for credentials and sender filtering.
- Add idempotent email processing behavior to avoid duplicate imports from retries.
- Add operational requirements for polling, error handling, and audit logging.

## Impact
- Affected specs: strong-ingestion
- Affected code: new email poller module, credential handling, scheduler wiring, and docs
