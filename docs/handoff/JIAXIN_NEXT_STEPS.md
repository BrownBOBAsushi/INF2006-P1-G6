# Jiaxin: next steps

## Baseline and current direction

This handoff is for the `jiaxin` branch at baseline `9fd47f5e85c2e74713c51474ee4f2c4de0837e7f`. Direction is right; the foundation is partial. The repository has a PostgreSQL/pgvector Compose service with a named volume and loopback development ports, one FastAPI process, Alembic wiring, four initial tables (`users`, `resume_profiles`, `sessions`, and `resume_chunks`), and `/health/live` plus `/health/ready`. The migration enables pgvector and declares 384-dimensional resume embeddings.

Recorded baseline checks show Python syntax and Compose YAML validation passing. Docker runtime attempts hit a local permission error, and dependency installation hit PyPI DNS resolution failure. No runtime startup, migration, health, or model-readiness result has been established.

Use [DATA_API_CONTRACT.md](DATA_API_CONTRACT.md) as the contract and [TEAM_PROMPTS.md](TEAM_PROMPTS.md) for ownership boundaries. Keep work local and synthetic. Do not provision AWS, add credentials, or claim completion from static checks.

## Fixes to make before safe saves

1. Align configuration with the actual driver and Compose location. Compose reads the repository-root `./.env`, while `src/.env.example` currently omits the database container variables. Document a root `.env` containing `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, and the matching `DATABASE_URL` in `src/backend/README.md` and the root startup instructions. Use the psycopg 3 URL form, `postgresql+psycopg://...`, in the supplied example and startup instructions. Keep values as local placeholders and never commit `.env`.

2. Make readiness prove the service it names. The current `/health/ready` only runs `SELECT 1`, so it can return 200 before Alembic has created the schema. Add an explicit migration/schema check and confirm the `vector` extension and expected vector dimension. Coordinate the model-cache/readiness portion with Chuying once the processing interface and pinned model are available; do not invent a second model-loading path.

3. Align models and migrations with the contract. Use timezone-aware columns that produce PostgreSQL `timestamptz`; add database default `0` for `users.resume_revision` (the Python default alone is insufficient); add indexes on `sessions.user_id` and `sessions.expires_at`; and declare the existing `resume_chunks.user_id` index in SQLAlchemy metadata as well as in the migration. Remove duplicate `alembic` and pin dependencies after verifying the local image. If the baseline migration is already applied, use a new forward migration; do not edit applied history.

4. Add backend smoke tests covering configuration, live/ready status, migration idempotency, and the schema invariants above. There are currently no backend test files, so a green import or syntax check is not application evidence. A separator/formatting repair in [TEAM_CONTRIBUTIONS.md](../../TEAM_CONTRIBUTIONS.md) is a small documentation cleanup and can be handled alongside this batch.

Add the `save_operations` support table from the contract before implementing PUT resume saves. It stores only operation metadata and is required for durable idempotency and unknown-outcome recovery. The remaining `jobs`, `job_requirements`, `requirement_embeddings`, and `app_state` tables are the next catalogue/matching work to coordinate with Chuying; their absence from this foundation is upcoming scope, not a defect to describe as already broken.

## Recommended implementation sequence

First prove the foundation with an isolated Compose project and new named volume. After configuration fixes and documenting startup commands in `src/backend/README.md`, propose:

```text
docker compose -p inf2006-jiaxin-check config --quiet
docker compose -p inf2006-jiaxin-check up -d db api
docker compose -p inf2006-jiaxin-check exec api alembic upgrade head
docker compose -p inf2006-jiaxin-check exec api alembic upgrade head
curl -i http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
```

Record actual commands and results only after they run. The project name isolates the volume, but fixed loopback mappings can collide with ports 5432 or 8000 already in use. Use free loopback host ports or ensure these are unused; do not disrupt unrelated services. Inspect `alembic_version`, the `vector` extension, `vector(384)`, timestamp types/defaults, and required indexes. Stop and restart the database without removing its volume, then verify schema state persists. Exercise readiness with dependency failure and recovery: expect 503 while unavailable and 200 after recovery, without internal details.

After this gate, implement Google bootstrap, verified login, PostgreSQL sessions, CSRF, `/api/me`, and logout. Then integrate revision-checked, idempotent resume saves with Chuying’s processing/vector pipeline: stale revisions must conflict, identical canonical content must be a no-op, and uncertain commits must be resolved through operation status. Coordinate API shapes and CSRF handling with Xue E and Nasya as their frontend flows connect.
