import json
import sys
import uuid
from types import ModuleType
from types import SimpleNamespace

import pytest

from app.processing.aws_storage import S3TemporaryStorage
from app.processing.sqs_transport import SqsTaskQueue
from app.processing import outbox_publisher
from app.processing import cloud_adapters
from app.db.models import OutboxEvent, ProcessingTask
from app.processing import local_worker


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]
        return {}

    def get_object(self, *, Bucket, Key):
        class Body:
            def __init__(self, value):
                self.value = value

            def read(self, amount=-1):
                return self.value if amount < 0 else self.value[:amount]

        return {"Body": Body(self.objects[(Bucket, Key)])}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


def test_s3_storage_round_trips_only_uuid_objects_under_private_prefix():
    client = FakeS3()
    storage = S3TemporaryStorage("synthetic-bucket", "temporary/uploads", client=client)

    reference = storage.store(b"%PDF-synthetic")

    assert storage.read(reference) == b"%PDF-synthetic"
    assert list(client.objects) == [("synthetic-bucket", f"temporary/uploads/{uuid.UUID(reference).hex}.pdf")]
    with pytest.raises(ValueError):
        storage.read("../../outside.pdf")


def test_s3_storage_rejects_uploads_over_five_mib_before_put():
    client = FakeS3()
    storage = S3TemporaryStorage("synthetic-bucket", "temporary/uploads", client=client)

    with pytest.raises(ValueError, match="size limit"):
        storage.store(b"x" * (5 * 1024 * 1024 + 1))
    assert client.objects == {}


def test_s3_storage_rejects_unsafe_prefixes():
    with pytest.raises(ValueError, match="safe prefix"):
        S3TemporaryStorage("synthetic-bucket", "temporary/../public", client=FakeS3())


class FakeSqs:
    def __init__(self):
        self.sent = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"MessageId": "synthetic-message-id"}


def test_sqs_messages_contain_only_task_identity_and_kind():
    client = FakeSqs()
    queue = SqsTaskQueue("https://sqs.invalid/synthetic", "EXTRACTION", client=client)
    task_id = uuid.uuid4()

    queue.publish(task_id)

    sent = client.sent[0]
    assert json.loads(sent["MessageBody"]) == {"task_id": str(task_id), "kind": "EXTRACTION"}
    assert "resume" not in sent["MessageBody"].lower()
    assert "owner" not in sent["MessageBody"].lower()


def test_sqs_transport_rejects_non_tls_queue_urls():
    with pytest.raises(ValueError, match="HTTPS queue URL"):
        SqsTaskQueue("http://sqs.invalid/queue", "EXTRACTION", client=FakeSqs())


def test_sqs_publish_requires_a_service_message_id_confirmation():
    queue = SqsTaskQueue("https://sqs.invalid/queue", "EXTRACTION",
                         client=SimpleNamespace(send_message=lambda **_kwargs: {}))

    with pytest.raises(RuntimeError, match="did not confirm"):
        queue.publish(uuid.uuid4())


class FakeSession:
    def __init__(self, task):
        self.task = task
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def get(self, _model, _key):
        return self.task

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_outbox_is_acknowledged_only_after_sqs_confirmation(monkeypatch):
    delivery = SimpleNamespace(event_id=uuid.uuid4(), task_id=uuid.uuid4(), lease_token=uuid.uuid4())
    task = SimpleNamespace(task_id=delivery.task_id, kind="EXTRACTION", state="PENDING")
    session = FakeSession(task)
    events = []
    queue = SimpleNamespace(publish=lambda task_id: events.append(("send", task_id)))
    monkeypatch.setattr(outbox_publisher, "claim_outbox_batch", lambda *_a, **_k: [delivery])
    monkeypatch.setattr(outbox_publisher, "ack_outbox",
                        lambda *_a, **_k: events.append(("ack", None)) or True)
    monkeypatch.setattr(outbox_publisher, "retry_outbox", lambda *_a, **_k: pytest.fail("unexpected retry"))

    assert outbox_publisher.OutboxPublisher({"EXTRACTION": queue}, session_factory=lambda: session).publish_once() == 1
    assert events == [("send", task.task_id), ("ack", None)]
    assert session.commits == 2
    assert session.closed


