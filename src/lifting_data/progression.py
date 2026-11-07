"""Progression analysis: working sets, rep ranges, status, and next-session prescriptions.

All rules are deterministic and explainable. Inspired by StrongLifts (fixed
increments, deload after repeated failure), Hevy (previous sets and rep-max
records), and hypertrophy programming practice (RPE/RIR-aware effort and
weekly set volume per muscle).
"""

from __future__ import annotations

import logging
import sqlite3
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from statistics import median

# Set types that are not counted as working sets.
NON_WORKING_SET_TYPES = frozenset({"warmup", "dropset"})

# Sets within this fraction of the session's working weight count as working sets.
WORKING_WEIGHT_TOLERANCE = 0.025
# Sessions within this fraction of each other count as "the same weight" for stall checks.
SAME_WEIGHT_TOLERANCE = 0.005

# Rep ranges are snapped to familiar program brackets.
LOW_BRACKETS = (3, 5, 6, 8, 10, 12, 15)
HIGH_BRACKETS = (5, 8, 10, 12, 15, 20)
MAX_RANGE_WIDTH = 6

ACTIVE_WINDOW_DAYS = 60
REP_RANGE_LOOKBACK_DAYS = 365
MAX_UP_EVENT_GAP_DAYS = 21

# Rep cost of a weight increase when there is no history of increases at all.
DEFAULT_REPS_LOST_PER_10PCT = 1.0
TARGET_RPE = 9.0

# A lone heavier set with at least this many reps is real work, not a test single.
MIN_TOP_SET_REPS = 5

logger = logging.getLogger(__name__)

STATUS_ORDER = ("Regressing", "Stalled", "Returning", "Holding", "Progressing", "Archived")


@dataclass(frozen=True)
class ProgressionConfig:
    increment: float = 5.0
    layoff_days: int = 14
    deload_pct: float = 0.10
    bodyweight: float = 180.0
    rep_ranges: dict[str, tuple[int, int]] = field(default_factory=dict)
    increments: dict[str, float] = field(default_factory=dict)
    ladders: dict[str, tuple[float, ...]] = field(default_factory=dict)


def load_config(path: str | None) -> ProgressionConfig:
    """Load an optional TOML config. Missing path → defaults; invalid content → error."""
    if path is None:
        return ProgressionConfig()
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {})
    rep_ranges: dict[str, tuple[int, int]] = {}
    increments: dict[str, float] = {}
    ladders: dict[str, tuple[float, ...]] = {}
    for name, opts in raw.get("exercises", {}).items():
        if "rep_range" in opts:
            low, high = opts["rep_range"]
            if not (0 < int(low) <= int(high)):
                raise ValueError(f"Invalid rep_range for {name}: {opts['rep_range']}")
            rep_ranges[name] = (int(low), int(high))
        if "increment" in opts:
            increments[name] = float(opts["increment"])
        if "ladder" in opts:
            ladders[name] = tuple(sorted(float(w) for w in opts["ladder"]))
    return ProgressionConfig(
        increment=float(defaults.get("increment", 5.0)),
        layoff_days=int(defaults.get("layoff_days", 14)),
        deload_pct=float(defaults.get("deload_pct", 0.10)),
        bodyweight=float(defaults.get("bodyweight", 180.0)),
        rep_ranges=rep_ranges,
        increments=increments,
        ladders=ladders,
    )


@dataclass(frozen=True)
class SetRecord:
    weight: float
    reps: int
    rpe: float | None
    set_type: str


@dataclass
class Session:
    started_at: str
    workout_name: str
    sets: list[SetRecord]
    assisted: bool = False
    working_weight: float = 0.0
    working_sets: list[SetRecord] = field(default_factory=list)

    @property
    def day(self) -> date:
        return date.fromisoformat(self.started_at[:10])

    @property
    def reps(self) -> list[int]:
        return [s.reps for s in self.working_sets]

    @property
    def total_reps(self) -> int:
        return sum(self.reps)

    @property
    def rpes(self) -> list[float]:
        return [s.rpe for s in self.working_sets if s.rpe is not None]

    @property
    def avg_rpe(self) -> float | None:
        values = self.rpes
        return sum(values) / len(values) if values else None


def epley(weight: float, reps: int) -> float:
    return weight * (1 + reps / 30.0)


def classify_working_sets(session: Session, previous_weight: float | None = None) -> None:
    """Pick the session's working weight and the sets performed at it.

    Working weight is the hardest weight (heaviest, or least assistance) that
    has at least two sets within tolerance, so a heavy single or a lighter
    ramp-up set does not define the session. Without such a weight, the
    hardest weight done for 3+ reps is used. If a single harder set (5+ reps)
    matches the previous session's working weight, that weight still counts:
    the lifter held it, even with lighter sets around it.
    """
    candidates = [s for s in session.sets if s.set_type not in NON_WORKING_SET_TYPES and s.reps > 0]
    if session.assisted and any(s.weight > 0 for s in candidates):
        # A blank (0 lb) assistance entry next to real ones is a logging gap, not unassisted reps.
        candidates = [s for s in candidates if s.weight > 0]
    if not candidates:
        session.working_weight = 0.0
        session.working_sets = []
        return

    def near(weight: float) -> list[SetRecord]:
        tolerance = abs(weight) * WORKING_WEIGHT_TOLERANCE + 1e-6
        return [s for s in candidates if abs(s.weight - weight) <= tolerance]

    hardest_first = sorted({s.weight for s in candidates}, reverse=not session.assisted)
    weight = next((w for w in hardest_first if len(near(w)) >= 2), None)
    if weight is None:
        weight = next((s.weight for s in sorted(candidates, key=lambda s: s.weight, reverse=not session.assisted) if s.reps >= 3), hardest_first[0])
    if previous_weight is not None and previous_weight > 0 and _harder(previous_weight, weight, session.assisted):
        held = [
            s for s in candidates
            if _same_weight(s.weight, previous_weight) and s.reps >= MIN_TOP_SET_REPS
        ]
        if held:
            weight = held[0].weight
    session.working_weight = weight
    session.working_sets = near(weight)


