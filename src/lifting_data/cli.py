from __future__ import annotations

import argparse
import logging
import os
import sqlite3
from datetime import date

from .charts import generate_all_exercises_page, generate_exercise_progress_chart
from .db import connect, init_db
from .email_ingest import EmailIngestConfig, ingest_from_gmail
from .ingest import ingest_csv
from .progression import analyze_all, load_config, plan_workouts


def _add_progression_args(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--config",
        default=None,
        help="Optional progression TOML (rep ranges, increments, weight ladders)",
    )
    subparser.add_argument(
        "--as-of",
        default=None,
        help="Evaluate as of this date (YYYY-MM-DD, default: today)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Strong and Hevy CSV ingest and charting")
    parser.add_argument("--db", default="data/lifts.db", help="Path to SQLite database")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize database schema")

    ingest_parser = subparsers.add_parser("ingest", help="Ingest a Strong or Hevy CSV export")
    ingest_parser.add_argument("--csv", required=True, help="Path to workout CSV file")
    ingest_parser.add_argument(
        "--format",
        choices=("auto", "strong", "hevy"),
        default="auto",
        help="CSV format (default: detect from headers)",
    )

    list_parser = subparsers.add_parser("list-exercises", help="List ingested exercise names")
    list_parser.add_argument("--limit", type=int, default=100, help="Max rows to print")

    plot_parser = subparsers.add_parser("plot", help="Generate exercise progress chart")
    plot_parser.add_argument("--exercise", required=True, help="Exercise name to chart")
    plot_parser.add_argument("--output", required=True, help="Output HTML file path")
    plot_parser.add_argument("--start", help="Start date filter (YYYY-MM-DD)")
    plot_parser.add_argument("--end", help="End date filter (YYYY-MM-DD)")
    _add_progression_args(plot_parser)

    plot_all_parser = subparsers.add_parser(
        "plot-all", help="Generate the dashboard: next workout, progress board, exercise detail, volume"
    )
    plot_all_parser.add_argument("--output", default="output/index.html", help="Output HTML file path")
    plot_all_parser.add_argument("--start", help="Start date filter (YYYY-MM-DD)")
    plot_all_parser.add_argument("--end", help="End date filter (YYYY-MM-DD)")
    _add_progression_args(plot_all_parser)

    next_parser = subparsers.add_parser(
        "next-workout", help="Print recommended weight, sets, and reps for the next session"
    )
    next_parser.add_argument(
        "--workout", default=None, help="Workout name (default: the one predicted next in your rotation)"
    )
    _add_progression_args(next_parser)

    ranges_parser = subparsers.add_parser(
        "rep-ranges", help="Print each active exercise's rep range, weight steps, and status"
    )
    ranges_parser.add_argument("--all", action="store_true", help="Include archived exercises")
    _add_progression_args(ranges_parser)

    email_parser = subparsers.add_parser(
        "ingest-email", help="Ingest Strong or Hevy CSV attachments from Gmail"
    )
    email_parser.add_argument("--imap-host", default="imap.gmail.com", help="IMAP host")
    email_parser.add_argument("--imap-port", type=int, default=993, help="IMAP TLS port")
    email_parser.add_argument("--imap-user", required=True, help="Gmail address used for IMAP")
    email_parser.add_argument(
        "--imap-password-env",
        default="GMAIL_APP_PASSWORD",
        help="Environment variable containing Gmail app password",
    )
    email_parser.add_argument("--source-mailbox", default="INBOX", help="Mailbox to scan for new exports")
    email_parser.add_argument(
        "--processed-mailbox",
        default="Strong/Processed",
        help="Mailbox/folder to move processed emails into",
    )
    email_parser.add_argument(
        "--allow-sender",
        action="append",
        default=[],
        help="Sender email allow-list entry (repeat flag for multiple)",
    )
    email_parser.add_argument(
        "--allow-all-senders",
        action="store_true",
        help="Explicitly allow all senders (disables sender allow-list guardrail)",
    )
    email_parser.add_argument(
        "--subject-contains",
        default=None,
        help="Optional subject substring filter for candidate messages",
    )
    email_parser.add_argument(
        "--download-dir",
        default="data/email-attachments",
        help="Local directory used for downloaded attachments",
    )
    email_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and validate attachments without ingest or moving messages",
    )

    return parser


def _as_of(args: argparse.Namespace) -> date:
    """Evaluation date: --as-of, else --end (when given), else today."""
    if args.as_of:
        return date.fromisoformat(args.as_of)
    end = getattr(args, "end", None)
    return date.fromisoformat(end[:10]) if end else date.today()


