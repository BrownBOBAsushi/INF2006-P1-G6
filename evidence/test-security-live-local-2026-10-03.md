# Live local security check

**Date (UTC):** 2026-10-03 15:19  
**Target:** local docker compose stack, nginx `http://localhost:8080`, APP_ENV=development (dev cookie name `session`)  
**Script:** `tests/security/live_security_check.py` (re-runnable; seeds and removes its own synthetic users)  
**Result:** 29/29 checks passed. Synthetic rows remaining after cleanup: 0.

Scope: real HTTP requests through nginx to the API with two synthetic users. Authentication, CSRF/Origin, and cross-user ownership of resume, task and operation resources. Local only; not evidence for the cloud deployment.

| # | Check | Expected | Actual | Error code | Pass |
|---|---|---|---|---|---|
| 1 | AUTH: GET /api/me with no cookie | 401 | 401 | AUTH_REQUIRED | PASS |
| 2 | AUTH: GET /api/resume with no cookie | 401 | 401 | AUTH_REQUIRED | PASS |
| 3 | AUTH: GET /api/matches with no cookie | 401 | 401 | AUTH_REQUIRED | PASS |
| 4 | AUTH: GET /api/resume/tasks/active with no cookie | 401 | 401 | AUTH_REQUIRED | PASS |
| 5 | AUTH: GET /api/me with forged session cookie | 401 | 401 | AUTH_REQUIRED | PASS |
| 6 | AUTH: GET /api/me with expired session | 401 | 401 | SESSION_EXPIRED | PASS |
| 7 | CONTROL: user B reads own resume | 200 | 200 |  | PASS |
| 8 | CONTROL: user B reads own task | 200 | 200 |  | PASS |
| 9 | CONTROL: user B reads own operation | 200 | 200 |  | PASS |
| 10 | OWNERSHIP: user A GET /api/resume returns A's (empty) resume, not B's | 404 | 404 | RESUME_NOT_FOUND | PASS |
| 11 | OWNERSHIP: user A GET B's task id | 404 | 404 | TASK_NOT_FOUND | PASS |
| 12 | OWNERSHIP: user A GET B's operation id | 404 | 404 | OPERATION_EXPIRED | PASS |
| 13 | OWNERSHIP: user A DELETE B's task id (valid A CSRF) | 404 | 404 | TASK_NOT_FOUND | PASS |
| 14 | OWNERSHIP: user A DELETE /api/resume acts only on A (revision conflict, B untouched) | 409 | 409 | REVISION_CONFLICT | PASS |
| 15 | OWNERSHIP: user A DELETE /api/resume (A's own revision) succeeds | 200 | 200 |  | PASS |
| 16 | OWNERSHIP: DB state of B after all A attempts (task PENDING, resume present, revision 1) | PENDING|1|1 | PENDING|1|1 |  | PASS |
| 17 | CSRF: PATCH /api/me, no X-CSRF-Token header | 403 | 403 | CSRF_INVALID | PASS |
| 18 | CSRF: DELETE /api/resume, no X-CSRF-Token header | 403 | 403 | CSRF_INVALID | PASS |
| 19 | CSRF: PATCH /api/me, wrong X-CSRF-Token | 403 | 403 | CSRF_INVALID | PASS |
| 20 | CSRF: DELETE /api/resume, wrong X-CSRF-Token | 403 | 403 | CSRF_INVALID | PASS |
| 21 | CSRF: PATCH /api/me, user B's CSRF token with A's cookie | 403 | 403 | CSRF_INVALID | PASS |
| 22 | CSRF: DELETE /api/resume, user B's CSRF token with A's cookie | 403 | 403 | CSRF_INVALID | PASS |
| 23 | CSRF: PATCH /api/me, missing Origin | 403 | 403 | CSRF_INVALID | PASS |
| 24 | CSRF: DELETE /api/resume, missing Origin | 403 | 403 | CSRF_INVALID | PASS |
| 25 | CSRF: PATCH /api/me, foreign Origin https://evil.example | 403 | 403 | CSRF_INVALID | PASS |
| 26 | CSRF: DELETE /api/resume, foreign Origin https://evil.example | 403 | 403 | CSRF_INVALID | PASS |
| 27 | CSRF: POST /api/resume/prepare, no token | 403 | 403 | CSRF_INVALID | PASS |
| 28 | CSRF: A's display_name unchanged after rejected PATCHes | Synthetic A | Synthetic A |  | PASS |
| 29 | CONTROL: PATCH /api/me with valid cookie+CSRF+Origin | 200 | 200 |  | PASS |