@dataclass(frozen=True)
class RepRange:
    low: int
    high: int
    source: str  # "config", "history", or "default"


@dataclass(frozen=True)
class Prescription:
    action: str  # increase, hold, deload, drop-back, return, add-reps
    weight: float
    target_reps: tuple[int, ...]
    reason: str
    short: str = ""  # one-line cue for compact views
    effort: str = ""  # target effort, e.g. "RPE 9–9.5 · about 1 rep left on the last set"
    goal: str = ""  # what earns the next weight change
    # Every set in session order: (weight, reps, is_working). Off-weight sets the
    # lifter does around the working sets (a lighter lead-in, a heavier top set)
    # are kept as last time; only working sets carry progression targets.
    plan: tuple[tuple[float, int, bool], ...] = ()

    @property
    def sets(self) -> int:
        return len(self.target_reps)

    def describe(self) -> str:
        reps = ",".join(str(r) for r in self.target_reps)
        load = "Bodyweight" if self.weight == 0 else f"{_fmt_weight(self.weight)} lb"
        return f"{load} × {reps}"


@dataclass
class ExerciseAnalysis:
    name: str
    kind: str  # weighted, assisted, bodyweight
    sessions: list[Session]
    rep_range: RepRange
    ladder: tuple[float, ...] | None
    increment: float
    scores: list[float]
    status: str
    status_reason: str
    change_4w: float | None
    change_12w: float | None
    prescription: Prescription | None


def _fmt_weight(weight: float) -> str:
    return f"{weight:g}"


def load_sessions(
    connection: sqlite3.Connection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, list[Session]]:
    """Load sets grouped into per-exercise sessions, ordered by time."""
    filters = ["(reps > 0 OR weight > 0)"]
    values: list[object] = []
    if start_date:
        filters.append("workout_date >= ?")
        values.append(start_date)
    if end_date:
        filters.append("workout_date <= ?")
        values.append(end_date + " 23:59:59" if len(end_date) == 10 else end_date)
    rows = connection.execute(
        f"""
        SELECT exercise_name, workout_date, workout_name, set_order, set_type, weight, reps, rpe
        FROM sets
        WHERE {' AND '.join(filters)}
        ORDER BY exercise_name, workout_date, set_order
        """,
        values,
    ).fetchall()

    by_exercise: dict[str, dict[str, Session]] = defaultdict(dict)
    for row in rows:
        name = row["exercise_name"]
        key = row["workout_date"]
        session = by_exercise[name].get(key)
        if session is None:
            session = Session(
                started_at=key,
                workout_name=row["workout_name"],
                sets=[],
                assisted=is_assisted(name),
            )
            by_exercise[name][key] = session
        session.sets.append(
            SetRecord(
                weight=float(row["weight"] or 0.0),
                reps=int(row["reps"] or 0),
                rpe=float(row["rpe"]) if row["rpe"] is not None else None,
                set_type=(row["set_type"] or "normal").lower(),
            )
        )

    result: dict[str, list[Session]] = {}
    for name, sessions in by_exercise.items():
        ordered = [sessions[k] for k in sorted(sessions)]
        previous: float | None = None
        for session in ordered:
            classify_working_sets(session, previous)
            if session.working_sets:
                previous = session.working_weight
        ordered = [s for s in ordered if s.working_sets]
        if ordered:
            result[name] = ordered
    return result


def is_assisted(name: str) -> bool:
    return "assist" in name.lower()


def _harder(a: float, b: float, assisted: bool) -> bool:
    """True when weight a is harder than weight b."""
    return a < b if assisted else a > b


def session_score(session: Session, kind: str, bodyweight: float) -> float:
    """Comparable strength score for a session (higher is better).

    Weighted lifts use the best working-set Epley estimate. Assisted and
    bodyweight lifts use (bodyweight - assistance) so less assistance or more
    reps both raise the score.
    """
    if kind == "assisted":
        load = max(bodyweight - session.working_weight, 1.0)
    elif kind == "bodyweight":
        load = bodyweight
    else:
        load = session.working_weight
    if kind == "weighted":
        sets = [s for s in session.sets if s.set_type not in NON_WORKING_SET_TYPES and s.reps > 0]
        return round(max(epley(s.weight, s.reps) for s in sets), 1)
    return round(max(epley(load, s.reps) for s in session.working_sets), 1)


