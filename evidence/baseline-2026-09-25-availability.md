> **STATUS CORRECTED 2026-09-25 (later session).** A subsequent session **gained Docker access**
> (`docker ps`/`exec`/`stats` all succeeded, no permission-denied) and the application at
> `localhost:8080` was **up and reachable** (it was simply not running at the time of the probes
> below). The full-application baseline has now been **RUN** — see `baseline-2026-09-25-fullapp.md`
> / `.json`. The "NOT RUN" / "connection refused" / "permission denied" findings recorded below
> were accurate for that earlier attempt but are **superseded**.

# Baseline attempt — 2026-09-25

Target: the real application at `http://localhost:8080/` in this checkout. Raw probe results and host details are in `baseline-2026-09-25-availability.json`. Git commit: `a46af8ede2d940b3a50ad4ca5d8a7787879942ca`.

## Reproduce the availability checks

```bash
docker info --format '{{.ServerVersion}}'
curl -sS -o /dev/null -w '%{http_code} %{time_total}\n' http://localhost:8080/
.venv/bin/python -c 'import numpy,psutil,httpx'
```

Docker API access returned `permission denied` for the user Docker socket, including a scoped escalated retry. The localhost request returned connection refused (`curl` exit 7, HTTP 000). The repository virtual environment lacks `numpy`, so its load runner cannot start there.

## Measurement status

| Metric | Real application result |
| --- | --- |
| Idle CPU and RAM | Not measured: application containers inaccessible |
| Active CPU and RAM | Not measured: no live application target |
| p50/p95 latency, successful throughput, errors, busy rejections at 1, 5, 10 concurrent users | Not measured: no live application target or isolated authenticated sessions |

`tests/load/api_load.py` targets `POST /api/resume/prepare`, `GET /api/jobs`, and `GET /health/ready`. Its `harness` target starts `tests/load/harness_app.py`, which omits application authentication, CSRF, and database work. Prior `load-api-harness-2026-09-21-api.*` figures are component/reference-harness results, not full application baseline figures. The existing runner's quick mode also omits 10 users, and its regular mode includes 25 users. It needs a bounded 1/5/10 configuration and isolated test sessions before use against the real application.

No synthetic accounts or resumes were created. Existing user data was not touched. No application behaviour or load script was changed.

## Resume attempt, 09:35 UTC

The new session first ran `docker ps`, then retried it through the built-in scoped permission flow. Both calls returned the same Docker socket `permission denied` error. `docker context show` returned `desktop-linux`, but that does not establish daemon access. Both `/` and `/openapi.json` at `localhost:8080` returned curl exit 7, HTTP 000. The application baseline remains **NOT RUN**. The raw commands and results are in `baseline-2026-09-25-resume-attempt.json`.
