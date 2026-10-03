# Scalability / resilience / recovery test record

**Brief reference:** Section 4 (Scalability and resilience) and Section 5.2 test (4).
**Status:** PASS for automatic replacement of failed web/API instances and for continuity during a single-target
withdrawal. Database failover/restore and load testing were not performed (see Limitations).

## Mechanisms implemented

| Mechanism | Configuration (source → captured state) |
|---|---|
| Load balancing across two AZs | `InternalAlb` → `AppHttpsTargetGroup` (HTTPS 8443, `GET /health/ready` every 30 s, unhealthy after 2 failures) — `src/infra/cloudformation/ingress-http-api.yaml` → `cloud-capture-2026-10-03/02-ingress.txt` |
| Self-healing compute | `AppAutoScalingGroup` min = max = desired = 2, `HealthCheckType: ELB`, grace 420 s, subnets in us-east-1a/b — `private-app.yaml` → `03-compute.txt` |
| Queue-based load levelling | Uploads return 202 and are processed by the worker from `ExtractionQueue`/`EmbeddingQueue`; failed messages move to DLQs after 5 receives — `private-base.yaml` → `05-data-stores.txt` |
| Detection | `AppInServiceAlarm` (`GroupInServiceInstances` minimum < 2 for 2 × 60 s, missing data = breaching) — `07-alarms.txt` |
| Managed backup | RDS automated backups, 1-day retention, point-in-time restore available — `05-data-stores.txt` |

## Test R1 — automatic replacement after an ELB health-check failure (observed in production)

- **Objective:** Show that an unhealthy web/API instance is removed and replaced without operator action.
- **Setup:** Stack `inf2006-private-app` created 2026-10-03 02:34 UTC with 2 instances.
- **Trigger:** Unplanned. One instance failed the ALB health check shortly after start-up. The application-level
  cause was not established (the operator had reported local readiness at 02:40:35 UTC).
- **Command:** `aws autoscaling describe-scaling-activities --auto-scaling-group-name <AppAutoScalingGroup>` (read-only).
- **Expected:** ASG marks the instance unhealthy from the ELB check, terminates it, and launches a replacement that
  becomes healthy; desired capacity of 2 is restored.
- **Actual (captured, UTC):** 02:42:46 "an instance was taken out of service in response to an ELB system health
  check failure" → terminated (completed 02:48:29); 02:42:46 "an instance was launched in response to an
  unhealthy instance needing to be replaced" → launch successful 02:42:53. The operator later reported both
  targets healthy.
- **Date:** 2026-10-03. **Artefact:** `evidence/cloud-capture-2026-10-03/11-autoscaling-activity.txt`.
- **Result:** PASS — automatic detection and replacement.

## Test R2 — recovery of the whole web/API tier after both instances stopped (Learner Lab session restart)

- **Objective:** Show that the service recovers when every web/API instance is stopped, and that monitoring
  detects the loss.
- **Trigger:** Unplanned. The Learner Lab session ended and restarted, stopping both instances.
- **Commands:** `describe-scaling-activities` and `aws cloudwatch describe-alarm-history --history-item-type StateUpdate` (read-only).
- **Expected:** EC2 health check detects stopped instances; ASG replaces them; `AppInServiceAlarm` enters ALARM
  while fewer than 2 instances are in service and returns to OK after recovery; public readiness returns 200.
- **Actual (captured, UTC):**
  - 05:23:37 and 05:25:31 — both instances "taken out of service in response to an EC2 health check indicating it
    has been terminated or stopped".
  - 05:23:39–05:26:50 — six replacement launches cancelled with `Client.InternalError: Client error on launch`
    while the lab environment was still unavailable (recorded as a failed attempt, not hidden).
  - 05:25:59 (13:25:59 SGT) — `AppInServiceAlarm` OK → ALARM.
  - 05:28:43 — two replacement instances launched successfully ("difference between desired and actual
    capacity").
  - 05:30:59 — `AppInServiceAlarm` ALARM → OK (2 in service).
  - 07:11:55 — both instances `InService`/`Healthy`; both ALB targets `healthy` (`02-ingress.txt`, `03-compute.txt`).
  - 07:14:31 — public `GET /health/ready` → HTTP 200 `{"status":"ready"}` (`09-public-probes.txt`).
- **Measured:** detection-to-alarm about 2.5 minutes after the first stop; capacity restored about 5 minutes after the
  first stop (05:23:37 → 05:28:52) once launches were possible; alarm cleared at 05:30:59.
- **Data:** saved résumé and matches remained available after recovery (state lives in RDS, not on instances) —
  [Operator-reported] after the lab restart.
- **Date:** 2026-10-03. **Artefacts:** `11-autoscaling-activity.txt`, `07-alarms.txt`, `02-ingress.txt`, `03-compute.txt`.
- **Result:** PASS — automatic recovery and alarm detection. Note: a whole-tier stop causes an outage until
  replacements start; two instances protect against a single-instance or single-AZ failure, not this case.

## Test R3 — controlled single-target withdrawal with service continuity

- **Objective:** Show that removing one target from the load balancer does not interrupt the service.
- **Steps (operator-executed, 2026-10-03):** suspend the ASG `HealthCheck` and `ReplaceUnhealthy` processes (so the
  ASG would not replace the instance during the test); deregister one healthy target from `AppHttpsTargetGroup`;
  wait for draining; request public `/health/ready` and use the app; re-register the target; resume the processes.
- **Expected:** HTTP 200 and an unaffected browser session while one target serves all traffic.
- **Actual [Operator-reported]:** public health HTTP 200 at 04:25:34 UTC with one target; the browser session,
  résumé and matches remained available; the target returned to healthy after re-registration; suspended-process
  list cleared. [Captured] 07:11:55 UTC: `SuspendedProcesses: []`, both targets healthy.
- **Artefact:** `evidence/cloud-acceptance-2026-10-03.md` (section "Worker, queues, storage, and continuity").
- **Result:** PASS (operator-reported; raw CLI output was not retained).

## Earlier test (historical stack)

On 2026-09-27 the earlier single-instance foundation (since torn down) passed an API-container stop/restart test
in which `ApiReadinessAlarm` went OK → ALARM → OK; the alarm history for that stack is still visible in
`07-alarms.txt` (20:31:19 → 20:34:19 SGT). Record: `evidence/cloud-foundation-run-2026-09-27.md`.

## Limitations and improvement plan

- **Database:** Single-AZ RDS; no failover and no restore test. Improvement: restore the latest automated backup into
  a temporary instance and run the schema checks (planned, not required by the brief).
- **Worker:** single instance, not in an Auto Scaling group; if it stops, uploads queue in SQS (4-day retention)
  until it returns, so work is delayed, not lost. Improvement: put the worker in its own ASG and scale on queue age.
- **No load test** against the cloud stack; the ASG has a fixed size of 2 (no scaling policy). Local load
  measurements are in `evidence/load-matching-2026-09-21.md` and `evidence/load-api-harness-2026-09-21-api.md`.
- **Root cause of the 02:42 health-check failure** was not established.
- Alarms have no notification action (SNS), so detection is visible only in CloudWatch.
