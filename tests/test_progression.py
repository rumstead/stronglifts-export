from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from lifting_data.charts import generate_all_exercises_page
from lifting_data.db import connect, init_db
from lifting_data.ingest import ingest_csv
from lifting_data.progression import (
    ProgressionConfig,
    Session,
    SetRecord,
    analyze_all,
    analyze_exercise,
    classify_working_sets,
    infer_rep_range,
    load_config,
    muscle_for,
    plan_workouts,
    post_increase_targets,
    reps_lost_per_10pct,
    snap_rep_range,
    weekly_muscle_volume,
)

START = date(2026, 9, 1)


def _session(day: int, sets: list[tuple[float, int]] | list[tuple[float, int, float | None, str]], assisted: bool = False, workout: str = "Upper") -> Session:
    records = []
    for entry in sets:
        weight, reps, *rest = entry
        rpe = rest[0] if rest else None
        set_type = rest[1] if len(rest) > 1 else "normal"
        records.append(SetRecord(float(weight), int(reps), rpe, set_type))
    session = Session(
        started_at=(START + timedelta(days=day)).isoformat() + " 07:00:00",
        workout_name=workout,
        sets=records,
        assisted=assisted,
    )
    classify_working_sets(session)
    return session


def _analyze(name: str, sessions: list[Session], as_of_day: int | None = None, config: ProgressionConfig | None = None):
    if as_of_day is None:
        as_of_day = (sessions[-1].day - START).days + 2
    as_of = START + timedelta(days=as_of_day)
    return analyze_exercise(name, sessions, config or ProgressionConfig(), as_of)


# ---- working sets ----

def test_heavy_single_and_warmups_do_not_define_working_weight() -> None:
    session = _session(0, [(135, 10, None, "warmup"), (255, 1), (205, 8), (205, 8), (205, 7)])
    assert session.working_weight == 205
    assert session.reps == [8, 8, 7]


def test_light_ramp_up_set_is_not_a_working_set() -> None:
    session = _session(0, [(50, 10), (70, 7), (70, 6)])
    assert session.working_weight == 70
    assert session.reps == [7, 6]


def test_dropsets_are_excluded() -> None:
    session = _session(0, [(100, 10), (100, 9), (60, 12, None, "dropset")])
    assert session.reps == [10, 9]


def test_assisted_prefers_least_assistance_and_ignores_blank_assistance() -> None:
    session = _session(0, [(0, 8), (40, 7), (20, 7), (20, 5)], assisted=True)
    assert session.working_weight == 20
    assert session.reps == [7, 5]


# ---- rep ranges ----

def test_rep_range_inferred_from_weight_increases() -> None:
    # Moves up after hitting 8, lands at 5-6 on the new weight: a 5-8 range.
    sessions = [
        _session(0, [(185, 8), (185, 8), (185, 8)]),
        _session(4, [(195, 6), (195, 6), (195, 5)]),
        _session(8, [(195, 8), (195, 8), (195, 8)]),
        _session(12, [(205, 6), (205, 5), (205, 5)]),
    ]
    rep_range = infer_rep_range(sessions, assisted=False)
    assert (rep_range.low, rep_range.high) == (5, 8)


def test_new_exercise_uses_default_rep_range() -> None:
    rep_range = infer_rep_range([_session(0, [(40, 10), (40, 8)])], assisted=False)
    assert (rep_range.low, rep_range.high, rep_range.source) == (8, 12, "default")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [((5, 8), (5, 8)), ((7, 10), (6, 10)), ((9, 12), (8, 12)), ((8, 11), (8, 10)), ((10, 12), (10, 12)), ((3, 12), (6, 12))],
)
def test_snap_rep_range(raw: tuple[float, float], expected: tuple[int, int]) -> None:
    assert snap_rep_range(*raw) == expected


def test_config_rep_range_overrides_inference(tmp_path: Path) -> None:
    config_path = tmp_path / "progression.toml"
    config_path.write_text(
        '[defaults]\nincrement = 2.5\n\n[exercises."Bench Press"]\nrep_range = [6, 10]\n',
        encoding="utf-8",
    )
    config = load_config(str(config_path))
    analysis = _analyze("Bench Press", [_session(0, [(100, 10), (100, 10)])], config=config)
    assert (analysis.rep_range.low, analysis.rep_range.high, analysis.rep_range.source) == (6, 10, "config")
    assert analysis.prescription is not None
    assert analysis.prescription.weight == 102.5


