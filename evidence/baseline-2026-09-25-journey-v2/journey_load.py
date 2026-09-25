"""Corrected resume-to-matches journey harness (v2) for the REAL app at localhost:8080.

PURE PYTHON STDLIB (nothing installed; tests/load/* untouched). Fixes applied vs v1:

* DEADLINE ACCOUNTING uses a monotonic budget (--step-deadline). Request socket timeouts and backoff
  sleeps are bounded by remaining time, and responses returned after the budget are rejected. urllib's
  timeout is a socket-operation timeout, not cancellable wall-clock enforcement; a slow-drip response can
  exceed the step budget before it returns. This limitation is recorded in run metadata.
* IDEMPOTENT SAVES. One Idempotency-Key per payload; transient retries reuse the SAME key (never rotated
  to hide a failure). A valid replay (200 with changed=false) is accepted. Success is declared only after
  reload confirms result_revision and canonical content equality — not on changed=true alone.
* MATCH VALIDATION. Requires matches.profile_revision == the saved/reloaded revision, and a fixture-based
  check (adjudicated labels) that a known-relevant (label>=2) job for the profile appears in the results.
* THREE OUTCOME BUCKETS kept separate: http_errors (transport/HTTP), schema assert_failures (contract
  shape / revision / content round-trip), and fixture_failures (label-based relevance). A busy rejection
  or an exhausted journey is an UNSUCCESSFUL outcome regardless of bucket.

Sessions are read from a restricted out-of-repo tokens file; tokens are never written to results.
"""
from __future__ import annotations

import argparse
import csv
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

REQUEST_HARD_CAP_S = 100.0            # ARCHITECTURE.md client timeout ceiling
ORIGIN = "http://localhost:8080"
RETRYABLE = {"PROCESSING_BUSY", "SERVICE_UNAVAILABLE", "PROCESSING_TIMEOUT", "SAVE_IN_PROGRESS", "MODEL_VERSION_UNAVAILABLE"}
BACKOFF_BASE_S, BACKOFF_FACTOR, BACKOFF_CAP_S = 0.25, 2.0, 3.0

_rng = random.Random(20260925)
_rng_lock = threading.Lock()


def _jitter(attempt):
    ceil = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (BACKOFF_FACTOR ** attempt))
    with _rng_lock:
        return _rng.uniform(0, ceil)


def canonical_hash(content):
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class Resp:
    __slots__ = ("status", "code", "body", "ms", "retry_after")

    def __init__(self, status, code, body, ms, retry_after=None):
        self.status, self.code, self.body, self.ms, self.retry_after = status, code, body, ms, retry_after


def _error_code(status, body):
    if isinstance(body, dict):
        for holder in (body, body.get("detail")):
            if isinstance(holder, dict) and isinstance(holder.get("error"), dict) and "code" in holder["error"]:
                return str(holder["error"]["code"])
    return f"HTTP_{status}"


def _details(body):
    """Contract error details from {error:{details}} or {detail:{error:{details}}}."""
    if isinstance(body, dict):
        for holder in (body, body.get("detail")):
            if isinstance(holder, dict) and isinstance(holder.get("error"), dict):
                d = holder["error"].get("details")
                if isinstance(d, dict):
                    return d
    return {}


def _do(req, timeout):
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            ms = (time.perf_counter() - t0) * 1000
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                body = {}
            return Resp(r.status, "OK" if r.status == 200 else _error_code(r.status, body), body, ms)
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        ra = e.headers.get("Retry-After")
        return Resp(e.code, _error_code(e.code, body), body, ms, float(ra) if ra and str(ra).isdigit() else None)
    except Exception as e:  # noqa: BLE001
        ms = (time.perf_counter() - t0) * 1000
        return Resp(0, f"CLIENT_{type(e).__name__}", {}, ms)


