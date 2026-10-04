# Live deployed-site security check

**Date (UTC):** 2026-10-03 17:02  
**Target:** deployed public API endpoint (URL redacted), two real signed-in test accounts (ids and cookies not recorded)  
**Script:** `tests/security/live_site_check.py` (operator-run; non-destructive)  
**Result:** 26/26 checks passed.

| # | Check | Expected | Actual | Error code | Pass |
|---|---|---|---|---|---|
| 1 | SETUP: two distinct signed-in users resolved (ids not shown) | 2 users | 2 users |  | PASS |
| 2 | AUTH: GET /api/me with no cookie | 401 | 401 | AUTH_REQUIRED | PASS |
| 3 | AUTH: GET /api/resume with no cookie | 401 | 401 | AUTH_REQUIRED | PASS |
| 4 | AUTH: GET /api/matches with no cookie | 401 | 401 | AUTH_REQUIRED | PASS |
| 5 | AUTH: GET /api/me with forged cookie | 401 | 401 | AUTH_REQUIRED | PASS |
| 6 | OWNERSHIP: A GET an unknown/other-owner task id | 404 | 404 | TASK_NOT_FOUND | PASS |
| 7 | OWNERSHIP: A GET an unknown/other-owner operation id | 404 | 404 | OPERATION_EXPIRED | PASS |
| 8 | OWNERSHIP: A DELETE an unknown/other-owner task id (valid A CSRF) | 404 | 404 | TASK_NOT_FOUND | PASS |
| 9 | OWNERSHIP: A DELETE /api/resume with a wrong revision acts on A only | 409 | 409 | REVISION_CONFLICT | PASS |
| 10 | SETUP: B uploads a synthetic fixture PDF and gets a task (202) | 202 | 202 |  | PASS |
| 11 | OWNERSHIP: A GET B's real task id | 404 | 404 | TASK_NOT_FOUND | PASS |
| 12 | OWNERSHIP: A DELETE B's real task id (valid A CSRF) | 404 | 404 | TASK_NOT_FOUND | PASS |
| 13 | CONTROL: B still sees own task after A's attempts | 200 | 200 |  | PASS |
| 14 | CONTROL: B can discard own task (cleanup) | 200 | 200 |  | PASS |
| 15 | CSRF: PATCH /api/me, no X-CSRF-Token | 403 | 403 | CSRF_INVALID | PASS |
| 16 | CSRF: DELETE /api/resume, no X-CSRF-Token | 403 | 403 | CSRF_INVALID | PASS |
| 17 | CSRF: PATCH /api/me, wrong X-CSRF-Token | 403 | 403 | CSRF_INVALID | PASS |
| 18 | CSRF: DELETE /api/resume, wrong X-CSRF-Token | 403 | 403 | CSRF_INVALID | PASS |
| 19 | CSRF: PATCH /api/me, B's CSRF token with A's cookie | 403 | 403 | CSRF_INVALID | PASS |
| 20 | CSRF: DELETE /api/resume, B's CSRF token with A's cookie | 403 | 403 | CSRF_INVALID | PASS |
| 21 | CSRF: PATCH /api/me, missing Origin | 403 | 403 | CSRF_INVALID | PASS |
| 22 | CSRF: DELETE /api/resume, missing Origin | 403 | 403 | CSRF_INVALID | PASS |
| 23 | CSRF: PATCH /api/me, foreign Origin | 403 | 403 | CSRF_INVALID | PASS |
| 24 | CSRF: DELETE /api/resume, foreign Origin | 403 | 403 | CSRF_INVALID | PASS |
| 25 | CSRF: POST /api/resume/prepare, no token | 403 | 403 | CSRF_INVALID | PASS |
| 26 | INTEGRITY: B's resume revision unchanged after all of A's attempts | 4 | 4 |  | PASS |