# ---- prescriptions ----

def _bench_history() -> list[Session]:
    return [
        _session(0, [(185, 8), (185, 8), (185, 8)]),
        _session(4, [(195, 6), (195, 6), (195, 5)]),
        _session(8, [(195, 8), (195, 8), (195, 8)]),
        _session(12, [(205, 6), (205, 5), (205, 5)]),
    ]


def test_top_of_range_on_every_set_moves_up_by_increment() -> None:
    sessions = _bench_history() + [_session(16, [(205, 8), (205, 8), (205, 8)])]
    rx = _analyze("Bench Press", sessions).prescription
    assert rx.action == "increase"
    assert rx.weight == 210
    # A 2.4% jump costs well under a rep, so the targets stay at 8 instead of resetting to 5.
    assert rx.target_reps == (8, 8, 8)


def _targets(reps, rpe, weight, new_weight, per_10pct, low=5, high=12):
    return post_increase_targets(reps, rpe, weight, new_weight, "weighted", 180.0, low, high, per_10pct)


def test_post_increase_targets_scale_with_jump_size() -> None:
    # Lifter who loses ~0.8 reps per 10%: a 5% jump keeps reps, a 33% jump costs ~3.
    assert _targets([10, 10, 10], None, 95, 100, 0.8) == (10, 10, 10)
    assert _targets([12, 12, 11], None, 15, 20, 0.8) == (9, 9, 8)


def test_post_increase_targets_use_rpe_reserve() -> None:
    # Same 15% jump: an easy RPE 7 session keeps more reps than a grinding RPE 10 one.
    easy = _targets([8, 8, 8], 7.0, 200, 230, 2.0)
    grind = _targets([8, 8, 8], 10.0, 200, 230, 2.0)  # low defaults to 5
    # 15% jump at 2 reps per 10% costs 3 reps; RPE 7 adds back 2, RPE 10 takes 1 more.
    assert easy == (7, 7, 7)
    assert grind == (5, 5, 5)  # 4 predicted, held at the bottom of the range


def test_post_increase_targets_stay_in_range_and_below_last_reps() -> None:
    assert _targets([10, 10, 10], 9.0, 100, 200, 3.0, low=8, high=10) == (8, 8, 8)
    assert _targets([10, 9, 9], 9.0, 100, 101, 0.5, low=6, high=12) == (10, 9, 9)


def test_reps_lost_per_10pct_measured_from_history() -> None:
    sessions = [
        _session(0, [(100, 10), (100, 10)]),
        _session(4, [(110, 9), (110, 9)]),  # +10%, -1 rep
        _session(8, [(110, 10), (110, 10)]),
        _session(12, [(121, 9), (121, 9)]),  # +10%, -1 rep
        _session(16, [(121, 10), (121, 10)]),
        _session(20, [(133.1, 9), (133.1, 9)]),  # +10%, -1 rep
    ]
    assert reps_lost_per_10pct(sessions, "weighted", 180.0) == pytest.approx(1.0)
    assert reps_lost_per_10pct(sessions[:4], "weighted", 180.0) is None


def test_within_range_adds_a_rep_to_the_weakest_set() -> None:
    sessions = _bench_history() + [_session(16, [(205, 8), (205, 7), (205, 6)])]
    rx = _analyze("Bench Press", sessions).prescription
    assert rx.action == "add-reps"
    assert rx.weight == 205
    assert rx.target_reps == (8, 7, 7)


def test_easy_session_by_rpe_adds_a_rep_to_every_set() -> None:
    sessions = _bench_history() + [_session(16, [(205, 7, 7.5, "normal"), (205, 7, 8.0, "normal"), (205, 6, 8.0, "normal")])]
    rx = _analyze("Bench Press", sessions).prescription
    assert rx.target_reps == (8, 8, 7)
    assert "reps in reserve" in rx.reason


