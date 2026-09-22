# Load tests

Owner: Chuying. Synthetic data only. Runner: `run.py` (see its docstring). Dated results are written to `../../evidence/load-matching-*.md/.json`.

```bash
python tests/load/run.py --scenario all --out-dir evidence      # full grid (several minutes)
python tests/load/run.py --scenario all --quick                  # smaller grid, smoke test
```

Implemented (measured, local machine): `matching-scale` (jobs x requirements x chunks, exact in-memory matcher),
`matching-concurrency` (1/5/10/25 in-process threads), `embedding-throughput` (real MiniLM on CPU), `db-ranking-scale`
(real PostgreSQL + pgvector ranking query up to 10,000 jobs).

**HTTP scenarios** (`api-concurrency`, `browse-during-processing`; `api` runs both), implemented in `api_load.py` and started by `run.py`:

```bash
python tests/load/run.py --scenario api --target harness --out-dir evidence     # reference harness (NOT the project's API)
python tests/load/run.py --scenario api --target http://127.0.0.1:8000 --cookie NAME=VALUE --csrf-token T --origin O   # real API
```

- `--target harness` starts `harness_app.py`: a throwaway FastAPI app that puts the real `ProcessingService` behind `POST /api/resume/prepare`,
  `GET /api/jobs` and `/health/*`. It has no auth, CSRF or database, so its numbers describe the slot and child over HTTP, **not Jiaxin's API**.
- Against a real API the script probes `/openapi.json` first and exits with status 3 (**NOT RUN**, no numbers) unless `POST /api/resume/prepare`,
  `GET /api/jobs` and `GET /health/ready` exist and a test session was supplied; it cannot perform Google sign-in.
- With no `--target` (and no `$LOAD_BASE_URL`) the HTTP scenarios exit 3 with NOT RUN.
- A 503 `PROCESSING_BUSY` is counted as a controlled rejection, not throughput.

**Not covered:** the real API (its routes do not exist yet), authentication cost, database cost under HTTP load, and anything on AWS.
