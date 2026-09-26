# Cloud Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and verify the team's proposed AWS deployment and durable resume-processing workflow, while keeping every cloud and assessment claim tied to current evidence.

**Architecture:** Keep Docker Compose as the local development environment and use AWS CloudFormation in two stacks/phases. First deploy only the existing synchronous API/web baseline and RDS foundation from a pinned commit/image; only after that works, implement and verify durable asynchronous processing locally, then extend infrastructure with S3, separate extraction and embedding SQS queues with DLQs, and private workers. Durable task and outbox records share PostgreSQL transactions; S3 uploads precede those transactions, while queue publication and cleanup are recoverable asynchronous work.

**Tech Stack:** Existing FastAPI/Python 3.11, SQLAlchemy/Alembic, PostgreSQL 16/pgvector, React/TypeScript, Docker Compose, AWS CloudFormation, EC2, RDS, S3, SQS, ECR, CloudWatch, and the supplied Learner Lab `LabRole`/`LabInstanceProfile`.

**Spec:** [Cloud architecture and team decisions](../../CLOUD_ARCHITECTURE.md), [requirements checklist](../../REQUIREMENTS_CHECKLIST.md), and [Learner Lab capability evidence](../../LEARNER_LAB_CAPABILITIES.md).

## Global Constraints

- The architecture remains proposed until dated cloud evidence proves implementation; this plan and local tests do not authorize provisioning or production changes.
- Use synthetic PDFs and accounts for testing. Never log raw resumes, cookies, credentials, secret values, or signed URLs.
- Use the supplied lab roles; do not create custom IAM users, roles, or groups. Verify the actual `LabRole` permissions and record any limitation.
- RDS is planned Single-AZ. A subnet group across two Availability Zones is placement coverage, not a standby or HA claim.
- After ML processing moves to the worker, the provisional API budget is 2 vCPU / 1 GiB; worker budget is 2 vCPU / 2 GiB; RDS candidate is `db.t3.micro` / 20 GiB gp2 / Single-AZ; worker concurrency is one extraction plus one embedding process. The foundation stage runs the current synchronous API, which loads ML processing in the API container. Gate its temporary API size on measured image/model memory, use a verified temporary size if needed, and do not run the 50-item workload on that intermediate setup. Exact EC2 classes, PostgreSQL minor, pgvector support, and safe memory headroom are verification gates.
- Targets: browse p95 at most 1 second while processing; each upload accepted within 2 seconds after transfer ends (per sample, not p95); extraction p95 at most 60 seconds from acceptance; embedding-ready p95 at most 60 seconds from explicit-save acceptance.
- Exercise 50 synthetic uploads and 50 synthetic saves as separate workloads. Record fixture count and sizes, failures, tail latency, cold/warm host results, and available CPU-credit observations. These targets and workloads are not existing results.
- Processing permits up to three attempts total, including the initial attempt, for transient failures. Unusable PDFs are terminal. SQS receive count is not an exact worker execution count; choose `maxReceiveCount` with visibility and worker behavior.
- A database outbox row is committed with each durable task. A publisher may deliver more than once and must mark a row sent only after SQS acknowledges. Publisher placement and transport require a recorded decision before implementation; do not silently add an AWS service.
- The extraction worker writes only a reviewable draft and extraction status. Explicit save promotes approved content and the uploaded PDF reference together in a DB transaction, with embedding state `PENDING`. Embedding workers write vectors/status only if the task and revision are still current at the atomic commit. Failure preserves saved content and PDF; only current-revision `READY` vectors are matchable.
- Retained-vs-disposable environment, failed/abandoned PDF retention and cleanup interval, queue poll interval, visibility/lease/reconciliation values, secrets delivery, TLS/hostname/OAuth callback, alarm thresholds, and backup/recovery objective are explicit decision gates. Assign an owner and verify each before its dependent task.
- A readiness gate is not deployment authorization. Cloud provisioning, public exposure, and teardown require a separate explicit human authorization after the concrete changes and resource list are reviewable.

## Review Focus

