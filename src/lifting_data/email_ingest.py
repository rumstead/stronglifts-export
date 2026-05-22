from __future__ import annotations

import hashlib
import imaplib
import re
import sqlite3
from dataclasses import dataclass
from email import message_from_bytes
from email.message import Message
from email.utils import parseaddr
from pathlib import Path

from .ingest import ingest_csv


@dataclass(frozen=True)
class EmailIngestConfig:
    imap_host: str
    imap_port: int
    username: str
    app_password: str
    source_mailbox: str
    processed_mailbox: str
    sender_allowlist: tuple[str, ...]
    subject_contains: str | None
    download_dir: str
    dry_run: bool = False


@dataclass(frozen=True)
class EmailIngestResult:
    messages_seen: int
    attachments_seen: int
    attachments_ingested: int
    attachments_skipped: int
    sets_inserted: int
    sets_skipped: int
    messages_moved: int


def attachment_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sender_is_allowed(sender_email: str, allowlist: tuple[str, ...]) -> bool:
    if not allowlist:
        return True
    normalized = sender_email.strip().lower()
    return normalized in {item.strip().lower() for item in allowlist}


def is_attachment_csv(filename: str | None, content_type: str) -> bool:
    file_name = (filename or "").lower()
    if file_name.endswith(".csv"):
        return True
    return content_type.lower() in {"text/csv", "application/csv", "application/vnd.ms-excel"}


def has_processed_email_attachment(
    connection: sqlite3.Connection,
    message_id: str,
    attachment_name: str,
    file_hash: str,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM email_imports
        WHERE (message_id = ? AND attachment_name = ?) OR attachment_hash = ?
        LIMIT 1
        """,
        (message_id, attachment_name, file_hash),
    ).fetchone()
    return row is not None


def record_processed_email_attachment(
    connection: sqlite3.Connection,
    *,
    message_id: str,
    sender_email: str,
    subject: str,
    attachment_name: str,
    file_hash: str,
    source_mailbox: str,
    inserted_sets: int,
    skipped_sets: int,
) -> None:
    with connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO email_imports (
                message_id,
                sender_email,
                subject,
                attachment_name,
                attachment_hash,
                source_mailbox,
                inserted_sets,
                skipped_sets
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                sender_email,
                subject,
                attachment_name,
                file_hash,
                source_mailbox,
                inserted_sets,
                skipped_sets,
            ),
        )


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    return cleaned.strip("-") or "strong-export.csv"


def _extract_attachments(message: Message) -> list[tuple[str, str, bytes]]:
    attachments: list[tuple[str, str, bytes]] = []
    for part in message.walk():
        if part.get_content_disposition() != "attachment":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        attachments.append(
            (
                part.get_filename() or "attachment.csv",
                part.get_content_type(),
                payload,
            )
        )
    return attachments


def _move_message(imap: imaplib.IMAP4_SSL, raw_msg_id: bytes, destination_mailbox: str) -> bool:
    copy_status, _ = imap.copy(raw_msg_id, destination_mailbox)
    if copy_status != "OK":
        return False
    store_status, _ = imap.store(raw_msg_id, "+FLAGS", "\\Deleted")
    return store_status == "OK"


def ingest_from_gmail(
    connection: sqlite3.Connection,
    config: EmailIngestConfig,
) -> EmailIngestResult:
    inbox_path = Path(config.download_dir)
    inbox_path.mkdir(parents=True, exist_ok=True)

    messages_seen = 0
    attachments_seen = 0
    attachments_ingested = 0
    attachments_skipped = 0
    sets_inserted = 0
    sets_skipped = 0
    messages_moved = 0

    imap = imaplib.IMAP4_SSL(config.imap_host, config.imap_port)
    try:
        imap.login(config.username, config.app_password)
        # Create destination mailbox if it does not already exist.
        imap.create(config.processed_mailbox)

        status, _ = imap.select(config.source_mailbox)
        if status != "OK":
            raise RuntimeError(f"Failed to select mailbox: {config.source_mailbox}")

        search_status, message_data = imap.search(None, "UNSEEN")
        if search_status != "OK":
            raise RuntimeError("Failed to search mailbox")

        message_ids = message_data[0].split()

        for raw_msg_id in message_ids:
            messages_seen += 1
            fetch_status, fetched = imap.fetch(raw_msg_id, "(RFC822)")
            if fetch_status != "OK" or not fetched or not fetched[0]:
                continue

            raw_payload = fetched[0][1]
            email_message = message_from_bytes(raw_payload)

            message_id = (email_message.get("Message-Id") or f"imap-{raw_msg_id.decode()}").strip()
            sender_email = parseaddr(email_message.get("From", ""))[1].strip().lower()
            subject = (email_message.get("Subject") or "").strip()

            if not sender_is_allowed(sender_email, config.sender_allowlist):
                continue
            if config.subject_contains and config.subject_contains.lower() not in subject.lower():
                continue

            message_had_processable_attachment = False

            for filename, content_type, payload in _extract_attachments(email_message):
                attachments_seen += 1
                if not is_attachment_csv(filename, content_type):
                    continue

                file_hash = attachment_hash(payload)
                safe_name = _safe_filename(filename)
                if has_processed_email_attachment(
                    connection,
                    message_id=message_id,
                    attachment_name=safe_name,
                    file_hash=file_hash,
                ):
                    attachments_skipped += 1
                    message_had_processable_attachment = True
                    continue

                local_path = inbox_path / f"{file_hash[:12]}-{safe_name}"
                local_path.write_bytes(payload)

                inserted = 0
                skipped = 0
                if not config.dry_run:
                    ingest_result = ingest_csv(connection, str(local_path))
                    inserted = ingest_result.inserted
                    skipped = ingest_result.skipped

                record_processed_email_attachment(
                    connection,
                    message_id=message_id,
                    sender_email=sender_email,
                    subject=subject,
                    attachment_name=safe_name,
                    file_hash=file_hash,
                    source_mailbox=config.source_mailbox,
                    inserted_sets=inserted,
                    skipped_sets=skipped,
                )

                attachments_ingested += 1
                sets_inserted += inserted
                sets_skipped += skipped
                message_had_processable_attachment = True

            if message_had_processable_attachment and not config.dry_run:
                if _move_message(imap, raw_msg_id, config.processed_mailbox):
                    messages_moved += 1

        if not config.dry_run:
            imap.expunge()
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()

    return EmailIngestResult(
        messages_seen=messages_seen,
        attachments_seen=attachments_seen,
        attachments_ingested=attachments_ingested,
        attachments_skipped=attachments_skipped,
        sets_inserted=sets_inserted,
        sets_skipped=sets_skipped,
        messages_moved=messages_moved,
    )
