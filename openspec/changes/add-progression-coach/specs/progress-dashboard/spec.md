## ADDED Requirements

### Requirement: Next Workout View
The dashboard SHALL open on a Next Workout view grouped by workout name, showing each exercise's last session and its prescription.

#### Scenario: Prescription visible per exercise
- **WHEN** the user opens the dashboard
- **THEN** each active exercise shows last session sets, the prescribed weight × sets × reps, and the reason

### Requirement: Progress Board
The dashboard SHALL summarize all active exercises on one screen.

#### Scenario: Stalled lifts surfaced first
- **WHEN** the Progress Board is shown
- **THEN** each active exercise has a sparkline, 4- and 12-week % change, and a status chip
- **AND** Stalled and Regressing exercises are listed first
- **AND** exercises not trained in 60 days are collapsed under Archived

### Requirement: Exercise Detail
The dashboard SHALL show focused progress charts for a selected exercise.

#### Scenario: Double progression visible
- **WHEN** reps increase at a fixed weight
- **THEN** a chart of total working reps per session, banded by weight, shows the increase

#### Scenario: Records by rep count
- **WHEN** an exercise detail is opened
- **THEN** it lists the best weight lifted at 5, 8, 10, and 12 reps with dates

### Requirement: Weekly Muscle Group Volume
The dashboard SHALL chart hard working sets per week per muscle group.

#### Scenario: Unmapped exercise
- **WHEN** an exercise does not match any muscle mapping keyword
- **THEN** its sets are counted under "Other" and the exercise is listed as unmapped