- API timeout or cancellation after S3 upload must leave either a durable task or a safely discoverable orphan; it must never acknowledge work before the object and DB task/outbox transaction exist. Pin in upload acceptance/reconciliation tests.
- Duplicate publication, worker redelivery, worker crash, and stale revision completion must not duplicate saves, alter newer content, or falsely mark current work ready. Pin in outbox and worker state-transition tests.
- An embedding error or abandoned review must retain the last explicitly saved content and PDF reference; a late worker must not overwrite a newer retry. Pin in revision and retry tests.
- User/task/PDF identifiers must remain owner-scoped, signed downloads short-lived, and logs free of resume content or secrets. Pin in two-user access and log-redaction tests.
- Cold starts, host CPU credits, concurrency, and failed items can break latency goals even when averages pass. Pin in separately reported cold/warm 50-upload and 50-save cloud runs.

---

## File Map

Existing files to extend: `src/backend/app/api/resume.py`, `src/backend/app/db/models.py`, `src/backend/app/processing/worker.py`, `src/backend/app/processing/pipeline.py`, `src/backend/migrations/versions/`, `src/frontend/src/features/resume/api/`, `src/frontend/src/features/resume/hooks/useResumeWorkspace.ts`, `docker-compose.yml`, `src/infra/README.md`, `src/README.md`, `docs/diagrams/cloud-architecture.md`, `docs/CLOUD_ARCHITECTURE.md`, `project_manifest.yaml`, and the `evidence/` records named below.

Proposed new files (names to use unless a repository convention discovered during implementation justifies an equivalent): `src/backend/app/processing/tasks.py` for DB-backed task transitions; `src/backend/app/processing/outbox.py` for claim/publish/ack logic; `src/backend/app/storage/s3.py` for owner-scoped object operations; `src/backend/app/processing/cloud_worker.py` for queue polling; `src/infra/cloudformation/main.yaml` for CloudFormation; and focused tests under `tests/backend/`, `tests/pipeline/`, `tests/frontend/`, and `tests/infra/`.

## Decision Gates

Each decision produces a short record in `docs/CLOUD_ARCHITECTURE.md` with owner, selected value, reason, and verification evidence. Dependent work stays unchecked until the gate is closed.

| Gate | Owner | Required decision and verification before dependent work |
|---|---|---|
| Environment lifecycle | Team deployment lead, named before infrastructure work | Choose retained vs disposable environment; document resource inventory, evidence-capture sequence, safe teardown procedure, and what may remain billable. Verify the proposed lifecycle against Learner Lab restart behavior. |
| PDF cleanup | Backend/data owner | Set failed and abandoned upload retention plus cleanup interval. Test that abandoned candidates are deleted while the previous saved reference remains usable, and that explicit file/account deletion removes owned objects. |
| Queue and recovery values | Backend/operations owner | Choose poll interval, visibility timeout, lease duration, reconciliation cadence, and `maxReceiveCount`/DLQ redrive consistent with three total transient attempts. Verify crash/retry tests and show queued-but-unpublished work is not misclassified as stuck. |
| Outbox publisher placement | Architecture owner and backend owner | Select an allowed placement and network path without implying a new service. Verify DB-to-SQS publish/ack/replay behavior and duplicate delivery before cloud worker rollout. |
| Secrets and transport | Deployment/security owner | Choose secret delivery from currently permitted lab services; choose TLS termination, exact hostname/certificate, and OAuth callback. Verify real sign-in, HTTPS, no secrets in images/logs, and callback allowlist before public workflow claims. |
| Compute/database fit | Chuying (measurements) and deployment lead | Check current lab quotas/classes, exact PostgreSQL 16 minor and pgvector, then migrations and a real vector query. Verify measured headroom for one extraction plus one embedding process on proposed worker budget; adjust only with recorded evidence. |
| Cost and evidence lifecycle | Zhihao (budget/deployment review) | Record a resource inventory and cost-control checks; capture dated/redacted configuration before any authorized teardown. Do not infer spend from a ten-minute recording or delayed budget dashboard. |

The architecture decision record must satisfy checklist S5.1-A02 before foundation provisioning. For **service model**, compare IaaS EC2 (selected: lab-listed, team controls OS/runtime and separate worker sizing) with a managed application/container service (less host administration, but service availability and Learner Lab permissions must be proven); also consider FaaS for short jobs (model cold-start/runtime limits need measurement). For **deployment model**, compare one VM running web/API/processing/database (fewer components, but shared host resources/failure domain and operator-managed backup) with the selected split public API/private worker/private RDS design (separate processing capacity and managed DB backups, with more network/operations cost); compare a managed/serverless deployment if lab permissions and budget support it. Record at least two alternatives for each choice and evidence-based trade-offs; this plan does not claim professor approval.

