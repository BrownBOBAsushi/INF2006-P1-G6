# Security control test record

**Brief reference:** Section 4 (Security: authentication/authorisation, least privilege, secret handling, restricted
network/data access, validation against a named threat) and Section 5.2 test (2).
**Status:** PASS for the three named threats tested below. Full threat mapping: [threat-control-map.md](threat-control-map.md).
**Date:** 2026-10-03.

## Named threats tested

- **T1 Unauthenticated access** — an attacker without a session calls the API directly to read or upload résumé data.
- **T2 Cross-site request forgery** — a malicious site makes a signed-in student's browser send a state-changing request.
- **T8 Direct network access** — an attacker bypasses the public entry point to reach the app instances or database.

## Test S1 — unauthenticated and cross-site requests against the deployed API (T1, T2)

- **Objective:** Show that the public API refuses data access without a session, and refuses state-changing
  requests from a foreign or missing Origin.
- **Setup:** Deployed stack, public API Gateway origin (redacted). No cookies sent. [Captured]
- **Command:** `curl -sS -X <METHOD> [-H 'Origin: https://evil.example'] https://<api-id>.execute-api.<region>.amazonaws.com<path>`
- **Expected:** 401 `AUTH_REQUIRED` for data routes; 403 `CSRF_INVALID` for a state-changing route from a missing or
  foreign Origin; readiness still 200.
- **Actual (2026-10-03T07:14:31Z):**

| Request | Status | Error code |
|---|---|---|
| `GET /health/ready` | 200 | — |
| `GET /api/me` (no cookie) | 401 | `AUTH_REQUIRED` |
| `GET /api/resume` (no cookie) | 401 | `AUTH_REQUIRED` |
| `GET /api/matches` (no cookie) | 401 | `AUTH_REQUIRED` |
| `POST /api/resume/prepare` (no cookie) | 401 | `AUTH_REQUIRED` |
| `POST /api/auth/logout` (no Origin, no CSRF token) | 403 | `CSRF_INVALID` "Origin not allowed." |
| `POST /api/auth/logout` (Origin `https://evil.example`) | 403 | `CSRF_INVALID` |
| `PUT /api/resume` (Origin `https://evil.example`, no cookie) | 401 | `AUTH_REQUIRED` |

- **Artefact:** `evidence/cloud-capture-2026-10-03/09-public-probes.txt`.
- **Result:** PASS.

## Test S2 — CSRF with a live session (T2) and token validation (automated)

- **Objective:** Show that a signed-in session still cannot be used for a state change without the session-bound
  CSRF token, and that Google-token and ownership checks reject forged input.
- **Command:** `docker compose -f docker-compose.dev.yml --profile test run --rm backend-tests` (disposable
  PostgreSQL/pgvector) — 133 passed, 2026-10-03T07:20:45Z (`evidence/local-tests-2026-10-03.md`).
- **Relevant tests (all passed):** `test_google_exchange_rejects_wrong_csrf`, `test_google_exchange_rejects_bad_origin`,
  `test_logout_requires_csrf_for_active_session`, `test_patch_me_requires_csrf_and_uses_the_contract_error_envelope`,
  `test_prepare_requires_csrf_and_capped_upload_has_no_store`, `test_delete_resume_rejects_bad_csrf`,
  `test_save_replay_noop_revision_and_operation_ownership`, plus `tests/backend/test_google_verify_diagnostics.py`.
- **Deployed corroboration [Operator-reported]:** with a live session, missing or invalid CSRF tokens returned 403 and
  the session stayed signed in; the session cookie carried `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/` in two
  separate `Set-Cookie` headers.
- **Result:** PASS.

## Test S3 — network isolation of compute and data (T8)

- **Objective:** Show that only the API Gateway endpoint is reachable from the Internet.
- **Command:** read-only `aws ec2 describe-instances`, `describe-security-groups`, `aws rds describe-db-instances`,
  `aws elbv2 describe-load-balancers` via `src/infra/scripts/capture-cloud-evidence.py`.
- **Expected:** no public IPs on instances; internal ALB; ingress chained VpcLink → ALB → app only; database reachable
  only from app and worker security groups; RDS not public.
- **Actual (2026-10-03T07:11–07:12Z):** all three instances `HasPublicIp: false`, IMDSv2 `required`; ALB
  `Scheme: internal`; `InternalAlbSecurityGroup` ingress 443 only from `VpcLinkSecurityGroup`;
  `AppTargetSecurityGroup` ingress 8443 only from `InternalAlbSecurityGroup`; `WorkerSecurityGroup` and
  `AppSecurityGroup` have no inbound rules; `DatabaseSecurityGroup` ingress 5432 only from `AppSecurityGroup` and
  `WorkerSecurityGroup`; RDS `PubliclyAccessible: false`, `StorageEncrypted: true`.
- **Artefacts:** `cloud-capture-2026-10-03/02-ingress.txt`, `03-compute.txt`, `04-security-groups.txt`, `05-data-stores.txt`.
- **Result:** PASS.

