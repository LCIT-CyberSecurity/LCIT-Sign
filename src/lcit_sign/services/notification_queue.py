from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.config import Settings
from lcit_sign.models.mail import MailConnector, Notification, NotificationStatus, NotificationType
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.crypto import decrypt_secret
from lcit_sign.services.mail import MailSendError, build_sender

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
# A simple per-cycle cap stands in for real rate limiting (spec §72) —
# proportionate to an internal tool's volume, not a public mail relay.
BATCH_LIMIT = 20


def enqueue_notification(
    db: DbSession,
    *,
    notification_type: NotificationType,
    recipient_email: str,
    subject: str,
    body_text: str,
    recipient_user_id: uuid.UUID | None = None,
    related_assignment_id: uuid.UUID | None = None,
) -> Notification:
    """Queue an email inside the caller's own transaction. Never sent here
    — only the background worker calls SMTP, so an outage never rolls
    back the business transaction that queued this (spec §73)."""
    notification = Notification(
        notification_type=notification_type,
        recipient_email=recipient_email,
        recipient_user_id=recipient_user_id,
        subject=subject,
        body_text=body_text,
        related_assignment_id=related_assignment_id,
    )
    db.add(notification)
    return notification


def _backoff_minutes(attempt_count: int) -> int:
    # Typeshed types int.__pow__ as returning Any (a negative exponent
    # could yield a float), so a left shift keeps this cleanly an int.
    return min(1 << attempt_count, 60)


def process_pending_notifications(db: DbSession, settings: Settings) -> int:
    """Send every due PENDING/RETRY notification, one at a time, each in
    its own commit so one failure can't roll back another's success.
    Returns how many were actually sent.
    """
    connector = db.get(MailConnector, 1)
    if connector is None or not settings.master_key:
        return 0

    password = None
    if connector.encrypted_password:
        password = decrypt_secret(settings.master_key, connector.encrypted_password)
    sender = build_sender(connector, password)

    now = datetime.now(UTC)
    due = db.execute(
        select(Notification)
        .where(
            Notification.status.in_([NotificationStatus.PENDING, NotificationStatus.RETRY]),
            Notification.next_attempt_at <= now,
        )
        .order_by(Notification.created_at)
        .limit(BATCH_LIMIT)
    ).scalars()

    sent_count = 0
    for notification in due:
        notification.status = NotificationStatus.PROCESSING
        notification.attempt_count += 1
        db.flush()

        try:
            sender.send(
                to=notification.recipient_email,
                subject=notification.subject,
                body=notification.body_text,
            )
        except MailSendError as exc:
            notification.last_error = str(exc)[:1000]
            if notification.attempt_count >= MAX_ATTEMPTS:
                notification.status = NotificationStatus.FAILED
                if notification.notification_type == NotificationType.REMINDER:
                    append_audit_event(
                        db, action="REMINDER_FAILED", result="FAILURE",
                        target_type="notification", target_id=str(notification.id),
                        metadata={"error": notification.last_error},
                    )
            else:
                notification.status = NotificationStatus.RETRY
                notification.next_attempt_at = now + timedelta(
                    minutes=_backoff_minutes(notification.attempt_count)
                )
        else:
            notification.status = NotificationStatus.SENT
            notification.sent_at = now
            sent_count += 1
            if notification.notification_type == NotificationType.REMINDER:
                append_audit_event(
                    db, action="REMINDER_SENT",
                    target_type="notification", target_id=str(notification.id),
                )
        db.commit()

    return sent_count