For async delivery, two SQS queues are selected to isolate extraction and embedding concurrency, retry/DLQ behavior, and backlog visibility. A no-queue bounded API wait would keep expensive work in request workers and couple processing delays to API availability. One shared queue would mix tasks with different runtimes and failure policies, allowing one stage's backlog to delay the other. Separate queues add configuration and cost, so verify the lab path and operational burden before rollout.

## Tasks

### Required execution order and dependencies

Follow this order even though the design work can be reviewed together: **Task 1a contracts only → Task 6a foundation template → Task 7 foundation deployment and RDS checks → Task 7b isolated backup/restore test → Tasks 2, 3, 4, and 5 local async data/storage/worker/outbox implementation → Task 1b API wiring → Task 8 frontend integration → full local journey → Task 6b async CloudFormation extension → Task 9 worker rollout → Task 10 cloud workload/evidence.** Each cloud deployment/workload still requires its separate human authorization gate. Task 6a must pin the existing synchronous API commit/image and exclude worker, S3, SQS, and outbox infrastructure. Do not change the pinned API until foundation evidence is captured. Task 6b adds async resources only after the real local journey passes.

### Task 1a: Freeze proposed async schemas only

**Files:**
- Create: `docs/CLOUD_API_CONTRACT.md`
- Modify: `src/frontend/src/features/resume/api/contractTypes.ts`
- Test: `src/frontend/src/features/resume/api/`

**Interfaces:**
- Existing local API: `POST /api/resume/prepare` currently returns a completed draft; `PUT /api/resume` currently performs synchronous save/embedding and returns `SaveResumeResponse`; `GET /api/resume/operations/{operation_id}` is owner-scoped. These are current contracts to migrate deliberately, not async behavior already present.
- Proposed contracts to freeze in schema types before route wiring: `POST /api/resume/prepare` returns `202 {task_id, state:"PENDING"}` only after S3 upload plus DB task/outbox commit; proposed owner-scoped `GET /api/resume/tasks/{task_id}` returns `202 {task_id,state:"PENDING"}`, `200 {task_id,state:"SUCCEEDED",draft,unassigned_text,warnings}`, or `200 {task_id,state:"FAILED",failure_code}`. `PUT /api/resume` returns `202 {operation_id,result_revision,changed,embedding_status:"PENDING"}` after approved content/revision/PDF reference plus embedding task/outbox commit; existing owner-scoped `GET /api/resume/operations/{operation_id}` returns its terminal embedding result. These are proposed contracts, not existing async endpoints.

- [ ] **Step 1: Add failing schema tests** for the proposed pending/success/failure shapes, stable operation/task IDs, and transient `unassigned_text`.
- [ ] **Step 2: Run focused frontend schema checks** and confirm the proposed type assertions fail.
- [ ] **Step 3: Record exact proposed schemas in `docs/CLOUD_API_CONTRACT.md` and add TypeScript types only**; leave backend code and the pinned foundation API unchanged.
- [ ] **Step 4: Run frontend type checks**; label the async routes as proposed until Task 1b implements them.

### Task 2: Add transactional task, outbox, and revision state

**Files:**
- Modify: `src/backend/app/db/models.py`
- Create: `src/backend/migrations/versions/<revision>_add_processing_tasks_and_outbox.py`
- Create: `src/backend/app/processing/tasks.py`
- Create: `src/backend/app/processing/outbox.py`
- Test: `tests/backend/test_schema_invariants.py`
- Test: `tests/backend/test_api_integration_disposable.py`
- Test: `tests/backend/test_outbox.py` (proposed)

**Interfaces:**
- Proposed task identity is stable across SQS duplicate deliveries and distinct for each retry attempt. Task rows include owner, kind, current revision where applicable, state, attempt identity/count, timestamps, and safe failure code; never persist PDF text in task/outbox payloads.
- `enqueue_task(db, *, owner_id, kind, task_key, revision, payload_ref) -> ProcessingTask` and `claim_outbox_batch(db, *, limit) -> list[OutboxEvent]` are proposed interfaces. Publisher acknowledgement updates a row only after AWS confirms send; failures leave it retryable.