def retrying(make_req, *, step_deadline_s, max_attempts):
    """Retry within a monotonic budget and reject any response returned after it.
    make_req(timeout)->Resp. urllib's socket timeout is not a cancellable wall deadline.
    Returns (resp, meta). meta.exhausted in {None,'attempt_budget','elapsed_deadline'}."""
    start = time.monotonic()
    deadline = start + step_deadline_s
    attempts, waited, first, trail, exhausted = 0, 0.0, None, [], None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            exhausted = "elapsed_deadline"
            break
        attempts += 1
        resp = make_req(min(remaining, REQUEST_HARD_CAP_S))
        if time.monotonic() >= deadline:
            resp = Resp(0, "CLIENT_DEADLINE_EXCEEDED", {}, resp.ms, resp.retry_after)
            trail.append((resp.code, round(resp.ms, 1)))
            first = first or resp.code
            exhausted = "elapsed_deadline"
            break
        trail.append((resp.code, round(resp.ms, 1)))
        if first is None:
            first = resp.code
        if resp.status == 200 or resp.code not in RETRYABLE:
            break
        if attempts >= max_attempts:
            exhausted = "attempt_budget"
            break
        delay = resp.retry_after if resp.retry_after is not None else _jitter(attempts)
        remaining = deadline - time.monotonic()
        if delay >= remaining:            # would sleep past the deadline: stop, do not retry early
            exhausted = "elapsed_deadline"
            break
        waited += delay
        time.sleep(delay)
    return resp, {"first_code": first, "attempts": attempts, "waited_s": round(waited, 3),
                  "elapsed_s": round(time.monotonic() - start, 3), "exhausted": exhausted, "trail": trail}


# ---------------------------------------------------------------- requests
def req_prepare(base, sess, body, ctype):
    return urllib.request.Request(base + "/api/resume/prepare", data=body, method="POST", headers={
        "Cookie": f"session={sess['raw_token']}", "X-CSRF-Token": sess["csrf_token"], "Origin": ORIGIN,
        "Content-Type": ctype})


def req_save(base, sess, content, expected_revision, idem_key):
    payload = json.dumps({"expected_revision": expected_revision, "content": content}).encode()
    return urllib.request.Request(base + "/api/resume", data=payload, method="PUT", headers={
        "Cookie": f"session={sess['raw_token']}", "X-CSRF-Token": sess["csrf_token"], "Origin": ORIGIN,
        "Content-Type": "application/json", "Idempotency-Key": idem_key})


def req_reload(base, sess):
    return urllib.request.Request(base + "/api/resume", method="GET", headers={"Cookie": f"session={sess['raw_token']}"})


def req_matches(base, sess, limit=20):
    return urllib.request.Request(base + f"/api/matches?limit={limit}", method="GET", headers={"Cookie": f"session={sess['raw_token']}"})


def req_browse(base, sess, limit=20):
    return urllib.request.Request(base + f"/api/jobs?limit={limit}", method="GET", headers={"Cookie": f"session={sess['raw_token']}"})


SUMMARY_FIELDS = ("job_id", "title", "company_name", "country_code", "location", "job_type",
                 "employment_time", "work_arrangement", "posted_at", "last_imported_at", "is_active")
ENUMS = {
    "job_type": {"INTERNSHIP", "OTHER", "UNKNOWN"},
    "employment_time": {"FULL_TIME", "PART_TIME", "UNKNOWN"},
    "work_arrangement": {"ON_SITE", "HYBRID", "REMOTE", "UNKNOWN"},
}


