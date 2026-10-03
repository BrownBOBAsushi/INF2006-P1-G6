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