- [ ] **Step 1: Add failing migration/schema tests** for unique task identity, owner FK, bounded states, outbox uniqueness, due/sent timestamps, and revision/task linkage.
- [ ] **Step 2: Run** `docker compose -f docker-compose.dev.yml --profile test run --rm backend-tests` against its disposable pgvector DB; confirm the new assertions fail.
- [ ] **Step 3: Add the Alembic migration and task/outbox models** without changing the existing `SaveOperation` idempotency contract except where Task 1b explicitly migrates it.
- [ ] **Step 4: Implement atomic task-plus-outbox creation and claim/ack/fail transitions**; claiming must use a lease or equivalent concurrency-safe claim so two publishers cannot corrupt row state.
- [ ] **Step 5: Add DB tests** proving task and outbox commit together, rollback together, duplicate task identity is rejected/replayed safely, and unacknowledged publication remains retryable.
- [ ] **Step 6: Re-run** the backend disposable migration/schema suite and `tests/backend/test_api_integration_disposable.py`.

**Dependency:** Must follow Task 7 and 7b in the required execution order; its schema shape may be reviewed earlier, but no async DB migration is added to the foundation baseline.

### Task 3: Add private S3 lifecycle and ownership checks

**Files:**
- Create: `src/backend/app/storage/s3.py`
- Modify: `src/backend/app/api/resume.py`
- Modify: `src/backend/app/db/models.py`
- Modify: `src/backend/migrations/versions/<revision>_add_saved_pdf_reference.py`
- Test: `tests/backend/test_resume.py`
- Test: `tests/backend/test_storage_s3.py` (proposed)

**Interfaces:**
- `put_candidate_pdf(owner_id, upload_id, pdf_bytes) -> ObjectRef`, `issue_download_url(owner_id, object_ref, expires_in) -> str`, and `delete_owned_pdf(owner_id, object_ref) -> None` are proposed interfaces. Object keys are generated by the server and are never accepted as proof of ownership.
- The DB stores candidate and current saved-object references. S3 upload occurs before the task transaction; reconciliation/cleanup handles an object left behind by a failed DB transaction. Explicit save promotes the reference in the same transaction as approved revision/task/outbox state; previous current PDF deletion happens after commit.

- [ ] **Step 1: Add failing storage/API tests** for generated owner-scoped keys, rejected cross-user download/delete, short-lived signed URL configuration, S3-success/DB-failure orphan cleanup, abandoned review preserving the prior PDF, and embedding failure preserving the newly saved PDF.
- [ ] **Step 2: Run** focused backend tests and confirm the storage/lifecycle assertions fail.
- [ ] **Step 3: Implement the object adapter and DB references** using injected clients so tests can use a deterministic fake; do not log object URLs, resume bytes, or signed query parameters.
- [ ] **Step 4: Implement explicit-save promotion and post-commit cleanup**; account/file deletion schedules or performs owned-object removal and leaves auditable safe state on partial failure.
- [ ] **Step 5: Run** focused ownership, deletion, and failure-path tests; record that cloud S3 behavior remains unverified until an authorized cloud check.

### Task 4: Move extraction and embedding behind local workers

**Files:**
- Create: `src/backend/app/processing/cloud_worker.py`
- Modify: `src/backend/app/processing/worker.py`
- Modify: `src/backend/app/processing/pipeline.py`
- Modify: `src/backend/app/main.py`
- Modify: `docker-compose.yml`
- Test: `tests/backend/test_resume.py`
- Test: `tests/pipeline/test_processing_slot.py`
- Test: `tests/backend/test_task_recovery.py` (proposed)
- Test: `tests/pipeline/test_revision_worker.py` (proposed)

**Interfaces:**
- A local worker consumes persisted task records through a small queue adapter; cloud SQS is an adapter to the same task handler. Extraction calls existing `pipeline.prepare_resume(pdf_bytes, ...)` and persists only a reviewable draft/status. Embedding calls existing `pipeline.embed_resume(content, model)` for the task's revision.
- `handle_extraction(task_id) -> None` and `handle_embedding(task_id) -> None` are proposed handlers. The worker's final DB commit checks owner, task attempt identity, task state, and current revision after compute; stale results are discarded. Each retry creates a new attempt row for the saved revision and reuses the PDF reference.