def browse_validation_code(body, expected_catalogue, *, limit=20):
    """Validate the public JobPage shape and rows against the synthetic fixture."""
    if not isinstance(body, dict) or not {"items", "total", "limit", "offset", "catalogue_revision"} <= set(body):
        return "BROWSE_SCHEMA_PAGE"
    items, total = body["items"], body["total"]
    if (not isinstance(items, list) or type(total) is not int or total != len(expected_catalogue)
            or body["limit"] != limit or body["offset"] != 0
            or type(body["catalogue_revision"]) is not int or body["catalogue_revision"] < 1
            or len(items) != min(limit, total)):
        return "BROWSE_SCHEMA_PAGINATION"
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not all(key in item for key in SUMMARY_FIELDS):
            return "BROWSE_SCHEMA_ITEM"
        if (not isinstance(item["job_id"], str) or item["job_id"] in seen
                or not isinstance(item["title"], str) or not item["title"].strip()
                or any(not isinstance(item[k], str) or not item[k].strip()
                       for k in ("company_name", "country_code", "location", "last_imported_at"))
                or (item["posted_at"] is not None and not isinstance(item["posted_at"], str))
                or type(item["is_active"]) is not bool
                or any(not isinstance(item[k], str) or item[k] not in values
                       for k, values in ENUMS.items())):
            return "BROWSE_SCHEMA_ITEM"
        signature = tuple(item[k] for k in ("title", "company_name", "country_code", "location",
                                             "job_type", "employment_time", "work_arrangement", "is_active"))
        if signature not in expected_catalogue or not item["is_active"]:
            return "BROWSE_CATALOGUE_CONTENT"
        seen.add(item["job_id"])
    return None


def safe_browse_validation_code(body, expected_catalogue):
    """Keep a malformed page or unexpected validator error visible as a failed sample."""
    try:
        return browse_validation_code(body, expected_catalogue)
    except Exception:  # noqa: BLE001 - the sampling worker must survive malformed response data
        return "BROWSE_SCHEMA_VALIDATION_ERROR"


def load_expected_catalogue(repo_root):
    jobs = json.loads((repo_root / "data/evaluation/jobs.json").read_text())["jobs"]
    return {
        (j["title"], j["company_name"], j["country_code"], j["location"], j["job_type"],
         j["employment_time"], j["work_arrangement"], j["is_active"])
        for j in jobs if j["is_active"]
    }


def _multipart(pdf):
    b = "----journeyv2" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"resume.pdf\"\r\n"
            "Content-Type: application/pdf\r\n\r\n").encode() + pdf + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


TOP_KEYS = {"skills", "projects", "experience", "education"}


