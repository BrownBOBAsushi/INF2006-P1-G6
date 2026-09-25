"""Complete resume-to-matches journey load harness for the REAL application at localhost:8080.

PURE PYTHON STDLIB (no numpy/httpx; nothing installed; tests/load/* untouched). Drives the actual
contract end to end per client:

    prepare (multipart PDF)  ->  PUT /api/resume (save: embedding + persistence, idempotent by key)
    ->  GET /api/resume (reload)  ->  GET /api/matches

Correctness is NOT "HTTP 200": every step's response schema is validated, the reloaded profile is
checked to be the saved content (canonical hash), a matchable profile + non-empty meaningful matches
are required, and failed assertions are recorded SEPARATELY from HTTP/transport errors.

Retry policy (RUNNER policy, distinct from the current frontend, which surfaces backoff to the user
and does not tight-poll): retryable transient codes (PROCESSING_BUSY, SERVICE_UNAVAILABLE,
PROCESSING_TIMEOUT, and SAVE_IN_PROGRESS on save) are retried honouring Retry-After if present, else
bounded full-jitter exponential backoff (base 0.25 s, x2, cap 3 s), with explicit attempt/elapsed
caps. Saves retry with the SAME Idempotency-Key (idempotent per DATA_API_CONTRACT: busy creates no
row; SAVE_IN_PROGRESS/timeout replay). REVIEW_REQUIRED is a confirmation step (resubmit the returned
cleaned draft under a NEW key), not a blind retry. Deterministic validation errors are never retried.
Sessions are read from an out-of-repo path; tokens are never written to results.

    python3 journey_load.py --base-url http://localhost:8080 --sessions <EXT>/sessions.json \
        --pdf-dir ../../tests/fixtures/pdf --scenario sequential --clients 5 --rounds 3 \
        --out results_sequential.json --timeline timeline_sequential.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CLIENT_TIMEOUT_S = 100.0
ORIGIN = "http://localhost:8080"
# Runner retry policy
RETRYABLE = {"PROCESSING_BUSY", "SERVICE_UNAVAILABLE", "PROCESSING_TIMEOUT", "SAVE_IN_PROGRESS", "MODEL_VERSION_UNAVAILABLE"}
BACKOFF_BASE_S, BACKOFF_FACTOR, BACKOFF_CAP_S = 0.25, 2.0, 3.0
MAX_ATTEMPTS, MAX_ELAPSED_S = 8, 60.0

_rng = random.Random(20260925)
_rng_lock = threading.Lock()


def _jitter(attempt: int) -> float:
    ceil = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (BACKOFF_FACTOR ** attempt))
    with _rng_lock:
        return _rng.uniform(0, ceil)  # full jitter


def canonical_hash(content: dict) -> str:
    blob = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Resp:
    __slots__ = ("status", "code", "body", "ms", "retry_after")

    def __init__(self, status, code, body, ms, retry_after=None):
        self.status, self.code, self.body, self.ms, self.retry_after = status, code, body, ms, retry_after


def _error_code(status: int, body):
    if isinstance(body, dict):
        for holder in (body, body.get("detail")):
            if isinstance(holder, dict) and isinstance(holder.get("error"), dict) and "code" in holder["error"]:
                return str(holder["error"]["code"])
    return f"HTTP_{status}"


def _do(req: urllib.request.Request) -> Resp:
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=CLIENT_TIMEOUT_S) as r:
            raw = r.read()
            ms = (time.perf_counter() - t0) * 1000
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                body = {}
            return Resp(r.status, "OK" if r.status == 200 else _error_code(r.status, body), body, ms)
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000
        raw = e.read()
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {}
        ra = e.headers.get("Retry-After")
        return Resp(e.code, _error_code(e.code, body), body, ms, float(ra) if ra and ra.isdigit() else None)
    except Exception as e:  # noqa: BLE001
        ms = (time.perf_counter() - t0) * 1000
        return Resp(0, f"CLIENT_{type(e).__name__}", {}, ms)


# ------------------------------------------------------------------ requests

def req_prepare(base, sess, body, ctype):
    return urllib.request.Request(base + "/api/resume/prepare", data=body, method="POST", headers={
        "Cookie": f"session={sess['raw_token']}", "X-CSRF-Token": sess["csrf_token"],
        "Origin": ORIGIN, "Content-Type": ctype})


def req_save(base, sess, content, expected_revision, idem_key):
    payload = json.dumps({"expected_revision": expected_revision, "content": content}).encode()
    return urllib.request.Request(base + "/api/resume", data=payload, method="PUT", headers={
        "Cookie": f"session={sess['raw_token']}", "X-CSRF-Token": sess["csrf_token"], "Origin": ORIGIN,
        "Content-Type": "application/json", "Idempotency-Key": idem_key})


def req_reload(base, sess):
    return urllib.request.Request(base + "/api/resume", method="GET",
                                  headers={"Cookie": f"session={sess['raw_token']}"})


def req_matches(base, sess, limit=20):
    return urllib.request.Request(base + f"/api/matches?limit={limit}", method="GET",
                                  headers={"Cookie": f"session={sess['raw_token']}"})


def req_browse(base, sess, limit=20):
    return urllib.request.Request(base + f"/api/jobs?limit={limit}", method="GET",
                                  headers={"Cookie": f"session={sess['raw_token']}"})


def _multipart(pdf: bytes):
    b = "----journey" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"resume.pdf\"\r\n"
            "Content-Type: application/pdf\r\n\r\n").encode() + pdf + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


# ------------------------------------------------------------------ retrying step

def retrying(make_req, *, is_write=False, key_for_retry=None):
    """Run one logical step with the runner retry policy. Returns (final_resp, meta) where meta records
    first-attempt outcome, attempts, waited_s, and each attempt's (code, ms)."""
    attempts, waited, t_start = 0, 0.0, time.perf_counter()
    first = None
    trail = []
    while True:
        attempts += 1
        resp = make_req()
        trail.append((resp.code, round(resp.ms, 1)))
        if first is None:
            first = resp.code
        if resp.status == 200:
            break
        if resp.code not in RETRYABLE:
            break  # deterministic / non-retryable: stop, caller asserts
        if attempts >= MAX_ATTEMPTS or (time.perf_counter() - t_start) > MAX_ELAPSED_S:
            break
        delay = resp.retry_after if resp.retry_after is not None else _jitter(attempts)
        waited += delay
        time.sleep(delay)
    return resp, {"first_code": first, "attempts": attempts, "waited_s": round(waited, 3), "trail": trail}