- [ ] **Step 1: Add failing tests** for draft-only extraction, explicit-save-only profile creation, duplicate delivery, attempt A completing after revision B, old attempt completing after retry, worker crash recovery, and embedding failure retaining saved content/PDF while matching stays unavailable.
- [ ] **Step 2: Run** `python -m pytest tests/pipeline -q -p no:cacheprovider` with the documented cached models and local PostgreSQL setup; confirm the new assertions fail.
- [ ] **Step 3: Implement local task handling and a Docker Compose worker** with one extraction process and one embedding process maximum; keep API browse requests independent from processing.
- [ ] **Step 4: Implement state-checked atomic result commits** and distinguish pending, retryable, terminal, and ready states. Do not reset the old failed task on retry.
- [ ] **Step 5: Add a reconciliation runner** using the Task 1 decision-gated lease/cadence values; it must distinguish unsent outbox rows and active leased work from stuck tasks.
- [ ] **Step 6: Run** the complete pipeline suite and backend resume/recovery tests. Defer the full app journey until Tasks 1b, 5, and 8 are complete.

### Task 5: Implement and verify the transactional outbox publisher locally

**Files:**
- Modify: `src/backend/app/processing/outbox.py`
- Modify: `docker-compose.yml`
- Test: `tests/backend/test_outbox.py`
- Test: `tests/backend/test_task_recovery.py`

**Interfaces:**
- `publish_pending_events(batch_size) -> PublishSummary` uses an injected transport. For local Compose the transport may use a durable local broker or direct test adapter, selected and documented without changing the cloud architecture's pending publisher-placement decision.
- Publish acknowledgement is persisted after broker confirmation. Repeated publish is expected; task handlers provide idempotency.

- [ ] **Step 1: Add failing crash-window tests** for process death after DB commit/before publish, broker success/before sent-mark commit, repeated publish, and concurrent publisher claims.
- [ ] **Step 2: Run** the focused backend suite and confirm the crash-window tests fail.
- [ ] **Step 3: Implement publisher polling and ack behavior** using the chosen local transport and bounded batch/poll settings from local test config.
- [ ] **Step 4: Verify** every committed task is eventually publishable, duplicate delivery has one logical effect, and no API request waits on extraction or embedding.

### Task 6a: Build the synchronous foundation template only

**Files:**
- Create: `src/infra/cloudformation/main.yaml`
- Create: `src/infra/scripts/bootstrap-api.sh`
- Modify: `src/infra/README.md`
- Modify: `src/README.md`
- Test: `tests/infra/test_template_contract.py` (proposed)

**Interfaces:**
- Template parameters make region, the pinned existing synchronous API commit/image, public hostname/certificate, OAuth callback, secret reference, and supplied lab role explicit inputs; secret values never enter parameters or user data.
- Foundation resources are public API/web EC2, private Single-AZ RDS, VPC/network paths, HTTPS ingress, and CloudWatch health/logging. Exclude S3, SQS, outbox publisher, and worker resources. Deploy using `LabRole`/`LabInstanceProfile`; document explicit permission denials.
- RDS bootstrap uses its administrative credential only to enable `vector` and create separate `app_migrator` and `app_runtime` roles. The migration credential is used only by an explicit migration step; API runtime receives a secret reference for the restricted role, which has no DDL or superuser capability. The API must not run Alembic automatically at container startup. No logs contain resume content or credentials.

- [ ] **Step 1: Add template contract checks** for foundation-only resources, HTTPS-only public ingress, private RDS, pinned image/commit input, supplied role reference, and absence of S3/SQS/worker/outbox resources or custom IAM users/roles/groups.
- [ ] **Step 2: Review lab limits and close foundation hostname/TLS/OAuth/secrets/temporary API size gates** before setting defaults.
- [ ] **Step 3: Write the foundation template and API bootstrap** using the pinned existing synchronous image/commit. Override the image's current Alembic startup command so the API runs only with `app_runtime`; run the same pinned image once as an explicit migration command using `app_migrator`. Do not change application routes or add async resources here.
- [ ] **Step 4: Validate** with template contract tests and `aws cloudformation validate-template --template-body file://src/infra/cloudformation/main.yaml` when AWS CLI is available, without creating a stack.

### Task 6b: Extend CloudFormation for the locally verified async system

**Files:**
- Modify: `src/infra/cloudformation/main.yaml`
- Create: `src/infra/scripts/bootstrap-worker.sh`
- Modify: `src/backend/Dockerfile`
- Modify: `docker-compose.yml`
- Test: `tests/infra/test_template_contract.py`

