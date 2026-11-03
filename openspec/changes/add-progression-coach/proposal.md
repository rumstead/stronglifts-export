# Change: Add Progression Coach and Progress Dashboard

## Why
The current page is a dropdown of every exercise ever logged (46, of which only 23 were trained since June 2026) with five near-identical line charts per exercise. It answers "what did I lift?" but not the two questions that matter at the gym:

1. **Am I progressing, and where am I stuck?** — across all lifts at a glance, not one dropdown entry at a time.
2. **What should I do next session?** — concrete weight × sets × reps.

The training history makes the gap concrete. The program is three straight working sets per exercise using double progression (fixed weight, add reps, then add weight):

| Exercise | Recent sessions | What the charts show today | What would actually help |
| --- | --- | --- | --- |
| Bench Press (Barbell) | 205×8,7,7 → 215×6,6,5 → (31-day gap) → 185×8,7,6 | e1RM "drop" | "Returning from layoff — 195 × 3, aim 8,7,7" |
| Lateral Raise (Dumbbell) | 15×11,11,9 … 15×11,12,11 | flat e1RM line (+1 rep barely moves Epley) | "Reps climbing: +5 total reps in 8 sessions; 1 rep from moving up" |
| Lat Pulldown (Cable) | 153×10,8,7 repeated through October | flat line | "No rep gains in 3 sessions at 153 — deload to 148 and build to 10" |
| Pull Up (Assisted) | 40 → 60 lb assistance | e1RM **rising** (wrong: more assistance is easier) | "Assistance increased — regression" |

## Inspiration
- **StrongLifts 5×5:** the app tells you the next weight. Success → add a fixed increment; three failed sessions → deload 10%. Simple, explainable rules.
- **Hevy:** "Previous" values shown inline with each set; per-exercise records by rep count (best 5RM, 8RM, 10RM…); weekly sets per muscle group; PR badges.
- **RP Hypertrophy:** weekly hard sets per muscle compared against volume landmarks (MEV/MAV/MRV), mesocycles that ramp effort (RIR 3 → 0) then deload, and feedback-driven adjustments.
- **Strong:** e1RM and best-set charts plus a records tab — essentially what exists today.

## What Changes
- **Progression engine (new `training-progression` capability):** per exercise, classify working sets, infer the rep range from history (overridable in a small config file), and prescribe the next session with a plain-language reason. Rules:
  - Double progression: all working sets at the top of the range → add weight (equipment-aware increment: barbell +5 lb, dumbbell/cable/machine next step); otherwise keep weight and target +1 rep on the weakest set.
  - Stall: no improvement in session performance for 3 exposures → recommend a 10% deload (StrongLifts rule) or a rep-range change.
  - Layoff: >14 days since the exercise was last trained → reduce load ~10% for one session.
  - Assisted exercises (`(Assisted)` in the name) are inverted: progress means *less* assistance.
  - Warm-up sets (Hevy `set_type = warmup`) and zero-weight/zero-rep rows are excluded from all metrics.
- **Progress dashboard (new `progress-dashboard` capability), replacing the five-chart dropdown:**
  - **Next Workout tab (default):** grouped by workout name (Lower, Upper One, Upper Two), each exercise shows last session's sets and the prescription.
  - **Progress Board:** one row per *active* exercise (trained in the last 60 days) with a 12-week sparkline, % change over 4 and 12 weeks, and a status chip — Progressing / Holding / Stalled / Regressing / Returning. Stalled and regressing lifts are listed first. Inactive exercises are collapsed under "Archived".
  - **Exercise detail:** one primary chart instead of five — per-session e1RM with a rolling trend line and PR markers — plus a **double-progression chart** (total working reps per session, banded by weight, so rep gains at a fixed weight are visible), a rep-max records table (best weight at 5/8/10/12 reps), and the last five sessions as a set table.
  - **Weekly volume by muscle group:** hard sets per week per muscle, with optional RP-style target bands, driven by a keyword → muscle mapping.
- **CLI:** `next-workout [--workout "Lower"]` prints the prescription in the terminal; `plot-all` emits the new dashboard.

## Non-Goals
- Writing routines back into Hevy (the API needs Hevy Pro; can be a follow-up).
- Full RP-style mesocycle planning or per-session soreness feedback.
- Machine learning or fatigue modelling; rules stay deterministic and explainable.

## Impact
- Affected specs: `training-progression` (new), `progress-dashboard` (new; supersedes the chart layout in `add-strong-csv-progress-pipeline/strong-visualization`).
- Affected code: new `src/lifting_data/progression.py`, rewritten `charts.py` template, `cli.py`, an optional `progression.toml` config, tests.
- No schema change; all metrics are derived from the existing `sets` table.

## Decisions
- Rep ranges are inferred from history (reps before each weight increase → top; reps after the jump → bottom, rounded down), snapped to familiar brackets, and overridable per exercise in `progression.toml`. Exercises with fewer than four sessions default to 8–12.
- Increments are 5 lb. Equipment with odd steps (cable row, lat pulldown, and other cable stacks where ≥25% of sessions use non-multiples of 5) moves to the next weight actually used; assisted movements always use observed weights.
- RPE from Hevy is already ingested (logged since September 2026). It is used to spot easy sessions (RPE ≤ 8 → add a rep to every set), flag grinding stalls, and is shown on every set. Trends stay on plain Epley so pre-RPE history remains comparable.
