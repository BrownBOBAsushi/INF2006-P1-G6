# Resume-to-matches journey baseline — v2 (corrected) — 2026-09-25

Corrected rerun addressing the review findings on the v1 journey benchmark. The **v1 run is preserved
unchanged** (`evidence/baseline-2026-09-25-journey.{md,json}` and `…-journey/`) as historical evidence;
this v2 work lives in `evidence/baseline-2026-09-25-journey-v2/` with per-run raw data under
`runs/<RUN_ID>/`. Nothing was committed. Application code/config/infrastructure were not changed.

Target: the real app at `http://localhost:8080` (nginx proxy → FastAPI api, **single worker + single
processing slot** → PostgreSQL 16 + pgvector → spawned embedding child). Git HEAD `0e8067a` (dev);
running api image code **verified byte-identical** to on-disk `src/backend` (sha256 over all
`app/**/*.py`). This run: `RUN_ID=20260925T205235-16677-516be94e57f2`.

## 1. What changed, and how each fix was verified

Focused self-checks run against the **real harness code** via a mocked transport + fake clock (no
server, no DB, nothing touched): `selfcheck.py` → **13/13 PASS**.

| # | Finding | Fix | Verification |
|---|---|---|---|
| 1 | Broad-prefix / known-clean deletion could hit other runs | Unique `RUN_ID`; a **manifest of exact created `user_id`s**; `delete` removes only those ids; no prefix wipe, no pre-delete; tokens in a `0700` out-of-repo `mktemp` dir (file `0600`), never printed/committed | Live: `delete` reported `requested=180 deleted=180 remaining=0`; a mid-run abort still triggered the **EXIT-trap cleanup** and left integrity digests identical (cleanup-on-failure observed) |
| 2 | Matches not tied to saved profile | Require `matches.profile_revision == reloaded revision`; **fixture check** (adjudicated label ≥2 job present in results); response-validation kept separate from HTTP failures | `selfcheck`: stale-revision flagged as a **schema** failure (not an HTTP error); fixture miss recorded in a separate bucket; live run `fixture_ok` 90/90 |
| 3 | Idempotent save mishandled (`changed=true` assumed) | One key per payload; **reuse the same key** for transient retries; **accept `changed=false` replay**; declare success only after **reload verifies revision + canonical content**; `REVIEW_REQUIRED` → new-key confirmation of returned cleaned draft; never rotate keys to hide failures | `selfcheck`: replay `changed=false` accepted & completed; content round-trip mismatch detected; key reuse asserted |
| 4 | Advertised elapsed limit not a real deadline | **Monotonic per-step deadline (30 s)**; per-request timeout & backoff **bounded by remaining budget**; honour `Retry-After`, but **stop** if it exceeds remaining budget; record **attempt-budget vs elapsed-deadline** exhaustion separately | `selfcheck`: all four deadline cases pass (stops at elapsed, never sleeps past, attempt-budget, retry-after-exceeds-budget stop) |
| 5 | Integrity check advisory & over-claimed | **Nonzero exit** on any digest difference; scope excludes **only this run's** users (protects pre-existing *and* other-run rows); deterministic **NULL-safe** md5 over **documented** tables/fields; no "all DB content" claim; md5+counts only | `selfcheck` integrity diff-guard trips nonzero; live before/after digests identical; header in `integrity.sql` lists exact coverage |
| 6 | Unsupported interpretation | Removed the six claims (see §4); observations/hypotheses/unmeasured separated; busy/exhausted = unsuccessful | This report |

## 2. Results (this run) and comparison with v1

3 rounds per scenario. Per-step latency is the **successful attempt only**; whole-journey **includes**
retries/waiting. **Failed-journey durations are reported separately** (this run had none). Small-n p95
is indicative, not tight.

