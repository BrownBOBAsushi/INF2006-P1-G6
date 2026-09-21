"""API-level (HTTP) load scenarios for the processing slot. Driven by tests/load/run.py.

    python tests/load/run.py --scenario browse-during-processing --target harness
    python tests/load/run.py --scenario api-concurrency          --target harness
    python tests/load/run.py --scenario api --target http://127.0.0.1:8000 --cookie "__Host-session=..." --csrf-token ... --origin http://localhost:8080

Targets
    harness   starts tests/load/harness_app.py (a REFERENCE app that wires the real ProcessingService behind HTTP; no auth, no DB).
              Numbers from it describe the slot behaviour over HTTP, NOT Jiaxin's API.
    <url>     any running API that implements the contract endpoints. The script probes /openapi.json first and stops with
              NOT RUN (exit 3) if POST /api/resume/prepare, GET /api/jobs or GET /health/ready are missing, or if no session was
              supplied for an authenticated API. It never guesses or fabricates a result.

Scenarios (IMPLEMENTATION_GUIDE.md: "Concurrent 1/5/10/25 requests; browse simultaneously with processing"):
    api-concurrency            1/5/10/25 concurrent resume-prepare requests; admitted vs busy (503) vs timeout (504) vs errors.
                               A busy response is a controlled rejection, NOT useful throughput.
    browse-during-processing   browse traffic alone (baseline), then the same browse traffic while several clients keep the
                               processing slot busy; shows browsing keeps working and how fast rejections are.
"""
from __future__ import annotations

import json
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "src" / "backend"
DEFAULT_PDF = ROOT / "tests" / "fixtures" / "pdf" / "resume_P10.pdf"
REQUIRED = [("post", "/api/resume/prepare"), ("get", "/api/jobs"), ("get", "/health/ready")]
CLIENT_TIMEOUT_S = 100.0                       # ARCHITECTURE.md: client timeout 100 s (proxy 90 s, child 60 s)
# Targets stated in ARCHITECTURE.md "Local acceptance": reported next to the measurements, not used to pass/fail anything.
TARGET_BUSY_RESPONSE_MS = 1000
TARGET_PROCESSING_S = 60


@dataclass
class Target:
    base_url: str
    kind: str                                  # "harness" | "external"
    headers: dict = field(default_factory=dict)
    cookies: dict = field(default_factory=dict)
    upload_mode: str = "raw"                   # "raw" body (harness) | "multipart" (contract)


class NotRun(Exception):
    """The scenario cannot run against this target; the message says why. Nothing is measured."""


@dataclass
class Sample:
    kind: str                                  # ok | busy | timeout | error
    status: int
    code: str
    ms: float


# ------------------------------------------------------------------ helpers

def pct(values, p):
    return float(np.percentile(values, p)) if values else float("nan")


def stats(ms: list[float]) -> dict:
    if not ms:
        return {"n": 0}
    return {"n": len(ms), "p50_ms": round(pct(ms, 50), 1), "p95_ms": round(pct(ms, 95), 1), "max_ms": round(max(ms), 1),
            "mean_ms": round(statistics.fmean(ms), 1)}


def make_client(t: Target) -> httpx.Client:
    return httpx.Client(base_url=t.base_url, headers=t.headers, cookies=t.cookies, timeout=CLIENT_TIMEOUT_S)


def error_code(resp: httpx.Response) -> str:
    """Contract error code from either {"error": {...}} or FastAPI's {"detail": {"error": {...}}}; else HTTP_<status>."""
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP_{resp.status_code}"
    if isinstance(body, dict):
        for holder in (body, body.get("detail")):
            if isinstance(holder, dict) and isinstance(holder.get("error"), dict) and "code" in holder["error"]:
                return str(holder["error"]["code"])
    return f"HTTP_{resp.status_code}"


def classify(status: int, code: str) -> str:
    if status == 200:
        return "ok"
    if code == "PROCESSING_BUSY":
        return "busy"
    if code == "PROCESSING_TIMEOUT":
        return "timeout"
    return "error"


