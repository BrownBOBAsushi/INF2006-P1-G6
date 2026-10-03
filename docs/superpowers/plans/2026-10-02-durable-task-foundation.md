# Durable task and outbox foundation

**Status:** The local application lifecycle uses the durable task/outbox foundation with detached extraction and embedding workers. Selectable S3/SQS adapters and the multi-instance API outbox publisher are now implemented; AWS resources, private worker deployment, and cloud acceptance remain future phases. See [local async processing](../../LOCAL_ASYNC_PROCESSING.md) for both adapter contracts.

## Scope

Add owner-scoped extraction/embedding task rows and one transactional outbox event per stable task identity. Callers create task and outbox rows in their existing transaction; the module never commits. PostgreSQL row locks with `SKIP LOCKED` coordinate claims. Attempt count increments only on a fresh task lease. Lease tokens fence old workers and publishers. Retries keep the task identity and are scheduled with `available_at`; maximum attempts end in `FAILED`. Completion requires the owning user, matching task revision, live lease token, and current user revision. Explicit resume deletion must call `cancel_owner_tasks` in its transaction; account deletion cascades both rows.

Publisher code may acknowledge only after transport confirmation. If a send succeeds but the acknowledgement transaction does not, the event may be published again; consumers treat task identity as the idempotency key. The AWS adapter implements this with SQS while retaining the PostgreSQL task and lease as authority.

## Implementation and verification files

- Schema and lifecycle: `src/backend/app/db/models.py`, `src/backend/migrations/versions/6a2fd7b41c90_add_processing_tasks_and_outbox.py`, `src/backend/app/processing/tasks.py`, `src/backend/app/processing/outbox.py`.
- Verification: `tests/backend/test_task_contracts.py`, `tests/backend/test_task_recovery.py`, `tests/backend/test_outbox.py`.
- Evidence: [`evidence/durable-task-foundation-2026-10-02.md`](../../../evidence/durable-task-foundation-2026-10-02.md).

## Completed local integration

The API accepts PDF work as a durable task, exposes owner-scoped task polling/discard, saves approved content and embedding work atomically, and does not start processing children or blanket-fail PROCESSING saves during startup. Separate local workers load extraction/privacy and embedding dependencies. Temporary inputs/results have expiry and deletion cleanup. PostgreSQL sessions remain persistent. The frontend recovers extraction status after reload, protects against stale task responses, and shows saved content separately from embedding readiness. The complete local contract and exact reproduction commands are in `docs/LOCAL_ASYNC_PROCESSING.md`.

Run the PostgreSQL integration tests only against a dedicated disposable database. SQLite is not evidence for row-lock concurrency. Do not enable multi-instance APIs until task/outbox integration, cross-instance authentication, startup recovery replacement, and the worker/frontend lifecycle pass their tests.

## Sequenced remaining phases

1. **Local verification:** run the PostgreSQL migration and integrated route/worker journey on the explicitly disposable database. Run full backend/frontend tests, frontend typecheck/build, and Compose startup on a host with Docker and the approved local model cache. Keep unrun checks clearly labeled.
2. **AWS infrastructure and deployment:** the code adapters are implemented and keep AWS-free local reproduction. Add temporary-input S3, two SQS queues/DLQs, private workers, and the final app topology only after the local lifecycle gates pass. Present exact cloud resource/configuration changes for approval before provisioning or external configuration.
3. **Cloud evidence:** after authorized deployment, use synthetic data to measure upload/extraction/save/embedding, duplicate delivery and worker recovery, API instance failure, cross-instance sessions, database restore to a separate database, monitoring, cost, and teardown. Record actual commands, dates, outcomes, evidence paths, and limits before updating acceptance claims.
