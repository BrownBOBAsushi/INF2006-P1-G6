"""Processing slot and isolated child: single non-blocking slot, 60 s deadline, terminate-and-join, recovery, disconnect safety.

Fast tests use a fake worker on the real protocol (slot_test_worker.py); the last section uses the real production child
(real spaCy/Presidio/MiniLM in a separate process)."""
import asyncio
import json
import socket
import subprocess
import sys
import threading
import time

import psutil
import pytest

import slot_test_worker as fw
from conftest import BACKEND, PDF_DIR

from app.processing import slot as slot_mod
from app.processing.errors import BUSY_RETRY_AFTER_SECONDS, ProcessingError
from app.processing.slot import DEADLINE_SECONDS, READY, RECOVERING, ProcessingService


@pytest.fixture()
def make_service():
    made = []

    def make(target=fw.main, **kw):
        svc = ProcessingService(worker_target=target, startup_timeout_s=kw.pop("startup_timeout_s", 60), **kw)
        made.append(svc)
        return svc

    yield make
    for svc in made:
        svc.stop()


def started(make_service, **kw):
    svc = make_service(**kw)
    svc.start()
    return svc


def in_thread(fn):
    out = {}

    def target():
        try:
            out["value"] = fn()
        except BaseException as exc:                                   # noqa: BLE001
            out["error"] = exc

    t = threading.Thread(target=target)
    t.start()
    return t, out


