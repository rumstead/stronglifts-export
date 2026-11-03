## 1. Metrics Foundation
- [x] 1.1 Exclude warm-up and empty sets from derived per-session metrics.
- [x] 1.2 Detect assisted exercises and invert their progress direction.
- [x] 1.3 Add per-session working-set summaries (weight, reps per set, total reps, e1RM).

## 2. Progression Engine
- [x] 2.1 Infer rep range per exercise from recent history; load overrides from `progression.toml`.
- [x] 2.2 Implement double progression, stall/deload, and layoff rules with equipment-aware increments.
- [x] 2.3 Classify exercise status (Progressing, Holding, Stalled, Regressing, Returning).
- [x] 2.4 Add `next-workout` CLI command.
- [x] 2.5 Unit tests using real-shaped fixtures (bench layoff, lateral raise rep creep, leg extension plateau, assisted pull-up).

## 3. Dashboard
- [x] 3.1 Next Workout tab grouped by workout name.
- [x] 3.2 Progress Board with sparklines, % change, status chips, archived section.
- [x] 3.3 Exercise detail: e1RM trend with PR markers, double-progression chart, rep-max records, recent sessions table.
- [x] 3.4 Weekly hard sets per muscle group with keyword mapping.
- [x] 3.5 Mobile layout check and README update.