# ------------------------------------------------------------------ one journey

def run_journey(base, sess, pdf_bytes, pdf_name):
    """Returns a dict describing one complete journey with per-step latency, retries, and assertions."""
    j = {"pdf": pdf_name, "pdf_bytes": len(pdf_bytes), "steps": {}, "assert_failures": [], "http_errors": [],
         "completed": False}
    t_j0 = time.perf_counter()

    # 1) prepare (retryable read)
    body, ctype = _multipart(pdf_bytes)
    r, meta = retrying(lambda: _do(req_prepare(base, sess, body, ctype)))
    j["steps"]["prepare"] = {"ms": round(r.ms, 1), **meta, "final_code": r.code}
    if r.status != 200:
        j["http_errors"].append(f"prepare:{r.code}")
        j["whole_ms"] = round((time.perf_counter() - t_j0) * 1000, 1)
        return j
    draft = r.body.get("draft")
    if not (isinstance(draft, dict) and set(draft) == {"skills", "projects", "experience", "education"}):
        j["assert_failures"].append("prepare.draft_shape")
    if not (isinstance(r.body.get("warnings"), list) and "unassigned_text" in r.body):
        j["assert_failures"].append("prepare.envelope_shape")
    matchable_input = bool(draft) and (len(draft.get("projects", [])) + len(draft.get("experience", [])) > 0)
    if not matchable_input:
        j["assert_failures"].append("prepare.no_project_or_experience")

    # 2) save (idempotent write: retry same key; REVIEW_REQUIRED -> confirm cleaned under new key)
    content = draft
    expected_revision = 0
    save_body = None
    confirmations = 0
    for _confirm in range(3):
        key = str(uuid.uuid4())
        r, meta = retrying(lambda: _do(req_save(base, sess, content, expected_revision, key)), is_write=True)
        save_body = r
        if r.status == 200:
            break
        if r.code == "REVIEW_REQUIRED":
            cleaned = (r.body.get("detail", {}) or {}).get("error", {}).get("details", {}).get("cleaned_draft") \
                if isinstance(r.body.get("detail"), dict) else r.body.get("error", {}).get("details", {}).get("cleaned_draft")
            if isinstance(cleaned, dict) and set(cleaned) == {"skills", "projects", "experience", "education"}:
                content = cleaned
                confirmations += 1
                continue
            j["assert_failures"].append("save.review_required_no_cleaned_draft")
            break
        break
    j["steps"]["save"] = {"ms": round(save_body.ms, 1), **meta, "final_code": save_body.code,
                          "confirmations": confirmations}
    if save_body.status != 200:
        j["http_errors"].append(f"save:{save_body.code}")
        j["whole_ms"] = round((time.perf_counter() - t_j0) * 1000, 1)
        return j
    sb = save_body.body
    if not (isinstance(sb, dict) and {"operation_id", "result_revision", "changed"} <= set(sb)):
        j["assert_failures"].append("save.response_shape")
    if sb.get("changed") is not True or sb.get("result_revision") != expected_revision + 1:
        j["assert_failures"].append("save.not_changed_or_wrong_revision")
    saved_hash = canonical_hash(content)
    saved_revision = sb.get("result_revision")

    # 3) reload — prove persistence + round-trip content equality + matchable
    r, meta = retrying(lambda: _do(req_reload(base, sess)))
    j["steps"]["reload"] = {"ms": round(r.ms, 1), **meta, "final_code": r.code}
    if r.status != 200:
        j["http_errors"].append(f"reload:{r.code}")
    else:
        rb = r.body
        if rb.get("revision") != saved_revision:
            j["assert_failures"].append("reload.revision_mismatch")
        if canonical_hash(rb.get("content", {})) != saved_hash:
            j["assert_failures"].append("reload.content_hash_mismatch")
        if rb.get("has_matchable_resume") is not True:
            j["assert_failures"].append("reload.not_matchable")

    # 4) matches — meaningful results
    r, meta = retrying(lambda: _do(req_matches(base, sess)))
    j["steps"]["matches"] = {"ms": round(r.ms, 1), **meta, "final_code": r.code}
    if r.status != 200:
        j["http_errors"].append(f"matches:{r.code}")
    else:
        mb = r.body
        if not (isinstance(mb, dict) and {"items", "total", "profile_revision"} <= set(mb)):
            j["assert_failures"].append("matches.page_shape")
        if not (isinstance(mb.get("total"), int) and mb["total"] > 0 and mb.get("items")):
            j["assert_failures"].append("matches.empty")
        else:
            has_passage = any(rq.get("closest_passage", {}).get("text")
                              for it in mb["items"] for rq in it.get("requirements", []))
            if not has_passage:
                j["assert_failures"].append("matches.no_closest_passage")

    j["whole_ms"] = round((time.perf_counter() - t_j0) * 1000, 1)
    j["completed"] = (not j["assert_failures"]) and (not j["http_errors"])
    return j


