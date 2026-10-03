"""DB-backed workers for local polling or explicit SQS delivery mode."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text

from app.db.models import OutboxEvent, ProcessingTask, ResumeChunk, ResumeProfile
from app.db.session import SessionLocal
from app.processing.cloud_adapters import make_storage, make_task_queues, processing_mode
from app.processing.local_storage import LocalTempStorage
from app.processing.outbox import ack_outbox, claim_outbox_batch, retry_outbox
from app.processing.tasks import claim_next_task, claim_published_task, complete_task, fail_task
from app.processing.slot import ProcessingService

log = logging.getLogger(__name__)
LEASE_FOR = timedelta(minutes=15)
POLL_SECONDS = 2
RETRY_DELAY = timedelta(seconds=5)
CLEANUP_INTERVAL_SECONDS = 60


class LocalWorker:
    def __init__(self, kind: str, *, handlers=None, storage: LocalTempStorage | None = None,
                 session_factory=SessionLocal, queue=None, mode: str | None = None):
        if kind not in {"EXTRACTION", "EMBEDDING"}:
            raise ValueError("worker kind must be EXTRACTION or EMBEDDING")
        self.kind = kind
        self.handlers = handlers
        self.processing_service = None
        self.session_factory = session_factory
        self.mode = mode or processing_mode()
        if self.mode not in {"local", "aws"}:
            raise ValueError("worker mode must be local or aws")
        self.storage = storage if storage is not None else make_storage()
        self.queue = queue
        if self.mode == "aws" and self.queue is None:
            self.queue = make_task_queues()[kind]

    def dispatch_outbox(self) -> int:
        """Acknowledge task identities only after the durable DB queue is visible.

        Workers scan processing_tasks directly, so a crash after SENT cannot lose work.
        """
        db = self.session_factory()
        try:
            deliveries = claim_outbox_batch(db, limit=20, lease_for=timedelta(minutes=1))
            db.commit()
        finally:
            db.close()
        sent = 0
        for delivery in deliveries:
            db = self.session_factory()
            try:
                task = db.get(ProcessingTask, delivery.task_id)
                if task is not None and task.state not in {"CANCELLED", "FAILED"}:
                    ack_outbox(db, event_id=delivery.event_id, lease_token=delivery.lease_token)
                    db.commit()
                    sent += 1
                else:
                    event = db.get(OutboxEvent, delivery.event_id)
                    if event is not None:
                        event.state = "CANCELLED"
                        event.lease_token = None
                        event.lease_expires_at = None
                    db.commit()
            except Exception as exc:
                db.rollback()
                try:
                    retry_outbox(db, event_id=delivery.event_id, lease_token=delivery.lease_token,
                                 retry_after=RETRY_DELAY)
                    db.commit()
                except Exception:
                    db.rollback()
                log.warning("local_outbox_delivery_failed exception_class=%s", type(exc).__name__)
            finally:
                db.close()
        return sent

    def run_one(self) -> bool:
        db = self.session_factory()
        try:
            task = claim_next_task(db, kind=self.kind, lease_for=LEASE_FOR)
            if task is None:
                db.rollback()
                return False
            task_id, owner_id, revision = task.task_id, task.owner_id, task.revision
            token, payload_ref = task.lease_token, task.payload_ref
            db.commit()
        finally:
            db.close()

        self._process_claimed(task_id, owner_id, revision, token, payload_ref)
        return True

    def _process_claimed(self, task_id, owner_id, revision, token, payload_ref):
        try:
            if self.kind == "EXTRACTION":
                if payload_ref is None:
                    raise ValueError("missing temporary input")
                result = self._run_handler("prepare", {"pdf": self.storage.read(payload_ref)})
                self._complete_extraction(task_id, owner_id, revision, token, payload_ref, result)
            else:
                content = self._approved_content(owner_id, revision)
                if content is None:
                    self._fail(task_id, owner_id, token, "STALE_REVISION", retryable=False)
                    return
                result = self._run_handler("embed", {"content": content})
                self._complete_embedding(task_id, owner_id, revision, token, result)
        except Exception as exc:  # exception text may contain user data; log only class and task identity
            from app.processing.errors import ProcessingError
            code = exc.code if isinstance(exc, ProcessingError) else "INTERNAL_ERROR"
            retryable = isinstance(exc, ProcessingError) and exc.retryable or not isinstance(exc, ProcessingError)
            self._fail(task_id, owner_id, token, code, retryable=retryable)
            log.warning("local_task_failed kind=%s task_id=%s code=%s exception_class=%s",
                        self.kind, task_id, code, type(exc).__name__)

    def run_queue_message(self) -> bool:
        """Receive and process one SQS message; DB state controls every transition."""
        messages = self.queue.receive()
        for message in messages:
            receipt = message.get("ReceiptHandle")
            try:
                import json
                import uuid
                body = json.loads(message.get("Body", ""))
                if set(body) != {"task_id", "kind"} or body["kind"] != self.kind:
                    raise ValueError("invalid task message")
                task_id = uuid.UUID(body["task_id"])
            except (ValueError, TypeError, KeyError):
                # Keep malformed payloads in SQS so the configured DLQ receives them.
                if receipt:
                    self.queue.change_visibility(receipt, 30)
                continue

            db = self.session_factory()
            try:
                task = claim_published_task(db, task_id=task_id, kind=self.kind, lease_for=LEASE_FOR)
                if task is not None:
                    claimed = (task.task_id, task.owner_id, task.revision, task.lease_token, task.payload_ref)
                    db.commit()
                    disposition = "claimed"
                else:
                    row = db.get(ProcessingTask, task_id)
                    event = db.scalar(select(OutboxEvent).where(OutboxEvent.task_id == task_id))
                    if row is None or row.state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                        disposition = "terminal"
                    elif row.kind != self.kind:
                        disposition = "invalid"
                    elif event is None or event.state in {"PENDING", "CANCELLED"} or row.state == "RETRY_WAIT":
                        # A durable outbox retry or cancellation now owns recovery.
                        disposition = "durable_retry"
                    elif row.state == "PROCESSING" and row.lease_expires_at:
                        remaining = max(1, int((row.lease_expires_at - datetime.now(timezone.utc)).total_seconds()))
                        disposition = ("leased", remaining)
                    else:
                        disposition = "not_ready"
                    db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

            if disposition == "claimed":
                self._process_claimed(*claimed)
                state_db = self.session_factory()
                try:
                    row = state_db.get(ProcessingTask, task_id)
                    event = state_db.scalar(select(OutboxEvent).where(OutboxEvent.task_id == task_id))
                    terminal = row is None or row.state in {"SUCCEEDED", "FAILED", "CANCELLED"}
                    durable_retry = row is not None and row.state == "RETRY_WAIT" and event is not None and event.state == "PENDING"
                finally:
                    state_db.close()
                if terminal or durable_retry:
                    if receipt:
                        self.queue.delete(receipt)
                elif receipt:
                    self.queue.change_visibility(receipt, int(LEASE_FOR.total_seconds()))
            elif disposition in {"terminal", "durable_retry"}:
                if receipt:
                    self.queue.delete(receipt)
            elif isinstance(disposition, tuple) and disposition[0] == "leased":
                if receipt:
                    self.queue.change_visibility(receipt, disposition[1])
            elif disposition == "invalid" and receipt:
                self.queue.change_visibility(receipt, 30)
            elif receipt:
                # Publication may have raced its SENT acknowledgement.
                self.queue.change_visibility(receipt, 5)
            return True
        return False

    def _run_handler(self, operation: str, payload: dict):
        if self.handlers is not None:
            return self.handlers[operation](payload)
        if self.processing_service is None:
            raise RuntimeError("worker process service has not started")
        lease = self.processing_service.try_acquire()
        try:
            return lease.run(operation, payload)
        finally:
            lease.release()

    def _approved_content(self, owner_id, revision):
        db = self.session_factory()
        try:
            profile = db.get(ResumeProfile, owner_id)
            if profile is None or profile.revision != revision:
                return None
            return profile.content
        finally:
            db.close()

    def _complete_extraction(self, task_id, owner_id, revision, token, payload_ref, result):
        db = self.session_factory()
        try:
            if not complete_task(db, task_id=task_id, owner_id=owner_id, revision=revision, lease_token=token):
                rejected = db.get(ProcessingTask, task_id)
                if rejected is not None and rejected.state == "CANCELLED":
                    db.commit()
                    self.storage.delete(payload_ref)
                else:
                    db.rollback()
                return
            task = db.get(ProcessingTask, task_id)
            task.result_data = result
            task.expires_at = datetime.now(timezone.utc) + self.storage.ttl
            task.payload_ref = None
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        if payload_ref is not None:
            self.storage.delete(payload_ref)

    def _complete_embedding(self, task_id, owner_id, revision, token, result):
        chunks, vectors = result.get("chunks", []), result.get("vectors", [])
        if len(chunks) != len(vectors):
            raise ValueError("embedding result shape mismatch")
        db = self.session_factory()
        try:
            if not complete_task(db, task_id=task_id, owner_id=owner_id, revision=revision, lease_token=token):
                task = db.get(ProcessingTask, task_id)
                if task is not None and task.state == "CANCELLED":
                    db.commit()
                else:
                    db.rollback()
                return
            db.execute(delete(ResumeChunk).where(
                ResumeChunk.user_id == owner_id, ResumeChunk.profile_revision == revision
            ))
            for chunk, vector in zip(chunks, vectors):
                db.add(ResumeChunk(
                    user_id=owner_id, profile_revision=revision, section=chunk["section"],
                    entry_index=chunk["entry_index"], chunk_index=chunk["chunk_index"], text=chunk["text"],
                    embedding=[float(value) for value in vector], embedding_version=result["version"],
                ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _fail(self, task_id, owner_id, token, code, *, retryable):
        from sqlalchemy import select
        from app.processing.tasks import validate_failure_code
        if code not in {"PDF_REQUIRED", "PDF_UNREADABLE", "PDF_ENCRYPTED", "TEXT_REQUIRED", "INVALID_CONTENT",
                        "INTERNAL_ERROR", "SERVICE_UNAVAILABLE", "PROCESSING_TIMEOUT", "STALE_REVISION"}:
            code = "INTERNAL_ERROR"
        validate_failure_code(code)
        db = self.session_factory()
        try:
            before = db.scalar(select(ProcessingTask).where(
                ProcessingTask.task_id == task_id,
                ProcessingTask.owner_id == owner_id,
            ).with_for_update().execution_options(populate_existing=True))
            owned_lease = (before is not None and before.state == "PROCESSING"
                           and before.lease_token == token)
            fail_task(db, task_id=task_id, owner_id=owner_id, lease_token=token,
                      failure_code=code, retryable=retryable, retry_after=RETRY_DELAY)
            task = db.get(ProcessingTask, task_id)
            terminal = owned_lease and task is not None and task.state in {"FAILED", "CANCELLED"}
            payload_ref = task.payload_ref if terminal else None
            if terminal:
                task.payload_ref = None
                task.result_data = None
                task.expires_at = None
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        if payload_ref is not None:
            self.storage.delete(payload_ref)

    def cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        db = self.session_factory()
        try:
            expired = db.scalars(select(ProcessingTask).where(
                ProcessingTask.expires_at <= now,
                ProcessingTask.result_data.is_not(None),
            ).with_for_update(skip_locked=True).execution_options(populate_existing=True)).all()
            for task in expired:
                task.result_data = None
                task.expires_at = None
            refs = set()
            stale = db.scalars(select(ProcessingTask).where(
                ProcessingTask.kind == "EXTRACTION",
                ProcessingTask.state.in_({"PENDING", "RETRY_WAIT", "PROCESSING"}),
                ProcessingTask.created_at <= now - self.storage.ttl,
                (ProcessingTask.state != "PROCESSING") | (ProcessingTask.lease_expires_at <= now),
            ).with_for_update(skip_locked=True).execution_options(populate_existing=True)).all()
            for task in stale:
                if task.state not in {"PENDING", "RETRY_WAIT", "PROCESSING"}:
                    continue
                if task.state == "PROCESSING" and task.lease_expires_at and task.lease_expires_at > now:
                    continue
                if task.payload_ref:
                    refs.add(task.payload_ref)
                task.state, task.failure_code = "FAILED", "TASK_EXPIRED"
                task.payload_ref = None
                task.result_data = None
                task.expires_at = None
                task.lease_token = None
                task.lease_expires_at = None
                event = db.scalar(select(OutboxEvent).where(OutboxEvent.task_id == task.task_id)
                                  .with_for_update())
                if event is not None:
                    event.state = "CANCELLED"
                    event.lease_token = None
                    event.lease_expires_at = None
            live_refs = set(db.scalars(select(ProcessingTask.payload_ref).where(
                ProcessingTask.payload_ref.is_not(None),
                ProcessingTask.state.in_({"PENDING", "PROCESSING", "RETRY_WAIT"}),
            )).all())
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        for ref in refs:
            self.storage.delete(ref)
        self.storage.cleanup_orphans(live_refs, older_than=now - self.storage.ttl)

    def _heartbeat_path(self) -> Path | None:
        value = os.environ.get("WORKER_HEARTBEAT_PATH", "").strip()
        return Path(value) if value else None

    def _clear_heartbeat(self) -> None:
        path = self._heartbeat_path()
        if path is not None:
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)

    def _publish_heartbeat(self) -> None:
        self._assert_processing_ready()
        path = self._heartbeat_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text("ready\n", encoding="ascii")
        os.replace(temporary, path)

    def _assert_processing_ready(self) -> None:
        if self.handlers is None and (
            self.processing_service is None or not self.processing_service.is_ready()
        ):
            raise RuntimeError("processing model child lost readiness")

    def _check_database(self) -> None:
        db = self.session_factory()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()

    def run_forever(self, stop):
        self._clear_heartbeat()
        try:
            if self.handlers is None:
                self.processing_service = ProcessingService(worker_args=(self.kind,))
                self.processing_service.start()
                if not self.processing_service.is_ready():
                    raise RuntimeError("processing model did not become ready")
            if self.mode == "aws":
                # The model child, DB session, AWS client/config and handler setup
                # must all exist before Compose can report this worker healthy.
                self._check_database()
            self.cleanup()
            self._publish_heartbeat()
            last_cleanup = time.monotonic()
            while not stop():
                self._assert_processing_ready()
                if self.mode == "aws":
                    worked = self.run_queue_message()
                else:
                    self.dispatch_outbox()
                    worked = self.run_one()
                now = time.monotonic()
                if now - last_cleanup >= CLEANUP_INTERVAL_SECONDS:
                    self.cleanup()
                    last_cleanup = now
                self._publish_heartbeat()
                if not worked:
                    time.sleep(POLL_SECONDS)
        finally:
            self._clear_heartbeat()
            if self.processing_service is not None:
                self.processing_service.stop()
            clients = {getattr(self.storage, "client", None), getattr(self.queue, "client", None)}
            for client in clients:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("EXTRACTION", "EMBEDDING"), required=True)
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LocalWorker(args.kind).run_forever(lambda: stopped)


if __name__ == "__main__":
    main()
