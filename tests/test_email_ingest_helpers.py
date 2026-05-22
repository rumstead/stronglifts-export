from __future__ import annotations

from pathlib import Path

from lifting_data.db import connect, init_db
from lifting_data.email_ingest import (
    attachment_hash,
    has_processed_email_attachment,
    is_attachment_csv,
    record_processed_email_attachment,
    sender_is_allowed,
)


def test_sender_allowlist_matching() -> None:
    allowlist = ("me@example.com", "other@example.com")
    assert sender_is_allowed("me@example.com", allowlist)
    assert sender_is_allowed("ME@EXAMPLE.COM", allowlist)
    assert not sender_is_allowed("nope@example.com", allowlist)
    assert not sender_is_allowed("me@example.com", ())
    assert sender_is_allowed("anyone@example.com", (), allow_all_senders=True)


def test_attachment_csv_detection() -> None:
    assert is_attachment_csv("strong-export.csv", "application/octet-stream")
    assert is_attachment_csv("attachment", "text/csv")
    assert not is_attachment_csv("image.png", "image/png")


def test_processed_attachment_dedupe_tracking(tmp_path: Path) -> None:
    db_path = tmp_path / "lifts.db"
    connection = connect(str(db_path))
    init_db(connection)

    file_hash = attachment_hash(b"csv-bytes")
    assert not has_processed_email_attachment(connection, "<message-1>", "strong.csv", file_hash)

    record_processed_email_attachment(
        connection,
        message_id="<message-1>",
        sender_email="me@example.com",
        subject="Strong export",
        attachment_name="strong.csv",
        file_hash=file_hash,
        source_mailbox="INBOX",
        inserted_sets=2,
        skipped_sets=0,
    )

    assert has_processed_email_attachment(connection, "<message-1>", "strong.csv", file_hash)
