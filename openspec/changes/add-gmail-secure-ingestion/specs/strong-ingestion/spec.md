## MODIFIED Requirements

### Requirement: Import Strong CSV Exports
The system SHALL import Strong workout CSV exports from either local files or secure email attachment retrieval.

#### Scenario: Valid CSV import from local file
- **WHEN** a valid Strong CSV file is provided from local storage
- **THEN** the system parses workout, exercise, and set data
- **AND** stores normalized records for later analysis

#### Scenario: Valid CSV import from Gmail attachment
- **WHEN** a matching Gmail message contains a valid Strong CSV attachment
- **THEN** the system retrieves the attachment over IMAP TLS
- **AND** ingests the parsed set data into storage

### Requirement: Idempotent Re-Import
The system SHALL support duplicate-safe re-import of previously ingested Strong CSV files and previously processed email attachments.

#### Scenario: Re-importing the same export file
- **WHEN** the same CSV content is imported more than once
- **THEN** duplicate set records are not created
- **AND** the import operation reports completion without data corruption

#### Scenario: Duplicate email processing retry
- **WHEN** the same message-id or attachment hash is encountered again
- **THEN** the system skips re-ingestion
- **AND** records that the email item was already processed

## ADDED Requirements

### Requirement: Secure Gmail Connectivity
The system SHALL connect to Gmail securely using IMAP over TLS and runtime-injected credentials.

#### Scenario: Poll mailbox securely
- **WHEN** the poller checks for new import messages
- **THEN** it connects to `imap.gmail.com` on port `993` using TLS
- **AND** reads credentials from runtime secrets, not source-controlled files

### Requirement: Email Intake Guardrails
The system SHALL enforce sender and attachment validation before ingesting emailed CSV files.

#### Scenario: Accepted sender and valid attachment
- **WHEN** a message comes from an allow-listed sender and includes a CSV attachment with Strong-required columns
- **THEN** the attachment is accepted for ingest
- **AND** processing metadata is recorded

#### Scenario: Untrusted sender or malformed attachment
- **WHEN** a message sender is not allow-listed or attachment validation fails
- **THEN** the system rejects the attachment
- **AND** logs a non-secret error event for operator review
