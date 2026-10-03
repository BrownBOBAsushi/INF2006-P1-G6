"""PostgreSQL integration coverage for durable task ownership and recovery."""

from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pgvector")
DISPOSABLE_DATABASE_URL = os.environ.get("DISPOSABLE_DATABASE_URL")
if not DISPOSABLE_DATABASE_URL:
    pytest.skip("DISPOSABLE_DATABASE_URL is required", allow_module_level=True)
if os.environ.get("DATABASE_URL") not in (None, DISPOSABLE_DATABASE_URL):
    pytest.skip("DATABASE_URL must equal the explicit disposable database URL", allow_module_level=True)

os.environ["DATABASE_URL"] = DISPOSABLE_DATABASE_URL

from sqlalchemy import create_engine, event as sa_event, select
from sqlalchemy.orm import sessionmaker

from app.db.models import OutboxEvent, ProcessingTask, User
from app.processing.tasks import (
    cancel_owner_tasks, claim_published_task, claim_task, complete_task,
    enqueue_task, fail_task,
)
from app.processing.outbox import ack_outbox, claim_outbox_batch


@pytest.fixture
def database():
    engine = create_engine(DISPOSABLE_DATABASE_URL)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    marker = f"task-test-{uuid.uuid4()}"
    user_id = uuid.uuid4()
    db = sessions()
    try:
        db.add(User(user_id=user_id, google_sub=marker))
        db.commit()
        yield db, user_id, marker, sessions
    finally:
        db.rollback()
        db.query(User).filter(User.google_sub == marker).delete(synchronize_session=False)
        db.commit()
        db.close()
        engine.dispose()


def test_enqueue_adds_task_and_outbox_to_the_callers_transaction(database):
    db, owner_id, _, _ = database
    task = enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key="upload-1", revision=0)
    task_id = task.task_id
    assert db.get(ProcessingTask, task_id) is not None
    assert db.scalar(select(OutboxEvent).where(OutboxEvent.task_id == task_id)) is not None
    db.rollback()
    assert db.get(ProcessingTask, task_id) is None


def test_claim_increments_once_and_active_redelivery_is_a_noop(database):
    db, owner_id, _, _ = database
    task = enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key="upload-2", revision=0)
    now = datetime.now(timezone.utc)
    first = claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=30), now=now)
    duplicate = claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=30), now=now)
    assert first is not None and first.attempts == 1
    assert duplicate is None
    assert db.get(ProcessingTask, task.task_id).attempts == 1


def test_sqs_delivery_claim_requires_sent_outbox_and_is_idempotent(database):
    db, owner_id, _, _ = database
    task = enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key="sqs-delivery", revision=0)
    task_id = task.task_id
    now = datetime.now(timezone.utc)

    assert claim_published_task(db, task_id=task_id, kind="EXTRACTION",
                                lease_for=timedelta(seconds=30), now=now) is None
    assert db.get(ProcessingTask, task_id).attempts == 0

    event_claim = claim_outbox_batch(db, limit=1, lease_for=timedelta(seconds=30), now=now)[0]
    assert ack_outbox(db, event_id=event_claim.event_id, lease_token=event_claim.lease_token, now=now)
    first = claim_published_task(db, task_id=task_id, kind="EXTRACTION",
                                 lease_for=timedelta(seconds=30), now=now)
    duplicate = claim_published_task(db, task_id=task_id, kind="EXTRACTION",
                                    lease_for=timedelta(seconds=30), now=now)
    wrong_queue = claim_published_task(db, task_id=task_id, kind="EMBEDDING",
                                       lease_for=timedelta(seconds=30), now=now)

    assert first is not None and first.attempts == 1
    assert duplicate is None and wrong_queue is None
    assert db.get(ProcessingTask, task_id).attempts == 1