def infer_rep_range(sessions: list[Session], assisted: bool) -> RepRange:
    """Infer the rep range from how the lifter has actually progressed.

    At each weight increase (within a normal training gap), the reps achieved
    just before the jump mark the top of the range, and the reps on the first
    session at the new weight mark the bottom. Without any such
    events, fall back to the 20th/90th percentile of recent working reps, or
    a default 8-12 for exercises with fewer than four sessions.

    Sessions at the weight currently being built are left out (when there is
    enough history without them): a miss right after a jump must not widen
    the range it is judged against.
    """
    if not sessions:
        return RepRange(8, 12, "default")
    cutoff = sessions[-1].day - timedelta(days=REP_RANGE_LOOKBACK_DAYS)
    recent = [s for s in sessions if s.day >= cutoff]
    in_progress = len(_trailing_run(sessions))
    if len(recent) - in_progress >= 4:
        recent = recent[: len(recent) - in_progress]
    tops: list[int] = []
    bottoms: list[int] = []
    for prev, cur in zip(recent, recent[1:]):
        if (cur.day - prev.day).days > MAX_UP_EVENT_GAP_DAYS:
            continue
        if _harder(cur.working_weight, prev.working_weight, assisted):
            tops.append(max(prev.reps))
            bottoms.append(min(cur.reps))

    if tops:
        raw_high = float(median(tops))
        raw_low = float(median(bottoms))
    elif len(recent) < 4:
        reps = sorted(r for x in recent for r in x.reps)
        if not reps or (reps[0] >= 6 and reps[-1] <= 12):
            return RepRange(8, 12, "default")
        # A new exercise done well outside 8-12 (e.g. 15-20 rep wrist work): use what was done.
        raw_low, raw_high = float(reps[0]), float(reps[-1])
    else:
        reps = sorted(r for s in recent[-10:] for r in s.reps)
        raw_low = float(reps[int(0.2 * (len(reps) - 1))])
        raw_high = float(reps[int(0.9 * (len(reps) - 1))])
    low, high = snap_rep_range(raw_low, raw_high)
    return RepRange(low, high, "history")


def snap_rep_range(raw_low: float, raw_high: float) -> tuple[int, int]:
    """Snap raw rep observations to familiar brackets (e.g. 5-8, 8-10, 8-12).

    The top is the nearest bracket (ties go lower, so you move up sooner).
    The bottom rounds down, so landing a rep short after a jump is still in range.
    """
    high = min(HIGH_BRACKETS, key=lambda b: (abs(b - raw_high), b))
    low = max((b for b in LOW_BRACKETS if b <= raw_low), default=LOW_BRACKETS[0])
    if high - low < 2:
        low = max((b for b in LOW_BRACKETS if b <= high - 2), default=1)
    if high - low > MAX_RANGE_WIDTH:
        low = min(b for b in LOW_BRACKETS if b >= high - MAX_RANGE_WIDTH)
    return int(low), int(high)


# Equipment is treated as having odd steps when at least this share of recent
# working sessions used a weight that is not a multiple of 5 lb.
ODD_STEP_SHARE = 0.25


def _uses_fixed_steps(session_weights: list[float]) -> bool:
    if not session_weights:
        return True
    odd = sum(1 for w in session_weights if abs(w / 5.0 - round(w / 5.0)) > 1e-6)
    return odd / len(session_weights) < ODD_STEP_SHARE


def build_ladder(name: str, sessions: list[Session], kind: str, config: ProgressionConfig) -> tuple[float, ...] | None:
    """Return observed weight steps for odd-increment equipment, else None (fixed increment)."""
    if name in config.ladders:
        return config.ladders[name]
    if name in config.increments:
        return None
    cutoff = sessions[-1].day - timedelta(days=REP_RANGE_LOOKBACK_DAYS)
    recent = [sess for sess in sessions if sess.day >= cutoff]
    weights = sorted({s.weight for sess in recent for s in sess.working_sets if s.weight > 0})
    if kind == "assisted" or not _uses_fixed_steps([sess.working_weight for sess in recent]):
        return tuple(weights) if weights else None
    return None


def _step(weight: float, harder: bool, kind: str, ladder: tuple[float, ...] | None, increment: float) -> float:
    """Move one step harder or easier from weight."""
    go_up = harder != (kind == "assisted")  # assisted: harder means less assistance
    if ladder:
        if go_up:
            above = [w for w in ladder if w > weight + 1e-6]
            if above:
                return above[0]
        else:
            below = [w for w in ladder if w < weight - 1e-6]
            if below:
                return below[-1]
    if go_up:
        return weight + increment
    return max(weight - increment, 0.0)


def _reduce_by_pct(weight: float, pct: float, kind: str, ladder: tuple[float, ...] | None, increment: float) -> float:
    """Ease the load by about pct, snapped to available weights."""
    if kind == "assisted":
        return _step(weight, harder=False, kind=kind, ladder=ladder, increment=increment)
    target = weight * (1 - pct)
    if ladder:
        options = [w for w in ladder if w < weight - 1e-6]
        if options:
            nearest = min(options, key=lambda w: abs(w - target))
            # Use a known stack weight only if it delivers at least half the intended cut.
            if weight - nearest >= weight * pct / 2:
                return nearest
    snapped = increment * round(target / increment) if increment > 0 else target
    if 0 < snapped < weight:
        return snapped
    return _step(weight, harder=False, kind=kind, ladder=ladder, increment=increment)


def _trailing_run(sessions: list[Session]) -> list[Session]:
    """Most recent consecutive sessions at the latest working weight, within the current block."""
    if not sessions:
        return []
    weight = sessions[-1].working_weight
    run: list[Session] = []
    for session in reversed(current_block(sessions)):
        if not _same_weight(session.working_weight, weight):
            break
        run.append(session)
    return list(reversed(run))


def _same_weight(a: float, b: float) -> bool:
    return abs(a - b) <= abs(b) * SAME_WEIGHT_TOLERANCE + 1e-6