def run_journey(base, sess, pdf_bytes, pdf_name, profile_id, relevant_titles, step_deadline_s, max_attempts):
    j = {"pdf": pdf_name, "profile_id": profile_id, "pdf_bytes": len(pdf_bytes), "steps": {},
         "assert_failures": [], "http_errors": [], "fixture_failures": [], "completed": False, "fixture_ok": None}
    t_j0 = time.perf_counter()

    # 1) prepare
    body, ctype = _multipart(pdf_bytes)
    r, meta = retrying(lambda to: _do(req_prepare(base, sess, body, ctype), to), step_deadline_s=step_deadline_s, max_attempts=max_attempts)
    j["steps"]["prepare"] = {"ms": round(r.ms, 1), **meta, "final_code": r.code}
    if r.status != 200:
        j["http_errors"].append(f"prepare:{r.code}:{meta['exhausted'] or 'no_retry'}")
        j["whole_ms"] = round((time.perf_counter() - t_j0) * 1000, 1)
        return j
    draft = r.body.get("draft")
    if not (isinstance(draft, dict) and set(draft) == TOP_KEYS):
        j["assert_failures"].append("prepare.draft_shape")
    if not (isinstance(r.body.get("warnings"), list) and "unassigned_text" in r.body):
        j["assert_failures"].append("prepare.envelope_shape")
    if not (draft and (len(draft.get("projects", [])) + len(draft.get("experience", [])) > 0)):
        j["assert_failures"].append("prepare.no_project_or_experience")

    # 2) save — one key per payload; transient retries reuse it; REVIEW_REQUIRED confirms cleaned under a new key
    content, expected_revision, confirmations = draft, 0, 0
    save_key = str(uuid.uuid4())
    r = None
    for _confirm in range(3):
        key = save_key  # SAME key for this payload (incl. all transient retries inside retrying())
        r, meta = retrying(lambda to, k=key, c=content: _do(req_save(base, sess, c, expected_revision, k), to),
                           step_deadline_s=step_deadline_s, max_attempts=max_attempts)
        if r.status == 200:
            break
        if r.code == "REVIEW_REQUIRED":
            cleaned = _details(r.body).get("cleaned_draft")
            if isinstance(cleaned, dict) and set(cleaned) == TOP_KEYS:
                content, save_key, confirmations = cleaned, str(uuid.uuid4()), confirmations + 1  # new payload -> new key
                continue
            j["assert_failures"].append("save.review_required_no_cleaned_draft")
        break
    j["steps"]["save"] = {"ms": round(r.ms, 1), **meta, "final_code": r.code, "confirmations": confirmations}
    if r.status != 200:
        j["http_errors"].append(f"save:{r.code}:{meta['exhausted'] or 'no_retry'}")
        j["whole_ms"] = round((time.perf_counter() - t_j0) * 1000, 1)
        return j
    sb = r.body
    if not (isinstance(sb, dict) and {"operation_id", "result_revision", "changed"} <= set(sb)):
        j["assert_failures"].append("save.response_shape")
    # ACCEPT replay: changed may be False on a valid idempotent replay. Require a sane result_revision;
    # authoritative persistence is verified by reload below (not by the changed flag).
    saved_hash = canonical_hash(content)
    saved_revision = sb.get("result_revision")
    j["steps"]["save"]["changed"] = sb.get("changed")
    if not (isinstance(saved_revision, int) and saved_revision >= 1):
        j["assert_failures"].append("save.bad_result_revision")

    # 3) reload — authoritative persistence + round-trip content equality + matchable
    r, meta = retrying(lambda to: _do(req_reload(base, sess), to), step_deadline_s=step_deadline_s, max_attempts=max_attempts)
    j["steps"]["reload"] = {"ms": round(r.ms, 1), **meta, "final_code": r.code}
    if r.status != 200:
        j["http_errors"].append(f"reload:{r.code}:{meta['exhausted'] or 'no_retry'}")
    else:
        rb = r.body
        if rb.get("revision") != saved_revision:
            j["assert_failures"].append("reload.revision_mismatch")
        if canonical_hash(rb.get("content", {})) != saved_hash:
            j["assert_failures"].append("reload.content_hash_mismatch")
        if rb.get("has_matchable_resume") is not True:
            j["assert_failures"].append("reload.not_matchable")
        saved_revision = rb.get("revision", saved_revision)  # authoritative revision for match check

    # 4) matches — profile_revision must equal the saved revision; fixture relevance check
    r, meta = retrying(lambda to: _do(req_matches(base, sess), to), step_deadline_s=step_deadline_s, max_attempts=max_attempts)
    j["steps"]["matches"] = {"ms": round(r.ms, 1), **meta, "final_code": r.code}
    if r.status != 200:
        j["http_errors"].append(f"matches:{r.code}:{meta['exhausted'] or 'no_retry'}")
    else:
        mb = r.body
        if not (isinstance(mb, dict) and {"items", "total", "profile_revision"} <= set(mb)):
            j["assert_failures"].append("matches.page_shape")
        else:
            if mb.get("profile_revision") != saved_revision:
                j["assert_failures"].append("matches.stale_profile_revision")
            if not (isinstance(mb.get("total"), int) and mb["total"] > 0 and mb.get("items")):
                j["assert_failures"].append("matches.empty")
            else:
                titles = [it.get("job", {}).get("title") for it in mb["items"]]
                top1 = titles[0] if titles else None
                j["match_summary"] = {
                    "returned": len(titles),
                    "top1_title": top1,
                    "top1_relevant": bool(top1 in relevant_titles) if relevant_titles else None,
                    "relevant2_in_results": bool(set(titles) & relevant_titles) if relevant_titles else None,
                    "any_closest_passage": any(rq.get("closest_passage", {}).get("text")
                                               for it in mb["items"] for rq in it.get("requirements", [])),
                }
                if not j["match_summary"]["any_closest_passage"]:
                    j["assert_failures"].append("matches.no_closest_passage")
                # fixture-based meaningfulness (labels are provisional -> separate bucket, non-fatal)
                if relevant_titles:
                    j["fixture_ok"] = j["match_summary"]["relevant2_in_results"]
                    if not j["fixture_ok"]:
                        j["fixture_failures"].append("matches.no_known_relevant_job_in_results")

    j["whole_ms"] = round((time.perf_counter() - t_j0) * 1000, 1)
    j["completed"] = (not j["assert_failures"]) and (not j["http_errors"])  # schema+transport success
    return j


