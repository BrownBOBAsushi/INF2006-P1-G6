"""DB-coordinated SQS publisher shared by every API instance."""
from __future__ import annotations

import logging
from datetime import timedelta

from app.db.models import OutboxEvent, ProcessingTask
from app.db.session import SessionLocal
from app.processing.outbox import ack_outbox, claim_outbox_batch, retry_outbox

log = logging.getLogger(__name__)


class OutboxPublisher:
    def __init__(self, queues, *, session_factory=SessionLocal):
        self.queues = queues
        self.session_factory = session_factory

    def publish_once(self, *, limit: int = 20) -> int:
        db = self.session_factory()
        try:
            deliveries = claim_outbox_batch(db, limit=limit, lease_for=timedelta(minutes=1))
            db.commit()
        finally:
            db.close()

        sent = 0
        for delivery in deliveries:
            db = self.session_factory()
            try:
                task = db.get(ProcessingTask, delivery.task_id)
                if task is None or task.state in {"CANCELLED", "FAILED"}:
                    event = db.get(OutboxEvent, delivery.event_id)
                    if event is not None:
                        event.state = "CANCELLED"
                        event.lease_token = None
                        event.lease_expires_at = None
                    db.commit()
                    continue

                # The only SQS payload is the database task identity and kind.
                self.queues[task.kind].publish(task.task_id)
                if ack_outbox(db, event_id=delivery.event_id, lease_token=delivery.lease_token):
                    db.commit()
                    sent += 1
                else:
                    db.rollback()
            except Exception as exc:
                db.rollback()
                try:
                    if retry_outbox(db, event_id=delivery.event_id,
                                    lease_token=delivery.lease_token,
                                    retry_after=timedelta(seconds=5)):
                        db.commit()
                    else:
                        db.rollback()
                except Exception:
                    db.rollback()
                log.warning("sqs_outbox_delivery_failed exception_class=%s", type(exc).__name__)
            finally:
                db.close()
        return sent