def wait_until(pred, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


# ------------------------------------------------------------------ configuration and isolation

def test_documented_deadline_is_60_seconds_and_is_the_default(make_service):
    assert DEADLINE_SECONDS == 60.0
    assert make_service().deadline_s == 60.0
    assert make_service(deadline_s=5).deadline_s == 5.0


def test_the_api_side_module_imports_no_ml_libraries():
    code = ("import sys; sys.path.insert(0, %r); import app.processing.slot; "
            "heavy = ('torch','spacy','presidio_analyzer','pdfplumber','sentence_transformers','transformers','numpy'); "
            "print(json.dumps([m for m in heavy if m in sys.modules]))" % str(BACKEND))
    out = subprocess.run([sys.executable, "-c", "import json; " + code], capture_output=True, text=True, check=True).stdout
    assert json.loads(out.strip().splitlines()[-1]) == []


def test_child_is_a_separate_process_and_stays_the_same_process_between_calls(make_service):
    svc = started(make_service)
    with svc.try_acquire() as lease:
        a = lease.run("pid", {})
        b = lease.run("pid", {})
    assert a == b != psutil.Process().pid and svc.child_pid == a


def test_lifecycle_and_readiness(make_service):
    svc = make_service()
    assert not svc.is_ready() and svc.state == "STOPPED"
    with pytest.raises(ProcessingError) as exc:
        svc.try_acquire()
    assert exc.value.code == "SERVICE_UNAVAILABLE" and exc.value.status_code == 503
    svc.start()
    assert svc.is_ready() and svc.state == READY
    svc.stop()
    assert not svc.is_ready()
    with pytest.raises(ProcessingError):
        svc.try_acquire()


def test_startup_failure_and_startup_timeout_are_reported_not_hung(make_service):
    bad = make_service(target=fw.main_fatal)
    with pytest.raises(ProcessingError) as exc:
        bad.start()
    assert exc.value.code == "SERVICE_UNAVAILABLE" and "ModelLoadError" in exc.value.reason and bad.state == "FAILED"
    slow = make_service(target=fw.main_never_ready, startup_timeout_s=1.5)
    t0 = time.monotonic()
    with pytest.raises(ProcessingError):
        slow.start()
    assert time.monotonic() - t0 < 8


# ------------------------------------------------------------------ the slot: one at a time, never queued

def test_second_request_gets_an_immediate_busy_response_and_slot_frees_afterwards(make_service):
    svc = started(make_service)
    lease = svc.try_acquire()
    t, out = in_thread(lambda: lease.run("sleep", {"seconds": 1.5}))
    time.sleep(0.3)
    t0 = time.monotonic()
    with pytest.raises(ProcessingError) as exc:
        svc.try_acquire()
    busy_ms = (time.monotonic() - t0) * 1000
    e = exc.value
    assert BUSY_RETRY_AFTER_SECONDS == 3                                   # contract: Retry-After: 3
    assert (e.code, e.status_code, e.retryable, e.retry_after_seconds) == ("PROCESSING_BUSY", 503, True, 3)
    assert busy_ms < 50                                                    # bounded: no waiting, no queue
    t.join()
    assert out["value"]["slept"] == 1.5
    lease.release()
    with svc.try_acquire() as again:                                       # slot is free once the work is done
        assert again.run("echo", {"a": 1})["echo"] == {"a": 1}


def test_slot_is_shared_by_all_operations_and_five_simultaneous_requests_admit_exactly_one(make_service):
    svc = started(make_service)

    async def scenario():
        async def one(i):
            try:
                return "ok", await svc.run_async("sleep" if i % 2 == 0 else "echo", {"seconds": 0.8, "i": i})
            except ProcessingError as e:
                return e.code, None

        t0 = time.monotonic()
        res = await asyncio.gather(*(one(i) for i in range(5)))
        return res, time.monotonic() - t0

    res, elapsed = asyncio.run(scenario())
    codes = sorted(c for c, _ in res)
    assert codes == ["PROCESSING_BUSY"] * 4 + ["ok"]
    assert elapsed < 3                                                     # rejected requests did not queue behind the winner


def test_lease_rules(make_service):
    svc = started(make_service)
    lease = svc.try_acquire()
    lease.release()
    lease.release()                                                        # idempotent
    with pytest.raises(RuntimeError):
        lease.run("echo", {})
    with svc.try_acquire() as l2:
        t, out = in_thread(lambda: l2.run("sleep", {"seconds": 0.5}))
        time.sleep(0.15)
        with pytest.raises(RuntimeError):
            l2.run("echo", {})                                             # one operation per lease at a time
        t.join()


# ------------------------------------------------------------------ client disconnect

def test_cancelling_the_request_does_not_free_a_running_slot(make_service):
    svc = started(make_service)

    async def scenario():
        task = asyncio.ensure_future(svc.run_async("sleep", {"seconds": 1.6}))
        await asyncio.sleep(0.3)
        task.cancel()                                                      # what a client disconnect does to the route
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.4)
        with pytest.raises(ProcessingError) as exc:                        # ~0.7 s in: the child is still computing
            svc.try_acquire()
        assert exc.value.code == "PROCESSING_BUSY"
        assert wait_until(lambda: not svc._slot.locked(), timeout=5)       # freed only after the work really ended
        with svc.try_acquire() as lease:
            return lease.run("echo", {"after": True})["echo"]

    assert asyncio.run(scenario()) == {"after": True}


def test_release_while_running_is_deferred_until_the_operation_ends(make_service):
    svc = started(make_service)
    lease = svc.try_acquire()
    t, _ = in_thread(lambda: lease.run("sleep", {"seconds": 1.0}))
    time.sleep(0.2)
    lease.release()                                                        # a naive `finally: lease.release()` on disconnect
    with pytest.raises(ProcessingError):
        svc.try_acquire()                                                  # still busy
    t.join()
    assert wait_until(lambda: not svc._slot.locked(), timeout=3)


# ------------------------------------------------------------------ deadline: terminate + join, recover

def test_deadline_terminates_and_joins_the_child_before_the_slot_is_released_then_recovers(make_service):
    svc = started(make_service, deadline_s=1.0)
    old_pid = svc.child_pid
    lease = svc.try_acquire()
    t0 = time.monotonic()
    with pytest.raises(ProcessingError) as exc:
        lease.run("sleep", {"seconds": 30})
    elapsed = time.monotonic() - t0
    assert (exc.value.code, exc.value.status_code, exc.value.retryable) == ("PROCESSING_TIMEOUT", 504, True)
    assert 1.0 <= elapsed < 4.0
    assert not psutil.pid_exists(old_pid)                                  # child was killed AND joined before we got here
    with pytest.raises(ProcessingError) as busy:
        svc.try_acquire()                                                  # the caller still holds the slot
    assert busy.value.code == "PROCESSING_BUSY"
    assert svc.state == RECOVERING and not svc.is_ready()                  # health would report not ready meanwhile
    lease.release()
    assert wait_until(svc.is_ready, timeout=30)                            # a fresh child was created
    assert svc.child_pid not in (None, old_pid)
    with svc.try_acquire() as again:
        assert again.run("echo", {"ok": 1})["echo"] == {"ok": 1}