def current_block(sessions: list[Session]) -> list[Session]:
    """Sessions since the last break longer than the active window."""
    start = 0
    for i in range(1, len(sessions)):
        if (sessions[i].day - sessions[i - 1].day).days > ACTIVE_WINDOW_DAYS:
            start = i
    return sessions[start:]


def _set_count(sessions: list[Session]) -> int:
    counts = Counter(len(s.working_sets) for s in sessions[-3:])
    count = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return max(1, min(count, 5))


def prescribe(
    sessions: list[Session],
    kind: str,
    rep_range: RepRange,
    ladder: tuple[float, ...] | None,
    increment: float,
    config: ProgressionConfig,
    as_of: date,
    reps_lost_per_10pct: float = DEFAULT_REPS_LOST_PER_10PCT,
) -> Prescription:
    """Recommend the next session, with one target per set.

    Targets are computed from the sets actually done; when the usual set count is
    higher than last session's, the extra sets repeat last session's final reps.
    """
    rx = _prescribe(sessions, kind, rep_range, ladder, increment, config, as_of, reps_lost_per_10pct)
    n_sets = _set_count(sessions)
    targets = list(rx.target_reps)[:n_sets]
    last_reps = sessions[-1].reps
    fill = min(last_reps[-1], rep_range.high) if last_reps else rep_range.low
    if rx.action in ("increase", "drop-back", "deload", "return") and targets:
        fill = targets[-1]
    while len(targets) < n_sets:
        targets.append(max(1, fill))
    plan = list(_session_plan(sessions[-1], rx.weight, targets, rx.action))
    # Match the number of sets you usually do in total, lead-in and top sets included.
    total = _hard_set_count(sessions)
    while len(plan) > total and sum(1 for x in plan if x[2]) > 1:
        last_working = max(i for i, x in enumerate(plan) if x[2])
        plan.pop(last_working)
    targets = [r for _, r, working in plan if working]
    return replace(rx, target_reps=tuple(targets), plan=tuple(plan))


def _hard_set_count(sessions: list[Session]) -> int:
    """Most common number of sets (warm-ups and drop sets excluded) in the last 3 sessions."""
    counts = Counter(
        sum(1 for x in s.sets if x.set_type not in NON_WORKING_SET_TYPES and x.reps > 0) for s in sessions[-3:]
    )
    return max(1, max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0])


def _session_plan(
    last: Session, weight: float, targets: list[int], action: str
) -> tuple[tuple[float, int, bool], ...]:
    """Lay the working targets out in the order the lifter does their sets.

    Sets at another weight stay where they were and repeat last time, as long as
    they keep the same relation to the working weight (a lighter lead-in stays
    lighter). A harder top set is skipped while easing back in or deloading.
    """
    hard = [x for x in last.sets if x.set_type not in NON_WORKING_SET_TYPES and x.reps > 0]
    working_ids = {id(x) for x in last.working_sets}
    remaining = list(targets)
    plan: list[tuple[float, int, bool]] = []
    for x in hard:
        if id(x) in working_ids:
            if remaining:
                plan.append((weight, remaining.pop(0), True))
            continue
        was_harder = _harder(x.weight, last.working_weight, last.assisted)
        if was_harder != _harder(x.weight, weight, last.assisted) or _same_weight(x.weight, weight):
            continue
        if was_harder and action in ("return", "deload"):
            continue
        plan.append((x.weight, x.reps, False))
    plan.extend((weight, r, True) for r in remaining)
    return tuple(plan)