# ---------------------------------------------------------------- scenarios
def scenario(base, sessions, pdfs, name, clients, rounds, browse_workers, timeline, mode, labels, expected_catalogue,
             step_deadline_s, max_attempts, acct_start=0):
    rows, browse_all = [], []
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
        browse_samples, blk = [], threading.Lock()
        browse_sessions = [sessions[-(1 + i)] for i in range(browse_workers)]

        def browser(bidx):
            sess = browse_sessions[bidx]
            while not stop.is_set():
                r = _do(req_browse(base, sess), REQUEST_HARD_CAP_S)
                validation = safe_browse_validation_code(r.body, expected_catalogue) if r.status == 200 else None
                with blk:
                    browse_samples.append((r.status if validation is None else 0, round(r.ms, 1), validation or r.code))
                time.sleep(0.05)

        bthreads = [threading.Thread(target=browser, args=(i,)) for i in range(browse_workers)]
        for bt in bthreads:
            bt.start()

        def journey_for(i):
            sess = next_sess()
            pdf_name, pdf = pdfs[(rnd * clients + i) % len(pdfs)]
            pid = pdf_name.replace("resume_", "").replace(".pdf", "")
            return sess, pdf, pdf_name, pid, labels.get(pid, set())

        ts_start = time.time()
        if mode == "sequential":
            journeys = []
            for i in range(clients):
                sess, pdf, pn, pid, rel = journey_for(i)
                journeys.append(run_journey(base, sess, pdf, pn, pid, rel, step_deadline_s, max_attempts))
        else:
            barrier = threading.Barrier(clients)
            slots = [journey_for(i) for i in range(clients)]

            def one(i):
                sess, pdf, pn, pid, rel = slots[i]
                barrier.wait()
                return run_journey(base, sess, pdf, pn, pid, rel, step_deadline_s, max_attempts)

            with ThreadPoolExecutor(max_workers=clients) as ex:
                journeys = list(ex.map(one, range(clients)))
        wall = time.perf_counter() - t0
        ts_end = time.time()
        stop.set()
        for bt in bthreads:
            bt.join()

        bs_ok = sum(1 for s, _, _ in browse_samples if s == 200)
        browse_all.append({"phase": phase, "n": len(browse_samples), "ok": bs_ok,
                           "ms": [m for s, m, _ in browse_samples if s == 200],
                           "non_ok_codes": {c: sum(1 for s2, _2, c2 in browse_samples if c2 == c and s2 != 200)
                                            for c in {c for s, _, c in browse_samples if s != 200}}})
        timeline.append({"phase": phase, "start_epoch": round(ts_start, 3), "end_epoch": round(ts_end, 3),
                         "clients": clients, "browse_workers": browse_workers})
        rows.append({"phase": phase, "round": rnd + 1, "clients": clients, "wall_s": round(wall, 3), "journeys": journeys})
        print(f"[{time.strftime('%H:%M:%S')}] {phase}: wall={wall:.2f}s "
              f"completed={sum(1 for j in journeys if j['completed'])}/{len(journeys)} "
              f"fixture_ok={sum(1 for j in journeys if j.get('fixture_ok'))} "
              f"browse_ok={bs_ok}/{len(browse_samples)}", flush=True)
    return rows, browse_all


