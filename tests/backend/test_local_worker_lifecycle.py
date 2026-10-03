from app.processing import local_worker
from app.processing.local_worker import LocalWorker


def test_cleanup_runs_on_cadence_even_when_worker_always_has_work(monkeypatch, tmp_path):
    worker = LocalWorker("EXTRACTION", handlers={}, storage=local_worker.LocalTempStorage(tmp_path))
    cleanups = []
    ticks = iter([0.0, 0.0, 60.0])
    loops = iter([False, False, True])
    monkeypatch.setattr(worker, "cleanup", lambda: cleanups.append("cleanup"))
    monkeypatch.setattr(worker, "dispatch_outbox", lambda: 0)
    monkeypatch.setattr(worker, "run_one", lambda: True)
    monkeypatch.setattr(local_worker.time, "monotonic", lambda: next(ticks))

    worker.run_forever(lambda: next(loops))

    assert cleanups == ["cleanup", "cleanup"]


def test_processing_child_stops_if_initial_cleanup_raises(monkeypatch, tmp_path):
    calls = []

    class Service:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            calls.append("start")

        def is_ready(self):
            return True

        def stop(self):
            calls.append("stop")

    monkeypatch.setattr(local_worker, "ProcessingService", Service)
    worker = LocalWorker("EXTRACTION", storage=local_worker.LocalTempStorage(tmp_path))
    monkeypatch.setattr(worker, "cleanup", lambda: (_ for _ in ()).throw(RuntimeError("cleanup failure")))

    import pytest
    with pytest.raises(RuntimeError, match="cleanup failure"):
        worker.run_forever(lambda: False)

    assert calls == ["start", "stop"]


def test_worker_heartbeat_waits_for_model_database_and_initial_cleanup(monkeypatch, tmp_path):
    from pathlib import Path

    heartbeat = tmp_path / "worker.ready"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(heartbeat))
    order = []

    class Service:
        def __init__(self, **_kwargs):
            self.ready = False

        def start(self):
            order.append("models")
            self.ready = True

        def is_ready(self):
            return self.ready

        def stop(self):
            order.append("stop")

    class Session:
        def execute(self, query):
            order.append(str(query))

        def close(self):
            pass

    monkeypatch.setattr(local_worker, "ProcessingService", Service)
    worker = LocalWorker(
        "EXTRACTION", storage=local_worker.LocalTempStorage(tmp_path / "storage"),
        session_factory=Session, queue=object(), mode="aws",
    )
    monkeypatch.setattr(worker, "cleanup", lambda: order.append("cleanup"))
    iterations = 0

    def receive_once():
        nonlocal iterations
        assert heartbeat.exists()
        assert order[:3] == ["models", "SELECT 1", "cleanup"]
        assert heartbeat.read_text() == "ready\n"
        iterations += 1
        return False

    monkeypatch.setattr(worker, "run_queue_message", receive_once)
    monkeypatch.setattr(local_worker.time, "sleep", lambda _seconds: None)

    worker.run_forever(lambda: iterations > 0)

    assert order == ["models", "SELECT 1", "cleanup", "stop"]
    assert not heartbeat.exists()


def test_worker_does_not_publish_heartbeat_when_model_start_fails(monkeypatch, tmp_path):
    import pytest

    heartbeat = tmp_path / "worker.ready"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(heartbeat))
    stopped = []

    class Service:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("model startup failed")

        def stop(self):
            stopped.append(True)

    monkeypatch.setattr(local_worker, "ProcessingService", Service)
    worker = LocalWorker("EMBEDDING", storage=local_worker.LocalTempStorage(tmp_path / "storage"))

    with pytest.raises(RuntimeError, match="model startup failed"):
        worker.run_forever(lambda: False)

    assert not heartbeat.exists()
    assert stopped == [True]


def test_worker_clears_heartbeat_and_stops_after_idle_model_child_dies(monkeypatch, tmp_path):
    import pytest

    heartbeat = tmp_path / "worker.ready"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(heartbeat))
    state = {"ready": False}
    stopped = []

    class Service:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            state["ready"] = True

        def is_ready(self):
            return state["ready"]

        def stop(self):
            stopped.append(True)
            state["ready"] = False

    class Session:
        def execute(self, _query):
            pass

        def close(self):
            pass

    monkeypatch.setattr(local_worker, "ProcessingService", Service)
    worker = LocalWorker(
        "EXTRACTION", storage=local_worker.LocalTempStorage(tmp_path / "storage"),
        session_factory=Session, queue=object(), mode="aws",
    )
    monkeypatch.setattr(worker, "cleanup", lambda: None)
    polls = 0

    def idle_poll():
        nonlocal polls
        assert heartbeat.exists()
        polls += 1
        state["ready"] = False
        return False

    monkeypatch.setattr(worker, "run_queue_message", idle_poll)
    monkeypatch.setattr(local_worker.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="lost readiness"):
        worker.run_forever(lambda: False)

    assert polls == 1
    assert not heartbeat.exists()
    assert stopped == [True]
