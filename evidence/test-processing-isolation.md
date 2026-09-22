# Processing isolation, slot and API-level load: test record

Status: RUN on 2026-09-21 (code at git `c95f962`, branch `feature/processing-isolation-and-api-load`). Synthetic data only.
Extends `test-processing-matching.md`, whose "process isolation ... not established" line this record supersedes for the parts listed below.

**Scope statement.** This covers only what Chuying owns: the isolated processing child, the single processing slot with the documented
60-second deadline, and the API-level load script. Nothing here was integrated into Jiaxin's routes (none of prepare, save or matches exist),
so no claim is made about the real API. The HTTP results below come from a **reference harness** that wires the same `ProcessingService` the
way `src/backend/JIAXIN_INTEGRATION.md` prescribes.

- **Objective:** show that (1) processing runs in a separate child process, (2) exactly one operation is admitted at a time and everything else is
  rejected immediately, (3) a running operation is stopped at 60 s by terminating and joining the child before the slot is freed and the child is
  recreated, (4) a client disconnect cannot free a running slot, (5) the load script measures the slot over HTTP and refuses to run when it cannot.
- **Setup:** Windows 11, AMD Ryzen 9 8945HS (16 logical CPUs), 31.3 GB RAM, Python 3.11.9, CPU only. Environment pinned in
  `src/backend/requirements-processing.txt` (verified identical to the installed set). Production child = real spaCy `en_core_web_sm`, Presidio,
  pdfplumber and MiniLM `all-MiniLM-L6-v2` at revision `1110a243...`.

## What Chuying implemented

| Item | Where | Behaviour |
|---|---|---|
| Isolated child (spawn) that loads models once, serves one request at a time, exits when the parent goes away | `app/processing/worker.py` | operations `prepare`, `save`; only exception class names cross back on unexpected errors |
| One process-wide slot, non-blocking admission, `Lease` | `app/processing/slot.py` | `try_acquire()` returns at once or raises `PROCESSING_BUSY` (503, `Retry-After: 3`); nothing is queued |
| 60 s deadline | `slot.py` `DEADLINE_SECONDS = 60.0` | on expiry: child terminated **and joined**, then the slot may be released, replacement child loads in the background, caller gets `PROCESSING_TIMEOUT` (504) |
| Crash handling and recovery | `slot.py` | crash -> `INTERNAL_ERROR` (500), child replaced; 3 failed replacements -> `FAILED`, `SERVICE_UNAVAILABLE` |
| Disconnect safety | `Lease.release()` | release while running is deferred until the operation has ended or its child is dead |
| Readiness | `ProcessingService.is_ready()` | False while starting/recovering/failed |
| Best-effort restrictions | `worker.restrict_child()` | offline env flags, one ML thread, in-process socket guard (not an OS sandbox) |
| HTTP load scenarios | `tests/load/api_load.py`, `run.py` | `api-concurrency` (1/5/10/25), `browse-during-processing`; `--target harness` or a real base URL |
| Reference harness | `tests/load/harness_app.py` | throwaway FastAPI app; **not** the product API |

## Commands and actual results

| Command | Result |
|---|---|
| `python -m pytest tests/pipeline -q` (processing env) | **185 passed** in 228 s, 0 skipped (22 slot tests, 11 HTTP tests, plus the 152 from before) |
| Jiaxin's `tests/backend` (test_migrations.py excluded: hard-codes `/app`) | **32 passed** (rerun after these changes) |
| `python tests/load/run.py --scenario browse-during-processing` (no target) | **NOT RUN**, exit 3, no output files |
| `python tests/load/run.py --scenario api --target http://127.0.0.1:9` | **NOT RUN**, exit 3 (nothing listening) |
| `python tests/load/run.py --scenario api --target harness --out-dir evidence` | completed; `evidence/load-api-harness-2026-09-21-api.md/.json` |
| `python tests/load/run.py --scenario api --target <real API>` | **NOT RUN**: Jiaxin's API has no `POST /api/resume/prepare`, `GET /api/jobs` or `GET /health/ready` route and needs a supplied session; refusal logic unit-tested against a fake OpenAPI document |

## What the tests establish

- **Isolation:** the child has a different PID from the API process and keeps it between calls; importing `app.processing.slot` loads none of torch,
  spaCy, Presidio, pdfplumber, sentence-transformers, transformers or numpy (checked in a fresh interpreter); the socket guard blocks an outbound connection
  that succeeds in an unguarded child (control included).
- **Slot:** with one operation running, a second `try_acquire()` fails in under 50 ms with code 503, `retryable`, `Retry-After` 3; five simultaneous
  `run_async` calls across two operation types admit exactly one and reject four, and finish in under 3 s (nothing queued behind the winner).
