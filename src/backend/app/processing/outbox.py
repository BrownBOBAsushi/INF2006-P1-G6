"""Leased PostgreSQL outbox claims. The transport remains an injected caller concern."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import OutboxEvent, ProcessingTask


@dataclass(frozen=True)
class OutboxDelivery:
    event_id: uuid.UUID
    task_id: uuid.UUID
    lease_token: uuid.UUID


def _now(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return result


def _lock_event(db: Session, event_id: uuid.UUID) -> OutboxEvent | None:
    # The outbox row may already be in this session's identity map. Flush
    # caller-owned changes before replacing that cached state with the locked
    # database version used for fencing.
    db.flush()
    return db.scalar(
        select(OutboxEvent)
        .where(OutboxEvent.event_id == event_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )


def claim_outbox_batch(
    db: Session,
    *,
    limit: int,
    lease_for: timedelta,
    now: datetime | None = None,
) -> list[OutboxDelivery]:
    """Claim due events without waiting on other publishers (`SKIP LOCKED`)."""
    if limit < 1 or lease_for <= timedelta(0):
        raise ValueError("batch limit and lease duration must be positive")
    query_time = _now(now)
    # Flush caller-owned state and refresh locked rows so a cached PENDING/CLAIMED
    # identity cannot replace another publisher's committed lease.
    db.flush()
    rows = db.scalars(
        select(OutboxEvent)
        .join(ProcessingTask, ProcessingTask.task_id == OutboxEvent.task_id)
        .where(
            ProcessingTask.state.in_(("PENDING", "RETRY_WAIT")),
            OutboxEvent.available_at <= query_time,
            (
                (OutboxEvent.state == "PENDING")
                | ((OutboxEvent.state == "CLAIMED") & (OutboxEvent.lease_expires_at <= query_time))
            ),
        )
        .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True, of=OutboxEvent)
        .execution_options(populate_existing=True)
    ).all()
    # SKIP LOCKED avoids row waits, but flush/select acquisition can still wait;
    # base the new lease expiry on time sampled after the selected locks.
    timestamp = _now(now)
    deliveries = []
    for event in rows:
        token = uuid.uuid4()
        event.state = "CLAIMED"
        event.attempts += 1
        event.lease_token = token
        event.lease_expires_at = timestamp + lease_for
        event.updated_at = timestamp
        deliveries.append(OutboxDelivery(event.event_id, event.task_id, token))
    db.flush()
    return deliveries


def ack_outbox(
    db: Session,
    *,
    event_id: uuid.UUID,
    lease_token: uuid.UUID,
    now: datetime | None = None,
) -> bool:
    """Mark sent only for a live current claim, after transport confirmation."""
    event = _lock_event(db, event_id)
    timestamp = _now(now)
    if (event is None or event.state != "CLAIMED" or event.lease_token != lease_token
            or event.lease_expires_at is None or event.lease_expires_at <= timestamp):
        return False
    event.state = "SENT"
    event.sent_at = timestamp
    event.lease_token = None
    event.lease_expires_at = None
    event.updated_at = timestamp
    db.flush()
    return True


def retry_outbox(
    db: Session,
    *,
    event_id: uuid.UUID,
    lease_token: uuid.UUID,
    retry_after: timedelta,
    now: datetime | None = None,
) -> bool:
    """Release a failed publish for retry; callers commit with their transaction."""
    if retry_after < timedelta(0):
        raise ValueError("retry delay cannot be negative")
    event = _lock_event(db, event_id)
    timestamp = _now(now)
    if (event is None or event.state != "CLAIMED" or event.lease_token != lease_token
            or event.lease_expires_at is None or event.lease_expires_at <= timestamp):
        return False
    event.state = "PENDING"
    event.available_at = timestamp + retry_after
    event.lease_token = None
    event.lease_expires_at = None
    event.updated_at = timestamp
    db.flush()
    return True