## Test S4 — live cross-user ownership, session and CSRF checks (T1, T2, ownership), local stack

- **Objective:** Show over real HTTP that user A cannot read, cancel or delete user B's résumé, task or save operation, and that
  unsafe requests are refused without a valid CSRF token and Origin.
- **Setup:** Local docker compose stack, nginx `http://localhost:8080`, dev cookie `session`. The script seeds two synthetic
  users with sessions, a résumé, an extraction task and a save operation for B, then deletes all synthetic rows.
- **Command:** `python3 tests/security/live_security_check.py --out evidence/test-security-live-local-2026-10-03.md`
- **Expected:** 401 without/with forged/expired session; 404 for B's resources when requested by A; DB state of B unchanged;
  403 `CSRF_INVALID` for missing/wrong/other-user CSRF token and missing/foreign Origin; owner controls return 200.
- **Actual:** 29/29 checks passed; B's task stayed `PENDING`, B's résumé and revision were unchanged. Full table:
  [test-security-live-local-2026-10-03.md](test-security-live-local-2026-10-03.md).
- **Limits:** local development stack (not the AWS deployment); sessions seeded in the database rather than via Google sign-in;
  cookie attributes (`__Host-`, Secure) and TLS are not exercised here.

## Test S5 — ownership, session and CSRF against the deployed site with two real accounts (T1, T2, ownership)

- **Objective:** Repeat the S4 checks on the deployed stack using two real signed-in test accounts (A and B), including the
  production `__Host-session` cookie.
- **Setup:** Deployed public API endpoint (redacted), two different Google accounts signed in; cookies supplied through
  environment variables, never printed or stored. B had a saved résumé (revision 4). The script has B upload a synthetic fixture PDF (`tests/fixtures/pdf/resume_P01.pdf`, not saved) to create a real task, and discards it afterwards.
- **Command:** `SITE_URL=<api-url> SITE_ORIGIN=<api-url> COOKIE_A=... COOKIE_B=... python3 tests/security/live_site_check.py`
  (operator-run, non-destructive: delete probes use a wrong revision, CSRF probes are rejected before any change).
- **Expected:** 401 without or with a forged cookie; 404 for unknown or other-owner task and operation ids; 409 (not a delete)
  for a wrong-revision delete; 403 `CSRF_INVALID` for missing, wrong and other-user CSRF tokens and for missing or foreign Origin;
  B's data unchanged.
- **Actual (2026-10-03 17:02 UTC):** 26 of 26 checks passed: A got 404 for both GET and DELETE on B's real task id, B still saw its own task (200) afterwards, B discarded it, and B's résumé revision was still 4 after all of A's attempts. (Two earlier runs the same evening, 23/23 and 22/22, skipped the real-task check because B had no active task at that revision; they were superseded and removed.)
  Full table: [test-security-live-cloud-real-task.md](test-security-live-cloud-real-task.md) (file named for the operator's local date).
- **Limits:** the operation-id check used a random id (B had no save operation to target); B's saved résumé was never requested by id, and `GET /api/resume` has no id, so A's own 404 shows only that A sees A's state. A single pair of accounts was used, and the run happened on the operator's machine.
- **Session cookie attributes (browser DevTools, Application → Cookies, both accounts, 2026-10-03 ~16:50 UTC; values not recorded):**
  name `__Host-session`, Path `/`, host-only (no Domain attribute, domain column is the API host), **HttpOnly ✓, Secure ✓,
  SameSite `Lax`**, size 57 bytes, expiry about 8 hours after sign-in (2026-10-04 ~00:4x UTC). The `__Host-` prefix requires Secure, Path `/` and no Domain,
  all of which are satisfied. Source: operator screenshots (not packaged, as they show other cookies on the same browser profile); the script itself does not read attributes.
- **Result:** PASS within those limits.

## Secret handling and least privilege (configuration evidence)

- Five runtime secrets are held in Secrets Manager (`06-secrets-and-logs.txt`, names and metadata only; values were
  not retrieved for this record). Boot scripts write them into 0600 root-only env files
  (`src/infra/scripts/write-private-app-compose-env.sh`, `bootstrap-private-worker.sh`). `.env` files are git-ignored;
  `src/.env.example` holds placeholders.
- Database access uses separate restricted roles (`app_migrator`, `app_runtime`) with superuser, createdb, createrole
  and bypassrls forbidden (`src/infra/scripts/configure-app-roles.sql`).
- **Limitation:** the Learner Lab forbids custom IAM roles, so every instance uses `LabRole`; IAM-level least
  privilege is not achieved and is compensated by network isolation and database roles.

## Limitations and improvement plan

- No direct authenticated API calls were made with two live accounts to probe object ownership on the cloud
  stack; ownership is covered by automated tests and by the design (user ID only from the session).
- No HSTS or Content-Security-Policy headers; ALB → target TLS is encrypted but the target certificate is not
  validated. Improvement: add security headers in Nginx.
- No rate limiting on authentication or upload routes beyond the single processing slot and queue.
- No penetration test or dependency vulnerability scan is recorded.
