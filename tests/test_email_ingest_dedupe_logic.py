from __future__ import annotations

from pathlib import Path

from lifting_data.db import connect, init_db
from lifting_data.email_ingest import (
    attachment_hash,
    has_processed_email_attachment,
    record_processed_email_attachment,
)


def test_same_message_allows_multiple_distinct_attachments(tmp_path: Path) -> None:
    db_path = tmp_path / "lifts.db"
    connection = connect(str(db_path))
    init_db(connection)

    first_hash = attachment_hash(b"first")
    second_hash = attachment_hash(b"second")

    record_processed_email_attachment(
        connection,
        message_id="<message-1>",
        sender_email="me@example.com",
        subject="Strong export",
        attachment_name="export-1.csv",
        file_hash=first_hash,
        source_mailbox="INBOX",
        inserted_sets=1,
        skipped_sets=0,
    )

    assert not has_processed_email_attachment(
        connection,
        message_id="<message-1>",
        attachment_name="export-2.csv",
        file_hash=second_hash,
    )