def _print_next_workout(connection: sqlite3.Connection, args: argparse.Namespace) -> int:
    as_of = _as_of(args)
    analyses = analyze_all(connection, load_config(args.config), as_of)
    plans, predicted = plan_workouts(connection, analyses, as_of)
    if not plans:
        print("No workouts in the last 60 days.")
        return 1
    wanted = args.workout or predicted or plans[0].name
    plan = next((p for p in plans if p.name.lower() == wanted.lower()), None)
    if plan is None:
        names = ", ".join(p.name for p in plans)
        print(f"Unknown workout '{wanted}'. Recent workouts: {names}")
        return 1
    label = " (up next)" if plan.name == predicted else ""
    print(f"{plan.name}{label} — based on your session on {plan.last_date}")
    for name in plan.exercises:
        analysis = analyses[name]
        rx = analysis.prescription
        if rx is None:
            continue
        print(f"\n  {name}  [{analysis.status}]")
        print(f"    Next: {rx.describe()}")
        print(f"    Why:  {rx.reason}")
        print(f"    Effort: {rx.effort}")
        print(f"    Next step: {rx.goal}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "ingest-email" and args.dry_run:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        init_db(connection)
    else:
        connection = connect(args.db)
        init_db(connection)

    if args.command == "init-db":
        print(f"Initialized database at {args.db}")
        return 0

    if args.command == "ingest":
        result = ingest_csv(connection, args.csv, csv_format=args.format)
        print(f"Import complete: inserted={result.inserted}, skipped={result.skipped}")
        return 0

    if args.command == "list-exercises":
        rows = connection.execute(
            """
            SELECT exercise_name, COUNT(*) AS set_count
            FROM sets
            GROUP BY exercise_name
            ORDER BY set_count DESC, exercise_name ASC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
        for row in rows:
            print(f"{row['exercise_name']}: {row['set_count']} sets")
        return 0

    if args.command == "plot":
        points = generate_exercise_progress_chart(
            connection,
            exercise_name=args.exercise,
            output_path=args.output,
            start_date=args.start,
            end_date=args.end,
            config=load_config(args.config),
            as_of=_as_of(args),
        )
        print(f"Chart generated with {points} points at {args.output}")
        return 0

    if args.command == "plot-all":
        count = generate_all_exercises_page(
            connection,
            output_path=args.output,
            start_date=args.start,
            end_date=args.end,
            config=load_config(args.config),
            as_of=_as_of(args),
        )
        print(f"Generated page with {count} exercises at {args.output}")
        return 0

    if args.command == "next-workout":
        return _print_next_workout(connection, args)

    if args.command == "rep-ranges":
        as_of = _as_of(args)
        analyses = analyze_all(connection, load_config(args.config), as_of)
        for name, analysis in analyses.items():
            if analysis.status == "Archived" and not args.all:
                continue
            low, high = analysis.rep_range.low, analysis.rep_range.high
            steps = "observed weights" if analysis.ladder else f"+{analysis.increment:g} lb"
            print(
                f"{name}: {low}-{high} reps ({analysis.rep_range.source}), steps {steps}, "
                f"status {analysis.status}"
            )
        return 0

    if args.command == "ingest-email":
        app_password = os.getenv(args.imap_password_env)
        if not app_password:
            parser.error(f"Missing app password environment variable: {args.imap_password_env}")
        if not args.allow_sender and not args.allow_all_senders:
            parser.error("Provide at least one --allow-sender or use --allow-all-senders explicitly")

        config = EmailIngestConfig(
            imap_host=args.imap_host,
            imap_port=args.imap_port,
            username=args.imap_user,
            app_password=app_password,
            source_mailbox=args.source_mailbox,
            processed_mailbox=args.processed_mailbox,
            sender_allowlist=tuple(args.allow_sender),
            subject_contains=args.subject_contains,
            download_dir=args.download_dir,
            allow_all_senders=args.allow_all_senders,
            dry_run=args.dry_run,
        )
        result = ingest_from_gmail(connection, config)
        print(
            "Email ingest complete: "
            f"messages_seen={result.messages_seen}, "
            f"messages_rejected_sender={result.messages_rejected_sender}, "
            f"messages_rejected_subject={result.messages_rejected_subject}, "
            f"attachments_seen={result.attachments_seen}, "
            f"attachments_ingested={result.attachments_ingested}, "
            f"attachments_skipped={result.attachments_skipped}, "
            f"attachments_invalid={result.attachments_invalid}, "
            f"sets_inserted={result.sets_inserted}, "
            f"sets_skipped={result.sets_skipped}, "
            f"messages_moved={result.messages_moved}"
        )
        return 0

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
