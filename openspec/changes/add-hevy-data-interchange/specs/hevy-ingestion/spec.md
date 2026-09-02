## ADDED Requirements

### Requirement: One-Time Strong Migration Artifact
The project SHALL provide one validated Strong-format migration artifact that converts the attached source's populated `Weight` values from pounds to kilograms without modifying the source.

#### Scenario: Generate migration copy
- **WHEN** the approved one-time migration is performed
- **THEN** each populated output weight equals the pound source value multiplied by `0.45359237`
- **AND** the output retains the Strong header, row count, column order, and non-weight logical values

#### Scenario: Preserve original export
- **WHEN** migration generation and validation complete
- **THEN** the source file's byte hash remains unchanged

### Requirement: Workout Export Format Detection
The system SHALL detect supported Strong and Hevy workout CSV files from parsed header signatures and SHALL allow an explicit format override.

#### Scenario: Detect native Hevy export
- **WHEN** a CSV contains the required Hevy snake_case headers and a supported unit-bearing weight column
- **THEN** the Hevy parser is selected

#### Scenario: Preserve Strong ingestion
- **WHEN** a CSV contains the existing required English Strong headers
- **THEN** the Strong parser is selected and existing behavior is preserved

#### Scenario: Unknown or explicitly mismatched format
- **WHEN** headers match no supported format or conflict with the explicit override
- **THEN** ingestion fails with expected and found header details
- **AND** no rows are written

### Requirement: Ingest Native Hevy Workout Exports
The system SHALL parse native Hevy workout exports into the existing set ingestion model, including workout identity, exercise, set order/type, weight, repetitions, duration, distance, and RPE when present.

#### Scenario: Ingest kilogram Hevy export
- **WHEN** a valid Hevy export provides `weight_kg`
- **THEN** the system treats that column as kilograms and stores its set rows

#### Scenario: Ingest pound Hevy export
- **WHEN** a valid Hevy export provides `weight_lbs`
- **THEN** the system treats that column as pounds and stores its set rows

#### Scenario: Tolerate additive columns
- **WHEN** a valid Hevy export includes unknown optional columns
- **THEN** supported fields are ingested without a format failure

#### Scenario: Reject conflicting units
- **WHEN** a Hevy row populates both supported weight columns
- **THEN** the file is rejected as ambiguous
- **AND** no rows from that file are committed

### Requirement: Idempotent Hevy Re-Import
The system SHALL prevent duplicate sets when identical or cumulative overlapping Hevy exports are ingested repeatedly.

#### Scenario: Re-import identical export
- **WHEN** the same Hevy export is ingested more than once
- **THEN** the second ingest inserts no duplicate sets
- **AND** reports existing sets as skipped

#### Scenario: Ingest cumulative export
- **WHEN** a later Hevy export contains old sets plus new sets
- **THEN** old sets are skipped
- **AND** only new sets are inserted

### Requirement: Atomic Hevy File Import
The system SHALL validate and parse an entire Hevy file before committing any of its set rows.

#### Scenario: Invalid row follows valid rows
- **WHEN** a later row fails required parsing or unit validation
- **THEN** no rows from the file are committed
- **AND** the error identifies the row and reason

### Requirement: Shared Local and Email Ingestion
The system SHALL apply the same format detection, parsing, and deduplication rules to local files and accepted email attachments.

#### Scenario: Email contains native Hevy export
- **WHEN** an accepted CSV attachment has a valid Hevy signature
- **THEN** it is validated and ingested with the Hevy parser

#### Scenario: Email dry-run
- **WHEN** a Hevy attachment is processed in dry-run mode
- **THEN** its format and validity are reported
- **AND** no file, database, mailbox, flag, or processed-attachment state is changed
