from types import SimpleNamespace
from datetime import timedelta

from app.processing.local_worker import LocalWorker


class _Storage:
    ttl = timedelta(hours=1)

    def __init__(self):
        self.deleted = []

    def delete(self, reference):
        self.deleted.append(reference)


class _Session:
    def __init__(self, task):
        self.task = task

    def get(self, _model, _task_id):
        return self.task

    def scalar(self, _statement):
        return self.task

    def rollback(self):
        pass

    def commit(self):
        pass

    def close(self):
        pass


def test_rejected_old_failure_token_keeps_current_workers_input(monkeypatch):
    task = SimpleNamespace(state="PROCESSING", lease_token="current-token", payload_ref="still-needed",
                           result_data=None, expires_at=None)
    storage = _Storage()
    worker = LocalWorker("EXTRACTION", handlers={}, storage=storage, session_factory=lambda: _Session(task))
    monkeypatch.setattr("app.processing.local_worker.fail_task", lambda *_a, **_k: False)

    worker._fail("task", "owner", "old-token", "INTERNAL_ERROR", retryable=True)

    assert task.payload_ref == "still-needed"
    assert storage.deleted == []


def test_rejected_old_failure_does_not_clear_new_success_result(monkeypatch):
    task = SimpleNamespace(state="SUCCEEDED", lease_token=None, payload_ref=None,
                           result_data={"draft": {"skills": ["current"]}}, expires_at="expires")
    storage = _Storage()
    worker = LocalWorker("EXTRACTION", handlers={}, storage=storage, session_factory=lambda: _Session(task))
    monkeypatch.setattr("app.processing.local_worker.fail_task", lambda *_a, **_k: False)

    worker._fail("task", "owner", "old-token", "INTERNAL_ERROR", retryable=True)

    assert task.result_data == {"draft": {"skills": ["current"]}}
    assert task.expires_at == "expires"


def test_rejected_old_completion_token_keeps_current_workers_input(monkeypatch):
    task = SimpleNamespace(state="PROCESSING")
    storage = _Storage()
    worker = LocalWorker("EXTRACTION", handlers={}, storage=storage, session_factory=lambda: _Session(task))
    monkeypatch.setattr("app.processing.local_worker.complete_task", lambda *_a, **_k: False)

    worker._complete_extraction("task", "owner", 1, "old-token", "still-needed", {})

    assert storage.deleted == []
