"""Full-application HTTP load driver for the baseline. PURE PYTHON STDLIB (no numpy/httpx),
so it needs no install and changes nothing in the repo or the app.

It drives the REAL running application at http://localhost:8080 (web/nginx proxy -> api -> db
-> processing child), using ISOLATED SYNTHETIC sessions minted by make_sessions.py. It does NOT
import tests/load/*; it re-implements the same closed-loop measurement so the reference scripts
stay untouched.

Metrics per (endpoint, concurrency): request latency p50/p95/max/mean (for admitted 200s),
successful throughput (admitted 200/s), error rate, and busy rejections (503 PROCESSING_BUSY).

    python3 http_load.py --base-url http://localhost:8080 --sessions sessions.json \
        --pdf ../../tests/fixtures/pdf/resume_P01.pdf --duration 15 --concurrency 1 5 10 \
        --out results.json

Each concurrency level C runs a closed loop of C worker threads for --duration seconds; worker i
uses session[i % len(sessions)] so each concurrent client is a distinct synthetic account.
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CLIENT_TIMEOUT_S = 100.0  # ARCHITECTURE.md client timeout


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def stats(ms: list[float]) -> dict:
    if not ms:
        return {"n": 0}
    return {"n": len(ms), "p50_ms": round(percentile(ms, 50), 1), "p95_ms": round(percentile(ms, 95), 1),
            "max_ms": round(max(ms), 1), "mean_ms": round(statistics.fmean(ms), 1)}


def _error_code(status: int, body: bytes) -> str:
    try:
        doc = json.loads(body)
    except (ValueError, TypeError):
        return f"HTTP_{status}"
    if isinstance(doc, dict):
        for holder in (doc, doc.get("detail")):
            if isinstance(holder, dict) and isinstance(holder.get("error"), dict) and "code" in holder["error"]:
                return str(holder["error"]["code"])
    return f"HTTP_{status}"


def _classify(status: int, code: str) -> str:
    if status == 200:
        return "ok"
    if code == "PROCESSING_BUSY":
        return "busy"
    if code == "PROCESSING_TIMEOUT":
        return "timeout"
    return "error"


def _multipart(pdf: bytes) -> tuple[bytes, str]:
    boundary = "----baseline" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="resume.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + pdf + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _do(req: urllib.request.Request) -> tuple[str, int, str, float]:
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=CLIENT_TIMEOUT_S) as resp:
            resp.read()
            ms = (time.perf_counter() - t0) * 1000
            return "ok" if resp.status == 200 else _classify(resp.status, _error_code(resp.status, b"")), resp.status, "OK", ms
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000
        body = e.read()
        code = _error_code(e.code, body)
        return _classify(e.code, code), e.code, code, ms
    except Exception as e:  # noqa: BLE001  (URLError, socket timeout, etc.)
        ms = (time.perf_counter() - t0) * 1000
        return "error", 0, f"CLIENT_{type(e).__name__}", ms


def prepare_req(base: str, sess: dict, body: bytes, ctype: str) -> urllib.request.Request:
    return urllib.request.Request(
        base + "/api/resume/prepare", data=body, method="POST",
        headers={"Cookie": f"session={sess['raw_token']}", "X-CSRF-Token": sess["csrf_token"],
                 "Origin": "http://localhost:8080", "Content-Type": ctype})


def browse_req(base: str, sess: dict) -> urllib.request.Request:
    return urllib.request.Request(
        base + "/api/jobs?limit=20", method="GET",
        headers={"Cookie": f"session={sess['raw_token']}"})


def run_level(base: str, sessions: list[dict], endpoint: str, conc: int, duration: float, pdf: bytes) -> dict:
    body, ctype = _multipart(pdf) if endpoint == "prepare" else (b"", "")
    samples: list[tuple] = []
    lock = threading.Lock()
    deadline = time.perf_counter() + duration

    def worker(idx: int):
        sess = sessions[idx % len(sessions)]
        local = []
        while time.perf_counter() < deadline:
            if endpoint == "prepare":
                r = _do(prepare_req(base, sess, body, ctype))
            else:
                r = _do(browse_req(base, sess))
            local.append(r)
        with lock:
            samples.extend(local)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        list(ex.map(worker, range(conc)))
    wall = time.perf_counter() - t0

    by = {"ok": [], "busy": [], "timeout": [], "error": []}
    codes: dict[str, int] = {}
    for kind, status, code, ms in samples:
        by[kind].append(ms)
        if kind in ("error", "busy", "timeout"):
            codes[code] = codes.get(code, 0) + 1
    total = len(samples)
    return {
        "endpoint": endpoint, "concurrency": conc, "duration_s": round(wall, 2), "total_requests": total,
        "requests_per_s": round(total / wall, 2),
        "admitted_ok": len(by["ok"]), "admitted_ok_per_s": round(len(by["ok"]) / wall, 2),
        "busy_503": len(by["busy"]), "busy_rate": round(len(by["busy"]) / total, 4) if total else 0,
        "timeout_504": len(by["timeout"]), "errors": len(by["error"]),
        "error_rate": round((len(by["error"]) + len(by["timeout"])) / total, 4) if total else 0,
        "ok_latency": stats(by["ok"]), "busy_latency": stats(by["busy"]),
        "non_ok_codes": codes,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8080")
    ap.add_argument("--sessions", required=True, type=Path)
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--duration", type=float, default=15.0)
    ap.add_argument("--concurrency", type=int, nargs="+", default=[1, 5, 10])
    ap.add_argument("--endpoints", nargs="+", default=["browse", "prepare"])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    sessions = json.loads(args.sessions.read_text())
    pdf = args.pdf.read_bytes()
    # one warm-up per endpoint (discarded)
    for ep in args.endpoints:
        run_level(args.base_url, sessions, ep, 1, 1.0, pdf)

    rows = []
    for ep in args.endpoints:
        for c in args.concurrency:
            print(f"[{time.strftime('%H:%M:%S')}] endpoint={ep} concurrency={c} ...", flush=True)
            row = run_level(args.base_url, sessions, ep, c, args.duration, pdf)
            rows.append(row)
            print(f"    ok={row['admitted_ok']} ok/s={row['admitted_ok_per_s']} busy={row['busy_503']} "
                  f"err={row['errors']} p50={row['ok_latency'].get('p50_ms')}ms p95={row['ok_latency'].get('p95_ms')}ms",
                  flush=True)

    args.out.write_text(json.dumps({
        "base_url": args.base_url, "pdf": str(args.pdf.name), "pdf_bytes": len(pdf),
        "sessions_used": len(sessions), "duration_s_per_level": args.duration,
        "concurrency_levels": args.concurrency, "rows": rows,
    }, indent=2))
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
