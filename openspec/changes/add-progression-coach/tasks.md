## 1. Metrics Foundation
- [ ] 1.1 Exclude warm-up and empty sets from derived per-session metrics.
- [ ] 1.2 Detect assisted exercises and invert their progress direction.
- [ ] 1.3 Add per-session working-set summaries (weight, reps per set, total reps, e1RM).

## 2. Progression Engine
- [ ] 2.1 Infer rep range per exercise from recent history; load overrides from `progression.toml`.
- [ ] 2.2 Implement double progression, stall/deload, and layoff rules with equipment-aware increments.
- [ ] 2.3 Classify exercise status (Progressing, Holding, Stalled, Regressing, Returning).
- [ ] 2.4 Add `next-workout` CLI command.
- [ ] 2.5 Unit tests using real-shaped fixtures (bench layoff, lateral raise rep creep, leg extension plateau, assisted pull-up).

## 3. Dashboard
- [ ] 3.1 Next Workout tab grouped by workout name.
- [ ] 3.2 Progress Board with sparklines, % change, status chips, archived section.
- [ ] 3.3 Exercise detail: e1RM trend with PR markers, double-progression chart, rep-max records, recent sessions table.
- [ ] 3.4 Weekly hard sets per muscle group with keyword mapping.
- [ ] 3.5 Mobile layout check and README update.