- **Deadline:** with a 1 s test deadline, a 30 s operation gets `PROCESSING_TIMEOUT` (504) after 1 to 4 s, the old child PID no longer exists at the moment the error
  is raised, the slot is still held by the caller at that point, state is `RECOVERING` and `is_ready()` False, then a new child (different PID) serves the next request.
  **The default deadline was tested for real:** an operation of 300 s with no overrides was stopped after **60.21 s** (accepted window 60.0 to 64.0 s).
  With the production child a 10 ms deadline killed real PDF preparation, the real models reloaded in the replacement, and the next preparation returned the exact expected draft.
- **Disconnect:** cancelling the awaiting task 0.3 s into a 1.6 s operation leaves the slot busy (a request at ~0.7 s is still rejected) and frees it only after the work ended;
  a `release()` while running is deferred.
- **Crash / errors:** a child `os._exit` gives 500 `INTERNAL_ERROR` (not retryable) and a replacement serves the next request; contract codes raised inside the child
  (for example `PDF_ENCRYPTED` 422) keep their codes; an unexpected `RuntimeError` carrying fake resume text surfaces only as reason `RuntimeError`
  (the text appears nowhere in the parent-side error); after a permanent replacement failure the state becomes `FAILED` and `try_acquire()` raises `SERVICE_UNAVAILABLE`.
  Startup failure and startup timeout are reported, not hung. A 5 MiB payload and result pass through the pipe.
- **Production child equivalence:** `prepare` in the child equals in-process `prepare_resume` for `resume_P01.pdf`; encrypted, scanned, non-PDF and 11-page inputs return
  `PDF_ENCRYPTED`, `TEXT_REQUIRED`, `PDF_REQUIRED`, `PDF_UNREADABLE`; `save` reproduces the in-process chunks and vectors (within 1e-6), reports version, content hash, and flags a
  privacy change with `review_required` and no email in the cleaned draft.
- **Over HTTP (harness with a fake worker):** busy is an immediate 503 with `Retry-After: 3` and the contract envelope; `/api/jobs` and `/health/ready` keep answering
  (under 300 ms) while processing is busy; deadline gives 504 then `/health/ready` 503 then recovery; crash gives 500 then recovery; oversize body gives 413 and frees the slot.

## Measured (this machine)

| Measurement | Result |
|---|---|
| Production child startup until ready (3 runs, measured in isolation) | 14.1 s, 14.2 s, 14.1 s (15.7 s inside the harness run) |
| Child memory (RSS after load and one preparation) | about 594 MB |
| One preparation of `resume_P10.pdf` (2 pages) in the child | about 0.91 to 0.94 s |
| Busy rejection latency over HTTP | p50 3.4 ms, p95 5.9 ms, max 35.7 ms (26,572 rejections) |
| Admitted preparation over HTTP | p50 901 ms, p95 1,180 ms, max 1,203 ms (27 completions) |
| Browse `/api/jobs` alone / while processing is saturated | p95 4.8 ms / 8.7 ms, 0 errors in 330 / 1,720 requests |
| Concurrency 1 / 5 / 10 / 25 (15 / 30 / 50 / 100 requests) | admitted-and-completed per second 1.14 / 0.72 / 0.65 / 0.48; busy share 0 / 96.7 / 98 / 99 %; 0 timeouts, 0 other errors |

Reading it: the design admits about one preparation per second on this machine (the slot serialises work); everything beyond that is rejected in a few milliseconds
without affecting browsing. The closed-loop clients ignore `Retry-After`, so they retry immediately (about 1,000 requests per second in the 25 s phase); real
clients back off for 3 s, so this is a stress condition, not a usage forecast. The ARCHITECTURE.md targets are shown only for reference: busy p95 5.9 ms against
"under 1 second" and admitted max 1.2 s against "within 60 seconds", **on the harness only**.

## Not done / not established

- **Not integrated into the API.** No route uses `ProcessingService`; Jiaxin's `/health/ready` does not consult `is_ready()`; `ACTIVE_EMBEDDING_VERSION` is still a stub.
  Everything Jiaxin must do is listed in `src/backend/JIAXIN_INTEGRATION.md`.
- **No numbers for the real API** (routes absent; authentication, CSRF, database and multipart parsing costs are not represented in the harness).
- **The child is not an OS sandbox:** no memory or CPU limit, network denial is an in-process guard only, file access is unrestricted.
- Startup is about 14 s; while the child is replaced after a timeout or crash new work gets `PROCESSING_BUSY` for that long.
- Only one platform (Windows 11) was tested; the spawn start method and pipe protocol are portable but unverified on Linux.
- Client disconnect was tested at the slot level (cancelled awaiting task), not with a real dropped TCP connection through uvicorn.
- One replacement-failure policy (3 attempts, then `FAILED`) was chosen by me; the docs do not specify it.
