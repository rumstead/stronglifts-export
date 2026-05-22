## Context
Strong exports require manual initiation in the mobile app. Emailing the export to a dedicated Gmail inbox allows the rest of the pipeline to run unattended on homelab infrastructure.

## Goals / Non-Goals
- Goals:
  - Securely connect to Gmail over IMAP TLS.
  - Process only expected CSV attachments from approved senders.
  - Guarantee idempotent email and CSV processing.
  - Keep credentials out of source control and image layers.
- Non-Goals:
  - Bypassing Strong export interaction on iPhone.
  - Parsing arbitrary attachment formats beyond CSV.
  - Full enterprise identity integration for the first iteration.

## Decisions
- Decision: Use a dedicated Gmail account or alias mailbox for ingestion-only traffic.
  - Rationale: reduces blast radius if mailbox rules or credentials are compromised.
- Decision: Use Gmail app password with 2-step verification enabled for IMAP access.
  - Rationale: avoids weaker account password usage while keeping integration simple.
- Decision: Poll IMAP over TLS (`imap.gmail.com:993`) with read-only processing conventions.
  - Rationale: encrypted transport and predictable retrieval model.
- Decision: Validate sender, subject pattern, attachment MIME type, and CSV headers before ingest.
  - Rationale: lowers risk of malformed or malicious attachment processing.
- Decision: Store processing metadata (message-id, attachment hash, processed-at) for dedupe and traceability.
  - Rationale: supports retries without duplicate ingestion.

## Risks / Trade-offs
- Risk: Gmail account lockout or suspicious login challenge.
  - Mitigation: dedicated account, app password, and restricted login geography/device.
- Risk: Attachment spoofing from unknown senders.
  - Mitigation: sender allow-list and strict attachment validation.
- Risk: Secret exposure via logs or commits.
  - Mitigation: no secrets in repo, no secret echo in logs, runtime-only environment injection.

## Migration Plan
1. Add email poller with dry-run mode.
2. Configure runtime secrets and sender allow-list.
3. Enable scheduled ingestion and monitor logs.
4. Roll out chart regeneration on successful imports.

## Open Questions
- Should the inbox be a dedicated Gmail account or an alias on an existing account?
- Should processed messages be moved to a folder or labeled in-place?
- What polling cadence is acceptable (for example 5m vs 15m)?