def test_outbox_send_failure_releases_for_retry_without_ack(monkeypatch):
    delivery = SimpleNamespace(event_id=uuid.uuid4(), task_id=uuid.uuid4(), lease_token=uuid.uuid4())
    task = SimpleNamespace(task_id=delivery.task_id, kind="EMBEDDING", state="PENDING")
    session = FakeSession(task)
    calls = []
    queue = SimpleNamespace(publish=lambda _task_id: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(outbox_publisher, "claim_outbox_batch", lambda *_a, **_k: [delivery])
    monkeypatch.setattr(outbox_publisher, "ack_outbox", lambda *_a, **_k: pytest.fail("must not ack failed send"))
    monkeypatch.setattr(outbox_publisher, "retry_outbox", lambda *_a, **_k: calls.append("retry") or True)

    assert outbox_publisher.OutboxPublisher({"EMBEDDING": queue}, session_factory=lambda: session).publish_once() == 0
    assert calls == ["retry"]
    assert session.rollbacks == 1


def test_aws_mode_fails_closed_when_required_settings_are_missing(monkeypatch):
    monkeypatch.setenv("PROCESSING_MODE", "aws")
    for name in ("AWS_REGION", "PROCESSING_TEMP_BUCKET", "PROCESSING_TEMP_PREFIX"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="AWS_REGION"):
        cloud_adapters.make_storage()


def test_unknown_processing_mode_is_rejected_instead_of_falling_back(monkeypatch):
    monkeypatch.setenv("PROCESSING_MODE", "remote-ish")

    with pytest.raises(RuntimeError, match="must be local or aws"):
        cloud_adapters.processing_mode()


def test_aws_queue_factory_rejects_same_queue_url_before_sdk_creation(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PROCESSING_EXTRACTION_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/extract")
    monkeypatch.setenv("PROCESSING_EMBEDDING_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/extract")
    sdk_calls = []
    boto3 = ModuleType("boto3")
    boto3.client = lambda *_a, **_k: sdk_calls.append("created") or object()
    botocore = ModuleType("botocore")
    config = ModuleType("botocore.config")
    config.Config = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", config)

    with pytest.raises(RuntimeError, match="must be distinct"):
        cloud_adapters.make_task_queues()

    assert sdk_calls == []


def test_aws_queue_factory_accepts_distinct_queue_urls_with_one_sdk_client(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("PROCESSING_EXTRACTION_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/extract")
    monkeypatch.setenv("PROCESSING_EMBEDDING_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/embed")
    calls = []
    client = object()
    boto3 = ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: calls.append((args, kwargs)) or client
    botocore = ModuleType("botocore")
    config = ModuleType("botocore.config")
    config.Config = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", config)

    queues = cloud_adapters.make_task_queues()

    assert set(queues) == {"EXTRACTION", "EMBEDDING"}
    assert queues["EXTRACTION"].queue_url.endswith("/extract")
    assert queues["EMBEDDING"].queue_url.endswith("/embed")
    assert all(queue.client is client for queue in queues.values())
    assert len(calls) == 1


class FakeQueue:
    def __init__(self, message):
        self.messages = [message]
        self.actions = []

    def receive(self):
        return self.messages

    def delete(self, receipt):
        self.actions.append(("delete", receipt))

    def change_visibility(self, receipt, seconds):
        self.actions.append(("visibility", receipt, seconds))


class FakeWorkerSession:
    def __init__(self, task, event):
        self.task = task
        self.event = event

    def get(self, model, _key):
        return self.task if model is ProcessingTask else self.event

    def scalar(self, _query):
        return self.event

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.mark.parametrize("state", ["SUCCEEDED", "FAILED", "CANCELLED"])
def test_sqs_receipt_is_deleted_for_database_terminal_tasks(monkeypatch, tmp_path, state):
    task_id = uuid.uuid4()
    task = SimpleNamespace(task_id=task_id, kind="EXTRACTION", state=state, lease_expires_at=None)
    queue = FakeQueue({"ReceiptHandle": "receipt", "Body": json.dumps({"task_id": str(task_id), "kind": "EXTRACTION"})})
    worker = local_worker.LocalWorker(
        "EXTRACTION", storage=SimpleNamespace(ttl=__import__("datetime").timedelta(hours=1)),
        queue=queue, mode="local", session_factory=lambda: FakeWorkerSession(task, SimpleNamespace(state="SENT")),
    )
    monkeypatch.setattr(local_worker, "claim_published_task", lambda *_a, **_k: None)

    assert worker.run_queue_message()
    assert queue.actions == [("delete", "receipt")]


def test_sqs_duplicate_with_live_database_lease_is_hidden_until_lease_expiry(monkeypatch, tmp_path):
    task_id = uuid.uuid4()
    from datetime import datetime, timedelta, timezone
    task = SimpleNamespace(task_id=task_id, kind="EXTRACTION", state="PROCESSING",
                           lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=40))
    event = SimpleNamespace(state="SENT")
    queue = FakeQueue({"ReceiptHandle": "receipt", "Body": json.dumps({"task_id": str(task_id), "kind": "EXTRACTION"})})
    worker = local_worker.LocalWorker(
        "EXTRACTION", storage=SimpleNamespace(ttl=timedelta(hours=1)), queue=queue, mode="local",
        session_factory=lambda: FakeWorkerSession(task, event),
    )
    monkeypatch.setattr(local_worker, "claim_published_task", lambda *_a, **_k: None)

    assert worker.run_queue_message()
    assert queue.actions[0][0:2] == ("visibility", "receipt")
    assert 1 <= queue.actions[0][2] <= 40


def test_sqs_receipt_is_deleted_after_durable_retry_or_success(monkeypatch):
    from datetime import timedelta
    task_id = uuid.uuid4()
    task = SimpleNamespace(task_id=task_id, kind="EXTRACTION", state="PROCESSING", lease_expires_at=None,
                           owner_id=uuid.uuid4(), revision=0, lease_token=uuid.uuid4(), payload_ref="opaque-ref")
    event = SimpleNamespace(state="SENT")
    queue = FakeQueue({"ReceiptHandle": "receipt", "Body": json.dumps({"task_id": str(task_id), "kind": "EXTRACTION"})})
    worker = local_worker.LocalWorker(
        "EXTRACTION", storage=SimpleNamespace(ttl=timedelta(hours=1)), queue=queue, mode="local",
        session_factory=lambda: FakeWorkerSession(task, event),
    )
    monkeypatch.setattr(local_worker, "claim_published_task", lambda *_a, **_k: task)

    def complete_retry(*_args):
        task.state = "RETRY_WAIT"
        event.state = "PENDING"

    monkeypatch.setattr(worker, "_process_claimed", complete_retry)

    assert worker.run_queue_message()
    assert queue.actions == [("delete", "receipt")]