def _prescribe(
    sessions: list[Session],
    kind: str,
    rep_range: RepRange,
    ladder: tuple[float, ...] | None,
    increment: float,
    config: ProgressionConfig,
    as_of: date,
    reps_lost_per_10pct: float = DEFAULT_REPS_LOST_PER_10PCT,
) -> Prescription:
    last = sessions[-1]
    low, high = rep_range.low, rep_range.high
    weight = last.working_weight
    n_sets = _set_count(sessions)
    reps = list(last.reps)[:n_sets]
    unit_change = lambda w: f"{_fmt_weight(w)} lb"  # noqa: E731
    rpe = last.avg_rpe
    rpe_note = f" @ RPE {rpe:.1f}" if rpe is not None else ""
    last_desc = f"{_fmt_weight(weight)}×{','.join(str(r) for r in last.reps)}{rpe_note}"

    days_off = (as_of - last.day).days
    if days_off >= config.layoff_days:
        eased = _reduce_by_pct(weight, config.deload_pct, kind, ladder, increment)
        mid = (low + high + 1) // 2
        return Prescription(
            "return",
            eased,
            tuple([mid] * n_sets),
            f"{days_off} days since last session ({last_desc}). Ease back in at {unit_change(eased)}, then resume.",
            short=f"{days_off} days off — ease back in",
        )

    if kind == "bodyweight":
        if min(reps) >= high:
            return Prescription(
                "add-load",
                weight,
                tuple([high] * n_sets),
                f"Hit {high}+ on every set ({last_desc}). Add load or a harder variation.",
                short=f"Hit {high} on every set — add load",
            )
        targets = _add_rep(reps, high)
        return Prescription("hold", weight, tuple(targets), f"Last {last_desc}. Add a rep to your weakest set.",
                            short="+1 rep on your weakest set")

    if min(reps) >= high:
        new_weight = _step(weight, harder=True, kind=kind, ladder=ladder, increment=increment)
        easy = rpe is not None and rpe <= 8.0
        why = f"Hit {high}+ on every set ({last_desc})"
        if easy:
            why += ", and it felt easy"
        verb = "less assistance" if kind == "assisted" else "move up"
        targets = post_increase_targets(
            reps, rpe, weight, new_weight, kind, config.bodyweight, low, high, reps_lost_per_10pct
        )
        aim = ",".join(str(t) for t in targets)
        return Prescription(
            "increase",
            new_weight,
            targets,
            f"{why}. {verb.capitalize()}: {unit_change(new_weight)}; aim for {aim} "
            f"(you usually lose ~{reps_lost_per_10pct:.1f} reps per 10% added).",
            short=f"Hit {high} on every set{' easily' if easy else ''} — {verb}",
        )

    run = _trailing_run(sessions)
    averages = [_avg(s.reps) for s in run]
    if len(run) >= 4 and max(averages[-3:]) <= max(averages[:-3]):
        eased = _reduce_by_pct(weight, config.deload_pct, kind, ladder, increment)
        grinding = rpe is not None and rpe >= 9.5
        effort = " while grinding near failure" if grinding else ""
        return Prescription(
            "deload",
            eased,
            tuple([high] * n_sets),
            f"No rep gains in 3 sessions at {unit_change(weight)}{effort}. "
            f"Deload {_cut_pct(weight, eased, kind)} to {unit_change(eased)} and push reps to {high}.",
            short=f"Stuck at {unit_change(weight)} for 3 sessions — deload",
        )

    if min(reps) < low:
        prev = sessions[-2] if len(sessions) >= 2 else None
        prev_same = prev is not None and _same_weight(prev.working_weight, weight)
        improving = prev is not None and _avg(last.reps) > _avg(prev.reps)
        if prev_same and min(prev.reps) < low and len(run) >= 2 and not improving:
            back = _step(weight, harder=False, kind=kind, ladder=ladder, increment=increment)
            # Aim for what you last managed at that weight, not the bottom of the range.
            earlier = next((x for x in reversed(sessions) if _same_weight(x.working_weight, back)), None)
            back_targets = [max(low, min(r, high)) for r in earlier.reps][:n_sets] if earlier else []
            back_targets += [back_targets[-1] if back_targets else low] * (n_sets - len(back_targets))
            return Prescription(
                "drop-back",
                back,
                tuple(back_targets),
                f"Below {low} reps two sessions running at {unit_change(weight)}. Drop back to {unit_change(back)} and rebuild.",
                short=f"Under {low} reps twice — drop back",
            )
        return Prescription(
            "hold",
            weight,
            tuple(_add_rep(reps, high)),
            f"Last {last_desc}, below the {low}–{high} range. Stay at {unit_change(weight)} until every set reaches {low}.",
            short=f"Build every set to {low}",
        )

    if rpe is not None and rpe <= 8.0:
        targets = [min(r + 1, high) for r in reps]
        why = f"Last {last_desc}, with reps in reserve. Add a rep to every set."
        short = "Reps in reserve last time — +1 rep each set"
    else:
        targets = _add_rep(reps, high)
        why = f"Last {last_desc}. Add a rep to your weakest set; move up once all sets hit {high}."
        short = f"+1 rep on your weakest set · move up at {high}"
    return Prescription("add-reps", weight, tuple(targets), why, short=short)


# Target effort per action. Hard-but-not-failure on progression sessions (your
# usual RPE 9–9.5), more in reserve when easing back or deloading.
EFFORT_BY_ACTION: dict[str, str] = {
    "return": "RPE 7–8 · 2–3 reps in reserve",
    "deload": "RPE 7–8 · 2–3 reps in reserve",
    "increase": "RPE 8.5–9 · 1–2 reps in reserve",
    "drop-back": "RPE 8.5–9 · 1–2 reps in reserve",
    "add-reps": "RPE 9–9.5 · ~1 rep left on the last set",
    "hold": "RPE 9–9.5 · ~1 rep left on the last set",
    "add-load": "RPE 9 · ~1 rep left",
}


def with_targets(
    rx: Prescription,
    last: Session,
    kind: str,
    rep_range: RepRange,
    ladder: tuple[float, ...] | None,
    increment: float,
) -> Prescription:
    """Attach the target effort and the condition for the next weight change."""
    low, high = rep_range.low, rep_range.high
    n = rx.sets
    w = _fmt_weight
    next_up = _step(rx.weight, harder=True, kind=kind, ladder=ladder, increment=increment)
    move = "less assistance" if kind == "assisted" else "move up"
    if kind == "bodyweight":
        if rx.action == "return":
            goal = "If it feels easy, back to full reps next time"
        else:
            goal = f"Hit {high} on all {n} sets → add load or a harder variation"
        return replace(rx, effort=EFFORT_BY_ACTION.get(rx.action, ""), goal=goal)
    if rx.action in ("return", "deload"):
        goal = f"Then back to {w(last.working_weight)} lb once every set hits {high}"
        if rx.action == "return":
            goal = f"If it feels easy, back to {w(last.working_weight)} lb next time"
    elif rx.action == "drop-back":
        goal = f"Rebuild to {high}×{n}, then retry {w(last.working_weight)} lb"
    elif rx.action == "add-load":
        goal = "Add weight or a harder variation once this is easy"
    elif rx.action == "increase":
        if all(t >= high for t in rx.target_reps):
            goal = f"Hit it → {w(next_up)} lb next time · {low}+ every set still counts"
        else:
            goal = f"{low}+ every set still counts · {move} again at {high}×{n}"
    else:
        goal = f"Hit {high} on every {w(rx.weight)} lb set → {w(next_up)} lb"
    return replace(rx, effort=EFFORT_BY_ACTION.get(rx.action, ""), goal=goal)


