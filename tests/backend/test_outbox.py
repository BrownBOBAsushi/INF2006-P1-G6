"""PostgreSQL integration coverage for transactional outbox publishing."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pgvector")
DISPOSABLE_DATABASE_URL = os.environ.get("DISPOSABLE_DATABASE_URL")
if not DISPOSABLE_DATABASE_URL:
    pytest.skip("DISPOSABLE_DATABASE_URL is required", allow_module_level=True)
if os.environ.get("DATABASE_URL") not in (None, DISPOSABLE_DATABASE_URL):
    pytest.skip("DATABASE_URL must equal the explicit disposable database URL", allow_module_level=True)

os.environ["DATABASE_URL"] = DISPOSABLE_DATABASE_URL

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import OutboxEvent, User
from app.processing.outbox import ack_outbox, claim_outbox_batch, retry_outbox
from app.processing.tasks import enqueue_task


@pytest.fixture
def database():
    engine = create_engine(DISPOSABLE_DATABASE_URL)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    marker = f"outbox-test-{uuid.uuid4()}"
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


def test_claim_ack_is_fenced_and_ack_means_transport_confirmed(database):
    db, owner_id, _, _ = database
    enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key="upload-5", revision=0)
    now = datetime.now(timezone.utc)
    old_claim = claim_outbox_batch(db, limit=1, lease_for=timedelta(seconds=1), now=now)
    assert len(old_claim) == 1
    new_claim = claim_outbox_batch(db, limit=1, lease_for=timedelta(seconds=30), now=now + timedelta(seconds=2))
    assert len(new_claim) == 1
    assert not ack_outbox(db, event_id=old_claim[0].event_id, lease_token=old_claim[0].lease_token)
    assert ack_outbox(db, event_id=new_claim[0].event_id, lease_token=new_claim[0].lease_token)
    event = db.get(OutboxEvent, new_claim[0].event_id)
    assert event.state == "SENT" and event.sent_at is not None


@pytest.mark.parametrize("transition", ["ack", "retry"])
def test_preloaded_old_outbox_token_cannot_mutate_reclaimed_event(database, transition):
    db, owner_id, _, sessions = database
    task = enqueue_task(db, owner_id=owner_id, kind="EXTRACTION", task_key=f"preloaded-outbox-{transition}", revision=0)
    now = datetime.now(timezone.utc)
    old = claim_outbox_batch(db, limit=1, lease_for=timedelta(seconds=1), now=now)[0]
    db.commit()
    event = db.get(OutboxEvent, old.event_id)  # cache the old CLAIMED event and token
    assert event.lease_token == old.lease_token
    with sessions() as other:
        fresh = claim_outbox_batch(other, limit=1, lease_for=timedelta(seconds=30), now=now + timedelta(seconds=2))[0]
        fresh_token = fresh.lease_token
        other.commit()
    assert fresh_token != old.lease_token
    # A publisher with a lagging local clock still must not acknowledge or
    # release another publisher's current claim.
    if transition == "ack":
        changed = ack_outbox(db, event_id=old.event_id, lease_token=old.lease_token,
                             now=now + timedelta(milliseconds=500))
    else:
        changed = retry_outbox(db, event_id=old.event_id, lease_token=old.lease_token,
                               retry_after=timedelta(seconds=1), now=now + timedelta(milliseconds=500))
    assert changed is False
    db.expire_all()
    current = db.get(OutboxEvent, old.event_id)
    assert current.state == "CLAIMED" and current.lease_token == fresh_token


def test_publish_failure_is_retryable_and_duplicate_delivery_keeps_task_identity(database):
    db, owner_id, _, _ = database
    task = enqueue_task(db, owner_id=owner_id, kind="EMBEDDING", task_key="revision-2", revision=0)
    now = datetime.now(timezone.utc)
    claim = claim_outbox_batch(db, limit=1, lease_for=timedelta(seconds=30), now=now)[0]
    assert retry_outbox(db, event_id=claim.event_id, lease_token=claim.lease_token,
                        retry_after=timedelta(seconds=5), now=now)
    assert claim_outbox_batch(db, limit=1, lease_for=timedelta(seconds=30), now=now + timedelta(seconds=4)) == []
    second = claim_outbox_batch(db, limit=1, lease_for=timedelta(seconds=30), now=now + timedelta(seconds=6))[0]
    assert second.task_id == task.task_id
    assert ack_outbox(db, event_id=second.event_id, lease_token=second.lease_token)
    assert db.scalar(select(OutboxEvent).where(OutboxEvent.task_id == task.task_id)).state == "SENT"
