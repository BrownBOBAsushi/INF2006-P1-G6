# Full-application baseline — 2026-09-25 (RUN)

Target: the **real running application** at `http://localhost:8080` — nginx SPA/proxy → FastAPI api
(single worker, single processing slot) → PostgreSQL 16 + pgvector → processing child.
Git commit `a46af8ede2d940b3a50ad4ca5d8a7787879942ca` (branch `dev`). Raw data:
`baseline-2026-09-25-fullapp.json` and the `baseline-2026-09-25-fullapp/` directory.

> **Scope.** These are **full-application** numbers over real HTTP with authentication, the nginx
> proxy, the database and the processing slot in the path. They are **distinct** from the
> component / reference-harness figures under `tests/load/` (`harness_app.py`, and `run.py`'s
> `matching-*` / `embedding-throughput` / `db-ranking-scale` scenarios), which measure isolated
> pieces with no auth/proxy and were **not** re-run here.

## Docker access

`docker ps` succeeded immediately in this session; `docker exec`, `docker stats` and `docker cp`
all worked with **no permission-denied** on `/Users/desmondchyezhihao/.docker/run/docker.sock`.
This differs from the prior Codex session (denied), so no scoped-permission escalation was needed.
The prior `baseline-2026-09-25-availability.*` and `-resume-attempt.json` records have been
annotated to reflect that access is now available and the baseline has been run.

## Environment

- Host: macOS 26.5.2 (25F84), arm64, 10 logical CPUs, 32 GiB RAM.
- Docker: client/server 29.8.0; Docker VM 10 CPUs, ~7.75 GiB.
- api: FastAPI 0.141.1 / uvicorn 0.53.0 / Python 3.11.16. `APP_ENV=development`, `APP_ORIGIN=http://localhost:8080`.
- Load driver: `baseline-2026-09-25-fullapp/http_load.py` — **pure Python 3.14.6 stdlib** on the host
  (no numpy/httpx; nothing installed; `tests/load/*` untouched and unimported).
- Container `inf2006-p1-g6-test-db-1` is an **unrelated** test DB (from `docker-compose.dev.yml`) and is
  excluded from the app-under-test figures.

## Reproduce

```bash
# 0. verify daemon + app
docker ps
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8080/health/ready      # 200 {"status":"ready"}

# 1. mint 10 ISOLATED synthetic accounts+sessions (runs inside the api container; existing data untouched)
docker cp evidence/baseline-2026-09-25-fullapp/make_sessions.py inf2006-p1-g6-api-1:/tmp/make_sessions.py
docker exec -e PYTHONPATH=/app inf2006-p1-g6-api-1 python /tmp/make_sessions.py create 10 \
  > evidence/baseline-2026-09-25-fullapp/sessions.json

# 2. run the full-app HTTP baseline (1/5/10 users, 15 s/level, both endpoints), sampling docker stats alongside
cd evidence/baseline-2026-09-25-fullapp
( for i in $(seq 1 160); do docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' \
    | sed "s/^/$(date +%s) /"; done ) > stats_active_raw.txt 2>&1 &
python3 http_load.py --base-url http://localhost:8080 --sessions sessions.json \
  --pdf ../../tests/fixtures/pdf/resume_P01.pdf --duration 15 --concurrency 1 5 10 \
  --endpoints browse prepare --out results.json
kill %1 2>/dev/null

# 3. clean up synthetic accounts (CASCADE deletes their sessions)
docker exec -e PYTHONPATH=/app inf2006-p1-g6-api-1 python /tmp/make_sessions.py delete
```

Each concurrency level is a 15 s closed loop of *C* threads; worker *i* uses a distinct synthetic
session (`session[i % 10]`). Idle stats were taken with no load; active stats were sampled during the run.

## CPU / RAM

Docker per-container CPU% (100% = 1 core; host has 10). RAM is stable throughout.

| Phase | api CPU% (mean / peak) | api RAM (MiB, peak) | db CPU% (mean/peak) | web CPU% (mean/peak) |
|---|---|---|---|---|
| **Idle** (no load) | 0.3 / 0.3 | 566 | 0.0 / 0.7 | 0.0 / 0.0 |
| **Browse load** (1/5/10) | 114.7 / 153.9 | 613 | 16.2 / 22.0 | 3.0 / 3.6 |
| **Prepare load** (1/5/10) | 176.8 / 238.4 | 622 | 16.1 / 36.1 | 21.4 / 53.3 |

The api container is CPU-bound under the closed-loop generator and is effectively saturated
(peak ≈ 2.4 cores); these are the **throughput-ceiling** figures, not steady per-user cost. RAM
barely moves (566 → 622 MiB), so memory is not a constraint at this scale.

## Latency / throughput / errors / busy rejections

### Browse — `GET /api/jobs?limit=20` (authenticated catalogue read, 30 jobs)

| Concurrent users | Throughput (ok/s) | p50 (ms) | p95 (ms) | Errors | Busy 503 |
|---|---|---|---|---|---|
| 1  | 277.1 | 3.5  | 4.0  | 0 | 0 |
| 5  | 307.0 | 15.9 | 20.1 | 0 | 0 |
| 10 | 255.7 | 38.4 | 51.0 | 0 | 0 |

Browse scales cleanly with no rejections; latency rises with contention as the single api worker
saturates, throughput plateaus around ~300 req/s.

### Prepare — `POST /api/resume/prepare` (multipart PDF → single processing slot)

| Concurrent users | Admitted ok/s | ok p50 (ms) | ok p95 (ms) | Busy 503 | Busy rate | Busy p50/p95 (ms) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|
| 1  | 15.2 | 62.8 | 71.2  | 0    | 0.0%  | –        | 0 | 0 |
| 5  | 12.5 | 81.3 | 103.4 | 8546 | 97.9% | 6.5 / 9.5   | 0 | 0 |
| 10 | 11.4 | 99.0 | 125.3 | 7622 | 97.8% | 16.1 / 26.2 | 0 | 0 |

The processing slot admits **one** prepare at a time (per `ProcessingService`); concurrent excess is
**fast-rejected** with `503 PROCESSING_BUSY` (busy p50 6.5–16 ms) rather than queued. Across all
prepare load there were **zero errors and zero timeouts** — the busy responses are the designed
controlled backpressure, not failures. (`prepare` on this fixture is PDF-parse + PII/NER draft only,
~60 ms; it does not embed or write persistent data — embedding happens on `save`.)

## Data safety

10 synthetic `User`+`Session` rows were created (google_sub prefix
`loadtest-synthetic-baseline-2026-09-25:`) and deleted after the run. Existing data verified
unchanged before and after: `users=1`, `sessions=3`, `resume_profiles=1`, `resume_chunks=11`,
`jobs=30`. No application code or configuration was changed; nothing was committed.