def effective_load(weight: float, kind: str, bodyweight: float) -> float:
    if kind == "assisted":
        return max(bodyweight - weight, 1.0)
    return weight


def reps_lost_per_10pct(sessions: list[Session], kind: str, bodyweight: float) -> float | None:
    """Median reps lost per 10% load increase, measured from this exercise's own jumps.

    The textbook Epley curve predicts ~3.5 reps per 10%; many lifters (who rarely
    train to true failure) lose far fewer, so the lifter's own history wins.
    Returns None with fewer than 3 jumps.
    """
    ratios: list[float] = []
    for prev, cur in zip(sessions, sessions[1:]):
        if (cur.day - prev.day).days > MAX_UP_EVENT_GAP_DAYS:
            continue
        if not _harder(cur.working_weight, prev.working_weight, kind == "assisted"):
            continue
        before = effective_load(prev.working_weight, kind, bodyweight)
        after = effective_load(cur.working_weight, kind, bodyweight)
        pct = (after / before - 1) * 100 if before > 0 else 0
        if pct <= 0:
            continue
        ratios.append(max(0.0, _avg(prev.reps) - _avg(cur.reps)) / pct * 10)
    return float(median(ratios)) if len(ratios) >= 3 else None


def post_increase_targets(
    reps: list[int],
    rpe: float | None,
    weight: float,
    new_weight: float,
    kind: str,
    bodyweight: float,
    low: int,
    high: int,
    per_10pct: float,
) -> tuple[int, ...]:
    """Per-set targets at a heavier weight: last reps minus the expected rep cost.

    The cost scales with the size of the jump, measured from the lifter's
    history. Reps left in reserve last time (RPE below 9) are added back; a
    grinding RPE above 9 takes a little more off. Targets stay in the rep range.
    """
    before = effective_load(weight, kind, bodyweight)
    after = effective_load(new_weight, kind, bodyweight)
    pct = (after / before - 1) * 100 if before > 0 else 0.0
    cost = per_10pct * pct / 10
    reserve = 0.0 if rpe is None else max(-1.0, min(2.0, TARGET_RPE - rpe))
    targets = []
    for r in reps:
        predicted = int(r - cost + reserve + 0.5)
        predicted = min(predicted, r + max(0, int(reserve)))  # never more than you just did, unless it was easy
        targets.append(max(low, min(high, predicted)))
    return tuple(targets)