**Interfaces:**
- Add private worker EC2, S3, separate extraction and embedding queues/DLQs, ECR, S3 gateway endpoint, provisional worker NAT egress, and the decision-gated outbox publisher path. Worker API and queue messages use the Task 1a contracts and Task 2–5 task semantics.
- Keep the existing public API endpoint stable through this extension. Runtime DB secret remains the restricted `app_runtime`; worker/migration/admin credentials use separate references and grants.

- [ ] **Step 1: Add failing template tests** for the new private worker and queue resources, private S3, distinct DLQs, permitted network paths, supplied role, and absence of custom IAM roles.
- [ ] **Step 2: Implement async stack resources and worker bootstrap** only after Tasks 2–5 and Task 8's real local journey pass.
- [ ] **Step 3: Re-run template validation and inspect the full change set**; verify foundation resources retain the pinned known-good baseline until the explicit API wiring update is included.

### Task 7: Prove the cloud foundation before asynchronous worker rollout

**Files:**
- Modify: `src/infra/README.md`
- Create: `evidence/cloud-foundation-YYYY-MM-DD.md`
- Modify: `project_manifest.yaml` only for facts supported by evidence
- Test: authorized cloud smoke procedure recorded in the evidence file

**Interfaces:**
- Cloud API/web deployment initially runs the existing synchronous API against private RDS; it does not claim async job support until Tasks 2–5 are implemented and verified locally. This API still loads ML processing in-process, so its temporary instance size is separately measured/verified and no 50-item workload is run on this intermediate setup.
- Foundation evidence records exact resource configuration, PostgreSQL minor and pgvector version, migration/vector-query result, HTTPS/auth callback, security-group paths, supplied role permissions, health checks, and whether the environment is retained or disposed.

- [ ] **Step 1: Require a separate human authorization** after the exact foundation-only CloudFormation change set, pinned API commit/image, resource inventory, expected lab/cost impact, evidence plan, and teardown choice are reviewable. This plan alone grants no deployment authority.
- [ ] **Step 2: After authorization, provision the foundation network, RDS, and API host** with the pinned synchronous API image, leaving the API process stopped until database bootstrap and migration finish.
- [ ] **Step 3: Bootstrap RDS with the administrator credential** to enable `vector` and create `app_migrator` and `app_runtime`; store separate secret references, run migrations in a one-off pinned-image command as `app_migrator`, and verify `app_runtime` cannot create/alter/drop objects and is not a superuser.
- [ ] **Step 4: Start the API with only the restricted `app_runtime` secret**; verify it does not run DDL or connect as administrator. Run real HTTPS sign-in, health, migration/vector-query and two-user ownership checks. Record temporary synchronous API memory fit; do not run the 50-item workload here.
- [ ] **Step 5: Capture dated, redacted foundation evidence** and report exact failures; no public URL, deployment status, or passing claim is made without evidence.
- [ ] **Step 6: Resolve failures and rerun affected checks** before adding worker resources; record teardown or retained-state instructions from the lifecycle gate.

### Task 7b: Back up and restore the cloud foundation safely

**Files:**
- Modify: `src/infra/cloudformation/main.yaml`
- Modify: `src/infra/README.md`
- Create: `src/infra/scripts/backup-restore-check.sh`
- Create: `evidence/backup-restore-YYYY-MM-DD.md`
- Test: isolated restore procedure

**Interfaces:**
- Before the test, the operations owner selects and records RPO/RTO targets and backup scope/retention. Do not invent targets in the plan or use a live database as the restore destination.
- Restore to a separate isolated RDS instance or disposable test stack. The source database remains untouched. If S3 PDF backup/versioning is selected, restore a synthetic object and verify its owner/reference mapping separately.

- [ ] **Step 1: Add a failing foundation restore verification** that compares schema/migration head, synthetic saved-profile row counts, and vector row counts/dimensions between the isolated restore and recorded source snapshot. PDF references and S3 objects are outside this foundation-stage test.
- [ ] **Step 2: Record the chosen RPO/RTO and backup scope** in the architecture/runbook before enabling the selected backup mechanism.
- [ ] **Step 3: Restore into an isolated target**, run migrations only if the restore requires a forward migration, and verify health plus the foundation's synchronous synthetic `login → browse → upload → review → save → recommendations → reload` journey; do not claim async recovery at this stage.
- [ ] **Step 4: Measure recovery time and recoverable-point gap**, compare them with the chosen RPO/RTO, retain evidence, and delete only the explicitly identified disposable restore target after evidence is secured.