@pytest.mark.slow
def test_the_default_60_second_deadline_really_fires_at_60_seconds(make_service):
    svc = started(make_service)                                            # default deadline, nothing overridden
    t0 = time.monotonic()
    with svc.try_acquire() as lease, pytest.raises(ProcessingError) as exc:
        lease.run("sleep", {"seconds": 300})
    elapsed = time.monotonic() - t0
    assert exc.value.code == "PROCESSING_TIMEOUT"
    assert 60.0 <= elapsed < 64.0, f"deadline fired after {elapsed:.1f}s"


def test_per_call_deadline_override_is_honoured(make_service):
    svc = started(make_service)
    with svc.try_acquire() as lease, pytest.raises(ProcessingError) as exc:
        lease.run("sleep", {"seconds": 10}, deadline_s=0.5)
    assert exc.value.code == "PROCESSING_TIMEOUT"


# ------------------------------------------------------------------ crash, errors, privacy of errors

def test_child_crash_is_a_safe_internal_error_and_the_child_is_replaced(make_service):
    svc = started(make_service)
    old = svc.child_pid
    with svc.try_acquire() as lease, pytest.raises(ProcessingError) as exc:
        lease.run("crash", {})
    assert (exc.value.code, exc.value.status_code, exc.value.retryable) == ("INTERNAL_ERROR", 500, False)
    assert wait_until(svc.is_ready, timeout=30) and svc.child_pid != old
    with svc.try_acquire() as lease:
        assert lease.run("echo", {"x": 2})["echo"] == {"x": 2}


def test_processing_errors_keep_their_contract_code_and_unexpected_errors_never_leak_text(make_service):
    svc = started(make_service)
    with svc.try_acquire() as lease:
        with pytest.raises(ProcessingError) as exc:
            lease.run("proc_error", {"code": "PDF_ENCRYPTED"})
        assert (exc.value.code, exc.value.status_code) == ("PDF_ENCRYPTED", 422)
        secret = "Priya Ramanathan Nair synthetic.student01@example.com"
        with pytest.raises(ProcessingError) as boom:
            lease.run("boom", {"secret": secret})
        assert boom.value.code == "INTERNAL_ERROR" and boom.value.reason == "RuntimeError"
        assert secret not in str(boom.value) and secret not in boom.value.message
        with pytest.raises(ProcessingError) as unknown:
            lease.run("nope", {})
        assert unknown.value.code == "INTERNAL_ERROR"
        assert lease.run("echo", {"still": "alive"})["echo"] == {"still": "alive"}     # an error does not kill the child


def test_a_5_mib_payload_and_result_pass_through_the_pipe(make_service):
    svc = started(make_service)
    with svc.try_acquire() as lease:
        assert len(lease.run("big", {"n": 5_242_880})) == 5_242_880


def test_repeated_recovery_failure_ends_in_service_unavailable_not_a_loop(make_service, tmp_path):
    svc = make_service(target=fw.main_ok_once, worker_args=(str(tmp_path / "started-once"),))
    svc.start()
    with svc.try_acquire() as lease, pytest.raises(ProcessingError):
        lease.run("crash", {})
    assert wait_until(lambda: svc.state == "FAILED", timeout=40)
    with pytest.raises(ProcessingError) as exc:
        svc.try_acquire()
    assert exc.value.code == "SERVICE_UNAVAILABLE" and not svc.is_ready()


# ------------------------------------------------------------------ restricted child

