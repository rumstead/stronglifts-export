from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

from lifting_data import email_ingest as email_ingest_module
from lifting_data.db import connect, init_db
from lifting_data.email_ingest import EmailIngestConfig, ingest_from_gmail


class _FakeImap:
    def __init__(self, _host: str, _port: int) -> None:
        message = EmailMessage()
        message["From"] = "me@example.com"
        message["Subject"] = "Strong export"
        message["Message-Id"] = "<message-1>"
        message.set_content("Attached")
        message.add_attachment(
            (
                "Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,RPE\n"
                "2026-05-01,Push Day,3600,Bench Press,1,100,5,,,8\n"
            ).encode("utf-8"),
            maintype="text",
            subtype="csv",
            filename="strong.csv",
        )
        self._raw_message = message.as_bytes()

    def login(self, _username: str, _app_password: str):
        return "OK", [b""]

    def create(self, _mailbox: str):
        return "OK", [b""]

    def select(self, _mailbox: str):
        return "OK", [b""]

    def search(self, _charset, _criteria: str):
        return "OK", [b"1"]

    def fetch(self, _raw_msg_id: bytes, _request: str):
        return "OK", [(b"1", self._raw_message)]

    def copy(self, _raw_msg_id: bytes, _destination_mailbox: str):
        return "OK", [b""]

    def store(self, _raw_msg_id: bytes, _flags_op: str, _flags: str):
        return "OK", [b""]

    def expunge(self):
        return "OK", [b""]

    def close(self):
        return "OK", [b""]

    def logout(self):
        return "BYE", [b""]


class _FakeHevyImap(_FakeImap):
    def __init__(self, host: str, port: int) -> None:
        super().__init__(host, port)
        message = EmailMessage()
        message["From"] = "me@example.com"
        message["Subject"] = "Hevy export"
        message["Message-Id"] = "<hevy-message-1>"
        message.set_content("Attached")
        message.add_attachment(
            (
                "title,start_time,end_time,exercise_title,set_index,set_type,weight_kg,reps\n"
                "Push Day,2026-05-01 08:00,2026-05-01 09:00,Bench Press,0,normal,100,5\n"
            ).encode("utf-8"),
            maintype="text",
            subtype="csv",
            filename="hevy.csv",
        )
        self._raw_message = message.as_bytes()


def _config(download_dir: Path, dry_run: bool) -> EmailIngestConfig:
    return EmailIngestConfig(
        imap_host="imap.example.com",
        imap_port=993,
        username="me@example.com",
        app_password="app-password",
        source_mailbox="INBOX",
        processed_mailbox="INBOX/Processed",
        sender_allowlist=("me@example.com",),
        subject_contains=None,
        download_dir=str(download_dir),
        dry_run=dry_run,
    )


def test_dry_run_does_not_mark_attachments_processed(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "lifts.db"
    connection = connect(str(db_path))
    init_db(connection)

    monkeypatch.setattr(email_ingest_module.imaplib, "IMAP4_SSL", _FakeImap)

    dry_run_result = ingest_from_gmail(connection, _config(tmp_path / "downloads", dry_run=True))

    assert dry_run_result.attachments_seen == 1
    assert dry_run_result.attachments_ingested == 0
    assert not (tmp_path / "downloads").exists()

    processed_after_dry_run = connection.execute("SELECT COUNT(*) AS c FROM email_imports").fetchone()["c"]
    assert processed_after_dry_run == 0

    non_dry_run_result = ingest_from_gmail(connection, _config(tmp_path / "downloads", dry_run=False))

    assert non_dry_run_result.attachments_ingested == 1

    processed_after_real_run = connection.execute("SELECT COUNT(*) AS c FROM email_imports").fetchone()["c"]
    assert processed_after_real_run == 1


def test_dry_run_accepts_hevy_without_side_effects(tmp_path: Path, monkeypatch) -> None:
    connection = connect(str(tmp_path / "lifts.db"))
    init_db(connection)
    monkeypatch.setattr(email_ingest_module.imaplib, "IMAP4_SSL", _FakeHevyImap)

    result = ingest_from_gmail(
        connection, _config(tmp_path / "downloads", dry_run=True)
    )

    assert result.attachments_seen == 1
    assert result.attachments_invalid == 0
    assert result.attachments_ingested == 0
    assert not (tmp_path / "downloads").exists()
    assert connection.execute("SELECT COUNT(*) FROM sets").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM email_imports").fetchone()[0] == 0
