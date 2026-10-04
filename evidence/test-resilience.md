# Scalability / resilience / recovery test record

**Brief reference:** Section 4 (Scalability and resilience) and Section 5.2 test (4).
**Status:** PASS for automatic replacement of failed web/API instances (observed R1/R2 and a controlled, timed test R4), for
continuity during a single-target withdrawal (R3), and for a database point-in-time restore verified by schema and row counts (R5). Finding R0 records a grace-period defect found and fixed on 2026-10-03. Load testing was not performed.

## Mechanisms implemented

| Mechanism | Configuration (source → captured state) |
|---|---|
| Load balancing across two AZs | `InternalAlb` → `AppHttpsTargetGroup` (HTTPS 8443, `GET /health/ready` every 30 s, unhealthy after 2 failures) — `src/infra/cloudformation/ingress-http-api.yaml` → `cloud-capture-2026-10-03/02-ingress.txt` |
| Self-healing compute | `AppAutoScalingGroup` min = max = desired = 2, `HealthCheckType: ELB`, grace 900 s (raised from 420 s, see Finding R0), subnets in us-east-1a/b — `private-app.yaml` → `03-compute.txt` |
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

## Finding R0 — replacement instances were killed before becoming healthy (grace period too short)

- **Observation (2026-10-03, 15:30–16:03 UTC, after a Learner Lab restart):** every replacement in us-east-1a was terminated by the
  ASG about 8 minutes after launch, before the ALB marked it healthy (launches at 15:30, 15:38, 15:46 and 15:55; the 15:38 and 15:46
  instances were taken out of service on "ELB system health check failure" at 15:46:56 and ~15:54). After the restart (about 15:26 UTC) the public endpoint
  returned HTTP 502 on every path (observed 15:33 UTC, `test-security-tls-2026-10-03.md`) until the first us-east-1b instance became
  healthy at about 15:40 UTC (outage of roughly ten minutes or more, not timed precisely); afterwards it stayed up only because
  the us-east-1b target was healthy.
- **Diagnosis (read-only SSM on the newest failing instance):** containers were running and `GET /health/ready` returned 200 locally;
  the ALB's own checks were already getting 200. Bootstrap took **348 s** (boot 15:47:03 → cloud-init finished 15:52:51), and
  the ALB needs several passing checks after that, so a replacement needs about 8 min to become healthy, longer than the 420 s
  `HealthCheckGracePeriod`. Instance bootstrap time was not broken down further; why us-east-1b was faster was not investigated.
- **Fix (operator-applied 2026-10-03 ~15:59 UTC):** `aws autoscaling update-auto-scaling-group --health-check-grace-period 900`
  and `HealthCheckGracePeriod: 900` in `src/infra/cloudformation/private-app.yaml` (the deployed stack template has not been
  re-applied, so the stack and the ASG differ until the next stack update).
- **Result after the fix:** the 15:55 instance became healthy at 16:02:44 (7 min 44 s after launch) and the replacement in
  Test R4 below became healthy without another loop. Updates to table row "Self-healing compute": grace is now 900 s.

## Test R4 — controlled termination of one app instance (automatic replacement, measured)

- **Objective:** Show, with timestamps, that losing one web/API instance is detected and repaired automatically and that the
  public service keeps answering.
- **Setup:** `AppAutoScalingGroup` (min = max = desired = 2, ELB health check, grace 900 s), both targets healthy at 16:04:01 UTC.
  A monitor polled the public `GET /health/ready` every ~3 s and the ALB target state and ASG instance state every ~15 s.
- **Command:** `aws ec2 terminate-instances --instance-ids <instance-2>` (us-east-1b), 2026-10-03 16:04:18 UTC, operator-approved.
- **Expected:** ASG detects the terminated instance, launches a replacement, the target becomes healthy; no manual action;
  the remaining instance keeps the service available.
- **Actual (UTC):**
  - 16:04:18 terminate requested. 16:04:19 probe 502 and 16:04:28 probe no response (the ALB still routed to the dying target) — the only 2 non-200 probes of 290 (about 10 s of impact).
  - 16:04:54 ASG shows the instance Unhealthy; 16:05:03 "taken out of service in response to an EC2 health check indicating it has been terminated"; 16:05:05 replacement launch started (successful 16:05:12).
  - 16:05:11 replacement registered (`initial`), 16:05:47 `unhealthy` while booting, **16:14:10 `healthy`**. Desired capacity of 2 restored with no operator action.
  - All probes from 16:04:29 to the end of the test (16:25) returned 200.
