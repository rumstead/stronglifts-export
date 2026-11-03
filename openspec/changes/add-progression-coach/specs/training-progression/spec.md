## ADDED Requirements

### Requirement: Working Set Classification
The system SHALL derive progression metrics only from working sets.

#### Scenario: Warm-up sets excluded
- **WHEN** a session contains sets with `set_type` of `warmup`, or sets with zero weight and zero reps
- **THEN** those sets are excluded from e1RM, volume, records, and prescriptions

#### Scenario: Assisted exercise direction
- **WHEN** an exercise name contains "Assisted"
- **THEN** a decrease in weight is treated as progress and an increase as regression

### Requirement: Next Session Prescription
The system SHALL recommend weight, set count, and target reps for the next session of each active exercise, with a human-readable reason.

#### Scenario: Top of rep range reached
- **WHEN** every working set in the last session met or exceeded the top of the exercise's rep range
- **THEN** the prescription increases weight by the exercise's increment
- **AND** targets the bottom of the rep range

#### Scenario: Within rep range
- **WHEN** the last session's working sets are within the rep range but not all at the top
- **THEN** the prescription keeps the same weight
- **AND** targets one more rep on the weakest set

#### Scenario: Stalled exercise
- **WHEN** session performance has not improved for 3 consecutive exposures
- **THEN** the prescription recommends a 10% deload, rounded to the increment, and states the stall as the reason

#### Scenario: Returning from a layoff
- **WHEN** more than 14 days have passed since the exercise was last trained
- **THEN** the prescription reduces load by about 10%, rounded to the increment, for one session

### Requirement: Exercise Progress Status
The system SHALL classify each active exercise as Progressing, Holding, Stalled, Regressing, or Returning.

#### Scenario: Status from recent history
- **WHEN** the dashboard or CLI is generated
- **THEN** each exercise trained in the last 60 days has exactly one status derived from its recent working-set history