def test_odd_step_equipment_moves_to_next_weight_you_have_used() -> None:
    sessions = [
        _session(0, [(143, 10), (143, 10), (143, 10)]),
        _session(4, [(148, 8), (148, 7), (148, 7)]),
        _session(8, [(153, 7), (153, 7), (153, 6)]),
        _session(12, [(148, 10), (148, 10), (148, 10)]),
    ]
    analysis = _analyze("Lat Pulldown (Cable)", sessions)
    assert analysis.ladder == (143, 148, 153)
    assert analysis.prescription.action == "increase"
    assert analysis.prescription.weight == 153


def test_below_range_twice_without_improvement_drops_back() -> None:
    sessions = [
        _session(0, [(75, 8), (75, 8), (75, 8)]),
        _session(4, [(80, 6), (80, 6), (80, 6)]),
        _session(8, [(80, 8), (80, 8), (80, 8)]),
        _session(12, [(85, 6), (85, 5), (85, 4)]),  # range is 5-8: below on the last set
        _session(16, [(85, 6), (85, 4), (85, 4)]),  # below again, and no better
    ]
    rx = _analyze("Incline Bench Press (Dumbbell)", sessions).prescription
    assert rx.action == "drop-back"
    assert rx.weight == 80


def test_no_rep_gains_in_three_sessions_deloads() -> None:
    sessions = _bench_history() + [
        _session(16, [(205, 7), (205, 7), (205, 7)]),  # best at this weight
        _session(20, [(205, 7), (205, 7), (205, 6)]),
        _session(24, [(205, 7), (205, 6), (205, 6)]),
        _session(28, [(205, 7), (205, 7), (205, 6)]),
    ]
    rx = _analyze("Bench Press", sessions).prescription
    assert rx.action == "deload"
    assert rx.weight == 185  # 205 * 0.9 = 184.5, rounded to the 5 lb step


def test_layoff_eases_back_in() -> None:
    sessions = _bench_history()
    analysis = _analyze("Bench Press", sessions, as_of_day=12 + 20)
    assert analysis.status == "Returning"
    assert analysis.prescription.action == "return"
    assert analysis.prescription.weight == 185


def test_assisted_progress_means_less_assistance() -> None:
    sessions = [
        _session(0, [(60, 8), (60, 8), (60, 8)], assisted=True),
        _session(4, [(40, 6), (40, 6), (40, 6)], assisted=True),
        _session(8, [(40, 8), (40, 8), (40, 8)], assisted=True),
        _session(12, [(20, 6), (20, 6), (20, 5)], assisted=True),
        _session(16, [(20, 8), (20, 8), (20, 8)], assisted=True),
    ]
    analysis = _analyze("Pull Up (Assisted)", sessions)
    assert analysis.kind == "assisted"
    assert analysis.status == "Progressing"
    assert analysis.prescription.action == "increase"
    assert analysis.prescription.weight < 20


def test_more_assistance_is_not_progress() -> None:
    sessions = [_session(d * 4, [(20, 8), (20, 8), (20, 8)], assisted=True) for d in range(4)]
    sessions += [_session(16 + d * 4, [(60, 8), (60, 8), (60, 8)], assisted=True) for d in range(3)]
    analysis = _analyze("Pull Up (Assisted)", sessions)
    assert analysis.status == "Regressing"


def test_old_history_is_archived_without_prescription() -> None:
    analysis = _analyze("Bench Press", _bench_history(), as_of_day=200)
    assert analysis.status == "Archived"
    assert analysis.prescription is None


# ---- muscles ----

@pytest.mark.parametrize(
    ("name", "muscle"),
    [
        ("Seated Leg Curl (Machine)", "Hamstrings"),
        ("Seated Incline Curl (Dumbbell)", "Biceps"),
        ("Lat Pulldown (Cable)", "Back"),
        ("Rear Delt Reverse Fly (Cable)", "Rear Delts"),
        ("Cable Fly Crossovers", "Chest"),
        ("Bulgarian Split Squat (Dumbbell)", "Quads"),
        ("Triceps Pushdown", "Triceps"),
        ("Lateral Raise (Cable)", "Side Delts"),
        ("Mystery Machine", "Other"),
    ],
)
def test_muscle_mapping(name: str, muscle: str) -> None:
    assert muscle_for(name) == muscle


# ---- integration with a Hevy export ----

