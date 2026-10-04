#!/usr/bin/env python3
"""Operator-run security check against the DEPLOYED site with two real signed-in test accounts.

Cookies are read from environment variables and never printed or written. Non-destructive: no résumé is saved or deleted
(delete probes use a deliberately wrong expected_revision; CSRF probes are expected to be rejected before any change).

    SITE_URL=https://<public-api-host>  SITE_ORIGIN=https://<origin-the-browser-uses> \
    COOKIE_A=<value of the __Host-session cookie for account A> COOKIE_B=<same for account B> \
    python3 tests/security/live_site_check.py [--out evidence/test-security-live-cloud-DATE.md]

Account A and B must be two different Google accounts that you own and that are signed in to the site.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid

COOKIE_NAME = "__Host-session"
results = []


def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Set {name} (see the docstring).")
    return value


SITE = env("SITE_URL").rstrip("/")
ORIGIN = env("SITE_ORIGIN").rstrip("/")
A_COOKIE, B_COOKIE = env("COOKIE_A"), env("COOKIE_B")


def call(method, path, cookie=None, csrf=None, origin=ORIGIN, body=None):
    headers = {}
    if cookie:
        headers["Cookie"] = f"{COOKIE_NAME}={cookie}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if origin:
        headers["Origin"] = origin
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(SITE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def upload_pdf(cookie, csrf, path):
    """Create a real extraction task for the cookie's user from a synthetic fixture PDF (multipart field 'file')."""
    boundary = "----sectest" + uuid.uuid4().hex
    with open(path, "rb") as f:
        pdf = f.read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"fixture.pdf\"\r\n"
            f"Content-Type: application/pdf\r\n\r\n").encode() + pdf + f"\r\n--{boundary}--\r\n".encode()
    headers = {"Cookie": f"{COOKIE_NAME}={cookie}", "X-CSRF-Token": csrf, "Origin": ORIGIN,
               "Content-Type": f"multipart/form-data; boundary={boundary}"}
    req = urllib.request.Request(SITE + "/api/resume/prepare", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def code_of(text):
    try:
        return json.loads(text)["error"]["code"]
    except Exception:
        return ""


def record(name, expected, status, text="", ok=None):
    passed = (status == expected) if ok is None else ok
    results.append((name, expected, status, code_of(text), passed))


def me(cookie):
    status, text = call("GET", "/api/me", cookie)
    if status != 200:
        sys.exit(f"GET /api/me returned {status} for a supplied cookie: it is expired or wrong. Sign in again and copy a fresh cookie.")
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=f"evidence/test-security-live-cloud-{dt.date.today()}.md")
    args = ap.parse_args()

    a, b = me(A_COOKIE), me(B_COOKIE)
    ua, ub = a["user"]["user_id"], b["user"]["user_id"]
    if ua == ub:
        sys.exit("COOKIE_A and COOKIE_B belong to the same user: use two different accounts.")
    csrf_a, csrf_b = a["csrf_token"], b["csrf_token"]
    results.append(("SETUP: two distinct signed-in users resolved (ids not shown)", "2 users", "2 users", "", True))
    rev_b, resume_b = b["resume_revision"], b["has_resume"]

    # Authentication
    for p in ("/api/me", "/api/resume", "/api/matches"):
        s, t = call("GET", p)
        record(f"AUTH: GET {p} with no cookie", 401, s, t)
    s, t = call("GET", "/api/me", cookie=uuid.uuid4().hex + uuid.uuid4().hex)
    record("AUTH: GET /api/me with forged cookie", 401, s, t)

    # Ownership (non-destructive)
    s, t = call("GET", f"/api/resume/tasks/{uuid.uuid4()}", A_COOKIE)
    record("OWNERSHIP: A GET an unknown/other-owner task id", 404, s, t)
    s, t = call("GET", f"/api/resume/operations/{uuid.uuid4()}", A_COOKIE)
    record("OWNERSHIP: A GET an unknown/other-owner operation id", 404, s, t)
    s, t = call("DELETE", f"/api/resume/tasks/{uuid.uuid4()}", A_COOKIE, csrf_a)
    record("OWNERSHIP: A DELETE an unknown/other-owner task id (valid A CSRF)", 404, s, t)
    s, t = call("DELETE", "/api/resume", A_COOKIE, csrf_a, body={"expected_revision": 987654321})
    record("OWNERSHIP: A DELETE /api/resume with a wrong revision acts on A only", 409, s, t)
    s, t = call("GET", "/api/resume", A_COOKIE)
    if resume_b and ub != ua:
        record("OWNERSHIP: A's GET /api/resume does not return B's résumé (status is A's own)", None, s, t,
               ok=(s in (200, 404) and (b["user"].get("display_name") or "\x00") not in t))
    # Cross-owner test with a REAL task: B uploads a synthetic fixture PDF (not saved), A then attacks B's real task id.
    fixture = os.environ.get("FIXTURE_PDF", "tests/fixtures/pdf/resume_P01.pdf")
    s, t = upload_pdf(B_COOKIE, csrf_b, fixture)
    if s == 202:
        tid = json.loads(t)["task_id"]
        record("SETUP: B uploads a synthetic fixture PDF and gets a task (202)", 202, s, t)
        s2, t2 = call("GET", f"/api/resume/tasks/{tid}", A_COOKIE)
        record("OWNERSHIP: A GET B's real task id", 404, s2, t2)
        s3, t3 = call("DELETE", f"/api/resume/tasks/{tid}", A_COOKIE, csrf_a)
        record("OWNERSHIP: A DELETE B's real task id (valid A CSRF)", 404, s3, t3)
        s4, t4 = call("GET", f"/api/resume/tasks/{tid}", B_COOKIE)
        record("CONTROL: B still sees own task after A's attempts", 200, s4, t4,
               ok=(s4 == 200 and json.loads(t4).get("state") != "CANCELLED"))
        s5, t5 = call("DELETE", f"/api/resume/tasks/{tid}", B_COOKIE, csrf_b)
        record("CONTROL: B can discard own task (cleanup)", 200, s5, t5)
    else:
        record("SETUP: B uploads a synthetic fixture PDF and gets a task (202)", 202, s, t)

    # CSRF on A's own valid session
    probes = [
        ("no X-CSRF-Token", dict(csrf=None)),
        ("wrong X-CSRF-Token", dict(csrf="x" * 43)),
        ("B's CSRF token with A's cookie", dict(csrf=csrf_b)),
        ("missing Origin", dict(csrf=csrf_a, origin=None)),
        ("foreign Origin", dict(csrf=csrf_a, origin="https://evil.example")),
    ]
    for label, kw in probes:
        s, t = call("PATCH", "/api/me", A_COOKIE, body={"display_name": a["user"].get("display_name") or "x"}, **kw)
        record(f"CSRF: PATCH /api/me, {label}", 403, s, t)
        s, t = call("DELETE", "/api/resume", A_COOKIE, body={"expected_revision": 987654321}, **kw)
        record(f"CSRF: DELETE /api/resume, {label}", 403, s, t)
    s, t = call("POST", "/api/resume/prepare", A_COOKIE, csrf=None)
    record("CSRF: POST /api/resume/prepare, no token", 403, s, t)

    # B unchanged
    after = me(B_COOKIE)
    results.append(("INTEGRITY: B's resume revision unchanged after all of A's attempts", rev_b, after["resume_revision"], "",
                    after["resume_revision"] == rev_b))

    passed = sum(1 for r in results if r[4])
    lines = [
        "# Live deployed-site security check",
        "",
        f"**Date (UTC):** {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M}  ",
        "**Target:** deployed public API endpoint (URL redacted), two real signed-in test accounts (ids and cookies not recorded)  ",
        "**Script:** `tests/security/live_site_check.py` (operator-run; non-destructive)  ",
        f"**Result:** {passed}/{len(results)} checks passed.",
        "",
        "| # | Check | Expected | Actual | Error code | Pass |",
        "|---|---|---|---|---|---|",
    ]
    for i, (name, exp, act, ec, ok) in enumerate(results, 1):
        lines.append(f"| {i} | {name} | {exp if exp is not None else 'A-only data'} | {act} | {ec} | {'PASS' if ok else '**FAIL**'} |")
    out = re.sub(r"https?://\S*execute-api\S*", "<api-url>", "\n".join(lines))
    open(args.out, "w").write(out + "\n")
    print(out)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
