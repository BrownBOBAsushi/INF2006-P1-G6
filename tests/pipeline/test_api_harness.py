"""HTTP-level behaviour of the processing slot through the REFERENCE harness (tests/load/harness_app.py), plus the load script's own
logic. The harness is not Jiaxin's API; these tests prove that the slot behaves as documented when wired the way the integration
guide says, and that the load script classifies results and refuses to run against a target that cannot be tested."""
import http.server
import json
import os
import subprocess
import sys
import threading
import time

import httpx
import pytest

os.environ["HARNESS_NO_AUTOSTART"] = "1"          # import the harness module without starting the production child

import slot_test_worker as fw
from conftest import ROOT

sys.path.insert(0, str(ROOT / "tests" / "load"))
import api_load                                    # noqa: E402
import harness_app                                 # noqa: E402
from starlette.testclient import TestClient        # noqa: E402

from app.processing.slot import ProcessingService  # noqa: E402


@pytest.fixture()
def client():
    svc = ProcessingService(worker_target=fw.main_http, deadline_s=1.0, startup_timeout_s=60)
    with TestClient(harness_app.create_app(svc)) as c:      # runs the lifespan: starts the child, stops it afterwards
        yield c


def post(client, body: bytes):
    return client.post("/api/resume/prepare", content=body, headers={"Content-Type": "application/octet-stream"})


def concurrently(fn):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", fn()))
    t.start()
    return t, out


def wait_ready(client, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if client.get("/health/ready").status_code == 200:
            return True
        time.sleep(0.1)
    return False


def test_success_returns_the_prepare_result_and_health_is_ready(client):
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").status_code == 200
    r = post(client, b"quick")
    assert r.status_code == 200 and set(r.json()) == {"draft", "unassigned_text", "warnings"}


def test_busy_is_an_immediate_503_with_the_contract_envelope_and_retry_after_3(client):
    slow, out = concurrently(lambda: post(client, b"sleep:0.9"))
    time.sleep(0.3)
    t0 = time.monotonic()
    r = post(client, b"quick")
    assert time.monotonic() - t0 < 0.5
    assert r.status_code == 503 and r.headers["Retry-After"] == "3"
    err = r.json()["error"]
    assert err["code"] == "PROCESSING_BUSY" and err["retryable"] is True and err["details"] == {} and err["request_id"]
    slow.join()
    assert out["r"].status_code == 200
    assert post(client, b"quick").status_code == 200        # slot free again


def test_browsing_and_health_keep_working_while_processing_is_busy(client):
    slow, out = concurrently(lambda: post(client, b"sleep:0.9"))
    time.sleep(0.3)
    for _ in range(5):
        t0 = time.monotonic()
        r = client.get("/api/jobs", params={"limit": 5})
        assert r.status_code == 200 and len(r.json()["items"]) == 5 and time.monotonic() - t0 < 0.3
    assert client.get("/health/ready").status_code == 200
    slow.join()


def test_deadline_gives_504_then_reports_not_ready_then_recovers(client):
    r = post(client, b"sleep:30")                             # child deadline is 1 s in this fixture
    assert r.status_code == 504
    err = r.json()["error"]
    assert (err["code"], err["retryable"]) == ("PROCESSING_TIMEOUT", True)
    assert client.get("/health/ready").status_code == 503      # replacement child is loading
    assert wait_ready(client)
    assert post(client, b"quick").status_code == 200


def test_child_crash_gives_500_and_the_service_recovers(client):
    r = post(client, b"crash")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR" and r.json()["error"]["retryable"] is False
    assert wait_ready(client)
    assert post(client, b"quick").status_code == 200


def test_processing_errors_map_to_their_contract_status_without_echoing_input(client):
    r = post(client, b"error:PDF_ENCRYPTED")
    assert r.status_code == 422 and r.json()["error"]["code"] == "PDF_ENCRYPTED"
    assert "PDF_ENCRYPTED" not in json.dumps(r.json()["error"]["message"])


def test_oversize_body_is_rejected_and_frees_the_slot(client):
    r = post(client, b"x" * (5_242_880 + 1))
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert post(client, b"quick").status_code == 200


# ------------------------------------------------------------------ load script logic

def test_error_code_and_classification_handle_both_envelope_shapes():
    r = lambda status, body: httpx.Response(status, json=body)                      # noqa: E731
    assert api_load.error_code(r(503, {"error": {"code": "PROCESSING_BUSY"}})) == "PROCESSING_BUSY"
    assert api_load.error_code(r(503, {"detail": {"error": {"code": "PROCESSING_BUSY"}}})) == "PROCESSING_BUSY"   # FastAPI HTTPException
    assert api_load.error_code(httpx.Response(502, text="bad gateway")) == "HTTP_502"
    assert api_load.error_code(r(401, {"detail": {"code": "AUTH_REQUIRED"}})) == "HTTP_401"
    assert [api_load.classify(*x) for x in [(200, "OK"), (503, "PROCESSING_BUSY"), (504, "PROCESSING_TIMEOUT"), (500, "INTERNAL_ERROR"), (401, "HTTP_401")]] \
        == ["ok", "busy", "timeout", "error", "error"]


def test_summarize_counts_each_class_and_error_codes():
    S = api_load.Sample
    out = api_load.summarize([S("ok", 200, "OK", 100.0), S("ok", 200, "OK", 300.0), S("busy", 503, "PROCESSING_BUSY", 5.0),
                              S("timeout", 504, "PROCESSING_TIMEOUT", 60000.0), S("error", 0, "CLIENT_ReadTimeout", 1.0)])
    assert out["total"] == 5 and out["ok"]["count"] == 2 and out["ok"]["max_ms"] == 300.0 and out["busy"]["count"] == 1
    assert out["timeout"]["count"] == 1 and out["error_codes"] == {"CLIENT_ReadTimeout": 1}


class _OpenApi(http.server.BaseHTTPRequestHandler):
    paths: dict = {}

    def do_GET(self):
        body = json.dumps({"paths": self.paths}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


def serve_openapi(paths):
    handler = type("H", (_OpenApi,), {"paths": paths})
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_probe_refuses_targets_that_lack_the_endpoints_or_a_session():
    complete = {"/api/resume/prepare": {"post": {}}, "/api/jobs": {"get": {}}, "/health/ready": {"get": {}}}
    srv, url = serve_openapi({"/api/resume": {"get": {}, "delete": {}}, "/api/jobs": {"get": {}}})       # like Jiaxin's API today
    try:
        with pytest.raises(api_load.NotRun) as exc:
            api_load.probe(api_load.Target(url, "external", cookies={"s": "x"}))
        assert "POST /api/resume/prepare" in str(exc.value) and "GET /health/ready" in str(exc.value)
    finally:
        srv.shutdown()
    srv, url = serve_openapi(complete)
    try:
        with pytest.raises(api_load.NotRun) as exc:
            api_load.probe(api_load.Target(url, "external"))                                                  # no session supplied
        assert "--cookie" in str(exc.value)
        api_load.probe(api_load.Target(url, "external", cookies={"s": "x"}))                                  # passes
    finally:
        srv.shutdown()
    with pytest.raises(api_load.NotRun):
        api_load.probe(api_load.Target("http://127.0.0.1:9", "external"))                                     # nothing listening


def test_run_py_without_a_target_exits_3_and_produces_no_numbers(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "tests" / "load" / "run.py"), "--scenario", "browse-during-processing",
                        "--out-dir", str(tmp_path)], capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "LOAD_BASE_URL"})
    assert p.returncode == 3 and "NOT RUN" in p.stderr and list(tmp_path.iterdir()) == []