| Scenario (n) | Eventual success | First-attempt | Fixture-relevant | Busy-503 / retries | Timeouts / exhaustion / asserts | prepare p50/p95 | save p50/p95 | reload p50/p95 | matches p50/p95 | **Whole-journey p50 / p95 / max** | Concurrent browse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Sequential (45) | 45/45 | 45/45 | 45/45 | 0 / 0 | 0 / 0 / 0 | 62 / 159 ms | 105 / 310 ms | 3 / 3 ms | 7 / 8 ms | **177 / 482 / 485 ms** | — |
| Burst 5 (15) | 15/15 | 3/15 | 15/15 | 30 / 30 | 0 / 0 / 0 | 75 / 122 ms | 107 / 210 ms | 3 / 7 ms | 9 / 15 ms | **6.22 / 12.27 / 12.29 s** | 2252 req, **100% ok**, p50 8 / p95 17 ms |
| Burst 10 (30) | 30/30 | 3/30 | 30/30 | 135 / 135 | 0 / 0 / 0 | 77 / 171 ms | 108 / 323 ms | 3 / 6 ms | 9 / 12 ms | **13.81 / 27.34 / 27.40 s** | 5018 req, **100% ok**, p50 8 / p95 17 ms |

- Single-thread journey throughput ≈ **4.7 completed/s**; under bursts achieved throughput falls to
  **~0.4/s** because clients serialise on one slot and spend most wall-time in `Retry-After` backoff
  (server-side per-step latency stays ~100 ms).
- **Zero** processing-timeouts, HTTP/transport errors, schema-assertion failures, and fixture misses
  across all 90 journeys; DB confirmed **452 persisted 384-dim non-null embeddings**, 97 succeeded save
  operations for this run's accounts.

**Methodology differences vs v1 (why some numbers moved):**
- v1 burst-10 completed **24/30** (6 gave up at `prepare` under an 8-attempt budget); v2 completed
  **30/30** with a **larger, deadline-bounded budget** (≤10 attempts within a 30 s/step monotonic
  deadline). Same server, different **client retry budget** → v2's whole-journey p95 rose to ~27 s.
  This is direct evidence that eventual completion is a function of the client's retry budget, not a
  server guarantee (see §4).
- v2 records **exhaustion reason** (attempt-budget vs elapsed-deadline) — both zero this run because
  every journey completed within budget.
- v2 adds a **fixture relevance** check and a **profile-revision** check that v1 lacked; both held.
- Sequential and burst-5 figures are consistent with v1 (whole p50 177 vs 181 ms; burst-5 p50 6.2 s in
  both), indicating stable measurement.

### Resources (docker stats, 2 s median interval, 0 missing gaps)
CPU% is per-container (100% = 1 core; host has 10). **Simultaneous app-memory** = peak of the
per-timestamp sum of api+db+web (never a sum of independent peaks).

| Phase | api CPU mean/peak | db CPU mean/peak | web CPU | **Simultaneous app-mem peak** | CPU samples |
|---|---|---|---|---|---|
| Idle | 1.1% / 5.1% | 0.6% / 3.7% | 0% | **682.8 MiB** | 6 |
| Sequential | 83–99% | ~2% | <1% | 690.1 MiB | 1–2/round (indicative) |
| Burst 5 | ~35% mean, ≤70% peak | ~5% | ~1% | 686.6 MiB | 8/round |
| Burst 10 | ~33% mean, ≤75% peak | ~5% | ~1% | 689.8 MiB | 17–18/round |

api memory ~627 MiB idle → simultaneous total ≤ ~690 MiB under all loads. DB ~10 MB under load
(catalogue tables tiny). Sequential CPU has few samples (short rounds) — treat as indicative.

## 3. Correctness evidence (beyond HTTP 200)

Each completed journey: prepare draft shape validated; save accepted with replay-awareness; **reload
confirmed the persisted revision and canonical content hash equalled the submitted content**;
`matches.profile_revision` equalled the reloaded revision; results contained a known-relevant job
(adjudicated label ≥2) for the profile with a non-empty closest passage. A separate DB read confirmed
384-dim non-null embeddings. Content-level md5 digests of all covered non-synthetic tables were
**identical before and after**; scoped cleanup removed exactly this run's 180 accounts (remaining 0).