def test_expired_lease_can_be_reclaimed_and_old_worker_is_fenced(database):
    db, owner_id, _, _ = database
    task = enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key="upload-3", revision=0)
    now = datetime.now(timezone.utc)
    old = claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=1), now=now)
    old_token = old.lease_token
    fresh = claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=30), now=now + timedelta(seconds=2))
    assert old is not None and fresh is not None
    assert fresh.attempts == 2
    assert not complete_task(db, task_id=task.task_id, owner_id=owner_id, revision=0, lease_token=old_token)
    assert complete_task(db, task_id=task.task_id, owner_id=owner_id, revision=0, lease_token=fresh.lease_token)


def test_retry_waits_until_due_and_exhausts_after_bounded_claims(database):
    db, owner_id, _, _ = database
    task = enqueue_task(db, owner_id=owner_id, kind="EMBEDDING", task_key="revision-1", revision=0)
    now = datetime.now(timezone.utc)
    claim = claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=30), now=now, max_attempts=2)
    assert claim is not None
    assert fail_task(db, task_id=task.task_id, owner_id=owner_id, lease_token=claim.lease_token,
                     failure_code="TEMPORARY_FAILURE", retryable=True, retry_after=timedelta(seconds=10),
                     max_attempts=2, now=now)
    assert claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=30),
                      max_attempts=2, now=now + timedelta(seconds=9)) is None
    second = claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=30),
                        max_attempts=2, now=now + timedelta(seconds=11))
    assert second is not None and second.attempts == 2
    assert not fail_task(db, task_id=task.task_id, owner_id=owner_id, lease_token=second.lease_token,
                         failure_code="TEMPORARY_FAILURE", retryable=True, retry_after=timedelta(seconds=1),
                         max_attempts=2, now=now + timedelta(seconds=11))
    assert db.get(ProcessingTask, task.task_id).state == "FAILED"


def test_completion_rejects_wrong_owner_and_stale_revision(database):
    db, owner_id, _, _ = database
    task = enqueue_task(db, owner_id=owner_id, kind="EMBEDDING", task_key="revision-0", revision=0)
    claim = claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=30))
    assert claim is not None
    assert not complete_task(db, task_id=task.task_id, owner_id=uuid.uuid4(), revision=0,
                             lease_token=claim.lease_token)
    assert not complete_task(db, task_id=task.task_id, owner_id=owner_id, revision=1,
                             lease_token=claim.lease_token)
    assert db.get(ProcessingTask, task.task_id).state == "PROCESSING"


def test_completion_refreshes_preloaded_user_revision_before_fencing(database):
    db, owner_id, _, sessions = database
    task = enqueue_task(db, owner_id=owner_id, kind="EMBEDDING", task_key="user-revision-refresh", revision=0)
    claim = claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=30))
    assert claim is not None
    stale_user = db.get(User, owner_id)
    assert stale_user.resume_revision == 0
    db.commit()
    with sessions() as other:
        user = other.get(User, owner_id)
        user.resume_revision = 1
        other.commit()
    assert not complete_task(db, task_id=task.task_id, owner_id=owner_id, revision=0,
                             lease_token=claim.lease_token)
    db.expire_all()
    assert db.get(ProcessingTask, task.task_id).state == "CANCELLED"


def test_completion_flushes_caller_revision_change_before_refresh(database):
    db, owner_id, _, _ = database
    user = db.get(User, owner_id)
    user.resume_revision = 1  # caller's pending domain update must not be discarded
    task = enqueue_task(db, owner_id=owner_id, kind="EMBEDDING", task_key="pending-user-revision", revision=1)
    claim = claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=30))
    assert claim is not None
    assert complete_task(db, task_id=task.task_id, owner_id=owner_id, revision=1,
                         lease_token=claim.lease_token)
    assert user.resume_revision == 1


def test_resume_delete_cancellation_invalidates_active_lease(database):
    db, owner_id, _, _ = database
    task = enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key="upload-4", revision=0)
    claim = claim_task(db, task_id=task.task_id, owner_id=owner_id, lease_for=timedelta(seconds=30))
    assert claim is not None
    from app.processing.tasks import cancel_owner_tasks
    assert cancel_owner_tasks(db, owner_id=owner_id) == 1
    assert not complete_task(db, task_id=task.task_id, owner_id=owner_id, revision=0,
                             lease_token=claim.lease_token)
    assert db.get(ProcessingTask, task.task_id).state == "CANCELLED"


