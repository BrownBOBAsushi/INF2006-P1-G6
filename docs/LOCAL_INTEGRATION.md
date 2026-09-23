# Local integration runbook

The supported localhost shape is one browser origin at `http://localhost:8080`:
the `web` container serves the built React app and proxies `/api` to one FastAPI
worker. PostgreSQL/pgvector is private to the Compose network and uses the named
`db_data` volume. The API image installs the pinned processing environment,
downloads the pinned MiniLM and spaCy assets during image build, and runs its
processing child offline.

Real Google login requires a public web client ID whose authorised JavaScript
origin is `http://localhost:8080`. Leave the example placeholder in place until
that client is configured. No Google credential belongs in the repository.

## Clean start

```sh
cp src/.env.example src/.env
# Edit src/.env: generate APP_SIGNING_KEY and set the public GOOGLE_CLIENT_ID.
docker compose --env-file src/.env build
docker compose --env-file src/.env up -d
docker compose --env-file src/.env ps
curl -fsS http://localhost:8080/health/live
```

The first image build needs network access to the pinned Python packages and
model assets. At runtime the API does not download models. `api` runs
`alembic upgrade head` before uvicorn starts; Compose waits for database health,
then API readiness before starting `web`. The browser API client has a 100
second deadline, while nginx allows 90 seconds for API reads and the backend
processing slot allows 60 seconds. Multipart requests are capped at 6 MiB by
nginx and the backend; PDFs are capped at 5 MiB and JSON at 256 KiB.

## Explicit synthetic catalogue import

This uses the real database importer and embeddings pipeline with the checked-in
synthetic catalogue. It does not call a live provider and is labelled synthetic.

```sh
docker compose --env-file src/.env run --rm \
  -v "$PWD/data/synthetic_jobs.json:/tmp/synthetic_jobs.json:ro" \
  api python -m app.catalogue.import_jobs --file /tmp/synthetic_jobs.json --dry-run
docker compose --env-file src/.env run --rm \
  -v "$PWD/data/synthetic_jobs.json:/tmp/synthetic_jobs.json:ro" \
  api python -m app.catalogue.import_jobs --file /tmp/synthetic_jobs.json
```

The dry run writes nothing. The real import is an explicit maintenance action;
it validates the whole batch before writing and increments the catalogue
revision only after a successful import.

## Local checks and stop

```sh
(cd src/frontend && npm run test -- --run)
(cd src/frontend && npm run typecheck)
(cd src/frontend && npm run build)
docker compose -f docker-compose.dev.yml --profile test run --rm backend-tests
docker compose -f docker-compose.dev.yml --profile test down
docker compose --env-file src/.env exec api alembic check
docker compose --env-file src/.env down
```

The test profile mounts `tests/backend` read-only into a separate test runner
and uses a temporary pgvector database, so its destructive migration tests
cannot touch the persistent application database. `docker compose down` keeps `db_data`, so sessions, resume content and imported
jobs remain available for the next start. To intentionally remove this local
database, inspect the target first and run `docker compose down -v`; this is a
separate destructive reset and is never part of clean stop.

The local gate remains pending until these commands are run on a host with
Docker, package/model access, an isolated database, and the configured Google
origin. A passing frontend suite alone does not establish real API or Google
acceptance.

## Evidence status

Recorded checks for this snapshot are separated from the acceptance gate:

- The frontend harness ran with `envDir:false`: 17 files and 198 tests passed;
  TypeScript and the production build passed. Four HTTP loopback tests remain
  excluded because the host returned `listenEPERM`. The bundled Node runtime was
  24.19.0 while the project declares Node 24.21.0.
- Production and development Compose files parse successfully. The Docker image
  build, model predownload, disposable test profile, full PostgreSQL run,
  localhost browser flow, Google login and load checks were not run because the
  host Docker socket and external package/model access are unavailable.
- Focused backend checks recorded 30 passed and 3 skipped where pgvector or a
  database was unavailable. Forty PDF fixture/extraction checks passed under an
  alternate cached runtime; that runtime is not evidence for the pinned
  production image.

## Development mode

Use `docker-compose.dev.yml` only for bind-mounted API reload and loopback API
port access. It does not replace the production-style single-origin check:

```sh
docker compose -f docker-compose.dev.yml up --build
cd src/frontend && npm run dev
```

The development Vite server proxies `/api` to `127.0.0.1:8000`; it still has no
fixture fallback in normal `npm run dev` mode.