### Task 8: Integrate frontend async states and the real local user journey

**Files:**
- Modify: `src/frontend/src/features/resume/api/contractTypes.ts`
- Modify: `src/frontend/src/features/resume/api/resumeApi.ts`
- Modify: `src/frontend/src/features/resume/hooks/useResumeWorkspace.ts`
- Modify: `src/frontend/src/features/resume/components/ResumeWorkspace.tsx`
- Test: `src/frontend/src/features/resume/__tests__/`
- Test: `tests/frontend/README.md`

**Interfaces:**
- The client uses the frozen Task 1a contracts. Pending extraction keeps the draft absent until completion; pending embedding preserves the saved profile and provides truthful status. Polling is bounded by the decision-gated interval/deadline and can resume after reload from the authenticated task/operation status.
- Failed or unknown outcome never displays “not saved” until status confirms failure; user drafts remain editable, and a retry creates a new task attempt without reuploading the saved PDF.

- [ ] **Step 1: Add failing UI/API tests** for pending extraction, extraction failure/retry, pending embedding, failed embedding with saved content retained, reload/reconnect recovery, and owner-scoped task rejection.
- [ ] **Step 2: Run** `cd src/frontend && npm run typecheck && npm test`; confirm the new behavior assertions fail before the hook/component changes.
- [ ] **Step 3: Implement pending/ready/failed UI states** without changing the explicit human review/save boundary.
- [ ] **Step 4: Run** frontend typecheck/tests/build. The full localhost journey waits for Task 1b and Task 5 so it includes API wiring and outbox dispatch; use the real API and local worker, not `tests/load/harness_app.py`.
- [ ] **Step 5: Update** `tests/frontend/README.md` with reproducible test commands and synthetic fixtures, replacing its stale “not implemented” status.
- [ ] **Step 6: Run the full local journey** `login → browse → upload → review → save → recommendations → reload` against the real API, local worker, and outbox dispatcher using synthetic data. Do not use `tests/load/harness_app.py` as application evidence.

### Task 1b: Wire the async API after local workers and outbox exist

**Files:**
- Modify: `src/backend/app/api/resume.py`
- Modify: `src/frontend/src/features/resume/api/resumeApi.ts`
- Test: `tests/backend/test_resume.py`

**Interfaces:**
- Implement only the Task 1a proposed routes and JSON fields, backed by Tasks 2–5. Preserve authentication, CSRF, idempotency, revision conflict, and owner checks. Keep the foundation image pinned until this code and the async local path pass.

- [ ] **Step 1: Add failing route tests** for accepted upload after S3 plus DB transaction, owner-scoped task status, accepted save plus durable outbox, and operation status through terminal embedding state.
- [ ] **Step 2: Run** focused backend tests and confirm they fail against the synchronous baseline.
- [ ] **Step 3: Wire routes to storage, task/outbox creation, and status reads**; return accepted only after required durable writes commit.
- [ ] **Step 4: Run** backend API tests and frontend API-client tests; verify repeated IDs replay safely and no work-status endpoint leaks another user's task.
- [ ] **Step 5: Defer the full localhost journey to Task 8 after the frontend and local outbox/worker path pass.**

### Task 9: Deploy asynchronous workers and exercise bounded retries

**Files:**
- Modify: `src/infra/cloudformation/main.yaml`
- Modify: `src/infra/scripts/bootstrap-worker.sh`
- Modify: `src/infra/README.md`
- Create: `evidence/cloud-worker-YYYY-MM-DD.md`
- Test: authorized cloud integration procedure

**Interfaces:**
- SQS messages carry opaque task ID, owner ID, task kind, and revision/attempt identity only; PDF bytes and resume text stay in private S3/PostgreSQL.
- Worker receives work, fetches owner-authorized inputs through the service path, applies terminal-vs-retryable classification, and commits only under the revision/task guard. The DLQ process and redrive values are those closed in the queue decision gate.