def prepare_once(client: httpx.Client, t: Target, pdf: bytes) -> Sample:
    t0 = time.perf_counter()
    try:
        if t.upload_mode == "multipart":
            resp = client.post("/api/resume/prepare", files={"file": ("resume.pdf", pdf, "application/pdf")})
        else:
            resp = client.post("/api/resume/prepare", content=pdf, headers={"Content-Type": "application/octet-stream"})
        ms = (time.perf_counter() - t0) * 1000
        code = "OK" if resp.status_code == 200 else error_code(resp)
        return Sample(classify(resp.status_code, code), resp.status_code, code, ms)
    except httpx.HTTPError as exc:
        return Sample("error", 0, f"CLIENT_{type(exc).__name__}", (time.perf_counter() - t0) * 1000)


def browse_once(client: httpx.Client) -> Sample:
    t0 = time.perf_counter()
    try:
        resp = client.get("/api/jobs", params={"limit": 20})
        ms = (time.perf_counter() - t0) * 1000
        return Sample("ok" if resp.status_code == 200 else "error", resp.status_code, "OK" if resp.status_code == 200 else error_code(resp), ms)
    except httpx.HTTPError as exc:
        return Sample("error", 0, f"CLIENT_{type(exc).__name__}", (time.perf_counter() - t0) * 1000)


def summarize(samples: list[Sample]) -> dict:
    out = {"total": len(samples)}
    for kind in ("ok", "busy", "timeout", "error"):
        subset = [s.ms for s in samples if s.kind == kind]
        out[kind] = {"count": len(subset), **({} if not subset else stats(subset))}
    out["error_codes"] = {}
    for s in samples:
        if s.kind == "error":
            out["error_codes"][s.code] = out["error_codes"].get(s.code, 0) + 1
    return out


# ------------------------------------------------------------------ target management

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_harness(deadline_s: float) -> tuple[subprocess.Popen, Target, float]:
    port = free_port()
    env = {**os.environ, "PYTHONPATH": str(BACKEND), "HARNESS_DEADLINE_SECONDS": str(deadline_s), "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"}
    t0 = time.monotonic()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "--app-dir", str(ROOT / "tests" / "load"), "harness_app:app",
                             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    while time.monotonic() - t0 < 300:
        if proc.poll() is not None:
            raise NotRun("the reference harness exited during startup")
        try:
            if httpx.get(base + "/health/ready", timeout=2).status_code == 200:
                return proc, Target(base, "harness"), time.monotonic() - t0
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    stop_harness(proc)
    raise NotRun("the reference harness did not become ready within 300 s")


def stop_harness(proc: subprocess.Popen) -> None:
    try:
        for child in psutil.Process(proc.pid).children(recursive=True):
            child.kill()
    except psutil.Error:
        pass
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


def probe(t: Target) -> None:
    """Raise NotRun with the exact reason if the target cannot be load-tested. Measures nothing."""
    try:
        doc = httpx.get(t.base_url + "/openapi.json", timeout=10).json()
    except (httpx.HTTPError, ValueError):
        raise NotRun(f"cannot read {t.base_url}/openapi.json: the API is not running or does not expose its schema") from None
    paths = doc.get("paths", {})
    missing = [f"{m.upper()} {p}" for m, p in REQUIRED if m not in paths.get(p, {})]
    if missing:
        raise NotRun("the target does not implement: " + ", ".join(missing))
    if t.kind == "external" and not t.cookies:
        raise NotRun("the target requires an authenticated session: pass --cookie NAME=VALUE (plus --csrf-token and --origin for "
                     "unsafe methods) from a test login; this script cannot perform Google sign-in")


# ------------------------------------------------------------------ scenarios