## 4. Corrected interpretation (replacing v1's over-claims)

The following v1 statements were unsupported and are withdrawn; each is replaced by an
observation / hypothesis / explicitly-unmeasured distinction.

- ~~"the processing slot is the sole scaling limit"~~ → **Observed:** the single processing slot is the
  **dominant constraint in these tests** — bursts produce many `503 PROCESSING_BUSY` while per-step
  latency stays ~100 ms. **Unmeasured:** database, network, memory pressure and CPU limits under
  production-scale load; other bottlenecks may dominate elsewhere.
- ~~"browsing is fully isolated / cannot contend"~~ → **Observed:** browse (`GET /api/jobs`) stayed
  100% successful (0 failures in ~7,270 requests) during bursts and does not touch the slot. **Not
  ruled out:** it shares the single api worker, so contention under much higher browse rates or larger
  catalogues is **untested**.
- ~~"longer retries guarantee eventual completion"~~ → **Observed:** with a larger retry budget v2
  completed 30/30 where v1 (smaller budget) completed 24/30. **Hypothesis, not guarantee:** more budget
  *may* complete more, but busy rejections and budget-exhausted journeys **remain unsuccessful
  outcomes**, and no budget guarantees success under sustained overload.
- ~~"2 GiB is definitely sufficient"~~ → **Observed:** simultaneous app-memory peaked ≤ ~690 MiB under
  these loads; memory looks non-binding here. **Not validated** for production concurrency, larger
  catalogues, or multiple resident model workers — no headroom claim is asserted.
- ~~"each additional worker needs a measured 0.6 GiB"~~ → **Withdrawn (fabricated).** Per-worker /
  per-model memory was **not measured**; api idle RSS (~627 MiB, one resident child) is the only
  related datum and is not a per-additional-worker figure.

## 5. Remaining limitations and what the evidence supports

**Limitations / blocked:** HTTP automation excludes browser rendering, human editing/review time, and
Google OAuth (synthetic sessions injected). Warm, single-node, **single-worker/single-slot**; cold
model-load not measured. Tiny catalogue (30 jobs) — matching cost at realistic scale **not** measured.
Small samples (n=15/30) → indicative p95. Whole-journey burst times are inflated by the runner's
`Retry-After` backoff (a client-policy artefact, not server processing time). No AWS/network, no
sustained (non-burst) arrival-rate, no disk/IOPS-at-scale measurements.

**What the evidence supports for architecture planning (local, warm, this config):**
- A full journey is **~0.18 s p50 warm**; steps are cheap except embedding in `save` (~105 ms p50).
  Reads (`reload`, `matches`) and browse are single-digit ms at this catalogue size.
- One worker + one slot sustains **~4–5 sequential journeys/s**; **concurrency does not add throughput
  here** — extra upload load converts to `503`+retry, so a single-EC2 candidate must pair with
  client-side backoff (already in the frontend) and an explicit decision on upload concurrency
  (more slots/workers vs a queue).
- Memory was not binding in these tests (≤ ~690 MiB simultaneous), so **CPU/embedding, not RAM, is the
  first thing to size** — but per-worker model memory and behaviour under production concurrency must
  be measured on the target instance family (arm64 local numbers won't transfer directly), along with
  cold start, matching at realistic catalogue size, and sustained arrival rates.

---
*Reproduce:* `bash evidence/baseline-2026-09-25-journey-v2/run_baseline.sh` (from repo root); analyse
with `python3 evidence/baseline-2026-09-25-journey-v2/analyze.py runs/<RUN_ID>`; validate logic with
`python3 evidence/baseline-2026-09-25-journey-v2/selfcheck.py`. Tokens are written to a restricted
out-of-repo temp dir and never enter evidence; synthetic accounts are deleted (verified) on success and
on failure. All new work is left uncommitted for review.