def _avg(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _cut_pct(weight: float, eased: float, kind: str) -> str:
    if kind == "assisted" or weight <= 0:
        return "one step"
    return f"{(1 - eased / weight) * 100:.0f}%"


def _add_rep(reps: list[int], cap: int) -> list[int]:
    targets = list(reps)
    if not targets:
        return targets
    weakest = max(i for i, r in enumerate(targets) if r == min(targets))
    targets[weakest] = min(targets[weakest] + 1, max(cap, targets[weakest]))
    return targets


def _best_in_window(sessions: list[Session], scores: list[float], end: date, days: int = 14) -> float | None:
    start = end - timedelta(days=days)
    window = [sc for s, sc in zip(sessions, scores) if start < s.day <= end]
    return max(window) if window else None


def _pct_change(sessions: list[Session], scores: list[float], weeks: int) -> float | None:
    last_day = sessions[-1].day
    now = _best_in_window(sessions, scores, last_day)
    then = _best_in_window(sessions, scores, last_day - timedelta(weeks=weeks))
    if now is None or not then:
        return None
    return round((now / then - 1) * 100, 1)


def classify_status(sessions: list[Session], scores: list[float], as_of: date, layoff_days: int) -> tuple[str, str]:
    last = sessions[-1].day
    days_off = (as_of - last).days
    if days_off > ACTIVE_WINDOW_DAYS:
        return "Archived", f"Last trained {last.isoformat()}"
    if days_off >= layoff_days:
        return "Returning", f"{days_off} days since last session"
    if len(sessions) >= 2 and (last - sessions[-2].day).days >= 21:
        return "Returning", f"Back after {(last - sessions[-2].day).days} days off"
    block = current_block(sessions)
    scores = scores[len(sessions) - len(block):]
    sessions = block
    if len(scores) < 4:
        return "Holding", "Not enough sessions yet"

    recent = scores[-3:]
    prior = scores[-6:-3]
    prior_avg = sum(prior) / len(prior) if prior else 0.0
    pct = (sum(recent) / len(recent)) / prior_avg - 1 if prior_avg > 0 else 0.0
    if max(recent) > max(scores[:-3]):
        return "Progressing", "New best in the last 3 sessions"
    if pct >= 0.02:
        return "Progressing", f"Last 3 sessions up {pct * 100:.1f}% vs the 3 before"
    if pct <= -0.03:
        return "Regressing", f"Last 3 sessions down {abs(pct) * 100:.1f}% vs the 3 before"
    window_start = last - timedelta(days=120)
    earlier = [sc for s, sc in zip(sessions[:-4], scores[:-4]) if s.day >= window_start]
    if len(scores) >= 6 and earlier and max(scores[-4:]) <= max(earlier):
        return "Stalled", "No improvement on your recent best in 4 sessions"
    return "Holding", "Within ±2% of recent sessions"


def _reconcile_status(status: str, reason: str, rx: Prescription, sessions: list[Session]) -> tuple[str, str]:
    """Keep the status consistent with the advice and with double progression.

    The trend score is an Epley estimate, which misreads double progression in
    both directions: a heavier weight with collapsing reps can look like
    progress, and moving up then rebuilding reps can look like a stall.
    """
    last = sessions[-1]
    weight = _fmt_weight(last.working_weight)
    if rx.action == "drop-back" and status in ("Progressing", "Holding"):
        return "Regressing", f"Reps falling at {weight} lb"
    if rx.action == "deload" and status in ("Progressing", "Holding"):
        return "Stalled", f"No rep gains in 3 sessions at {weight} lb"
    if rx.action not in ("add-reps", "hold") or status not in ("Stalled", "Holding", "Regressing"):
        return status, reason
    run = _trailing_run(sessions)
    if len(run) >= 2 and _avg(run[-1].reps) > _avg(run[-2].reps):
        return "Progressing", f"Reps up at {weight} lb"
    before = sessions[-len(run) - 1] if len(sessions) > len(run) else None
    moved_up = before is not None and _harder(last.working_weight, before.working_weight, last.assisted)
    if moved_up and len(run) <= 2 and status != "Holding":
        return "Holding", f"Moved up to {weight} lb — building reps"
    return status, reason


def analyze_exercise(
    name: str,
    sessions: list[Session],
    config: ProgressionConfig,
    as_of: date,
    global_reps_lost_per_10pct: float = DEFAULT_REPS_LOST_PER_10PCT,
) -> ExerciseAnalysis:
    recent_unloaded = all(s.working_weight == 0 for s in sessions[-5:])
    if is_assisted(name) and not recent_unloaded:
        kind = "assisted"
    elif recent_unloaded:
        kind = "bodyweight"
    else:
        kind = "weighted"
    if name in config.rep_ranges:
        low, high = config.rep_ranges[name]
        rep_range = RepRange(low, high, "config")
    else:
        rep_range = infer_rep_range(sessions, assisted=kind == "assisted")
    increment = config.increments.get(name, config.increment)
    ladder = build_ladder(name, sessions, kind, config)
    scores = [session_score(s, kind, config.bodyweight) for s in sessions]
    status, status_reason = classify_status(sessions, scores, as_of, config.layoff_days)
    prescription = None
    if status != "Archived":
        own_cost = reps_lost_per_10pct(sessions, kind, config.bodyweight)
        prescription = prescribe(
            sessions, kind, rep_range, ladder, increment, config, as_of,
            reps_lost_per_10pct=own_cost if own_cost is not None else global_reps_lost_per_10pct,
        )
        prescription = with_targets(prescription, sessions[-1], kind, rep_range, ladder, increment)
        status, status_reason = _reconcile_status(status, status_reason, prescription, sessions)
    return ExerciseAnalysis(
        name=name,
        kind=kind,
        sessions=sessions,
        rep_range=rep_range,
        ladder=ladder,
        increment=increment,
        scores=scores,
        status=status,
        status_reason=status_reason,
        change_4w=_pct_change(sessions, scores, 4),
        change_12w=_pct_change(sessions, scores, 12),
        prescription=prescription,
    )


def _global_reps_lost_per_10pct(sessions: dict[str, list[Session]], bodyweight: float) -> float:
    """Median rep cost across all exercises, for lifts with too few jumps of their own."""
    values = []
    for name, history in sessions.items():
        kind = "assisted" if is_assisted(name) else "weighted"
        value = reps_lost_per_10pct(history, kind, bodyweight)
        if value is not None:
            values.append(value)
    return float(median(values)) if values else DEFAULT_REPS_LOST_PER_10PCT


def analyze_all(
    connection: sqlite3.Connection,
    config: ProgressionConfig | None = None,
    as_of: date | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, ExerciseAnalysis]:
    """Analyze every exercise, ordered by most recent session first."""
    config = config or ProgressionConfig()
    if as_of is None:
        as_of = date.fromisoformat(end_date[:10]) if end_date else date.today()
    # Nothing after the evaluation date may influence it.
    cap = as_of.isoformat()
    end_date = min(end_date[:10], cap) if end_date else cap
    sessions = load_sessions(connection, start_date, end_date)
    configured = set(config.rep_ranges) | set(config.increments) | set(config.ladders)
    for name in sorted(configured - set(sessions)):
        logger.warning("Config names an exercise with no data (check spelling): %s", name)
    global_cost = _global_reps_lost_per_10pct(sessions, config.bodyweight)
    analyses = {
        name: analyze_exercise(name, s, config, as_of, global_cost) for name, s in sessions.items()
    }
    # Most recently trained first; ties broken alphabetically.
    by_name = sorted(analyses.items())
    by_recent = sorted(by_name, key=lambda kv: kv[1].sessions[-1].started_at, reverse=True)
    return dict(by_recent)


@dataclass(frozen=True)
class WorkoutPlan:
    name: str
    last_date: str
    exercises: list[str]


def plan_workouts(
    connection: sqlite3.Connection,
    analyses: dict[str, ExerciseAnalysis],
    as_of: date,
) -> tuple[list[WorkoutPlan], str | None]:
    """Group active exercises by workout, using each workout's latest session as the template.

    Exercise order follows the export's row order (Hevy numbers sets per exercise,
    so set_order cannot order exercises within a workout).

    Returns the plans and the workout predicted to come next in the rotation.
    """
    cutoff = (as_of - timedelta(days=ACTIVE_WINDOW_DAYS)).isoformat()
    rows = connection.execute(
        """
        SELECT workout_date, workout_name, exercise_name, MIN(id) AS first_row
        FROM sets
        WHERE workout_date >= ? AND workout_date <= ? AND (reps > 0 OR weight > 0)
        GROUP BY workout_date, workout_name, exercise_name
        ORDER BY workout_date, first_row
        """,
        (cutoff, as_of.isoformat() + " 23:59:59"),
    ).fetchall()
    sessions: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        if row["exercise_name"] in analyses:
            sessions[(row["workout_date"], row["workout_name"])].append(row["exercise_name"])
    ordered = sorted(sessions)
    latest: dict[str, tuple[str, list[str]]] = {}
    for key in ordered:
        latest[key[1]] = (key[0], sessions[key])
    plans = [
        WorkoutPlan(name=name, last_date=when[:10], exercises=exercises)
        for name, (when, exercises) in sorted(latest.items(), key=lambda kv: kv[0])
    ]

    titles = [key[1] for key in ordered]
    # Collapse consecutive duplicates (several exercises share one workout timestamp).
    sequence = [t for i, t in enumerate(titles) if i == 0 or titles[i - 1] != t]
    next_name: str | None = None
    if sequence:
        successors = Counter(b for a, b in zip(sequence, sequence[1:]) if a == sequence[-1])
        if successors:
            next_name = successors.most_common(1)[0][0]
        else:
            # Least recently trained workout is a reasonable guess.
            next_name = min(latest.items(), key=lambda kv: kv[1][0])[0]
    return plans, next_name


# Muscle mapping: first matching keyword wins, so specific patterns come first.
MUSCLE_RULES: tuple[tuple[str, str], ...] = (
    ("leg curl", "Hamstrings"),
    ("romanian", "Hamstrings"),
    ("rdl", "Hamstrings"),
    ("deadlift", "Hamstrings"),
    ("leg extension", "Quads"),
    ("split squat", "Quads"),
    ("rfe", "Quads"),
    ("squat", "Quads"),
    ("leg press", "Quads"),
    ("lunge", "Quads"),
    ("calf", "Calves"),
    ("hip abduct", "Glutes"),
    ("hip thrust", "Glutes"),
    ("glute", "Glutes"),
    ("rear delt", "Rear Delts"),
    ("reverse fly", "Rear Delts"),
    ("face pull", "Rear Delts"),
    ("lateral raise", "Side Delts"),
    ("shoulder press", "Front Delts"),
    ("overhead press", "Front Delts"),
    ("tricep", "Triceps"),
    ("dip", "Triceps"),
    ("skull", "Triceps"),
    ("curl", "Biceps"),
    ("pull up", "Back"),
    ("pullup", "Back"),
    ("chin up", "Back"),
    ("pulldown", "Back"),
    ("row", "Back"),
    ("straight arm", "Back"),
    ("bench", "Chest"),
    ("chest", "Chest"),
    ("fly", "Chest"),
    ("crossover", "Chest"),
    ("push up", "Chest"),
    ("crunch", "Abs"),
    ("plank", "Abs"),
    ("ab ", "Abs"),
)

# Approximate weekly hard-set guidelines (low end of productive range, high end of
# the adaptive range), loosely following commonly published hypertrophy volume guidelines.
VOLUME_TARGETS: dict[str, tuple[int, int]] = {
    "Chest": (10, 20),
    "Back": (10, 22),
    "Side Delts": (8, 22),
    "Rear Delts": (6, 18),
    "Front Delts": (0, 12),
    "Biceps": (8, 20),
    "Triceps": (6, 16),
    "Quads": (8, 18),
    "Hamstrings": (6, 16),
    "Glutes": (0, 12),
    "Calves": (8, 16),
    "Abs": (0, 20),
}


def muscle_for(exercise_name: str) -> str:
    lowered = exercise_name.lower() + " "
    for keyword, muscle in MUSCLE_RULES:
        if keyword in lowered:
            return muscle
    return "Other"


def weekly_muscle_volume(
    analyses: dict[str, ExerciseAnalysis], as_of: date, weeks: int = 12
) -> dict[str, object]:
    """Hard sets (not warm-ups or drop sets) per muscle per ISO week (Monday start)."""
    this_monday = as_of - timedelta(days=as_of.weekday())
    week_starts = [this_monday - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    index = {w: i for i, w in enumerate(week_starts)}
    counts: dict[str, list[int]] = defaultdict(lambda: [0] * weeks)
    unmapped: set[str] = set()
    for name, analysis in analyses.items():
        muscle = muscle_for(name)
        if muscle == "Other":
            unmapped.add(name)
        for session in analysis.sessions:
            monday = session.day - timedelta(days=session.day.weekday())
            if monday in index:
                # Every hard set counts, including back-off and pyramid sets.
                counts[muscle][index[monday]] += sum(
                    1 for st in session.sets if st.set_type not in NON_WORKING_SET_TYPES and st.reps > 0
                )
    muscles = [m for m in list(VOLUME_TARGETS) + ["Other"] if m in counts and any(counts[m])]
    return {
        "weeks": [w.isoformat() for w in week_starts],
        "muscles": muscles,
        "sets": {m: counts[m] for m in muscles},
        "targets": {m: VOLUME_TARGETS.get(m) for m in muscles},
        "unmapped": sorted(unmapped),
    }