def scenario_api_concurrency(t: Target, pdf: bytes, quick: bool) -> dict:
    plan = {1: 6, 5: 10} if quick else {1: 15, 5: 30, 10: 50, 25: 100}
    with make_client(t) as warm:                                    # one warm-up request, discarded
        prepare_once(warm, t, pdf)
    rows = []
    for conc, total in plan.items():
        samples: list[Sample] = []
        lock = threading.Lock()
        local = threading.local()

        def work(_):
            if not hasattr(local, "client"):
                local.client = make_client(t)
            s = prepare_once(local.client, t, pdf)
            with lock:
                samples.append(s)

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=conc) as ex:
            list(ex.map(work, range(total)))
        wall = time.perf_counter() - t0
        summ = summarize(samples)
        rows.append({"concurrency": conc, "requests": total, "wall_s": round(wall, 2),
                     "admitted_ok_per_s": round(summ["ok"]["count"] / wall, 2), "busy_rate": round(summ["busy"]["count"] / total, 3),
                     "error_rate": round((summ["error"]["count"] + summ["timeout"]["count"]) / total, 3), **summ})
        print(f"  concurrency={conc:>2}: ok={summ['ok']['count']} busy={summ['busy']['count']} timeout={summ['timeout']['count']} "
              f"error={summ['error']['count']} wall={wall:.1f}s", flush=True)
    return {"note": "closed-loop concurrent resume-prepare requests. 'busy' (503 PROCESSING_BUSY) is a controlled rejection, not useful "
                    "throughput; 'admitted_ok_per_s' counts only completed preparations.", "pdf_bytes": len(pdf), "rows": rows}


def scenario_browse_during_processing(t: Target, pdf: bytes, quick: bool) -> dict:
    baseline_s, phase_s = (3, 8) if quick else (5, 25)
    browse_workers, proc_workers = 4, 5

    def run_phase(seconds: float, with_processing: bool):
        stop = threading.Event()
        browse, proc = [], []
        lock = threading.Lock()

        def browser():
            with make_client(t) as c:
                while not stop.is_set():
                    s = browse_once(c)
                    with lock:
                        browse.append(s)
                    time.sleep(0.05)

        def processor():
            with make_client(t) as c:
                while not stop.is_set():
                    s = prepare_once(c, t, pdf)
                    with lock:
                        proc.append(s)

        threads = [threading.Thread(target=browser) for _ in range(browse_workers)]
        if with_processing:
            threads += [threading.Thread(target=processor) for _ in range(proc_workers)]
        for th in threads:
            th.start()
        time.sleep(seconds)
        stop.set()
        for th in threads:
            th.join()
        return browse, proc

    with make_client(t) as warm:
        prepare_once(warm, t, pdf)
    base_browse, _ = run_phase(baseline_s, False)
    print(f"  baseline browse: {len(base_browse)} requests", flush=True)
    load_browse, load_proc = run_phase(phase_s, True)
    print(f"  under processing: browse={len(load_browse)} prepare={len(load_proc)}", flush=True)
    bs, ls, ps = summarize(base_browse), summarize(load_browse), summarize(load_proc)
    busy_p95 = ps["busy"].get("p95_ms")
    ok_max = ps["ok"].get("max_ms")
    return {"note": f"{browse_workers} browse clients (GET /api/jobs, 50 ms think time) alone for {baseline_s} s, then for {phase_s} s together "
                    f"with {proc_workers} clients repeatedly submitting resume-prepare requests (closed loop).",
            "browse_baseline": bs, "browse_during_processing": ls, "processing": ps,
            "architecture_targets_for_reference": {
                "busy_response_target_ms": TARGET_BUSY_RESPONSE_MS, "busy_response_p95_ms_measured": busy_p95,
                "admitted_processing_target_s": TARGET_PROCESSING_S,
                "admitted_processing_max_s_measured": None if ok_max is None else round(ok_max / 1000, 2),
                "note": "targets come from ARCHITECTURE.md 'Local acceptance'; they concern the real API, so they are only indicative here."}}


SCENARIO_FUNCS = {"api-concurrency": scenario_api_concurrency, "browse-during-processing": scenario_browse_during_processing}


