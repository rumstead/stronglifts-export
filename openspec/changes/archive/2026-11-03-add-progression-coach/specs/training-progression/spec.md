## ADDED Requirements

### Requirement: Working Set Classification
The system SHALL derive progression metrics only from working sets.

#### Scenario: Warm-up sets excluded
- **WHEN** a session contains sets with `set_type` of `warmup`, or sets with zero weight and zero reps
- **THEN** those sets are excluded from e1RM, volume, records, and prescriptions

#### Scenario: Heavy singles and ramp-up sets excluded
- **WHEN** a session mixes a heavy single or lighter ramp-up sets with straight sets
- **THEN** the working weight is the hardest weight done for two or more sets
- **AND** a lone harder set of 5+ reps at the previous session's working weight keeps that weight

#### Scenario: Assisted exercise direction
- **WHEN** an exercise name contains "Assisted"
- **THEN** a decrease in weight is treated as progress and an increase as regression

### Requirement: Next Session Prescription
The system SHALL recommend weight, set count, and target reps for the next session of each active exercise, with a human-readable reason.

#### Scenario: Top of rep range reached
- **WHEN** every working set in the last session met or exceeded the top of the exercise's rep range
- **THEN** the prescription increases weight by one step (the configured increment, or the next weight used on odd-step equipment)
- **AND** each set's target is last session's reps minus the lifter's measured rep cost for the jump, adjusted for RPE reserve and kept within the rep range

#### Scenario: Within rep range
- **WHEN** the last session's working sets are within the rep range but not all at the top
- **THEN** the prescription keeps the same weight
- **AND** targets one more rep on the weakest set

#### Scenario: Stalled exercise
- **WHEN** session performance has not improved for 3 consecutive exposures
- **THEN** the prescription recommends about a 10% deload, snapped to available weights, and states the stall and the actual cut as the reason

#### Scenario: Returning from a layoff
- **WHEN** more than 14 days have passed since the exercise was last trained
- **THEN** the prescription reduces load by about 10%, rounded to the increment, for one session

#### Scenario: Below range twice without improvement
- **WHEN** the weakest working set was below the rep range in two consecutive sessions at the same weight and reps did not improve
- **THEN** the prescription drops back one weight step

#### Scenario: Effort and next step
- **WHEN** a prescription is produced
- **THEN** it includes a target effort (RPE and reps in reserve) for the session type
- **AND** the condition that earns the next weight change

### Requirement: Rep Range Inference
The system SHALL infer each exercise's rep range from the lifter's history, overridable by configuration.

#### Scenario: Inferred from weight increases
- **WHEN** an exercise has prior weight increases
- **THEN** the top of the range is the median reps reached before an increase and the bottom is where the lifter landed after it, snapped to familiar brackets

#### Scenario: Configured override
- **WHEN** a progression TOML names the exercise with a `rep_range`
- **THEN** that range is used instead of the inferred one
- **AND** configured exercise names with no data produce a warning

### Requirement: Evaluation Date
The system SHALL evaluate progression as of a given date, defaulting to today.

#### Scenario: Historical evaluation
- **WHEN** `--as-of` is given
- **THEN** sessions after that date do not affect prescriptions, statuses, or the workout rotation

### Requirement: Exercise Progress Status
The system SHALL classify each active exercise as Progressing, Holding, Stalled, Regressing, or Returning.

#### Scenario: Status from recent history
- **WHEN** the dashboard or CLI is generated
- **THEN** each exercise trained in the last 60 days has exactly one status derived from its recent working-set history

#### Scenario: Status agrees with the advice
- **WHEN** the prescription is a drop-back or a deload
- **THEN** the status is not reported as Progressing
