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
    snap_rep_range,
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
    assert rx.target_reps == (5, 5, 5)


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