def run_api_scenarios(names: list[str], *, target: str, pdf_path: Path, quick: bool, cookie: str | None, csrf: str | None,
                      origin: str | None, deadline_s: float = 60.0) -> dict:
    pdf = pdf_path.read_bytes()
    proc = None
    ready_s = None
    try:
        if target == "harness":
            proc, t, ready_s = start_harness(deadline_s)
            print(f"harness ready after {ready_s:.1f} s (child process loads spaCy, Presidio and MiniLM)", flush=True)
        else:
            headers = {k: v for k, v in (("X-CSRF-Token", csrf), ("Origin", origin)) if v}
            cookies = dict([cookie.split("=", 1)]) if cookie else {}
            t = Target(target.rstrip("/"), "external", headers, cookies, "multipart")
            probe(t)
        results = {}
        for name in names:
            print(f"[{name}]", flush=True)
            results[name] = SCENARIO_FUNCS[name](t, pdf, quick)
        return {"target": {"kind": t.kind, "base_url": t.base_url if t.kind == "external" else "http://127.0.0.1:<port> (reference harness)",
                           "description": "tests/load/harness_app.py: NOT the project's API; no auth/CSRF/database"
                           if t.kind == "harness" else "external API"},
                "harness_ready_seconds": None if ready_s is None else round(ready_s, 1), "pdf": str(pdf_path.name), "pdf_bytes": len(pdf),
                "deadline_s": deadline_s, "quick": quick, "scenarios": results}
    finally:
        if proc is not None:
            stop_harness(proc)


def to_markdown(run: dict, meta: dict) -> str:
    L = [f"# API-level load measurements ({meta['date']})", "",
         f"Code version: git `{meta['git']['commit'][:10]}`" + (" (uncommitted changes present)" if meta["git"]["dirty_outside_evidence"] else "") + ".", ""]
    if run["target"]["kind"] == "harness":
        L += ["> **Target: the REFERENCE HARNESS (`tests/load/harness_app.py`), not the project's API.** It has no authentication, CSRF or "
              "database, so these numbers describe the processing slot and child process over real HTTP on this machine. They are not "
              "evidence about Jiaxin's routes, which do not exist yet.", ""]
    L += [f"- harness readiness time (child loading models): {run['harness_ready_seconds']} s", f"- PDF: {run['pdf']} ({run['pdf_bytes']} bytes)",
          f"- child deadline: {run['deadline_s']} s", "", "```json", json.dumps(meta["machine"], indent=2), "```", ""]
    for name, res in run["scenarios"].items():
        L += [f"## {name}", "", res["note"], ""]
        if name == "api-concurrency":
            cols = ["concurrency", "requests", "wall_s", "admitted_ok_per_s", "busy_rate", "error_rate"]
            L += ["| " + " | ".join(cols + ["ok p50/p95/max ms", "busy p50/p95/max ms", "timeout n", "error n"]) + " |",
                  "|" + "---|" * (len(cols) + 4)]
            for r in res["rows"]:
                fmt = lambda d: "-" if not d.get("count") else f"{d['p50_ms']} / {d['p95_ms']} / {d['max_ms']}"      # noqa: E731
                L.append("| " + " | ".join(str(r[c]) for c in cols) + f" | {fmt(r['ok'])} | {fmt(r['busy'])} | {r['timeout']['count']} | {r['error']['count']} |")
        else:
            for label, key in (("Browse alone (baseline)", "browse_baseline"), ("Browse while processing is busy", "browse_during_processing")):
                b = res[key]
                L.append(f"- **{label}:** {b['total']} requests; ok {b['ok']['count']} (p50 {b['ok'].get('p50_ms')} ms, p95 {b['ok'].get('p95_ms')} ms, "
                         f"max {b['ok'].get('max_ms')} ms); errors {b['error']['count']} {b['error_codes'] or ''}")
            p = res["processing"]
            L += [f"- **Processing clients:** {p['total']} requests: admitted ok {p['ok']['count']} (p50 {p['ok'].get('p50_ms')} ms, p95 {p['ok'].get('p95_ms')} ms, "
                  f"max {p['ok'].get('max_ms')} ms), busy 503 {p['busy']['count']} (p50 {p['busy'].get('p50_ms')} ms, p95 {p['busy'].get('p95_ms')} ms, "
                  f"max {p['busy'].get('max_ms')} ms), timeout 504 {p['timeout']['count']}, other errors {p['error']['count']} {p['error_codes'] or ''}",
                  f"- ARCHITECTURE.md targets, for reference only: {json.dumps(res['architecture_targets_for_reference'])}"]
        L.append("")
    return "\n".join(L) + "\n"
