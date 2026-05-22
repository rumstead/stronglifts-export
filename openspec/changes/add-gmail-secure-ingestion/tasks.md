## 1. Security Setup Plan
- [x] 1.1 Create a dedicated Gmail mailbox or alias for ingestion traffic. (Using primary Gmail with filter/label per user choice)
- [x] 1.2 Enable 2-step verification and generate an app password for IMAP.
- [x] 1.3 Define sender allow-list and subject/attachment rules.
- [x] 1.4 Define runtime secret injection method for homelab deployment.

## 2. Ingestion Plan
- [x] 2.1 Add IMAP poller that fetches unread messages with CSV attachments.
- [x] 2.2 Validate message sender and attachment format before ingest.
- [x] 2.3 Persist message-id and attachment hash to ensure idempotent processing.
- [x] 2.4 Trigger existing CSV ingest and chart regeneration flow on accepted files. (CSV ingest complete; chart generation remains explicit command)
- [x] 2.5 Mark or move processed emails to prevent repeated handling.

## 3. Operations Plan
- [x] 3.1 Add dry-run mode for safe initial rollout.
- [x] 3.2 Add structured logs and failure counters for observability. (CLI summary counters added)
- [x] 3.3 Define scheduler cadence and retry strategy. (Hourly cron guidance documented)
- [x] 3.4 Document incident response actions for auth failures and malformed emails.

## 4. Validation Plan
- [x] 4.1 Validate OpenSpec change with strict mode.
- [x] 4.2 Run end-to-end test with a real emailed Strong CSV attachment.
- [x] 4.3 Verify dedupe behavior across duplicate emails and duplicate attachments.
