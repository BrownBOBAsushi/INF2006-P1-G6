"""PostgreSQL task lifecycle primitives; callers own and commit the transaction."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import OutboxEvent, ProcessingTask, User

TASK_KINDS = frozenset({"EXTRACTION", "EMBEDDING"})
TERMINAL_TASK_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _now(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return result


def _lease_duration(value: timedelta) -> None:
    if value <= timedelta(0):
        raise ValueError("lease duration must be positive")


def validate_task_spec(*, kind: str, task_key: str, revision: int, max_attempts: int = 3) -> None:
    """Validate fields safe to persist before a database transaction is touched."""
    if kind not in TASK_KINDS:
        raise ValueError("unsupported task kind")
    if not task_key or len(task_key) > 200:
        raise ValueError("task key must contain 1 to 200 characters")
    if revision < 0 or max_attempts < 1:
        raise ValueError("revision and attempt limit are out of range")


def validate_failure_code(failure_code: str) -> None:
    """Reject free-form errors so task rows cannot become resume-text log sinks."""
    if not _SAFE_CODE.fullmatch(failure_code):
        raise ValueError("failure code must be a safe uppercase code")


def _clear_lease(task: ProcessingTask) -> None:
    task.lease_token = None
    task.lease_expires_at = None


def _lock_task(db: Session, *, task_id: uuid.UUID, owner_id: uuid.UUID) -> ProcessingTask | None:
    # Flush caller-owned writes first, then overwrite any clean/stale identity-map
    # copy with the row version protected by this lock.
    db.flush()
    return db.scalar(
        select(ProcessingTask)
        .where(ProcessingTask.task_id == task_id, ProcessingTask.owner_id == owner_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )


def _lock_outbox(db: Session, *, task_id: uuid.UUID) -> OutboxEvent | None:
    db.flush()
    return db.scalar(
        select(OutboxEvent)
        .where(OutboxEvent.task_id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def enqueue_task(
    db: Session,
    *,
    owner_id: uuid.UUID,
    kind: str,
    task_key: str,
    revision: int,
    payload_ref: str | None = None,
    max_attempts: int = 3,
    now: datetime | None = None,
) -> ProcessingTask:
    """Add a task and publication row atomically without committing the caller's transaction.

    A duplicate (owner, kind, task_key) is rejected by the database unique
    constraint. The caller may look up and replay that identity after rollback.
    Payload references are opaque; resume bytes or text do not belong here.
    """
    validate_task_spec(kind=kind, task_key=task_key, revision=revision, max_attempts=max_attempts)
    timestamp = _now(now)
    task = ProcessingTask(
        task_id=uuid.uuid4(), owner_id=owner_id, kind=kind, task_key=task_key,
        revision=revision, payload_ref=payload_ref, state="PENDING", attempts=0,
        max_attempts=max_attempts, available_at=timestamp,
    )
    db.add(task)
    db.flush()
    event = OutboxEvent(task_id=task.task_id, state="PENDING", attempts=0, available_at=timestamp)
    db.add(event)
    db.flush()
    return task


def claim_task(
    db: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID,
    lease_for: timedelta,
    max_attempts: int | None = None,
    now: datetime | None = None,
) -> ProcessingTask | None:
    """Claim due work under a row lock; redelivery under a live lease is a no-op."""
    _lease_duration(lease_for)
    task = _lock_task(db, task_id=task_id, owner_id=owner_id)
    # Production time must be sampled after a potentially blocking row lock.
    # An explicit `now` remains a fixed test/replay clock by design.
    timestamp = _now(now)
    if task is None or task.state in TERMINAL_TASK_STATES:
        return None
    if task.state == "PROCESSING" and task.lease_expires_at > timestamp:
        return None
    if task.state not in {"PENDING", "RETRY_WAIT", "PROCESSING"} or task.available_at > timestamp:
        return None
    attempt_limit = max_attempts if max_attempts is not None else task.max_attempts
    if attempt_limit < 1:
        raise ValueError("attempt limit must be positive")
    if task.attempts >= min(attempt_limit, task.max_attempts):
        task.state = "FAILED"
        task.failure_code = "ATTEMPTS_EXHAUSTED"
        _clear_lease(task)
        _cancel_outbox(db, task.task_id)
        db.flush()
        return None
    task.attempts += 1
    task.state = "PROCESSING"
    task.failure_code = None
    task.lease_token = uuid.uuid4()
    task.lease_expires_at = timestamp + lease_for
    task.updated_at = timestamp
    db.flush()
    return task


def claim_next_task(
    db: Session,
    *,
    kind: str,
    lease_for: timedelta,
    now: datetime | None = None,
) -> ProcessingTask | None:
    """Claim the oldest due DB-queue item; the task row remains recoverable after delivery."""
    if kind not in TASK_KINDS:
        raise ValueError("unsupported task kind")
    timestamp = _now(now)
    candidate = db.execute(
        select(ProcessingTask.task_id, ProcessingTask.owner_id)
        .join(OutboxEvent, OutboxEvent.task_id == ProcessingTask.task_id)
        .where(
            ProcessingTask.kind == kind,
            OutboxEvent.state == "SENT",
            ProcessingTask.state.in_({"PENDING", "RETRY_WAIT", "PROCESSING"}),
            ProcessingTask.available_at <= timestamp,
            ((ProcessingTask.state != "PROCESSING") | (ProcessingTask.lease_expires_at <= timestamp)),
        )
        .order_by(ProcessingTask.created_at, ProcessingTask.task_id)
        .limit(1)
    ).first()
    if candidate is None:
        return None
    return claim_task(
        db, task_id=candidate.task_id, owner_id=candidate.owner_id,
        lease_for=lease_for, now=now,
    )


def claim_published_task(
    db: Session,
    *,
    task_id: uuid.UUID,
    kind: str,
    lease_for: timedelta,
    now: datetime | None = None,
) -> ProcessingTask | None:
    """Claim one SQS identity only after its outbox publication is committed."""
    if kind not in TASK_KINDS:
        raise ValueError("unsupported task kind")
    task = db.scalar(
        select(ProcessingTask)
        .join(OutboxEvent, OutboxEvent.task_id == ProcessingTask.task_id)
        .where(ProcessingTask.task_id == task_id, ProcessingTask.kind == kind, OutboxEvent.state == "SENT")
        .with_for_update(of=ProcessingTask, skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if task is None:
        return None
    return claim_task(db, task_id=task.task_id, owner_id=task.owner_id, lease_for=lease_for, now=now)


def complete_task(
    db: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID,
    revision: int,
    lease_token: uuid.UUID,
    now: datetime | None = None,
) -> bool:
    """Fence completion by owner, revision, live lease and current account revision.

    The worker must write its domain result in this same transaction, and only
    after this returns true. A missing/deleted owner or stale revision cannot
    produce a successful completion.
    """
    # Completion and cancellation both lock User before ProcessingTask. This
    # makes a resume deletion/revision change serialize with late worker writes.
    db.flush()
    user = db.scalar(
        select(User).where(User.user_id == owner_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        return False
    task = _lock_task(db, task_id=task_id, owner_id=owner_id)
    timestamp = _now(now)
    if (task is None or task.state != "PROCESSING" or task.lease_token != lease_token
            or task.lease_expires_at is None or task.lease_expires_at <= timestamp
            or task.revision != revision):
        return False
    if user.resume_revision != revision:
        task.state = "CANCELLED"
        task.failure_code = "STALE_REVISION"
        task.result_data = None
        task.expires_at = None
        _clear_lease(task)
        _cancel_outbox(db, task.task_id)
        db.flush()
        return False
    task.state = "SUCCEEDED"
    task.failure_code = None
    task.updated_at = timestamp
    _clear_lease(task)
    db.flush()
    return True


def fail_task(
    db: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID,
    lease_token: uuid.UUID,
    failure_code: str,
    retryable: bool,
    retry_after: timedelta = timedelta(0),
    max_attempts: int | None = None,
    now: datetime | None = None,
) -> bool:
    """Record one fenced failure and make the same task identity retryable."""
    validate_failure_code(failure_code)
    if retry_after < timedelta(0):
        raise ValueError("retry delay cannot be negative")
    task = _lock_task(db, task_id=task_id, owner_id=owner_id)
    timestamp = _now(now)
    if (task is None or task.state != "PROCESSING" or task.lease_token != lease_token
            or task.lease_expires_at is None or task.lease_expires_at <= timestamp):
        return False
    # Lock the outbox row before the final lease check as its lock can wait too.
    event = _lock_outbox(db, task_id=task_id)
    timestamp = _now(now)
    if task.lease_expires_at <= timestamp:
        return False
    attempt_limit = min(max_attempts or task.max_attempts, task.max_attempts)
    if retryable and task.attempts < attempt_limit:
        task.state = "RETRY_WAIT"
        task.available_at = timestamp + retry_after
        if event is not None:
            event.state = "PENDING"
            event.available_at = task.available_at
            event.sent_at = None
            event.lease_token = None
            event.lease_expires_at = None
            event.updated_at = timestamp
    else:
        task.state = "FAILED"
        if event is not None:
            event.state = "CANCELLED"
            event.lease_token = None
            event.lease_expires_at = None
            event.updated_at = timestamp
    task.failure_code = failure_code
    task.updated_at = timestamp
    _clear_lease(task)
    db.flush()
    return task.state == "RETRY_WAIT"


def cancel_owner_tasks(db: Session, *, owner_id: uuid.UUID, now: datetime | None = None) -> int:
    """Wait for active leases, then cancel all work before explicit resume deletion.

    Lock order is User -> ProcessingTask -> OutboxEvent, matching completion.
    Do not use SKIP LOCKED here: a concurrent worker claim must finish before
    deletion can proceed, otherwise its active task could be silently missed.
    """
    db.flush()
    user = db.scalar(
        select(User).where(User.user_id == owner_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        return 0
    tasks = db.scalars(
        select(ProcessingTask)
        .where(
            ProcessingTask.owner_id == owner_id,
            ProcessingTask.state.not_in(TERMINAL_TASK_STATES)
            | ((ProcessingTask.kind == "EXTRACTION") & ProcessingTask.result_data.is_not(None)),
        )
        .order_by(ProcessingTask.task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    timestamp = _now(now)
    for task in tasks:
        task.state = "CANCELLED"
        task.failure_code = "CANCELLED_BY_OWNER"
        task.result_data = None
        task.expires_at = None
        task.payload_ref = None
        task.updated_at = timestamp
        _clear_lease(task)
        _cancel_outbox(db, task.task_id)
    db.flush()
    return len(tasks)


def _cancel_outbox(db: Session, task_id: uuid.UUID) -> None:
    event = _lock_outbox(db, task_id=task_id)
    if event is not None:
        event.state = "CANCELLED"
        event.lease_token = None
        event.lease_expires_at = None
        event.updated_at = datetime.now(timezone.utc)
