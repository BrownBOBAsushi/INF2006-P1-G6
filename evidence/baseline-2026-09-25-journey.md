# Resume-to-matches journey baseline — 2026-09-25

Full end-to-end journey and concurrent-burst measurements against the **real running application**
at `http://localhost:8080` (nginx SPA/proxy → FastAPI api, single worker + single processing slot →
PostgreSQL 16 + pgvector → spawned embedding child). Purpose: reliable local metrics to inform a
simple, justified AWS architecture. Nothing in the app was changed or optimised.

Raw data and scripts: `evidence/baseline-2026-09-25-journey/` (`run_baseline.sh` orchestrates;
`journey_load.py` drives; `analyze.py` → `analysis.json`; `stats_raw.txt`, `results_*.json`,
`timeline_*.json`, `integrity_*.txt`).

## What was measured, and how it differs from HTTP-200 counting

Each client runs the **actual contract**: `POST /api/resume/prepare` (multipart PDF) → `PUT /api/resume`
(save: privacy re-check + chunking + MiniLM embedding + persistence, idempotent via `Idempotency-Key`)
→ `GET /api/resume` (reload) → `GET /api/matches`. Success is **not** HTTP 200: every response is
schema-checked; `save` must report `changed=true` and `result_revision=expected+1`; `reload` must
match the saved revision, be `has_matchable_resume=true`, and its content must equal the saved content
by **canonical hash** (round-trip); `matches` must return `total>0` with a non-empty `closest_passage`.
A separate DB read confirmed persisted **384-dim non-null embeddings** (124 chunks over the last
burst's synthetic users). Assertion failures are tracked separately from HTTP/transport errors —
**there were none of either** in any completed journey.

### Environment
- Git HEAD `0e8067a` (dev). **Running image code verified byte-identical to on-disk `src/backend`**
  (sha256 over all `app/**/*.py`); images built 2026-09-23, HEAD adds only docs since. api image
  `sha256:6ef666…`, web `sha256:2adbfc…`, db `pgvector/pgvector:pg16`.
- api: FastAPI 0.141.1 / uvicorn 0.53.0 / Python 3.11.16, **single worker, single processing slot**.
- Host macOS 26.5.2 arm64, 10 logical CPUs, 32 GiB. Docker 29.8.0; Docker VM 10 CPUs / ~7.75 GiB.
- Catalogue: **30 active jobs, 95 requirements, 110 requirement embeddings**, revision 1. DB ~8.9 MB
  (→9.6 MB under load with synthetic rows; tables tiny: jobs 104 kB, req-embeddings 304 kB).
- Caches **warm** (containers up ~2 days, model resident, catalogue page-cached). Warm-up journeys
  (3 sequential, 2 per burst) discarded before the 3 measured rounds.

### Retry policy (test runner — distinct from the frontend)
Retryable transient codes (`PROCESSING_BUSY`, `SERVICE_UNAVAILABLE`, `PROCESSING_TIMEOUT`,
`SAVE_IN_PROGRESS`) honour `Retry-After` (server sends `3` for busy) else full-jitter exponential
backoff (base 0.25 s, ×2, cap 3 s), **max 8 attempts / 60 s**. Saves retry with the **same
Idempotency-Key** (idempotent per the contract: a busy request creates no operation row;
`SAVE_IN_PROGRESS`/timeout replay). `REVIEW_REQUIRED` is handled as a **confirmation** (resubmit the
returned cleaned draft under a new key), never a blind retry; deterministic validation errors are
never retried. The current frontend surfaces backoff to the user and does not tight-poll; this runner
policy is a stand-in, reported explicitly so it is not mistaken for server behaviour.

## 1. Compact results

Per-step figures are the **service latency of the successful attempt** (exclude client backoff).
Whole-journey **includes** all retries and waiting. Percentiles on small n are noted; treat p95 as
indicative, not tight.

| Scenario (n journeys) | Eventual success | First-attempt success | Busy-503 / retries | Timeouts / errors / assert-fails | prepare p50/p95 | save p50/p95 | reload p50/p95 | matches p50/p95 | **Whole-journey p50 / p95 / max** | Concurrent browse |
|---|---|---|---|---|---|---|---|---|---|---|
| **Sequential 1-user** (n=45) | 45/45 (100%) | 45/45 (100%) | 0 / 0 | 0 / 0 / 0 | 64 / 160 ms | 106 / 308 ms | 3 / 5 ms | 8 / 11 ms | **181 / 477 / 501 ms** | — |
| **Burst of 5** (n=15) | 15/15 (100%) | 3/15 (20%) | 30 / 30 | 0 / 0 / 0 | 73 / 109 ms | 107 / 205 ms | 3 / 5 ms | 8 / 12 ms | **6.21 / 12.35 / 12.57 s** | 2272 req, **100% ok**, p50 8.5 / p95 18 ms |
| **Burst of 10** (n=30) | 24/30 (80%) | 3/30 (10%) | 132 / 126 | 0 / 0 / 0 | 75 / 242 ms | 107 / 317 ms | 3 / 9 ms | 8 / 17 ms | **10.77 / 21.38 / 21.75 s** | 3900 req, **100% ok**, p50 9.7 / p95 18.5 ms |

- **Single-thread journey throughput ≈ 4.6 completed/s** (45 journeys in 9.8 s back-to-back).
- Under bursts, achieved **completed/s falls to ~0.4** — not because the server got slower (per-step
  latency held ~100 ms) but because clients **serialise on one slot and wait** through `Retry-After`.
- Burst-10's **6 incomplete journeys all failed at `prepare` with `503 PROCESSING_BUSY`** after
  exhausting the runner's 8-attempt budget. These are **app-returned controlled rejections, not
  errors or data faults**; a more patient client/frontend would eventually complete them.
- **No `PROCESSING_TIMEOUT`, no unexpected errors, no assertion failures** in any run; every completed
  journey persisted correct embeddings and returned meaningful matches.

### Resources (docker stats, 2 s median interval, 0 missing-sample gaps)
CPU% is per-container (100% = 1 core; host has 10). **Simultaneous total app memory** is the peak of
the per-timestamp sum of api+db+web (never a sum of independent peaks).

| Phase | api CPU mean/peak | api mem peak | db CPU mean/peak | web CPU mean/peak | **Simultaneous app-mem peak** |
|---|---|---|---|---|---|
| Idle (no load) | 0.2% / 0.2% | 620 MiB | 0.6% / 3.5% | 0.0% | **667.5 MiB** |
| Sequential | 73–97% / 97% | 628 MiB | ~2% / 3% | 0.3% | 682 MiB |
| Burst of 5 | ~34% / 68% | 619 MiB | ~5% / 6.5% | 1.0% | 672 MiB |
| Burst of 10 | ~32% / 68% | 632 MiB | ~5% / 7.9% | 1.1% | **686 MiB** |

CPU-sample counts are small for sequential rounds (1–2 samples/round at 2 s cadence over ~3 s rounds);
burst rounds have 8–14 samples each. Memory is stable throughout (~667→686 MiB simultaneous).

## 2. Observed bottlenecks (with evidence)

1. **The single global processing slot is the sole scaling limit.** `ProcessingService` admits exactly
   one operation at a time and `prepare` **and** `save` both go through it (`app/processing/slot.py`).
   Evidence: sequential runs never see a busy (0/45) and complete in ~181 ms; the moment 5 or 10
   clients start together, 30 and 132 `503 PROCESSING_BUSY` appear and whole-journey time jumps to
   6–21 s while **per-step service latency stays ~100 ms**. Concurrency adds waiting, not work.
2. **CPU does not rise with concurrency — it falls.** api CPU mean is ~95% under back-to-back
   sequential load but only ~32% under bursts, because the extra clients are blocked in backoff while
   one slot does the work. This is direct evidence that the ceiling is the **serialised slot**, not
   raw CPU. (Per the brief, we do **not** infer saturation from CPU% alone; here the busy-rejection
   counts are the primary evidence and CPU corroborates.)
3. **`save` (embedding) is the heaviest step**, ~106 ms p50 vs ~64 ms `prepare`; `reload` and
   `matches` are cheap (3–8 ms p50) because the catalogue is tiny (30 jobs) and pgvector search is
   trivial at this size. So today's cost is CPU-bound model inference in the child, not the database.
4. **Browsing is fully isolated from processing.** `GET /api/jobs` never touches the slot; it stayed
   **100% successful (0 failures in 6,172 requests)** at p50 ≈ 9 ms / p95 ≈ 18 ms even during the
   10-client burst. Read traffic and processing do not contend today.

## 3. Limitations and blocked measurements

- **HTTP automation only.** Excludes browser rendering / SPA JS, human editing and privacy-review
  reading time, and Google OAuth (synthetic sessions were injected directly into the DB). Real
  wall-clock per user will be longer (human time dominates).
- **Warm, single-node, single-worker.** Models were resident and the DB was ~9 MB and page-cached;
  a cold start (model load) is not measured here (child startup budget is 180 s per `slot.py`).
  Only one uvicorn worker and one processing slot were running.
- **Small samples / tiny catalogue.** n = 15 (burst-5) and 24 completed (burst-10); p95 is indicative.
  Matching latency at 30 jobs says little about matching at thousands — **not** measured.
- **Whole-journey burst times are inflated by the runner's `Retry-After`=3 s backoff**, a client-policy
  artefact; they are the *user-perceived* time under this policy, not server processing time.
- **Not measured / blocked:** AWS/network latency, cold model load, multi-worker or multi-slot
  scaling, larger catalogues, sustained (non-burst) arrival rates, and disk IOPS under real volume.

## 4. Corrections to the previous report (`baseline-2026-09-25-fullapp.*`)

The earlier committed baseline is **preserved and its measurements stand**, but its scope was narrower
than "the full application journey":

- **It measured only two endpoints** — `GET /api/jobs` (browse) and `POST /api/resume/prepare` — driven
  as isolated closed loops. It **never exercised the complete journey**: no `PUT /api/resume`, so **no
  embedding, no persistence, no reload, and no `/api/matches`** were measured. Its `prepare` latency
  (~60 ms) therefore reflects PDF-parse + PII draft only; **the heavy embedding cost lives in `save`**
  (~106 ms p50, measured here), which that report did not capture.
- **Its "busy rejections" were unsuccessful attempts.** They were correctly separated from unexpected
  errors, but a `503 PROCESSING_BUSY` is a **rejected upload from the user's perspective**, not
  throughput and not a success — it only becomes a success after client retry. The prior phrasing
  ("controlled backpressure, not failures") is accurate about the *server* but should not be read as
  "the request succeeded." This run reports **first-attempt vs eventual success separately** to make
  that explicit (e.g. burst-5: 20% first-attempt, 100% eventual after retries).
- No numbers in the prior report are retracted; this is a scope/interpretation correction only.

## 5. Implications for a single-EC2 candidate, and what still needs AWS testing

**What the data supports for a single EC2 instance:**
- **Memory is a non-issue at this scale**: the whole app (api+db+web) peaks at **~686 MiB simultaneously**
  under load. A small instance (e.g. 2 GiB class) covers memory comfortably; **CPU, not RAM, is the
  constraint.**
- A single instance with today's **one worker + one processing slot** delivers a full journey in
  **~0.18 s warm** and **~4–5 journeys/s** when requests arrive one at a time, with cheap DB/matching.
  For a coursework-scale load of a handful of concurrent uploads, **a single modest EC2 (a few vCPUs)
  is a defensible starting point** — provided uploads are effectively serialised and clients retry on
  `503`/`Retry-After` (the frontend already surfaces backoff).
- The clean split — **browse never contends with processing** — means read traffic scales far better
  than uploads on the same box.

**What must be decided/tested on AWS before committing:**
- **Concurrency strategy for uploads.** One slot means bursts queue behind ~100 ms of real work each,
  and the current UX is client-side retry. On AWS, decide between (a) **more processing slots/workers**
  (needs vCPUs and memory per resident model — ~0.6 GiB and ~1 core of embedding work each), or
  (b) a **queue + async result** pattern. Measure real embedding throughput per vCPU on the target
  instance family (Graviton vs x86) — local arm64 numbers won't transfer directly.
- **Cold start / autoscaling behaviour** (model load ≈ seconds to the 180 s budget) if instances scale
  to zero or scale out.
- **Matching at realistic catalogue size** (thousands of jobs) — pgvector exact search cost and whether
  an ANN index / managed Postgres (RDS) is needed; today's 30-job numbers don't extrapolate.
- **Sustained arrival rates and p95 under network latency**, plus disk/IOPS for a larger DB, none of
  which the local warm single-node run can establish.

---
*Data safety:* all synthetic accounts (60/scenario, prefix `loadtest-journey-2026-09-25:`) were deleted
on exit; content-level md5 digests of every non-synthetic table (including `resume_chunks.embedding`
vectors) were **identical before and after** — existing data content is provably unchanged. Session
tokens were generated outside the repo and never printed or stored in evidence. No application code or
configuration was changed; nothing was committed.
