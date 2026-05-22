from __future__ import annotations

import csv
import hashlib
import imaplib
import io
import logging
import re
import sqlite3
from dataclasses import dataclass
from email import message_from_bytes
from email.message import Message
from email.utils import parseaddr
from pathlib import Path

from .ingest import ingest_csv
from .strong_csv import REQUIRED_COLUMNS

log = logging.getLogger(__name__)


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
    allow_all_senders: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class EmailIngestResult:
    messages_seen: int
    messages_rejected_sender: int
    messages_rejected_subject: int
    attachments_seen: int
    attachments_ingested: int
    attachments_skipped: int
    attachments_invalid: int
    sets_inserted: int
    sets_skipped: int
    messages_moved: int


def attachment_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sender_is_allowed(sender_email: str, allowlist: tuple[str, ...], allow_all_senders: bool = False) -> bool:
    if allow_all_senders:
        return True
    if not allowlist:
        return False
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


def _validate_csv_headers(payload: bytes) -> None:
    """Raise ValueError if payload is missing required Strong CSV columns."""
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    columns = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS.difference(columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")


def ingest_from_gmail(
    connection: sqlite3.Connection,
    config: EmailIngestConfig,
) -> EmailIngestResult:
    inbox_path = Path(config.download_dir)
    if not config.dry_run:
        inbox_path.mkdir(parents=True, exist_ok=True)

    messages_seen = 0
    messages_rejected_sender = 0
    messages_rejected_subject = 0
    attachments_seen = 0
    attachments_ingested = 0
    attachments_skipped = 0
    attachments_invalid = 0
    sets_inserted = 0
    sets_skipped = 0
    messages_moved = 0

    imap = imaplib.IMAP4_SSL(config.imap_host, config.imap_port)
    try:
        imap.login(config.username, config.app_password)
        # Create destination mailbox if it does not already exist.
        # Skip in dry-run: creating a label/mailbox is a remote side effect.
        if not config.dry_run:
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
            # BODY.PEEK[] fetches the full message without setting the \Seen flag,
            # keeping polling idempotent and dry-run side-effect free.
            fetch_status, fetched = imap.fetch(raw_msg_id, "(BODY.PEEK[])")
            if fetch_status != "OK" or not fetched or not fetched[0]:
                log.warning("Failed to fetch message uid=%s", raw_msg_id.decode())
                continue

            raw_payload = fetched[0][1]
            email_message = message_from_bytes(raw_payload)

            message_id = (email_message.get("Message-Id") or f"imap-{raw_msg_id.decode()}").strip()
            sender_email = parseaddr(email_message.get("From", ""))[1].strip().lower()
            subject = (email_message.get("Subject") or "").strip()

            if not sender_is_allowed(sender_email, config.sender_allowlist, config.allow_all_senders):
                log.info("Rejected message from unlisted sender: %s (message-id=%s)", sender_email, message_id)
                messages_rejected_sender += 1
                if not config.dry_run:
                    imap.store(raw_msg_id, "+FLAGS", "\\Seen")
                continue
            if config.subject_contains and config.subject_contains.lower() not in subject.lower():
                log.info(
                    "Rejected message: subject %r does not contain %r (message-id=%s)",
                    subject, config.subject_contains, message_id,
                )
                messages_rejected_subject += 1
                if not config.dry_run:
                    imap.store(raw_msg_id, "+FLAGS", "\\Seen")
                continue

            message_had_processable_attachment = False

            for filename, content_type, payload in _extract_attachments(email_message):
                attachments_seen += 1
                if not is_attachment_csv(filename, content_type):
                    log.debug("Skipping non-CSV attachment %r (%s)", filename, content_type)
                    continue

                file_hash = attachment_hash(payload)
                safe_name = _safe_filename(filename)

                if config.dry_run:
                    try:
                        _validate_csv_headers(payload)
                        log.info(
                            "[dry-run] Attachment %r from %s passes header validation",
                            safe_name, sender_email,
                        )
                    except ValueError as exc:
                        log.warning(
                            "[dry-run] Attachment %r from %s failed validation: %s",
                            safe_name, sender_email, exc,
                        )
                        attachments_invalid += 1
                    message_had_processable_attachment = True
                    continue

                if has_processed_email_attachment(
                    connection,
                    message_id=message_id,
                    attachment_name=safe_name,
                    file_hash=file_hash,
                ):
                    log.debug("Skipping already-processed attachment %r (hash=%s)", safe_name, file_hash[:12])
                    attachments_skipped += 1
                    message_had_processable_attachment = True
                    continue

                try:
                    _validate_csv_headers(payload)
                except ValueError as exc:
                    log.warning(
                        "Attachment %r from %s failed validation: %s",
                        safe_name, sender_email, exc,
                    )
                    attachments_invalid += 1
                    message_had_processable_attachment = True
                    continue

                local_path = inbox_path / f"{file_hash[:12]}-{safe_name}"
                local_path.write_bytes(payload)
                try:
                    ingest_result = ingest_csv(connection, str(local_path))
                except (ValueError, csv.Error) as exc:
                    log.warning(
                        "Attachment %r from %s failed to parse: %s",
                        safe_name, sender_email, exc,
                    )
                    attachments_invalid += 1
                    message_had_processable_attachment = True
                    continue

                record_processed_email_attachment(
                    connection,
                    message_id=message_id,
                    sender_email=sender_email,
                    subject=subject,
                    attachment_name=safe_name,
                    file_hash=file_hash,
                    source_mailbox=config.source_mailbox,
                    inserted_sets=ingest_result.inserted,
                    skipped_sets=ingest_result.skipped,
                )
                log.info(
                    "Ingested %r from %s: inserted=%d skipped=%d",
                    safe_name, sender_email, ingest_result.inserted, ingest_result.skipped,
                )
                attachments_ingested += 1
                sets_inserted += ingest_result.inserted
                sets_skipped += ingest_result.skipped
                message_had_processable_attachment = True

            if message_had_processable_attachment and not config.dry_run:
                if _move_message(imap, raw_msg_id, config.processed_mailbox):
                    messages_moved += 1
                else:
                    log.warning(
                        "Failed to move message to %s (message-id=%s); leaving unread for retry",
                        config.processed_mailbox, message_id,
                    )

        if not config.dry_run:
            imap.expunge()
    finally:
        try:
            imap.close()
        except Exception:
            pass
        try:
            imap.logout()
        except Exception:
            pass

    return EmailIngestResult(
        messages_seen=messages_seen,
        messages_rejected_sender=messages_rejected_sender,
        messages_rejected_subject=messages_rejected_subject,
        attachments_seen=attachments_seen,
        attachments_ingested=attachments_ingested,
        attachments_skipped=attachments_skipped,
        attachments_invalid=attachments_invalid,
        sets_inserted=sets_inserted,
        sets_skipped=sets_skipped,
        messages_moved=messages_moved,
    )