- **Measured:** detection about 45 s after termination; replacement launched 47 s after; healthy at the ALB about 9 min 5 s after launch (9 min 52 s after termination), single-instance capacity in between.
- **Artefacts:** `evidence/recovery-test-2026-10-03/state-log.txt`, `evidence/recovery-test-2026-10-03/public-probe-log.txt` (instance IDs redacted: `<instance-1>` survivor, `<instance-2>` terminated, `<instance-3>` replacement).
- **Result:** PASS — automatic detection and replacement, with about 10 s of probe failures at the moment of termination and degraded capacity (one instance) for about 10 minutes. This shows the system recovers from a single-instance crash; it does not show recovery from a whole-AZ or database failure.

## Test R5 — database restore from automated backup (point-in-time)

- **Objective:** Show that the RDS automated backups can restore the database into a working, private, encrypted instance.
- **Command (operator-approved, 2026-10-03 16:04:39 UTC):** `aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier <db> --target-db-instance-identifier inf2006-restore-test-temp --use-latest-restorable-time --db-instance-class db.t3.micro --no-publicly-accessible --no-multi-az` with the source's subnet group and security group.
- **Expected:** a new instance with the same engine version and encrypted storage, not public, created from the latest restorable time.
- **Actual:** RDS event "Restored from DB instance ... to 2026-10-03 16:00:40" at 16:13:35 UTC; the new instance reached an endpoint by about 16:15 and a `backing-up` status afterwards. Restored instance: PostgreSQL 16.15, 20 GB, `StorageEncrypted: true`, `PubliclyAccessible: false`, `db.t3.micro` — identical engine version, size and encryption to the source. Elapsed from request to restored instance event: about 9 minutes.
- **Content check (operator-run, 2026-10-03 ~16:35 UTC):** `AWS_PROFILE=inf2006-lab bash tests/infra/verify_restore.sh <app-instance> inf2006-restore-test-temp`
  (script `tests/infra/verify_restore.sh` + `restore_verify.py`; run inside the api container via SSM with the application's runtime role,
  credentials not printed). Source and restored databases returned **identical results**: 12 tables, extensions `plpgsql` and
  `vector` (pgvector), and identical row counts for the 11 readable tables — `app_state` 1, `job_requirements` 1433, `jobs` 247,
  `processing_outbox` 10, `processing_tasks` 10, `requirement_embeddings` 1756, `resume_chunks` 17, `resume_profiles` 2,
  `save_operations` 9, `sessions` 3, `users` 4. (`alembic_version` returned `permission denied` for the runtime role on both
  databases — the application role cannot read the migration table, consistent with least privilege; the migration revision was therefore not compared.)
- **Limits:** the restore point was the latest restorable time (16:00:40 UTC), minutes before the test, so this shows a
  recent-state restore, not recovery from corruption days old. Row counts and schema presence were compared; row contents were not.
  The database contents were not inspected; only counts are recorded. The restore went into a temporary instance; it was not swapped into the
  application, and no application cut-over was timed. Restore creation took about 9 minutes (RDS Single-AZ, db.t3.micro, 20 GB).
- **Cleanup:** the temporary instance `inf2006-restore-test-temp` was deleted after the check (see below).
- **Result:** PASS — a point-in-time restore of the automated backup produced a private, encrypted instance with the same
  engine version, schema, pgvector extension and row counts as the source.

## Earlier test (historical stack)

On 2026-09-27 the earlier single-instance foundation (since torn down) passed an API-container stop/restart test
in which `ApiReadinessAlarm` went OK → ALARM → OK; the alarm history for that stack is still visible in
`07-alarms.txt` (20:31:19 → 20:34:19 SGT). Record: `evidence/cloud-foundation-run-2026-09-27.md`.

## Limitations and improvement plan

- **Database:** Single-AZ RDS; no failover (an instance or AZ failure means downtime until a restore, which took about 9 minutes in R5 plus a cut-over that was not tested). Improvement: Multi-AZ, or a documented restore-and-repoint runbook.
- **Worker:** single instance, not in an Auto Scaling group; if it stops, uploads queue in SQS (4-day retention)
  until it returns, so work is delayed, not lost. Improvement: put the worker in its own ASG and scale on queue age.
- **No load test** against the cloud stack; the ASG has a fixed size of 2 (no scaling policy). Local load
  measurements are in `evidence/load-matching-2026-09-21.md` and `evidence/load-api-harness-2026-09-21-api.md`.
- **Root cause of the 02:42 health-check failure** was not established.
- Alarms have no notification action (SNS), so detection is visible only in CloudWatch.
