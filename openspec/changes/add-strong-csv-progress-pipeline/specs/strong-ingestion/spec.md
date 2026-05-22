## ADDED Requirements

### Requirement: Import Strong CSV Exports
The system SHALL import Strong workout CSV exports that include set-level workout data.

#### Scenario: Valid CSV import
- **WHEN** a valid Strong CSV file is provided
- **THEN** the system parses workout, exercise, and set data
- **AND** stores normalized records for later analysis

### Requirement: Idempotent Re-Import
The system SHALL support duplicate-safe re-import of previously ingested Strong CSV files.

#### Scenario: Re-importing the same export
- **WHEN** the same CSV content is imported more than once
- **THEN** duplicate set records are not created
- **AND** the import operation reports completion without data corruption

### Requirement: Derived Metrics
The system SHALL derive progress-friendly metrics from imported set data.

#### Scenario: Compute metrics during ingest
- **WHEN** a set has weight and reps values
- **THEN** the system computes per-set volume as weight multiplied by reps
- **AND** stores an estimated one-rep max value for trend analysis
