"""Focused verification of the harness's decision logic — no server, no DB, no data touched.

Drives the REAL journey_load code paths by monkeypatching the transport (urllib.request.urlopen) and,
for deadline tests, the clock. Covers: strict retry deadlines (attempt-budget vs elapsed-deadline,
Retry-After exceeding budget), valid idempotent replay (changed=false accepted), stale match-revision
detection, content round-trip mismatch detection, fixture relevance decision, and the integrity-diff
guard (nonzero on mismatch). Exit status is nonzero if any check fails.

    python3 selfcheck.py
"""
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import types
import uuid
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("journey_load", HERE / "journey_load.py")
JL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(JL)

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# ---- fake transport ---------------------------------------------------------
class FakeResp(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(json.dumps(body).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def make_urlopen(script):
    """script: callable(req)->(status, body) or raises. 200 -> FakeResp; else HTTPError."""
    def fake(req, timeout=None):
        status, body, headers = script(req)
        if status == 200:
            return FakeResp(status, body)
        raise urllib.error.HTTPError(req.full_url, status, "err", headers, io.BytesIO(json.dumps(body).encode()))
    return fake


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def perf_counter(self):
        return self.t

    def sleep(self, s):
        self.t += s


# ---- 1. deadline / exhaustion ----------------------------------------------
def test_deadlines():
    orig = JL.time
    fc = FakeClock()
    JL.time = fc
    try:
        # busy forever with Retry-After=3, step_deadline=5 -> must STOP at elapsed_deadline, not sleep past
        def busy(_req, ra=3):
            return None
        r, meta = JL.retrying(lambda to: JL.Resp(503, "PROCESSING_BUSY", {}, 1.0, retry_after=3),
                              step_deadline_s=5, max_attempts=99)
        check("deadline.retry_after_stops_at_elapsed", meta["exhausted"] == "elapsed_deadline", str(meta))
        check("deadline.did_not_sleep_past", fc.t <= 5 + 1e-9, f"t={fc.t}")
        # attempt-budget: small max_attempts, big deadline, jitter backoff (no retry-after)
        fc.t = 0.0
        r, meta = JL.retrying(lambda to: JL.Resp(503, "PROCESSING_BUSY", {}, 1.0, retry_after=None),
                              step_deadline_s=10_000, max_attempts=3)
        check("deadline.attempt_budget", meta["exhausted"] == "attempt_budget" and meta["attempts"] == 3, str(meta))
        # success on 2nd attempt -> no exhaustion
        fc.t = 0.0
        seq = [JL.Resp(503, "PROCESSING_BUSY", {}, 1.0, retry_after=None), JL.Resp(200, "OK", {}, 1.0)]
        r, meta = JL.retrying(lambda to: seq.pop(0), step_deadline_s=100, max_attempts=5)
        check("deadline.success_stops", meta["exhausted"] is None and meta["attempts"] == 2, str(meta))
        # retry-after larger than whole budget on first failure -> stop immediately, no early retry
        fc.t = 0.0
        r, meta = JL.retrying(lambda to: JL.Resp(503, "PROCESSING_BUSY", {}, 1.0, retry_after=30),
                              step_deadline_s=5, max_attempts=99)
        check("deadline.retry_after_exceeds_budget_stops", meta["exhausted"] == "elapsed_deadline" and meta["attempts"] == 1, str(meta))
        # A transport that returns success after its supplied socket timeout is late;
        # reject it and account elapsed-deadline rather than counting a success.
        fc.t = 0.0
        def late_success(_timeout):
            fc.t = 6.0
            return JL.Resp(200, "OK", {"accepted": True}, 6000.0)
        r, meta = JL.retrying(late_success, step_deadline_s=5, max_attempts=3)
        check("deadline.late_success_rejected", r.status == 0 and r.code == "CLIENT_DEADLINE_EXCEEDED"
              and meta["exhausted"] == "elapsed_deadline" and meta["elapsed_s"] == 6.0, str(meta))

        # Simulate a slow response body read: urllib's socket timeout is not a wall
        # deadline, so a body returned late is still rejected by retrying().
        fc.t = 0.0
        class SlowBody(FakeResp):
            def read(self, *args):
                fc.t = 6.0
                return super().read(*args)
        orig_open = JL.urllib.request.urlopen
        JL.urllib.request.urlopen = lambda req, timeout=None: SlowBody(200, {"ok": True})
        try:
            r, meta = JL.retrying(lambda to: JL._do(JL.urllib.request.Request("http://x"), to),
                                  step_deadline_s=5, max_attempts=1)
        finally:
            JL.urllib.request.urlopen = orig_open
        check("deadline.slow_read_success_rejected", r.status == 0 and r.code == "CLIENT_DEADLINE_EXCEEDED"
              and meta["exhausted"] == "elapsed_deadline", str(meta))
    finally:
        JL.time = orig


# ---- 2. full journey through mocked transport ------------------------------
DRAFT = {"skills": ["Python", "Flask"], "projects": [{"title": "t", "description": "d", "technologies": ["Python"]}],
         "experience": [], "education": []}


def journey_with(save_status_body, reload_body, matches_body, relevant_titles=frozenset({"Backend Software Engineer Intern"})):
    def script(req):
        u, m = req.full_url, req.method
        if u.endswith("/api/resume/prepare"):
            return 200, {"draft": DRAFT, "unassigned_text": "", "warnings": []}, {}
        if u.endswith("/api/resume") and m == "PUT":
            return (*save_status_body, {})
        if u.endswith("/api/resume") and m == "GET":
            return 200, reload_body, {}
        if "/api/matches" in u:
            return 200, matches_body, {}
        return 404, {"error": {"code": "X"}}, {}
    orig = JL.urllib.request.urlopen
    JL.urllib.request.urlopen = make_urlopen(script)
    try:
        return JL.run_journey("http://x", {"raw_token": "t", "csrf_token": "c"}, b"%PDF", "resume_P01.pdf",
                              "P01", relevant_titles, step_deadline_s=5, max_attempts=3)
    finally:
        JL.urllib.request.urlopen = orig


def test_journey_paths():
    saved_hash = JL.canonical_hash(DRAFT)
    good_reload = {"revision": 1, "content": DRAFT, "embedding_version": "v", "has_matchable_resume": True}
    good_matches = {"total": 1, "profile_revision": 1, "items": [
        {"job": {"title": "Backend Software Engineer Intern"}, "requirements": [
            {"closest_passage": {"text": "Flask", "section": "PROJECT", "entry_index": 0}}], "eligibility_notes": []}]}

    # valid idempotent replay: changed=false, rev=1 -> accepted, completed, fixture ok
    j = journey_with((200, {"operation_id": "o", "result_revision": 1, "changed": False}), good_reload, good_matches)
    check("replay.changed_false_accepted", j["completed"] and j["steps"]["save"]["changed"] is False, str(j["assert_failures"] + j["http_errors"]))
    check("replay.fixture_ok", j["fixture_ok"] is True)

    # first save changed=true also fine
    j = journey_with((200, {"operation_id": "o", "result_revision": 1, "changed": True}), good_reload, good_matches)
    check("save.changed_true_completed", j["completed"])

    # stale match profile_revision -> flagged, not completed, and it is a SCHEMA assert (not http error)
    stale = dict(good_matches, profile_revision=0)
    j = journey_with((200, {"operation_id": "o", "result_revision": 1, "changed": True}), good_reload, stale)
    check("matches.stale_revision_detected", "matches.stale_profile_revision" in j["assert_failures"] and not j["completed"])
    check("matches.stale_is_not_http_error", not j["http_errors"])

    # content round-trip mismatch -> flagged
    bad_reload = dict(good_reload, content={"skills": ["DIFFERENT"], "projects": [], "experience": [], "education": []})
    j = journey_with((200, {"operation_id": "o", "result_revision": 1, "changed": True}), bad_reload, good_matches)
    check("reload.content_mismatch_detected", "reload.content_hash_mismatch" in j["assert_failures"])

    # fixture: known-relevant job absent from results -> fixture_failure (separate), but schema still completes
    off = {"total": 1, "profile_revision": 1, "items": [
        {"job": {"title": "Totally Unrelated Job"}, "requirements": [
            {"closest_passage": {"text": "x", "section": "PROJECT", "entry_index": 0}}], "eligibility_notes": []}]}
    j = journey_with((200, {"operation_id": "o", "result_revision": 1, "changed": True}), good_reload, off)
    check("fixture.separate_from_schema", j["completed"] and j["fixture_ok"] is False and "matches.no_known_relevant_job_in_results" in j["fixture_failures"])


# ---- 3. integrity-diff guard -----------------------------------------------
def test_integrity_guard():
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "before.txt"; b = Path(d) / "after.txt"
        a.write_text("users|1|abc\n"); b.write_text("users|1|abc\n")
        same = subprocess.run(["diff", "-q", str(a), str(b)]).returncode
        b.write_text("users|1|CHANGED\n")
        diff = subprocess.run(["diff", "-q", str(a), str(b)]).returncode
        check("integrity.diff_guard", same == 0 and diff != 0)


def test_browse_validation():
    signature = ("Synthetic Intern", "Example Co", "SG", "Singapore", "INTERNSHIP", "FULL_TIME", "HYBRID", True)
    item = dict(zip(JL.SUMMARY_FIELDS, (str(uuid.uuid4()), *signature[:7], None, "2026-09-25T00:00:00Z", True)))
    page = {"items": [item], "total": 1, "limit": 20, "offset": 0, "catalogue_revision": 1}
    expected = {signature}
    check("browse.valid_page_and_synthetic_item", JL.browse_validation_code(page, expected) is None)
    check("browse.http200_bad_envelope_rejected", JL.browse_validation_code({"ok": True}, expected) == "BROWSE_SCHEMA_PAGE")
    bad_page = dict(page, items=[dict(item, title="Not in synthetic catalogue")])
    check("browse.http200_unexpected_catalogue_content_rejected",
          JL.browse_validation_code(bad_page, expected) == "BROWSE_CATALOGUE_CONTENT")
    check("browse.http200_bad_pagination_rejected",
          JL.browse_validation_code(dict(page, total=2), expected) == "BROWSE_SCHEMA_PAGINATION")
    for value in ([], {"unexpected": "enum"}):
        malformed = dict(page, items=[dict(item, job_type=value)])
        check(f"browse.http200_unhashable_enum_{type(value).__name__}_rejected",
              JL.browse_validation_code(malformed, expected) == "BROWSE_SCHEMA_ITEM")
    original_validator = JL.browse_validation_code
    JL.browse_validation_code = lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("injected"))
    try:
        check("browse.unexpected_validator_exception_becomes_sample_failure",
              JL.safe_browse_validation_code(page, expected) == "BROWSE_SCHEMA_VALIDATION_ERROR")
    finally:
        JL.browse_validation_code = original_validator


def test_synthetic_create_compensation():
    """Exercise output-publication failure after commit and exact-ID compensation."""
    saved_modules = {name: sys.modules.get(name) for name in
                    ("sqlalchemy", "app", "app.auth", "app.auth.security", "app.db", "app.db.models", "app.db.session")}
    sqlalchemy_stub = types.ModuleType("sqlalchemy"); sqlalchemy_stub.select = lambda model: None
    app_stub = types.ModuleType("app"); app_stub.__path__ = []
    auth_stub = types.ModuleType("app.auth"); auth_stub.__path__ = []
    security_stub = types.ModuleType("app.auth.security")
    security_stub.new_session_token = lambda: ("raw-test-token", "hash-test-token")
    security_stub.new_csrf_token = lambda: "csrf-test-token"
    security_stub.session_expiry = lambda: None
    db_stub = types.ModuleType("app.db"); db_stub.__path__ = []
    models_stub = types.ModuleType("app.db.models")
    class FakeSessionModel:
        def __init__(self, **kwargs): self.kwargs = kwargs
    models_stub.Session, models_stub.User = FakeSessionModel, object
    session_stub = types.ModuleType("app.db.session"); session_stub.SessionLocal = None
    sys.modules.update({"sqlalchemy": sqlalchemy_stub, "app": app_stub, "app.auth": auth_stub,
                        "app.auth.security": security_stub, "app.db": db_stub,
                        "app.db.models": models_stub, "app.db.session": session_stub})
    synth_spec = importlib.util.spec_from_file_location("synthetic_helper", HERE / "synthetic.py")
    SYN = importlib.util.module_from_spec(synth_spec)
    synth_spec.loader.exec_module(SYN)

    persisted, deleted_queries = [], []
    class Column:
        def __init__(self): self.ids = None
        def in_(self, ids): return ("ids", set(map(str, ids)))
    class FakeUser:
        user_id = Column()
        def __init__(self, **kwargs): self.user_id = None; self.kwargs = kwargs
    class Query:
        def __init__(self, model): self.model, self.ids = model, set()
        def where(self, clause): self.ids = clause[1]; return self
    class Result:
        def __init__(self, values): self.values = values
        def scalars(self): return self
        def all(self): return self.values
    class FakeDB:
        def __init__(self): self.pending, self.to_delete = [], []
        def add(self, obj):
            if isinstance(obj, FakeUser): self.pending.append(obj)
        def flush(self):
            for user in self.pending:
                if user.user_id is None: user.user_id = uuid.uuid4()
        def commit(self): persisted.extend(self.pending)
        def rollback(self): pass
        def close(self): pass
        def delete(self, obj):
            self.to_delete.append(obj)
            if obj in persisted: persisted.remove(obj)
        def execute(self, query):
            ids = query.ids
            if query.model is FakeUser:
                values = [u for u in persisted if str(u.user_id) in ids]
            else:
                values = [u.user_id for u in persisted if str(u.user_id) in ids]
            if query.model is FakeUser:
                deleted_queries.append(set(ids))
            return Result(values)
    old_db, old_user, old_select = SYN.SessionLocal, SYN.User, SYN.select
    SYN.SessionLocal, SYN.User, SYN.select = FakeDB, FakeUser, lambda model: Query(model)
    old_replace = SYN.os.replace
    with tempfile.TemporaryDirectory() as d:
        token_path, manifest_path = str(Path(d) / "tokens.json"), str(Path(d) / "manifest.json")
        # Creation-time failure before commit must leave no account or published file.
        class CommitFailDB(FakeDB):
            calls = 0
            def commit(self):
                self.calls += 1
                if self.calls == 1: raise OSError("injected commit failure")
                super().commit()
        SYN.SessionLocal = CommitFailDB
        try:
            SYN.create(1, "selfcheck-create-fail", token_path, manifest_path)
        except OSError:
            pass
        check("synthetic.commit_failure_no_published_files", not Path(token_path).exists()
              and not Path(manifest_path).exists() and not persisted)
        deleted_queries.clear()

        # Publication failure after commit triggers deletion of only the new IDs.
        SYN.SessionLocal = FakeDB
        keep = FakeUser(); keep.user_id = uuid.uuid4(); persisted.append(keep)
        Path(manifest_path).write_text(json.dumps({"user_ids": [str(keep.user_id)]}))
        SYN.os.replace = lambda *_args: (_ for _ in ()).throw(OSError("injected rename failure"))
        try:
            SYN.create(1, "selfcheck-publish-fail", token_path, manifest_path)
        except OSError:
            pass
        finally:
            SYN.os.replace = old_replace
        check("synthetic.publish_failure_compensates_exact_created_ids",
              len(persisted) == 1 and persisted[0] is keep and len(deleted_queries) == 1
              and len(deleted_queries[0]) == 1,
              f"persisted={len(persisted)} queries={len(deleted_queries)} sizes={[len(q) for q in deleted_queries]}")
        check("synthetic.publish_failure_removes_partial_outputs",
              not Path(token_path).exists()
              and json.loads(Path(manifest_path).read_text()) == {"user_ids": [str(keep.user_id)]})
    SYN.SessionLocal, SYN.User, SYN.select = old_db, old_user, old_select
    for name, module in saved_modules.items():
        if module is None: sys.modules.pop(name, None)
        else: sys.modules[name] = module


if __name__ == "__main__":
    test_deadlines()
    test_journey_paths()
    test_browse_validation()
    test_integrity_guard()
    test_synthetic_create_compensation()
    print(f"\n{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)
