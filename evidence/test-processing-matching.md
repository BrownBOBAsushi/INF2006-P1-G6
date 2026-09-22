# Processing / matching / catalogue test record

Status: RUN on 2026-09-21 (code at git `1011ba7`, branch `feature/processing-matching-pipeline`). Synthetic data only.
This complements `test-data-ai.md` (ranking quality on labelled fixtures). **Not** an API, security-policy or cloud test: no route calls
these modules yet.

- **Objective:** verify that each stage of PDF -> extraction -> privacy -> structured resume -> 240-token chunks -> MiniLM embeddings ->
  catalogue import -> requirement-level matching (exact aggregation) -> top 5 -> skill gaps -> explanation works as implemented code,
  and measure how the matching computation scales locally.
- **Setup:** Windows 11, AMD Ryzen 9 8945HS (16 logical CPUs), 31.3 GB RAM, Python 3.11.9, CPU only. Environment pinned in
  `src/backend/requirements-processing.txt` (sentence-transformers 6.1.0, torch 2.14.0, transformers 5.17.0, presidio-analyzer 2.2.364,
  spaCy 3.8.16 + en_core_web_sm 3.8.0, pdfplumber 0.11.10, SQLAlchemy 2.0.54, pgvector 0.5.0 (Python client), pgserver 0.1.4).
  Database tests use a **real PostgreSQL 16.2 with pgvector 0.6.2** (embedded via `pgserver`, loopback), not Docker.
  Model: `sentence-transformers/all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, 384 dimensions.

## Commands and actual results

| Command | Result |
|---|---|
| `python -m pytest tests/pipeline -q` (processing env) | **152 passed** in 76 s. 0 skipped. |
| `python -m pytest tests/analytics tests/fixtures -q` (analytics env, unchanged) | **35 passed** in 48 s. |
| Jiaxin's `tests/backend` against a database migrated to the new head (`test_migrations.py` excluded: it hard-codes the Docker path `/app`) | **32 passed**. |
| `python analytics/evaluate.py --fixtures data/evaluation` (documented command, MiniLM) rerun, compared with `evidence/data-ai-eval-2026-09-20.json` | all development and held-out metrics **identical** (held-out requirement-level 0.640 / 0.760 / 0.922). |
| `alembic check` on a database upgraded to head | "No new upgrade operations detected": models and migrations agree. |
| `python tests/load/run.py --scenario all --out-dir evidence` | completed, 0 errors; see `evidence/load-matching-2026-09-21.md/.json`. |
| `python tests/load/run.py --scenario browse-during-processing` | **NOT RUN**: not implemented (needs API, auth, processing slot); exits 3, produces no numbers. |

## What the tests establish (by stage)

- **PDF extraction:** valid, multi-page (3 and exactly 10 pages), 11 pages (rejected), encrypted, non-PDF/empty input, scanned image-only,
  nearly empty, truncated/corrupt, oversize (limit exact at 5,242,880 bytes). Each maps to a deterministic contract code; none raises
  through; error text and logs contain no document content.
- **Privacy:** on 10 generated PDFs no fictional name/email/phone/address/ID/URL survives `prepare_resume`, and all project/experience
  titles and skills survive; technical terms (Python, Node.js, ASP.NET, C++, CI/CD, TCP/IP, Raspberry Pi...) are untouched; output is
  deterministic across runs and fresh analyzers; logs carry counts only; final re-check flags content it would change.
- **240-token limit:** measured with the model's own tokenizer at 50 words, exactly 240 tokens (one chunk), 241 tokens (split), 6,000 words,
  and empty input; nothing dropped or duplicated; every embedded text is <= 240 tokens; `embed` rejects longer text; the chunker is identical
  to the one in `analytics/evaluate.py`. Note the evaluation fixtures themselves never exceed 240 tokens, so this is exercised by dedicated
  unit tests with synthetic long text.
- **Embeddings:** 384 dimensions read from the model, unit-normalised float32, bitwise-identical across calls and a fresh model load,
  batch == single (1e-5), empty/whitespace/None rejected, no silent network download.
- **Catalogue import (real PostgreSQL):** valid import (30 jobs, requirements, vectors of dimension 384, revision 1), repeat import changes nothing
  (same job ids, no vectors computed, revision unchanged), display-only change updates the job with 0 new vectors, changed requirement text embeds
  only the new text, invalid/missing-field batch writes nothing, embedding failure and a failed write roll back, dry-run writes nothing,
  absence never deactivates, `is_active=false` closes a job.
- **Matching:** hand-built vectors prove best/weak match, AND (all requirements count), OR (one alternative suffices), preferred ignored, ties by
  job_id, near-ties by score, fewer than 5 and more than 5 jobs with pagination, shuffle-invariance, incomplete/no-required jobs omitted and counted,
  and that aggregation happens **before** top-k (a global-limit approach would rank job A first; the contract formula ranks B first).
  The same scenarios pass in real SQL; on the real catalogue **SQL ranking == in-memory ranking == `evaluate.py` requirement-level scores**
  for all 10 profiles (order identical, scores within 1e-5).
- **Skill gaps / explanations:** the PRD example (Python, SQL, Git, REST API matched; AWS, Docker missing), OR groups reported once, aliases,
  no substring matching, unassessed requirements never called missing; every explanation statement names its requirement and passage; public
  output has no scores; no suitability/hiring claims.
- **End to end:** `resume_P01.pdf` -> top 5 from 30 jobs (contains at least 2 of the 3 jobs labelled relevant), J01 explanation: Python/Java and
  SQL/PostgreSQL evidenced, "Writes automated tests" (pytest, unit testing) not evidenced; the same PDF gives identical results twice.

## Evaluation results

Unchanged: `evidence/data-ai-eval-2026-09-20.md`, `test-data-ai.md` (labels are AI-drafted, human review pending; requirement-level and BM25 are
indistinguishable on held-out). This work did not modify labels, fixtures or the evaluation script; it added a test proving the production
matcher reproduces the harness's requirement-level scores. No new quality numbers were produced.

## Load / scalability (measured; component level only)

Full tables in `evidence/load-matching-2026-09-21.md`. Highlights, this machine, synthetic random vectors, 30 timed repetitions:

| Measurement | Result |
|---|---|
| Exact in-memory ranking, 1,000 jobs x 4 requirements (5,207 vectors), 10 chunks | p50 49.5 ms, p95 64.1 ms |
| Same at 5,000 / 10,000 jobs | p50 272.6 ms / 559.1 ms (about linear in jobs x requirements) |
| 1,000 jobs, 100 chunks (517,900 similarities) | p50 62.0 ms |
| PostgreSQL 16.2 + pgvector 0.6.2 ranking query (exact), 1,000 jobs | p50 33.1 ms, p95 42.1 ms |
| Same at 5,000 / 10,000 jobs | p50 261.0 ms / 458.7 ms, p95 278.7 / 480.7 ms |
| Concurrent in-process matching (1,000 jobs), 1 / 5 / 10 / 25 threads | 18.9 / 14.4 / 13.8 / 13.8 req/s; p95 61.9 / 601 / 1,191 / 2,603 ms; 0 errors |
| MiniLM on CPU (1 thread): load / RSS after load / single text / batch | 10.2 s / 542 MB / p50 32 ms / 31.9 resume chunks per s (176.8 requirement texts per s) |

Reading: matching cost grows with jobs x requirements (and only weakly with chunks); adding threads does **not** raise throughput on this machine
(it falls slightly and latency grows about linearly), which is consistent with ARCHITECTURE.md's one-processing-slot design. The architecture's
local target "matches p95 < 2 s at 1,000 jobs" concerns the whole HTTP request; only the query/computation was measured (well under 2 s), so
that target is **not** claimed as met. The 10,000-job run is a stress experiment with no pass claim.

## Defects found by these tests and fixed (kept for the record)

1. pdfminer logs raw document tokens at DEBUG: with root DEBUG logging resume text reached the log. Fixed by capping pdfminer/pdfplumber/presidio
   loggers at WARNING in `app/processing/__init__.py`; guarded by tests.
2. Alembic's `fileConfig` disables existing loggers, which had made "no PII in logs" assertions pass vacuously in a full run; the fixtures now re-enable
   loggers and the tests assert that logging is live.
3. The header-name rule wrongly redacted "BSc Computer Science" when applied to a field; it now applies only to the first line of a whole document.
4. spaCy's small model tagged "Android", "Volunteer", "Email" and "Raspberry Pi" as people; handled with technical-term and common-word allow-lists.
   This class of false positive (and unknown false negatives) remains possible for other words.
5. Entries titled "Project 3" were mistaken for the Projects heading (digits were stripped); wrapped education lines became separate entries. Fixed.
6. `app_state.id` was created as SERIAL; the contract specifies a plain singleton `int`; fixed in the model and migration.

## Not run / not established

- No HTTP or API-level test, no authentication/authorization test of these modules, no `browse-during-processing` load scenario, nothing on AWS.
- No process-isolation, timeout or admission-slot behaviour exists or was tested.
- Privacy recall/precision on real resumes and non-Singapore formats: not measured (synthetic PII only). Section parsing was tested on PDFs made by our own
  generator, so real-world layouts (columns, graphics, tables) are untested.
- Human review of evaluation labels: still pending.
- Tests ran on pgvector 0.6.2; the compose image's pgvector version was not tested.

> **Update (later on 2026-09-21):** the first bullet above ("No process-isolation, timeout or admission-slot behaviour exists or was tested") is superseded: the isolated child, slot and 60 s deadline now exist and are tested in `test-processing-isolation.md`. They are still not wired into any API route.
