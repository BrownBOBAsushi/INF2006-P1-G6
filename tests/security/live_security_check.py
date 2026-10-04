#!/usr/bin/env python3
"""Live HTTP security check against a running local stack (docker compose, nginx on :8080).

Seeds two synthetic users with sessions directly in the local database, probes the real API
(cookie auth, CSRF, cross-user ownership), writes a markdown report, then removes the synthetic
rows (ON DELETE CASCADE). Uses only the standard library and `docker exec`.

    python3 tests/security/live_security_check.py [--out evidence/test-security-live-local-DATE.md]

Local development stack only: the dev cookie name ("session") and Origin http://localhost:8080 are assumed.
"""
import argparse
import datetime as dt
import hashlib
import json
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8080"
ORIGIN = "http://localhost:8080"
COOKIE = "session"
DB_CONTAINER = "inf2006-p1-g6-db-1"
MARK = "synthetic-sec-test-" + uuid.uuid4().hex[:8]
SECRET_B = "SYNTHETIC-SKILL-OF-USER-B"


def sql(query):
    out = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER, "sh", "-c", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1'],
        input=query, text=True, capture_output=True,
    )
    if out.returncode != 0:
        sys.exit(f"SQL failed: {out.stderr}")
    return out.stdout.strip()


def make_user(label):
    uid, raw, csrf = str(uuid.uuid4()), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    sql(f"INSERT INTO users(user_id, google_sub, display_name) VALUES ('{uid}', '{MARK}-{label}', 'Synthetic {label}');"
        f"INSERT INTO sessions(token_hash, user_id, csrf_token, expires_at) VALUES "
        f"('{hashlib.sha256(raw.encode()).hexdigest()}', '{uid}', '{csrf}', now() + interval '1 hour');")
    return {"id": uid, "raw": raw, "csrf": csrf}


def call(method, path, user=None, csrf=..., origin=ORIGIN, cookie=None, body=None):
    headers = {}
    token = cookie if cookie is not None else (user["raw"] if user else None)
    if token:
        headers["Cookie"] = f"{COOKIE}={token}"
    if csrf is ...:
        csrf = user["csrf"] if user else None
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if origin:
        headers["Origin"] = origin
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def code_of(text):
    try:
        return json.loads(text)["error"]["code"]
    except Exception:
        return ""


results = []


