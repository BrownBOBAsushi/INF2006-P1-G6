# Local asynchronous processing integration — 2026-10-02

**Implementation:** The API now enqueues durable extraction tasks; detached local worker processes publish outbox events and claim `SENT` task rows. Extraction and embedding worker pools load separate handlers. PDFs use the shared local temporary volume; temporary extraction-result JSON is stored in task rows with a one-hour configurable expiry and cleanup on terminal failure, explicit discard, profile deletion, expiry, and orphan cleanup. The PDF itself is unlinked after extraction succeeds. Approved content, successful save operation, and embedding work commit atomically; embedding reads the current approved database revision. API startup/readiness no longer starts processing children or sweeps all `PROCESSING` saves. Workers run cleanup on a periodic cadence even under continuous load and stop their child process if startup cleanup fails. The frontend recovers extraction tasks after reload, discards server-side temporary drafts on confirmation, rejects stale session/task responses, and distinguishes saved content from embedding readiness.

The new task result migration is `6a2fd7b41c90 -> 1f02c7a89d31_add_temporary_task_results.py`. Compose adds `extraction-worker` and `embedding-worker` with a shared `processing_temp_data` volume; it retains PostgreSQL as the session/task store. The local queue is task-table-backed and PostgreSQL-specific. It is not evidence of SQS or AWS behavior.

## Checks executed here

Offline backend contracts, recovery helpers, outbox, local storage, worker fencing/handler separation, and API-boundary helpers:

```sh
cd src/backend
DATABASE_URL=postgresql+psycopg://test:test@127.0.0.1:1/test APP_ORIGIN=http://localhost:8080 GOOGLE_CLIENT_ID=disposable-test-client APP_SIGNING_KEY=disposable-test-signing-key .venv/bin/python -m pytest ../../tests/backend/test_task_contracts.py ../../tests/backend/test_task_recovery.py ../../tests/backend/test_outbox.py ../../tests/backend/test_local_temp_storage.py ../../tests/backend/test_local_worker_fencing.py ../../tests/backend/test_local_worker_lifecycle.py ../../tests/backend/test_worker_handler_separation.py ../../tests/backend/test_api_boundary_helpers.py ../../tests/backend/test_backend_contract_helpers.py ../../tests/backend/test_google_verify_diagnostics.py -q
```

Observed from `src/backend`: **45 passed, 2 skipped**. The skipped tests require a disposable PostgreSQL service; the port-1 database URL is intentionally unreachable and this command does not prove live PostgreSQL behavior.

Frontend checks:

```sh
npm exec vitest run -- --exclude '**/client.http.test.ts'
npm run typecheck
npm run build -- --outDir /tmp/inf2006-frontend-async-build
```

Observed: **219 tests passed across 17 files**, TypeScript typecheck passed, and Vite production build passed to the temporary output directory. The normal output-directory build could not remove the existing `src/frontend/dist/assets` directory (`EPERM`); it was left untouched. The excluded HTTP client test expects a live localhost server, which this environment cannot access.

Compose YAML parsed successfully with the API and both worker services sharing the temporary volume. PostgreSQL migration SQL generation succeeded through revision `1f02c7a89d31`. The parent agent also independently reported a `TestClient` liveness smoke returning 200 while confirming there were no processing children and `torch` was not imported; it did not verify database readiness.

## Database acceptance status

The integrated disposable-PostgreSQL tests are authored in `tests/backend/test_api_integration_disposable.py`. They cover `202` upload, outbox dispatch, injected extraction, owner-only task polling from a second DB session reusing the same cookie, cross-user denial, explicit save while embedding is pending, injected privacy/embedding handlers, ready state, and deletion. Temporary-file assertions follow each task's opaque `payload_ref`; JSON DELETE requests use the installed TestClient `request` interface. A separate test covers CSRF-protected draft discard and profileless deletion fencing/cleanup.

**User-reported PostgreSQL runs after migration to `1f02c7a89d31`:** The first targeted API/task/outbox run reported **29 passed, 1 failed** because the extraction result poll returned `result: null` after the worker completed. Root cause: the integration test reused the fixture's same SQLAlchemy `Session` for every TestClient request, while production `get_db()` creates a new session per request. A task object retained in the fixture identity map remained `PENDING` after a separate worker session committed `SUCCEEDED` and `result_data`. The test now uses a request-scoped DB session override only for the integrated journey; other tests, including commit-failure injection, retain the shared fixture. An offline SQLite ORM reproduction confirmed the boundary: the retained same-session query observed `PENDING`/no result, while a fresh request-equivalent session observed `SUCCEEDED`/result. This SQLite check demonstrates identity-map behavior only, not PostgreSQL semantics.

The user's next PostgreSQL run after that fixture correction reported **29 passed, 1 failed** at the final task-status assertion: resume deletion returned the expected revision 2, but the test expected the extraction task GET to return 404 and got 200. This is the intended durable-task contract: owner-scoped GET retains a terminal `CANCELLED` task status; deletion clears `result_data`, `expires_at`, and `payload_ref`, cancels its outbox event, advances the revision, and excludes the old task from active-task discovery. The endpoint returns `404` for missing/other-owner tasks and expired successful extraction results. The integration assertion now checks the retained `CANCELLED` response with `result` and `expires_at` null, verifies active discovery returns null, and checks the persisted row has no result/expiry/input and no chunks remain. An offline serialization check produced that cancelled response. The corrected PostgreSQL suite has not yet been rerun; TCP access is denied in this environment. Backend collection successfully collected **112 tests** with the explicit disposable URL set; collection is not execution.

The earlier foundation suite result of **30 passed in 0.70s** was reported by the user after a missing test import was fixed. That result predates this integration and does not verify these new routes, migration, workers, or frontend lifecycle. The Docker socket is unavailable, so Compose startup and model-backed worker execution were not verified. Live Google sign-in and cloud deployment were not tested.

For the migration and integrated disposable-PostgreSQL run commands, see [the local async processing runbook](../docs/LOCAL_ASYNC_PROCESSING.md).

**Later user-reported PostgreSQL verification (2026-10-02):** against the isolated `inf2006-cloud-test-db-55433` disposable PostgreSQL database on `127.0.0.1:55433`, the migration followed by `test_api_integration_disposable.py`, `test_task_recovery.py`, and `test_outbox.py` reported **31 passed, 2 warnings in 1.49s**. The warnings were Starlette's `httpx` deprecation and AnyIO's `BlockingPortal` alias. The coding agent could not connect to this host because local TCP was denied, so this result remains user-reported. It covers those named DB tests only, not model-backed processing, Compose startup, Google sign-in, or cloud behavior.