# ------------------------------------------------------------------ scenarios

def scenario(base, sessions, pdfs, name, clients, rounds, browse_workers, timeline, mode, acct_start=0):
    rows = []
    browse_all = []
    # distinct account per journey slot across the whole scenario, plus browse accounts, to keep clients isolated
    acct = {"i": acct_start}
    acct_lock = threading.Lock()

    def next_sess():
        with acct_lock:
            s = sessions[acct["i"] % len(sessions)]
            acct["i"] += 1
        return s

    for rnd in range(rounds):
        t0 = time.perf_counter()
        phase = f"{name}:{mode}:c{clients}:round{rnd + 1}"
        stop = threading.Event()
        browse_samples = []
        blk = threading.Lock()
        browse_sessions = [sessions[-(1 + i)] for i in range(browse_workers)]  # dedicated tail accounts

        def browser(bidx):
            sess = browse_sessions[bidx]
            while not stop.is_set():
                r = _do(req_browse(base, sess))
                with blk:
                    browse_samples.append((r.status, round(r.ms, 1), r.code))
                time.sleep(0.05)

        bthreads = [threading.Thread(target=browser, args=(i,)) for i in range(browse_workers)]
        for bt in bthreads:
            bt.start()

        ts_start = time.time()
        if mode == "sequential":
            journeys = []
            for i in range(clients):
                sess = next_sess()
                pdf_name, pdf = pdfs[(rnd * clients + i) % len(pdfs)]
                journeys.append(run_journey(base, sess, pdf, pdf_name))
        else:  # burst: synchronised concurrent start
            start_barrier = threading.Barrier(clients)
            slots = [(next_sess(), pdfs[(rnd * clients + i) % len(pdfs)]) for i in range(clients)]

            def one(i):
                sess, (pdf_name, pdf) = slots[i]
                start_barrier.wait()
                return run_journey(base, sess, pdf, pdf_name)

            with ThreadPoolExecutor(max_workers=clients) as ex:
                journeys = list(ex.map(one, range(clients)))
        wall = time.perf_counter() - t0
        ts_end = time.time()
        stop.set()
        for bt in bthreads:
            bt.join()

        bs_ok = sum(1 for s, _, _ in browse_samples if s == 200)
        browse_all.append({"phase": phase, "n": len(browse_samples), "ok": bs_ok,
                           "ms": sorted(m for _, m, _ in browse_samples if _ == 200) if False else [m for s, m, _ in browse_samples if s == 200]})
        timeline.append({"phase": phase, "start_epoch": round(ts_start, 3), "end_epoch": round(ts_end, 3),
                         "clients": clients, "browse_workers": browse_workers})
        rows.append({"phase": phase, "round": rnd + 1, "clients": clients, "wall_s": round(wall, 3),
                     "journeys": journeys})
        print(f"[{time.strftime('%H:%M:%S')}] {phase}: wall={wall:.2f}s "
              f"completed={sum(1 for j in journeys if j['completed'])}/{len(journeys)} "
              f"browse_ok={bs_ok}/{len(browse_samples)}", flush=True)
    return rows, browse_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8080")
    ap.add_argument("--sessions", required=True, type=Path)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--mode", choices=["sequential", "burst"], required=True)
    ap.add_argument("--clients", type=int, required=True)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--browse-workers", type=int, default=0)
    ap.add_argument("--warmup", type=int, default=0, help="warm-up journeys (discarded) before measured rounds")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeline", type=Path, required=True)
    args = ap.parse_args()

    sessions = json.loads(args.sessions.read_text())
    pdf_files = sorted(args.pdf_dir.glob("resume_P*.pdf"))
    pdfs = [(p.name, p.read_bytes()) for p in pdf_files]
    if not pdfs:
        raise SystemExit("no resume_P*.pdf fixtures found")

    timeline = []
    if args.warmup:
        print(f"warm-up: {args.warmup} journeys (discarded)", flush=True)
        ts_start = time.time()
        for i in range(args.warmup):
            run_journey(args.base_url, sessions[i % len(sessions)], pdfs[i % len(pdfs)][1], pdfs[i % len(pdfs)][0])
        timeline.append({"phase": "warmup", "start_epoch": round(ts_start, 3), "end_epoch": round(time.time(), 3),
                         "clients": 1, "browse_workers": 0})

    rows, browse = scenario(args.base_url, sessions, pdfs, args.scenario, args.clients, args.rounds,
                            args.browse_workers, timeline, args.mode, acct_start=args.warmup)
    args.out.write_text(json.dumps({
        "base_url": args.base_url, "scenario": args.scenario, "mode": args.mode, "clients": args.clients, "rounds": args.rounds,
        "browse_workers": args.browse_workers, "warmup": args.warmup,
        "pdfs": [{"name": n, "bytes": len(b)} for n, b in pdfs],
        "retry_policy": {"retryable": sorted(RETRYABLE), "backoff_base_s": BACKOFF_BASE_S, "factor": BACKOFF_FACTOR,
                         "cap_s": BACKOFF_CAP_S, "max_attempts": MAX_ATTEMPTS, "max_elapsed_s": MAX_ELAPSED_S,
                         "honours_retry_after": True, "full_jitter": True},
        "rows": rows, "browse": browse,
    }, indent=2))
    args.timeline.write_text(json.dumps(timeline, indent=2))
    print(f"wrote {args.out} and {args.timeline}", flush=True)


if __name__ == "__main__":
    main()