def check(name, expected, status, text, extra=None):
    ok = status in expected if isinstance(expected, (set, tuple, list)) else status == expected
    if extra is not None:
        ok = ok and extra
    results.append((name, sorted(expected) if isinstance(expected, (set, tuple, list)) else [expected], status, code_of(text), ok))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=f"evidence/test-security-live-local-{dt.date.today()}.md")
    args = ap.parse_args()

    a, b = make_user("A"), make_user("B")
    task_b, op_b = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        sql(f"INSERT INTO resume_profiles(user_id, revision, content, content_hash, embedding_version) "
            f"VALUES ('{b['id']}', 1, '{{\"skills\": [\"{SECRET_B}\"]}}', 'x', 'none');"
            f"UPDATE users SET resume_revision = 1 WHERE user_id = '{b['id']}';"
            f"INSERT INTO processing_tasks(task_id, owner_id, kind, task_key, revision, state) "
            f"VALUES ('{task_b}', '{b['id']}', 'EXTRACTION', 'sec-test', 0, 'PENDING');"
            f"INSERT INTO save_operations(user_id, operation_id, payload_hash, state, expected_revision, expires_at) "
            f"VALUES ('{b['id']}', '{op_b}', 'x', 'SUCCEEDED', 0, now() + interval '1 hour');")

        # --- Authentication ---------------------------------------------------------------
        for p in ("/api/me", "/api/resume", "/api/matches", "/api/resume/tasks/active"):
            s, t = call("GET", p)
            check(f"AUTH: GET {p} with no cookie", 401, s, t)
        s, t = call("GET", "/api/me", cookie=secrets.token_urlsafe(32))
        check("AUTH: GET /api/me with forged session cookie", 401, s, t)
        sql(f"UPDATE sessions SET expires_at = now() - interval '1 minute' WHERE user_id = '{a['id']}';")
        s, t = call("GET", "/api/me", a)
        check("AUTH: GET /api/me with expired session", 401, s, t)
        sql(f"UPDATE sessions SET expires_at = now() + interval '1 hour' WHERE user_id = '{a['id']}';")

        # --- Controls: owner can reach own data -------------------------------------------
        s, t = call("GET", "/api/resume", b)
        check("CONTROL: user B reads own resume", 200, s, t, SECRET_B in t)
        s, t = call("GET", f"/api/resume/tasks/{task_b}", b)
        check("CONTROL: user B reads own task", 200, s, t)
        s, t = call("GET", f"/api/resume/operations/{op_b}", b)
        check("CONTROL: user B reads own operation", 200, s, t)

        # --- Cross-user ownership ---------------------------------------------------------
        s, t = call("GET", "/api/resume", a)
        check("OWNERSHIP: user A GET /api/resume returns A's (empty) resume, not B's", 404, s, t, SECRET_B not in t)
        s, t = call("GET", f"/api/resume/tasks/{task_b}", a)
        check("OWNERSHIP: user A GET B's task id", 404, s, t)
        s, t = call("GET", f"/api/resume/operations/{op_b}", a)
        check("OWNERSHIP: user A GET B's operation id", 404, s, t)
        s, t = call("DELETE", f"/api/resume/tasks/{task_b}", a)
        check("OWNERSHIP: user A DELETE B's task id (valid A CSRF)", 404, s, t)
        s, t = call("DELETE", "/api/resume", a, body={"expected_revision": 1})
        check("OWNERSHIP: user A DELETE /api/resume acts only on A (revision conflict, B untouched)", 409, s, t)
        s, t = call("DELETE", "/api/resume", a, body={"expected_revision": 0})
        check("OWNERSHIP: user A DELETE /api/resume (A's own revision) succeeds", 200, s, t)
        state_b = sql(f"SELECT state FROM processing_tasks WHERE task_id = '{task_b}';")
        has_b = sql(f"SELECT count(*) FROM resume_profiles WHERE user_id = '{b['id']}';")
        rev_b = sql(f"SELECT resume_revision FROM users WHERE user_id = '{b['id']}';")
        results.append(("OWNERSHIP: DB state of B after all A attempts (task PENDING, resume present, revision 1)",
                        ["PENDING|1|1"], f"{state_b}|{has_b}|{rev_b}", "", f"{state_b}|{has_b}|{rev_b}" == "PENDING|1|1"))

        # --- CSRF (unsafe methods on A's own valid session) --------------------------------
        for name, kw in [
            ("no X-CSRF-Token header", dict(csrf=None)),
            ("wrong X-CSRF-Token", dict(csrf=secrets.token_urlsafe(32))),
            ("user B's CSRF token with A's cookie", dict(csrf=b["csrf"])),
            ("missing Origin", dict(origin=None)),
            ("foreign Origin https://evil.example", dict(origin="https://evil.example")),
        ]:
            s, t = call("PATCH", "/api/me", a, body={"display_name": "csrf-probe"}, **kw)
            check(f"CSRF: PATCH /api/me, {name}", 403, s, t)
            s, t = call("DELETE", "/api/resume", a, body={"expected_revision": 0}, **kw)
            check(f"CSRF: DELETE /api/resume, {name}", 403, s, t)
        s, t = call("POST", "/api/resume/prepare", a, csrf=None)
        check("CSRF: POST /api/resume/prepare, no token", 403, s, t)
        name_a = sql(f"SELECT display_name FROM users WHERE user_id = '{a['id']}';")
        results.append(("CSRF: A's display_name unchanged after rejected PATCHes", ["Synthetic A"], name_a, "", name_a == "Synthetic A"))
        s, t = call("PATCH", "/api/me", a, body={"display_name": "Synthetic A2"})
        check("CONTROL: PATCH /api/me with valid cookie+CSRF+Origin", 200, s, t)
    finally:
        sql(f"DELETE FROM users WHERE google_sub LIKE '{MARK}-%';")
        left = sql(f"SELECT count(*) FROM users WHERE google_sub LIKE '{MARK}-%';")

    passed = sum(1 for r in results if r[4])
    lines = [
        "# Live local security check",
        "",
        f"**Date (UTC):** {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M}  ",
        f"**Target:** local docker compose stack, nginx `{BASE}`, APP_ENV=development (dev cookie name `session`)  ",
        "**Script:** `tests/security/live_security_check.py` (re-runnable; seeds and removes its own synthetic users)  ",
        f"**Result:** {passed}/{len(results)} checks passed. Synthetic rows remaining after cleanup: {left or 0}.",
        "",
        "Scope: real HTTP requests through nginx to the API with two synthetic users. Authentication, CSRF/Origin, "
        "and cross-user ownership of resume, task and operation resources. Local only; not evidence for the cloud deployment.",
        "",
        "| # | Check | Expected | Actual | Error code | Pass |",
        "|---|---|---|---|---|---|",
    ]
    for i, (name, exp, act, ec, ok) in enumerate(results, 1):
        lines.append(f"| {i} | {name} | {'/'.join(map(str, exp))} | {act} | {ec} | {'PASS' if ok else '**FAIL**'} |")
    open(args.out, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