- [ ] **Step 1: Add cloud-worker acceptance tests** for duplicate SQS delivery, visibility timeout/retry, terminal invalid PDF, worker crash, DLQ visibility, current revision guard, and embedding failure preservation.
- [ ] **Step 2: Run local integration tests** with the same queue adapter semantics and record expected attempt accounting (initial attempt plus at most two transient retries).
- [ ] **Step 3: Require separate human review/authorization** of the worker stack change set and the specific resources before cloud worker rollout.
- [ ] **Step 4: After authorization, deploy workers and verify** SQS publish/consume, S3 gateway access, ECR image pulls including required S3 path, outbound SSM/CloudWatch path, task completion, and no raw resume data in logs.
- [ ] **Step 5: Capture dated, redacted evidence** including redelivery/terminal cases; do not equate SQS receive count with handler execution count.
- [ ] **Step 6: Under the chosen backup scope, verify PDF/S3 recovery** by restoring a synthetic object and checking its owner and saved-profile reference in an isolated target; record this separately from the foundation database restore.

### Task 10: Measure the agreed workloads and complete assessment evidence

**Files:**
- Modify: `tests/load/README.md`
- Modify: `tests/load/api_load.py`
- Create: `evidence/cloud-load-YYYY-MM-DD.md`
- Modify: `evidence/test-functional.md`
- Modify: `evidence/test-security.md`
- Modify: `evidence/test-resilience.md`
- Modify: `evidence/monitoring.md`
- Modify: `docs/diagrams/cloud-architecture.md`
- Modify: `evidence/architecture.svg` and packaged export selected by the team
- Modify: `project_manifest.yaml`
- Modify: `AI_USE_DECLARATION.md`

**Interfaces:**
- Extend the runner to target the actual deployed API and authenticated synthetic sessions. Do not report `harness_app.py` measurements as project API or cloud results.
- Report two independent runs: 50 uploads and 50 explicit saves, using the existing synthetic PDF fixture set; state repeated-fixture distribution and exact file sizes. Do not invent a PDF size limit or claim 50 concurrent users unless that is the actual configured schedule.
- Report browse p95 during processing; each upload acceptance latency after transfer; extraction p95 from accepted upload; embedding-ready p95 from accepted save; failures and retry counts; tail values; cold/warm host; CPU/memory/credit observations; and test environment/version/date/artifact paths.

- [ ] **Step 1: Add load-runner assertions** that fail if the API target is missing, responses cannot be correlated to task IDs, or terminal failures are dropped from totals.
- [ ] **Step 2: Run** current local runner smoke checks with synthetic sessions; verify the runner distinguishes acceptance latency from extraction completion and does not silently retry away failures.
- [ ] **Step 3: After worker cloud verification and separate human authorization for workload generation, run** the 50-upload and 50-save workloads as separate experiments with safe rate/concurrency recorded in advance.
- [ ] **Step 4: Compare each metric with its target**, list failures and tail latencies, and preserve raw redacted summaries; mark targets not met as failures with diagnosis rather than rewriting them as passes.
- [ ] **Step 5: Run the four required assessment records** (functional, security, data/AI, resilience/recovery) and a monitoring query/health check. Record each required field from `docs/REQUIREMENTS_CHECKLIST.md`.
- [ ] **Step 6: Align the editable diagram, README, `src/infra/README.md`, checklist, manifest, report, and packaged export** with implemented names and evidence. `evidence/architecture.svg` is an existing candidate path; verify package inclusion and do not include the obsolete `cloud-architecture-draft.png` as canonical.
- [ ] **Step 7: Complete `AI_USE_DECLARATION.md`** with tools, locations, sources/baselines, verification, licences, and attribution; leave the manifest's deployed/test status false unless corresponding evidence exists.
- [ ] **Step 8: Complete clean-package path checks** for the manifest and final evidence only after actual results exist; capture the upload receipt as a separate user action.

## Verification Commands

Run focused checks at each task, then the relevant full suites:

```bash
docker compose -f docker-compose.dev.yml --profile test run --rm backend-tests
python -m pytest tests/pipeline -q -p no:cacheprovider
cd src/frontend && npm run typecheck && npm test && npm run build
docker compose config
```

The backend suite uses a disposable pgvector DB. Pipeline tests need their documented dependency environment, cached models, and local PostgreSQL fixture. The frontend commands are the repository's documented scripts. CloudFormation validation and cloud runtime checks are separate; local success does not prove cloud capability, deployment, security, or latency.