def test_child_network_guard_blocks_outbound_connections(make_service):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    try:
        open_child = started(make_service, target=fw.main)
        restricted = started(make_service, target=fw.main_restricted)
        with open_child.try_acquire() as a:
            assert a.run("connect", {"port": port}) == "connected"         # control: the connection works without the guard
        with restricted.try_acquire() as b:
            assert b.run("connect", {"port": port}) == "blocked"
    finally:
        listener.close()


# ------------------------------------------------------------------ the real production child

@pytest.fixture(scope="module")
def real_service():
    svc = ProcessingService()                                              # production worker, default 60 s deadline
    t0 = time.monotonic()
    svc.start()
    svc.startup_seconds = time.monotonic() - t0
    yield svc
    svc.stop()


def test_production_prepare_in_the_child_equals_in_process_and_propagates_error_codes(real_service, redactor):
    from app.processing.pipeline import prepare_resume
    data = (PDF_DIR / "resume_P01.pdf").read_bytes()
    with real_service.try_acquire() as lease:
        got = lease.run("prepare", {"pdf": data})
        local = prepare_resume(data, redactor)
        assert got == {"draft": local.draft, "unassigned_text": local.unassigned_text, "warnings": local.warnings}
        for name, code in (("edge_encrypted.pdf", "PDF_ENCRYPTED"), ("edge_scanned_image_only.pdf", "TEXT_REQUIRED"),
                           ("edge_not_a_pdf.pdf", "PDF_REQUIRED"), ("edge_11_pages.pdf", "PDF_UNREADABLE")):
            with pytest.raises(ProcessingError) as exc:
                lease.run("prepare", {"pdf": (PDF_DIR / name).read_bytes()})
            assert exc.value.code == code
        with pytest.raises(ProcessingError) as bad:
            lease.run("prepare", {"pdf": "not bytes"})
        assert bad.value.code == "INVALID_CONTENT"


def test_production_save_reproduces_in_process_embeddings_and_flags_privacy_changes(real_service, model, profiles):
    import numpy as np
    from app.processing.config import EMBEDDING_VERSION
    from app.processing.content import content_hash
    from app.processing.pipeline import embed_resume
    content = profiles["P01"]["content"]
    with real_service.try_acquire() as lease:
        res = lease.run("save", {"content": content})
        assert res["review_required"] is False and res["version"] == EMBEDDING_VERSION and res["content_hash"] == content_hash(content)
        local = embed_resume(content, model)
        assert res["chunks"] == local.chunks and res["vectors"].shape == (len(local.chunks), 384)
        assert np.allclose(res["vectors"], local.vectors, atol=1e-6)
        dirty = json.loads(json.dumps(content))
        dirty["projects"][0]["description"] += " Reach me at synthetic.student01@example.com."
        flagged = lease.run("save", {"content": dirty})
        assert flagged["review_required"] is True and "example.com" not in json.dumps(flagged["cleaned"])
        with pytest.raises(ProcessingError) as exc:
            lease.run("save", {"content": {"skills": []}})
        assert exc.value.code == "INVALID_CONTENT"


def test_production_child_startup_time_is_recorded(real_service):
    assert 0 < real_service.startup_seconds < slot_mod.STARTUP_TIMEOUT_SECONDS


def test_production_deadline_kills_real_work_and_the_service_recovers(profiles):
    svc = ProcessingService(deadline_s=0.01)                               # far shorter than any real preparation
    svc.start()
    try:
        old = svc.child_pid
        with svc.try_acquire() as lease, pytest.raises(ProcessingError) as exc:
            lease.run("prepare", {"pdf": (PDF_DIR / "resume_P10.pdf").read_bytes()})
        assert exc.value.code == "PROCESSING_TIMEOUT" and not psutil.pid_exists(old)
        assert wait_until(svc.is_ready, timeout=120)                        # real models reload in the replacement child
        with svc.try_acquire() as lease:
            res = lease.run("prepare", {"pdf": (PDF_DIR / "resume_P10.pdf").read_bytes()}, deadline_s=30)
        assert res["draft"] == profiles["P10"]["content"]
    finally:
        svc.stop()
