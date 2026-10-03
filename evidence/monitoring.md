# Logging, monitoring and operational query record

**Brief reference:** Section 4 (Operations: logging/monitoring and one operational test or alert/query).
**Status:** PASS — logs are centralised, an operational Logs Insights query was run, and an alarm was observed
transitioning on a real outage. Date: 2026-10-03. All artefacts are in `evidence/cloud-capture-2026-10-03/`.

## What is collected

| Signal | Configuration | Artefact |
|---|---|---|
| API, web (Nginx access) and worker container logs | Docker `awslogs` driver → `ApiLogGroup`, `WebLogGroup`, `WorkerLogGroup`, 30-day retention | `06-secrets-and-logs.txt` |
| API Gateway access log | `AccessLogGroup` | `src/infra/cloudformation/ingress-http-api.yaml` |
| Load-balancer health | `AppHttpsTargetGroup` health check `GET /health/ready` (readiness checks the database) | `02-ingress.txt` |
| Alarms | `AppInServiceAlarm`, `ExtractionAgeAlarm`, `EmbeddingAgeAlarm` (oldest message ≥ 900 s for 5 min), `ExtractionDlqAlarm`, `EmbeddingDlqAlarm` (≥ 1 visible message) | `07-alarms.txt` |

**Privacy of logs:** the Nginx `log_format inf2006_sanitized` records client address, time, method, path *without
query string*, status and bytes — no cookies, headers, user agents or bodies
(`src/infra/nginx/web-private-https.conf`). Processing code logs counts, never résumé text (tested by
`test_logs_contain_counts_only_never_the_original_text`).

## Operational query (Logs Insights)

- **Objective:** Use production logs to see what the service is doing and spot errors.
- **Command:** `python3 src/infra/scripts/capture-logs-insights.py <out-dir>` (runs `aws logs start-query` /
  `get-query-results` on `/inf2006/inf2006-private-app/web`; aggregates only). Queries are reproduced in full in
  `08-logs-insights.txt`.
- **Window:** 2026-10-02T07:13Z – 2026-10-03T07:13Z. **Records matched:** 2,269.
- **Result and interpretation:**
  - 2,035 of 2,269 requests (90%) were `GET /health/ready` from ALB health checks (2 targets × every 30 s). This is
    the expected baseline, and it shows the readiness path is exercised continuously.
  - User traffic came from the acceptance session: sign-in (`POST /api/auth/google` 200 × 9), résumé uploads
    (`POST /api/resume/prepare` 202 × 3), saves (`PUT /api/resume` 200 × 7), task polling
    (`GET /api/resume/tasks/…` 200 × 36) and matching (`GET /api/matches` 200 × 17).
  - Error responses are explained by deliberate tests, not faults: 413 × 2 and 415 × 1 (oversized/no-file upload
    probes), 401 (unauthenticated probes and pre-login checks), 403 × 2 (logout without a valid CSRF origin),
    422 × 2 on `/api/matches` (the API returns `RESUME_REQUIRED` or
    `INSUFFICIENT_RESUME_INFORMATION` when no usable résumé is saved; which one occurred is not in the access log), 409 × 1 (stale-revision conflict), and 404s
    for `favicon.ico` and `GET /api/resume` before any résumé existed.
  - **No 5xx responses** in the window.

## Alarm observed on a real failure

- `AppInServiceAlarm` went OK → **ALARM** at 05:25:59 UTC and ALARM → **OK** at 05:30:59 UTC on 2026-10-03
  when both web/API instances stopped during a Learner Lab restart and the Auto Scaling group replaced them.
  Details and timeline: [test-resilience.md](test-resilience.md) Test R2.
- The four queue alarms were `OK` throughout because no queue metric datapoints were received in their windows and
  missing data is configured as non-breaching — expected for an idle queue, but it also means these alarms have not
  yet been seen to fire.

## Limitations and improvement plan

- No SNS/e-mail action is attached to any alarm; an operator must look at CloudWatch. Improvement: add an SNS topic
  (available in the Learner Lab) to `AlarmActions`.
- No CloudWatch dashboard; the evidence is query and alarm output.
- Queue-alarm firing (message age ≥ 900 s or a DLQ message) was not exercised.
- `storedBytes` for the log groups lags; query results, not that counter, show log ingestion.
