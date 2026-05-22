## ADDED Requirements

### Requirement: Exercise Trend Charts
The system SHALL generate charts showing exercise progress over time.

#### Scenario: Generate an exercise chart
- **WHEN** a user requests a chart for a named exercise
- **THEN** the chart includes historical points ordered by workout date
- **AND** exposes weight, reps, or estimated one-rep max trends

### Requirement: Date Range Filtering
The system SHALL support filtering charted data by date range.

#### Scenario: Restrict chart to recent training period
- **WHEN** a start date and end date are provided
- **THEN** only sets within the date range are included
- **AND** chart output reflects the filtered interval

### Requirement: Exportable Chart Output
The system SHALL output charts in a shareable file format.

#### Scenario: Save chart file
- **WHEN** chart generation runs successfully
- **THEN** an output file is created in a configured directory
- **AND** the output can be viewed in a standard web browser