HEVY_HEADER = (
    "title,start_time,end_time,description,exercise_title,superset_id,"
    "exercise_notes,set_index,set_type,weight_lbs,reps,distance_miles,duration_seconds,rpe\n"
)


def _hevy_row(title: str, when: str, exercise: str, index: int, weight: float, reps: int, rpe: str = "", set_type: str = "normal") -> str:
    return f'{title},"{when}","{when}",,{exercise},,,{index},{set_type},{weight},{reps},,,{rpe}\n'


def test_plan_follows_rotation_and_exercise_order(tmp_path: Path) -> None:
    rows = []
    days = [("Upper", "1 Oct 2026, 07:00"), ("Lower", "3 Oct 2026, 07:00"), ("Upper", "6 Oct 2026, 07:00"), ("Lower", "8 Oct 2026, 07:00"), ("Upper", "10 Oct 2026, 07:00")]
    for title, when in days:
        if title == "Upper":
            # Row order (not name order) defines exercise order within a workout.
            rows += [_hevy_row(title, when, "Squat Rack Row", i, 100, 10, "9") for i in range(3)]
            rows += [_hevy_row(title, when, "Bench Press (Barbell)", i, 200, 8, "9") for i in range(3)]
        else:
            rows += [_hevy_row(title, when, "Leg Extension (Machine)", i, 150, 10, "9") for i in range(3)]
    csv_path = tmp_path / "hevy.csv"
    csv_path.write_text(HEVY_HEADER + "".join(rows), encoding="utf-8")

    connection = connect(str(tmp_path / "lifts.db"))
    init_db(connection)
    ingest_csv(connection, str(csv_path))

    as_of = date(2026, 10, 11)
    analyses = analyze_all(connection, as_of=as_of)
    plans, next_name = plan_workouts(connection, analyses, as_of)

    assert next_name == "Lower"
    upper = next(p for p in plans if p.name == "Upper")
    assert upper.exercises == ["Squat Rack Row", "Bench Press (Barbell)"]
    assert analyses["Bench Press (Barbell)"].sessions[-1].rpes == [9.0, 9.0, 9.0]

    output = tmp_path / "index.html"
    count = generate_all_exercises_page(connection, str(output), as_of=as_of)
    html = output.read_text(encoding="utf-8")
    assert count == 3
    assert '"next_workout": "Lower"' in html
    assert "Hard sets per muscle per week" in html


# ---- regressions from code review ----

def test_weighted_after_bodyweight_sessions_does_not_crash() -> None:
    sessions = [_session(d * 3, [(0, 10), (0, 10), (0, 10)]) for d in range(6)]
    sessions += [_session(18 + d * 3, [(25, 10), (25, 10), (25, 10)]) for d in range(3)]
    analysis = _analyze("Chest Dip", sessions)
    assert analysis.kind == "weighted"
    assert analysis.prescription is not None


def test_drop_back_is_never_reported_as_progressing() -> None:
    sessions = [
        _session(0, [(75, 8), (75, 8), (75, 8)]),
        _session(4, [(80, 6), (80, 6), (80, 6)]),
        _session(8, [(80, 8), (80, 8), (80, 6)]),
        _session(12, [(85, 6), (85, 5), (85, 4)]),
        _session(16, [(85, 6), (85, 4), (85, 4)]),
    ]
    analysis = _analyze("Incline Bench Press (Dumbbell)", sessions)
    assert analysis.prescription.action == "drop-back"
    assert analysis.status == "Regressing"


def test_lone_top_set_at_last_sessions_weight_is_kept() -> None:
    first = _session(0, [(250, 10), (250, 10), (250, 9)])
    second = Session(
        started_at="2026-09-08 07:00:00",
        workout_name="Upper",
        sets=[SetRecord(220, 9, 8.5, "normal"), SetRecord(220, 8, 9.0, "normal"), SetRecord(250, 8, 9.5, "normal")],
    )
    classify_working_sets(second, previous_weight=first.working_weight)
    assert second.working_weight == 250
    # A lone heavy single is still a test, not the working weight.
    single = Session("2026-09-08 07:00:00", "Upper", [SetRecord(255, 1, None, "normal"), SetRecord(205, 8, None, "normal"), SetRecord(205, 8, None, "normal")])
    classify_working_sets(single, previous_weight=255)
    assert single.working_weight == 205


