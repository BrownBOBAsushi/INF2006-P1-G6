# Local automated test run — 2026-10-03

**Executed by:** Claude Code (AI agent) on the operator's macOS workstation, at the operator's request.
**Source:** branch `codex/cloud-task-foundation`, HEAD `6b48744` plus uncommitted documentation changes (no application source changes).
**Environment:** offline; no cloud resources used. Model weights read from the local Hugging Face cache (`HF_HUB_OFFLINE=1`).
**Raw output:** `evidence/local-tests-2026-10-03/*.log` (hostnames and local paths redacted).

| Suite | Command (from repository root unless stated) | Started (UTC) | Result |
|---|---|---|---|
| Infrastructure contracts | `python3 -m unittest discover -s tests/infra -p 'test_*.py'` | 07:16:27 | **63 tests OK** |
| Backend API, auth/CSRF, migrations, schema, tasks/outbox | `docker compose -f docker-compose.dev.yml --profile test build backend-tests` then `... run --rm backend-tests` (disposable pgvector DB) | 07:20:45 | **133 passed** |
| Frontend | `cd src/frontend && npm run typecheck && npm test && npm run build` | 07:16:40 | typecheck clean; **223 passed (18 files)**; production build succeeded |
| Analytics unit tests | `analytics/.venv/bin/python -m pytest tests/analytics -q` | 07:16:40 | **16 passed** |
| Data/AI evaluation reproduction | `analytics/.venv/bin/python analytics/evaluate.py --fixtures data/evaluation --out-dir <dir>` | 07:16:46 | Completed; held-out MiniLM results identical to the 2026-09-20 record (requirement-level 0.640 / 0.760 / 0.922). Output: `data-ai-eval-2026-10-03.{md,json}` |
| Processing pipeline | `cd src/backend && HF_HUB_OFFLINE=1 .venv/bin/python -m pytest ../../tests/pipeline -q` | 07:20:55 | **216 passed, 1 failed, 3 errors** (see below) |

## Failures and diagnosis

1. **Stale backend test image (resolved during the run).** The first backend run at 07:16:40 failed collection with 9
   import errors (`OutboxEvent`, `ProcessingTask`, `app.processing.local_worker`, `aws_storage`, `local_storage`).
   The `inf2006-p1-g6-backend-tests` image was 10 days old and predated commit `1f454d0`. Rebuilding the image
   (`... build backend-tests`) resolved it: 133 passed. Improvement: document `build` before `run` in
   `tests/backend/README.md`.
2. **Pipeline: 4 tests in `tests/pipeline/test_processing_slot.py` fail.**
   `test_production_deadline_kills_real_work_and_the_service_recovers` (failed) and three
   `test_production_*` tests (errors) construct `ProcessingService()` without `worker_args`. Since commit `1f454d0`,
   the production child entry point is `production_main(conn, kind)` and production code passes the worker kind
   (`src/backend/app/processing/local_worker.py:395`: `ProcessingService(worker_args=(self.kind,))`). The child
   therefore exits with `TypeError: production_main() missing 1 required positional argument: 'kind'`, surfacing as
   `SERVICE_UNAVAILABLE:child_start_failed:pipe_closed`. This is test drift after the async split (extraction and
   embedding now run in separate children), not a defect in the production call path. `tests/load/harness_app.py:45`
   has the same stale default. Improvement: update these tests to construct one service per kind
   (`EXTRACTION` for prepare, `EMBEDDING` for save/embeddings) and rerun.

## Not covered by this run

- No browser end-to-end run, no Google sign-in, no load test, no cloud call.
- The pipeline suite was not re-run after any fix; the 4 failures remain open.