def load_labels(repo_root):
    jobs = json.loads((repo_root / "data/evaluation/jobs.json").read_text())["jobs"]
    id2title = {j["source_job_id"]: j["title"] for j in jobs}
    labels = {}
    with open(repo_root / "data/evaluation/labels_adjudicated_v1.csv") as f:
        for row in csv.DictReader(f):
            if row["relevance"] == "2":  # known-relevant jobs per profile
                labels.setdefault(row["profile_id"], set()).add(id2title.get(row["job_id"]))
    return labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8080")
    ap.add_argument("--sessions", required=True, type=Path, help="restricted out-of-repo tokens file")
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--repo-root", required=True, type=Path)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--mode", choices=["sequential", "burst"], required=True)
    ap.add_argument("--clients", type=int, required=True)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--browse-workers", type=int, default=0)
    ap.add_argument("--warmup", type=int, default=0)
    ap.add_argument("--step-deadline", type=float, default=30.0)
    ap.add_argument("--max-attempts", type=int, default=10)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--timeline", type=Path, required=True)
    args = ap.parse_args()

    sessions = json.loads(args.sessions.read_text())["sessions"]
    pdfs = [(p.name, p.read_bytes()) for p in sorted(args.pdf_dir.glob("resume_P*.pdf"))]
    if not pdfs:
        raise SystemExit("no resume_P*.pdf fixtures")
    labels = load_labels(args.repo_root)
    expected_catalogue = load_expected_catalogue(args.repo_root)

    timeline = []
    if args.warmup:
        print(f"warm-up: {args.warmup} journeys (discarded)", flush=True)
        ts = time.time()
        for i in range(args.warmup):
            pn, pdf = pdfs[i % len(pdfs)]
            pid = pn.replace("resume_", "").replace(".pdf", "")
            run_journey(args.base_url, sessions[i % len(sessions)], pdf, pn, pid, labels.get(pid, set()),
                        args.step_deadline, args.max_attempts)
        timeline.append({"phase": "warmup", "start_epoch": round(ts, 3), "end_epoch": round(time.time(), 3),
                         "clients": 1, "browse_workers": 0})

    rows, browse = scenario(args.base_url, sessions, pdfs, args.scenario, args.clients, args.rounds,
                            args.browse_workers, timeline, args.mode, labels, expected_catalogue, args.step_deadline,
                            args.max_attempts, acct_start=args.warmup)
    args.out.write_text(json.dumps({
        "base_url": args.base_url, "scenario": args.scenario, "mode": args.mode, "clients": args.clients,
        "rounds": args.rounds, "browse_workers": args.browse_workers, "warmup": args.warmup,
        "pdfs": [{"name": n, "bytes": len(b)} for n, b in pdfs],
        "retry_policy": {"retryable": sorted(RETRYABLE), "backoff_base_s": BACKOFF_BASE_S, "factor": BACKOFF_FACTOR,
                         "cap_s": BACKOFF_CAP_S, "max_attempts": args.max_attempts, "step_deadline_s": args.step_deadline,
                         "honours_retry_after": True, "stops_if_retry_after_exceeds_budget": True, "same_key_for_transient_retry": True,
                         "wall_deadline": "late_responses_rejected; urllib socket timeout cannot cancel slow-drip reads"},
        "fixture": "data/evaluation/labels_adjudicated_v1.csv relevance>=2 per profile (provisional labels)",
        "rows": rows, "browse": browse,
    }, indent=2))
    args.timeline.write_text(json.dumps(timeline, indent=2))
    print(f"wrote {args.out} and {args.timeline}", flush=True)


if __name__ == "__main__":
    main()
