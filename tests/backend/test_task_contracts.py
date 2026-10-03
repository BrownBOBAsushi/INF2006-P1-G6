"""Offline task contract checks that do not claim PostgreSQL concurrency proof."""

import pytest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import OutboxEvent, ProcessingTask, User
from app.processing import outbox as outbox_lifecycle
from app.processing.outbox import _lock_event, claim_outbox_batch
from app.processing.tasks import _lock_task, enqueue_task, validate_failure_code, validate_task_spec


def test_task_identity_is_owner_kind_and_caller_key():
    identities = [constraint for constraint in ProcessingTask.__table__.constraints
                  if constraint.name == "uq_processing_tasks_identity"]
    assert len(identities) == 1
    assert {column.name for column in identities[0].columns} == {"owner_id", "kind", "task_key"}


def test_task_rows_keep_only_opaque_reference_and_safe_state_fields():
    assert {"payload_ref", "failure_code", "lease_token", "lease_expires_at"}.issubset(
        ProcessingTask.__table__.columns.keys()
    )
    assert "content" not in ProcessingTask.__table__.columns
    assert "pdf_bytes" not in ProcessingTask.__table__.columns
    assert {constraint.name for constraint in ProcessingTask.__table__.constraints} >= {
        "ck_processing_tasks_state", "ck_processing_tasks_attempt_bounds", "ck_processing_tasks_lease_state"
    }
    assert {constraint.name for constraint in OutboxEvent.__table__.constraints} >= {
        "uq_processing_outbox_task", "ck_processing_outbox_lease_state"
    }


@pytest.mark.parametrize("kind", ["EXTRACTION", "EMBEDDING"])
def test_supported_task_spec_is_accepted(kind):
    validate_task_spec(kind=kind, task_key="opaque-request-id", revision=4, max_attempts=3)


@pytest.mark.parametrize("kwargs", [
    {"kind": "OTHER", "task_key": "x", "revision": 0, "max_attempts": 3},
    {"kind": "EXTRACTION", "task_key": "", "revision": 0, "max_attempts": 3},
    {"kind": "EMBEDDING", "task_key": "x", "revision": -1, "max_attempts": 3},
    {"kind": "EMBEDDING", "task_key": "x", "revision": 0, "max_attempts": 0},
])
def test_invalid_task_spec_is_rejected(kwargs):
    with pytest.raises(ValueError):
        validate_task_spec(**kwargs)


def test_failure_code_rejects_free_form_resume_content():
    validate_failure_code("TEMPORARY_FAILURE_2")
    with pytest.raises(ValueError):
        validate_failure_code("Failed parsing Desmond resume.pdf")


def test_production_locked_read_helpers_refresh_stale_identity_map_rows(tmp_path):
    # SQLite has no row-level SKIP LOCKED behavior; this only verifies that the
    # production ORM reads replace stale cached objects after another session's
    # commit. PostgreSQL integration tests remain the concurrency proof.
    engine = create_engine(f"sqlite:///{tmp_path / 'task-refresh.db'}")
    Base.metadata.create_all(engine, tables=[User.__table__, ProcessingTask.__table__, OutboxEvent.__table__])
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    owner_id = uuid.uuid4()
    try:
        with sessions() as seed:
            seed.add(User(user_id=owner_id, google_sub=f"offline-{uuid.uuid4()}"))
            seed.flush()
            task = enqueue_task(seed, owner_id=owner_id, kind="EXTRACTION", task_key="offline-refresh",
                               revision=0, now=datetime.now(timezone.utc))
            task_id = task.task_id
            event_id = seed.query(OutboxEvent).filter_by(task_id=task_id).one().event_id
            seed.commit()

        with sessions() as stale, sessions() as writer:
            stale_task = stale.get(ProcessingTask, task_id)
            stale_event = stale.get(OutboxEvent, event_id)
            assert stale_task.state == "PENDING" and stale_event.state == "PENDING"
            stale.commit()  # retain clean ORM objects without holding SQLite's read transaction
            writer_task = writer.get(ProcessingTask, task_id)
            writer_task.state = "PROCESSING"
            writer_task.attempts = 1
            writer_task.lease_token = uuid.uuid4()
            writer_task.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
            writer_event = writer.get(OutboxEvent, event_id)
            writer_event.state = "CLAIMED"
            writer_event.lease_token = uuid.uuid4()
            writer_event.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
            writer.commit()

            refreshed_task = _lock_task(stale, task_id=task_id, owner_id=owner_id)
            refreshed_event = _lock_event(stale, event_id)
            assert refreshed_task is stale_task and stale_task.state == "PROCESSING"
            assert refreshed_event is stale_event and stale_event.state == "CLAIMED"
            assert stale_task.lease_token == writer_task.lease_token
            assert stale_event.lease_token == writer_event.lease_token
    finally:
        engine.dispose()


def test_completion_samples_production_clock_after_potentially_blocking_locks(monkeypatch):
    from app.processing import tasks as task_lifecycle

    started = datetime(2026, 10, 2, tzinfo=timezone.utc)
    clock = {"now": started}

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    owner_id = uuid.uuid4()
    token = uuid.uuid4()
    task = SimpleNamespace(
        state="PROCESSING", lease_token=token, lease_expires_at=started + timedelta(seconds=5),
        revision=0, task_id=uuid.uuid4(), failure_code=None, updated_at=None,
    )

    class SessionThatWaitsForLocks:
        calls = 0

        def flush(self):
            pass

        def scalar(self, _statement):
            self.calls += 1
            if self.calls == 1:  # User row lock was acquired after a simulated 10s wait
                clock["now"] = started + timedelta(seconds=10)
                return SimpleNamespace(resume_revision=0)
            return task  # task row lock is already held; lease has expired

    monkeypatch.setattr(task_lifecycle, "datetime", FakeDateTime)
    result = task_lifecycle.complete_task(
        SessionThatWaitsForLocks(), task_id=task.task_id, owner_id=owner_id,
        revision=0, lease_token=token,
    )
    assert result is False
    assert task.state == "PROCESSING"


@pytest.mark.parametrize("include_event", [False, True])
def test_production_outbox_batch_claim_runs_and_samples_time_after_query(monkeypatch, include_event):
    started = datetime(2026, 10, 2, tzinfo=timezone.utc)
    clock = {"now": started}

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    event = SimpleNamespace(
        event_id=uuid.uuid4(), task_id=uuid.uuid4(), state="PENDING", attempts=0,
        lease_token=None, lease_expires_at=None, updated_at=None,
    )

    class Rows:
        def all(self):
            return [event] if include_event else []

    class SessionThatWaitsForSelect:
        def flush(self):
            pass

        def scalars(self, _statement):
            clock["now"] = started + timedelta(seconds=10)
            return Rows()

    monkeypatch.setattr(outbox_lifecycle, "datetime", FakeDateTime)
    deliveries = claim_outbox_batch(
        SessionThatWaitsForSelect(), limit=1, lease_for=timedelta(seconds=30),
    )
    if include_event:
        assert len(deliveries) == 1
        assert event.state == "CLAIMED"
        assert event.lease_expires_at == started + timedelta(seconds=40)
    else:
        assert deliveries == []