def test_two_database_sessions_cannot_claim_the_same_live_task(database):
    db, owner_id, _, sessions = database
    task = enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key="upload-concurrent", revision=0)
    task_id = task.task_id
    db.commit()

    def claim_once():
        with sessions() as connection:
            result = claim_task(connection, task_id=task_id, owner_id=owner_id,
                                lease_for=timedelta(seconds=30))
            connection.commit()
            return result is not None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim_once(), range(2)))
    assert results.count(True) == 1
    assert db.get(ProcessingTask, task_id).attempts == 1


def test_preloaded_pending_task_cannot_overwrite_another_sessions_lease(database):
    db, owner_id, _, sessions = database
    task = enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key="preloaded-pending", revision=0)
    task_id = task.task_id
    db.commit()
    assert db.get(ProcessingTask, task_id).state == "PENDING"  # cache a clean identity-map object
    now = datetime.now(timezone.utc)
    with sessions() as other:
        first = claim_task(other, task_id=task_id, owner_id=owner_id,
                           lease_for=timedelta(seconds=30), now=now)
        assert first is not None
        other.commit()
    assert claim_task(db, task_id=task_id, owner_id=owner_id,
                      lease_for=timedelta(seconds=30), now=now + timedelta(seconds=1)) is None
    db.expire_all()
    assert db.get(ProcessingTask, task_id).attempts == 1


@pytest.mark.parametrize("transition", ["complete", "fail"])
def test_preloaded_old_task_lease_token_cannot_mutate_reclaimed_task(database, transition):
    db, owner_id, _, sessions = database
    task = enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key=f"old-token-{transition}", revision=0)
    task_id = task.task_id
    db.commit()
    now = datetime.now(timezone.utc)
    old = claim_task(db, task_id=task_id, owner_id=owner_id, lease_for=timedelta(seconds=1), now=now)
    old_token = old.lease_token
    db.commit()
    with sessions() as other:
        fresh = claim_task(other, task_id=task_id, owner_id=owner_id,
                           lease_for=timedelta(seconds=30), now=now + timedelta(seconds=2))
        assert fresh is not None and fresh.lease_token != old_token
        other.commit()
    # Model a worker whose local clock lags. The database's current lease token
    # must still fence it even though the stale ORM object has a live old lease.
    if transition == "complete":
        changed = complete_task(db, task_id=task_id, owner_id=owner_id, revision=0,
                                lease_token=old_token, now=now + timedelta(milliseconds=500))
    else:
        changed = fail_task(db, task_id=task_id, owner_id=owner_id, lease_token=old_token,
                            failure_code="OLD_WORKER", retryable=False,
                            now=now + timedelta(milliseconds=500))
    assert changed is False
    db.expire_all()
    current = db.get(ProcessingTask, task_id)
    assert current.state == "PROCESSING" and current.lease_token != old_token


def test_cancellation_waits_for_claimed_task_then_cancels_it(database):
    db, owner_id, _, sessions = database
    task = enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key="cancel-concurrent", revision=0)
    task_id = task.task_id
    claim = claim_task(db, task_id=task_id, owner_id=owner_id, lease_for=timedelta(seconds=30))
    assert claim is not None  # holds this session's task row lock
    query_finished = threading.Event()

    def after_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "FROM processing_tasks" in statement:
            query_finished.set()

    sa_event.listen(db.get_bind(), "after_cursor_execute", after_execute)

    def cancel():
        with sessions() as other:
            count = cancel_owner_tasks(other, owner_id=owner_id)
            other.commit()
            return count

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cancel)
        try:
            time.sleep(0.15)
            assert not query_finished.is_set()  # task lock blocks cancellation; no SKIP LOCKED loss
            db.commit()
            assert future.result(timeout=5) == 1
            assert query_finished.is_set()
        finally:
            sa_event.remove(db.get_bind(), "after_cursor_execute", after_execute)
    db.expire_all()
    assert db.get(ProcessingTask, task_id).state == "CANCELLED"
