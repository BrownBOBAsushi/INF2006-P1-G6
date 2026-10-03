# Local asynchronous resume processing

The localhost Compose stack runs three independent roles: the API, an extraction worker, and an embedding worker. Both worker pools use PostgreSQL-backed `processing_tasks` plus `processing_outbox`; this remains the default `PROCESSING_MODE=local` adapter. API startup and `/health/ready` do not start or warm a model process. The extraction worker loads PDF/privacy code, while the embedding worker loads the embedding model.

## Lifecycle

`POST /api/resume/prepare` validates and writes the PDF to temporary storage, then commits an extraction task and outbox event together and returns `202` with a task UUID. In local mode, the publisher changes a due outbox event to `SENT` only after the task is durably visible in PostgreSQL. Workers claim due `SENT` tasks from the database, so a crash after local publication cannot lose the task; duplicate publication is harmless because the task UUID and row lease are authoritative. Expired worker leases can be reclaimed, and stale lease tokens cannot complete a task or overwrite a newer revision.

Extraction results are owner-scoped, temporary task data. The browser polls the task endpoint and can rediscover the current owner's in-progress or completed draft after reload. The user must review and explicitly save the extracted content. Discard and resume deletion clear task results and cancel work; temporary PDFs are unlinked on completion, terminal failure, discard, or deletion. A one-hour local default TTL is configurable with `PROCESSING_TEMP_TTL_SECONDS`; worker cleanup expires abandoned tasks/results and removes orphaned files, including upload staging files left by a crash.

Saving does a synchronous privacy recheck but does not initialize the embedding model. The approved profile revision, successful `SaveOperation`, and embedding task/outbox event commit in one transaction. The UI reports saved content separately from recommendation readiness and polls the profile briefly while embedding is pending. Matching only uses vectors for the current profile revision. If embedding fails, saving the same approved details again schedules a retry without changing the content revision.

Session rows remain in PostgreSQL. Task reads and discard are owner-scoped; discard and delete require the session's origin/CSRF checks. No PDF is saved to browser storage, the profile, or a download endpoint. Local mode does not load AWS credentials or make AWS calls.

## AWS adapter contract

The code now has a selectable AWS adapter, but no AWS resources or cloud acceptance have been verified. Leave `PROCESSING_MODE` unset or set it to `local` for the AWS-free path. AWS mode is explicit and fails startup if required settings are absent; it never falls back to local storage or DB scanning.

Set these environment variable names on the API and worker processes for AWS mode:

```sh
PROCESSING_MODE=aws
AWS_REGION=<region>
PROCESSING_TEMP_BUCKET=<private-temporary-input-bucket>
PROCESSING_TEMP_PREFIX=temporary-resume-inputs
PROCESSING_TEMP_TTL_SECONDS=3600
PROCESSING_EXTRACTION_QUEUE_URL=<extraction-queue-url>
PROCESSING_EMBEDDING_QUEUE_URL=<embedding-queue-url>
```

The bucket and queues must be created separately. The bucket must remain private, block public access, and have a lifecycle expiration backstop no shorter than the configured task retention. Each SQS queue needs its own DLQ and a 900-second visibility timeout to match the database task lease. Configure worker IAM access only for the temporary prefix and the two queues; this repository does not create those policies or resources.

AWS mode writes PDF bytes under a generated UUID key and reads them through the SDK's default TLS certificate validation. SQS messages carry only the task UUID and kind. The database task revision and fenced lease remain authoritative: publishers mark an outbox row `SENT` only after SQS returns a message ID; workers delete a receipt only after terminal state or a durable database retry is committed. A confirmed send whose DB acknowledgement fails may be sent again, so SQS delivery is at least once. The API runs a DB-leased publisher loop, allowing multiple API instances to share one outbox safely. Workers use the same extraction and embedding handlers as local mode; embedding obtains only approved content from PostgreSQL.

The adapters and a layered private stack/bootstrap implementation are code-only preparation. Queue/DLQ, temporary-bucket, and private-network resources are defined in the new templates; they are not deployed or cloud-validated. Shared-role permissions, model startup, complete app deployment, and cloud recovery measurements remain later verification gates. See [the private rollout runbook](PRIVATE_CLOUD_ROLLOUT.md).

## Local Compose

After configuring the existing local `src/.env` file, apply migrations and start the stack:

```sh
export APP_ORIGIN=http://localhost:8080
export GOOGLE_CLIENT_ID=disposable-test-client
export APP_SIGNING_KEY=disposable-test-signing-key
docker compose --env-file src/.env run --rm api alembic upgrade head
docker compose --env-file src/.env up --build -d
docker compose --env-file src/.env ps
curl -fsS http://localhost:8080/health/live
curl -fsS http://localhost:8080/health/ready
```

The worker services are named `extraction-worker` and `embedding-worker`. The `processing_temp_data` volume is mounted by the API and both workers; do not mount a different volume or local path for any role. The test and synthetic reproduction use no cloud services. A functioning model cache is needed for workers to process work; API liveness/readiness is independent of model startup.

## Disposable PostgreSQL verification

Run only against a dedicated disposable PostgreSQL database with pgvector. The command below uses the isolated test database reported by the user on loopback port 55433. `test:test` is disposable synthetic test authentication, never a production credential. Recheck the target before running migrations:

```sh
(
  set -e
  export DISPOSABLE_DATABASE_URL='postgresql+psycopg://test:test@127.0.0.1:55433/task_tests'
  export DATABASE_URL="$DISPOSABLE_DATABASE_URL"
  export APP_ORIGIN='http://localhost:8080'
  export GOOGLE_CLIENT_ID='disposable-test-client'
  export APP_SIGNING_KEY='disposable-test-signing-key'
  export PYTHONPATH=src/backend
  src/backend/.venv/bin/alembic -c src/backend/alembic.ini upgrade head
  src/backend/.venv/bin/python -m pytest \
    tests/backend/test_api_integration_disposable.py \
    tests/backend/test_task_recovery.py \
    tests/backend/test_outbox.py -q
)
```

This suite uses injected extraction/embedding handlers, not model downloads. Its integrated journey covers accepted upload, delivery, extraction, owner-only polling from a second database session reusing the cookie, explicit save while embedding is pending, embedding completion, readiness, and deletion. The task recovery/outbox tests cover duplicate delivery, retries, and lease fencing. The database URL must point to an isolated test database; do not aim these tests at a shared or production database.

## Evidence boundary

**User-reported verification:** on 2026-10-02, the migration and the three focused suites above ran against the isolated `inf2006-cloud-test-db-55433` database and reported **31 passed, 2 warnings in 1.49s**. The warnings were Starlette's `httpx` deprecation and AnyIO's `BlockingPortal` alias. This is user-reported evidence, not a run by the current coding agent. It verifies only those migrations and suites; it does not verify model-backed processing, Docker Compose startup, live Google sign-in, or AWS/cloud behavior. See [the dated local integration evidence](../evidence/local-async-processing-2026-10-02.md).