def test_deload_does_not_use_a_stack_step_that_barely_cuts() -> None:
    sessions = [
        _session(0, [(148, 10), (148, 10), (148, 10)]),
        _session(4, [(153, 10), (153, 9), (153, 9)]),  # best at 153
        _session(8, [(153, 9), (153, 8), (153, 8)]),
        _session(12, [(153, 9), (153, 8), (153, 7)]),
        _session(16, [(153, 9), (153, 9), (153, 8)]),
    ]
    rx = _analyze("Lat Pulldown (Cable)", sessions).prescription
    assert rx.action == "deload"
    assert rx.weight == 140  # 148 would only be a 3% cut
    assert "8%" in rx.reason


def test_assisted_at_zero_assistance_progresses_like_bodyweight() -> None:
    sessions = [_session(d * 4, [(0, 8), (0, 8), (0, 8)], assisted=True) for d in range(5)]
    analysis = _analyze("Pull Up (Assisted)", sessions)
    assert analysis.kind == "bodyweight"
    assert analysis.prescription.describe().startswith("Bodyweight")
    assert "lb" not in analysis.prescription.goal


def test_single_top_set_gets_a_single_target() -> None:
    sessions = [_session(d * 4, [(135 + 5 * d, 5)]) for d in range(5)]
    assert _analyze("Bench Press", sessions).prescription.sets == 1


def test_extra_sets_are_padded_after_adding_the_rep() -> None:
    sessions = [_session(d * 4, [(73, 8), (73, 8), (73, 8)]) for d in range(2)]
    sessions.append(_session(8, [(73, 7), (73, 7)]))
    rx = _analyze("Triceps Pushdown", sessions).prescription
    assert rx.target_reps == (7, 8, 7)


def _db_with(tmp_path: Path, rows: list[str]):
    csv_path = tmp_path / "hevy.csv"
    csv_path.write_text(HEVY_HEADER + "".join(rows), encoding="utf-8")
    connection = connect(str(tmp_path / "lifts.db"))
    init_db(connection)
    ingest_csv(connection, str(csv_path))
    return connection


def test_as_of_ignores_later_sessions(tmp_path: Path) -> None:
    rows = [_hevy_row("Upper", "1 Oct 2026, 07:00", "Bench Press (Barbell)", i, 200, 8) for i in range(3)]
    rows += [_hevy_row("Upper", "20 Oct 2026, 07:00", "Bench Press (Barbell)", i, 225, 8) for i in range(3)]
    connection = _db_with(tmp_path, rows)
    analysis = analyze_all(connection, as_of=date(2026, 10, 5))["Bench Press (Barbell)"]
    assert analysis.sessions[-1].working_weight == 200
    plans, _ = plan_workouts(connection, {"Bench Press (Barbell)": analysis}, date(2026, 10, 5))
    assert plans[0].last_date == "2026-10-01"


def test_volume_counts_back_off_sets(tmp_path: Path) -> None:
    rows = [_hevy_row("Upper", "5 Oct 2026, 07:00", "Bench Press (Barbell)", i, w, r) for i, (w, r) in enumerate([(225, 5), (225, 5), (185, 10)])]
    rows.append(_hevy_row("Upper", "5 Oct 2026, 07:00", "Bench Press (Barbell)", 3, 95, 10, set_type="warmup"))
    connection = _db_with(tmp_path, rows)
    as_of = date(2026, 10, 7)
    volume = weekly_muscle_volume(analyze_all(connection, as_of=as_of), as_of)
    assert volume["sets"]["Chest"][-1] == 3


def test_unknown_config_exercise_is_warned(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    rows = [_hevy_row("Upper", "5 Oct 2026, 07:00", "Bench Press (Barbell)", i, 200, 8) for i in range(3)]
    connection = _db_with(tmp_path, rows)
    config = ProgressionConfig(rep_ranges={"Bench Pres (Barbell)": (6, 8)})
    with caplog.at_level("WARNING"):
        analyze_all(connection, config=config, as_of=date(2026, 10, 7))
    assert "Bench Pres (Barbell)" in caplog.text
