# Durable task foundation — 2026-10-02

**Result:** Local schema and lifecycle primitives are implemented. Offline contract checks and PostgreSQL migration SQL generation passed. PostgreSQL runtime/concurrency tests were authored but not executed: Docker access is denied in this environment and no local PostgreSQL server is available. No application lifecycle, API, worker, AWS resource, or Google sign-in behavior was verified by this milestone.

## Commands and observed results

From repository root:

```sh
PYTHONPATH=src/backend src/backend/.venv/bin/python -m pytest tests/backend/test_task_contracts.py -q
```

Expected/actual before review repair: 9 offline contract tests passed. These check safe task inputs/failure codes and schema metadata; they do not prove SQL locking or database transitions.

```sh
DATABASE_URL=postgresql+psycopg://synthetic:synthetic@localhost/synthetic PYTHONPATH=src/backend src/backend/.venv/bin/alembic -c src/backend/alembic.ini upgrade head --sql
```

Expected/actual: Alembic generated PostgreSQL DDL through revision `6a2fd7b41c90`, including task/outbox tables, foreign keys, uniqueness, checks and due indexes. `--sql` does not connect to or mutate a database and is not migration runtime proof.

```sh
PYTHONPATH=src/backend src/backend/.venv/bin/python -m pytest tests/backend/test_task_contracts.py tests/backend/test_task_recovery.py tests/backend/test_outbox.py -q
```

After review-cycle-1 repairs, the combined command was run again and produced **10 passed, 2 skipped**. The additional offline SQLite check exercises the production identity-map refresh helpers only; SQLite does not implement PostgreSQL row locks. The task-recovery and outbox PostgreSQL integration modules skip unless `DISPOSABLE_DATABASE_URL` is explicitly set to an isolated PostgreSQL test database and `DATABASE_URL` is equal to it. Actual database integration, two-session claim concurrency, retry transitions, cancellation lock waits, cascade deletion, and crash-window behavior remain unverified here. Do not substitute SQLite for these checks.

The focused API helper/Google diagnostic tests were rerun after the review repair with:

```sh
DATABASE_URL=postgresql+psycopg://test:test@localhost:1/test APP_ORIGIN=http://localhost:8080 GOOGLE_CLIENT_ID=synthetic-client APP_SIGNING_KEY=synthetic-test-key PYTHONPATH=src/backend src/backend/.venv/bin/python -m pytest tests/backend/test_google_verify_diagnostics.py tests/backend/test_backend_contract_helpers.py tests/backend/test_api_boundary_helpers.py -q
```

Observed: 22 passed in 0.39s. The database URL targets an unreachable local port and those tests do not verify live Google sign-in; localhost:8080 was separately observed offline. Google live status remains unverified.

The earlier RED collection run of the new integration modules failed because `ProcessingTask` and `OutboxEvent` did not yet exist; it was a test-first check, not an acceptance result.

Review cycle 1 found stale SQLAlchemy identity-map reads could authorize obsolete task/outbox transitions, cancellation could skip locked tasks, and one test reused a mutable ORM alias as its old lease snapshot. Locked reads now flush caller changes then refresh existing ORM objects, completion/deletion use User-to-task-to-outbox lock order, and cancellation waits instead of skipping. PostgreSQL regressions cover stale cached claims/tokens and a cancellation lock wait. The corresponding tests were authored but could not run without PostgreSQL.

Review cycle 2 found production time was sampled before potentially blocking row locks. Lease decisions now use the production clock after the relevant locks are acquired; explicitly supplied `now` values remain fixed test clocks. An executed fake-session test advances the clock during User-lock acquisition and confirms expired work cannot complete. The outbox test fixture's fourth yielded value is now unpacked. Final focused result after these repairs: `11 passed, 2 skipped`; the skipped modules are still PostgreSQL-only integration tests, so database locking/cancellation acceptance remains open.

The final review then found `claim_outbox_batch` used the post-query `timestamp` while building its pre-query eligibility filter. The filter now consistently uses `query_time`; the post-lock `timestamp` still sets the claimed lease expiry. A direct fake-session test executes the production batch function for both empty and one-event results, advances the clock during selection, and confirms the lease uses post-query time. Final focused command now reports **13 passed, 2 skipped**. `py_compile` for the touched Python modules/tests and `git diff --check` also pass. PostgreSQL-only integration remains skipped and unverified.

**Final scoped review (2026-10-02): PASS-WITH-CONCERNS.** The fresh reviewer independently reproduced `13 passed, 2 skipped` and clean whitespace checks. No blocker remains in the authorized local foundation scope. PostgreSQL concurrent claims, row-lock waits, and migration execution against a live disposable database remain unverified; the two skipped modules and offline migration generation are not runtime database proof. No application or cloud behavior is claimed by this result.

**Earlier user-reported disposable PostgreSQL run (2026-10-02):** `29 passed, 1 failed`. The failure was `tests/backend/test_task_recovery.py::test_cancellation_waits_for_claimed_task_then_cancels_it`, where `cancel_owner_tasks` was not imported at module scope. The missing test import was fixed, then the suite was rerun as recorded below.

**Later user-reported rerun (2026-10-02):** after the import fix, the disposable PostgreSQL foundation suite completed with **30 passed in 0.70s**. This verifies the foundation tests as reported by the user, but predates and does not cover the subsequently integrated API routes, detached local workers, temporary result migration, or frontend lifecycle. Those integration checks are recorded separately in [local async processing evidence](local-async-processing-2026-10-02.md).

## Boundaries

The added primitives are not wired into `/api/resume/prepare`, save, delete, startup recovery, a local worker, or a publisher. The API still has global `PROCESSING` save recovery on startup and still starts the process-wide processing child; that startup behavior blocks API scale-out. The frontend remains on synchronous request completion. AWS target status remains proposed, and Google sign-in status remains unverified. See [the implementation plan](../docs/superpowers/plans/2026-10-02-durable-task-foundation.md) for integration gates.
