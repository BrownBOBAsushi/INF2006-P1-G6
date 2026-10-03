# Functional workflow test record

**Brief reference:** Section 4 (Application: meaningful workflow and input validation) and Section 5.2 test (1).
**Status:** PASS for the main workflow and input validation on the deployed service, with one extraction-quality
defect recorded. Date: 2026-10-03 (Singapore time unless stated).

## Workflow under test

Sign in with Google → upload a résumé PDF → asynchronous extraction and privacy redaction → review and edit the
draft → save (asynchronous embedding) → view ranked internship matches with supporting evidence → search, page and
refresh.

## Test F1 — end-to-end journey on the deployed AWS service

- **Objective:** Confirm the complete student workflow works through the production path
  (HttpApi → VpcLink → InternalAlb → app instances → RDS, with the worker via SQS/S3).
- **Setup:** Stacks `inf2006-private-base-retry1`, `inf2006-private-ingress`, `inf2006-private-app` (configuration in
  `evidence/cloud-capture-2026-10-03/` files `01-stacks.txt`, `02-ingress.txt`, `03-compute.txt`). Catalogue of 247 imported listings (see `data/README.md`). Test
  account "Cloud Acceptance Test" and synthetic PDF `synthetic-internship-resume.pdf` (fictional person). Chrome on
  macOS. Two signed-in accounts were used: the test account for steps 2–4, 9 and Test F2, and the operator's
  existing account (already holding a saved synthetic résumé) for steps 5–8. Provenance: **[Observed]** steps were
  carried out and observed directly by an AI agent operating the browser; sign-in was performed by the operator.
- **Steps and expected/actual results:**

| # | Step | Expected | Actual |
|---|---|---|---|
| 1 | Open the app and sign in with Google | Session created; profile page loads | [Operator-reported] sign-in succeeded; session persisted across refresh |
| 2 | Upload the synthetic PDF | 202 accepted; extraction task completes; review screen shows a redacted draft | [Observed] review screen shown; email redacted; an "unplaced text" warning shown |
| 3 | Review and save | First save returns 200; revision 1 | [Observed] HTTP 200 in 12.58 s, revision 1 (first save includes embedding) |
| 4 | Edit a project description and save again | 200; revision increments | [Observed] HTTP 200 in 649 ms, revision 2 |
| 5 | Save unchanged content twice | No new revision | [Observed] HTTP 200 in 0.609 s and 0.549 s; revision stayed at 2 |
| 6 | Open Matches | Ranked list with requirement evidence | [Observed] 247 results; page 2 reachable |
| 7 | Search, clear search, refresh | Filters apply and reset; state persists after refresh | [Observed] empty search then clear restored results; refresh kept profile and matches |
| 8 | Go offline, request matches, go online, Retry | Visible error with Retry; recovery after reconnect | [Observed] failure shown with Retry; after reconnect 247 results |
| 9 | Go offline, save changed content, reconnect | Draft kept; automatic retry; exactly one revision increment | [Observed] two failures (`net::ERR_INTERNET_DISCONNECTED`), "Trying again" at 3 s and 6 s, "Your draft is here"; after reconnect "Your earlier save completed", revision 3 |

- **Production log corroboration [Captured]:** the same day's access log shows `POST /api/auth/google` 200 × 9,
  `POST /api/resume/prepare` 202 × 3, `GET /api/resume/tasks/…` 200 × 36, `PUT /api/resume` 200 × 7,
  `GET /api/matches` 200 × 17 and no 5xx responses (`cloud-capture-2026-10-03/08-logs-insights.txt`).
- **Result:** PASS.
- **Artefacts:** `evidence/cloud-acceptance-2026-10-03.md` (section "Application and data observations"),
  `evidence/cloud-capture-2026-10-03/08-logs-insights.txt`.

## Test F2 — input validation on the deployed service

- **Objective:** Show that invalid input is rejected with clear errors and does not change saved data.
- **Steps [Observed, browser-issued requests on the test account]:**

| Input | Expected | Actual |
|---|---|---|
| `POST /api/resume/prepare`, multipart with no file, total 6,291,456 bytes (exactly 6 MiB) | Request reaches the API; rejected because no PDF | HTTP 415 `PDF_REQUIRED` |
| Same request at 6,291,457 bytes | Rejected for size before the API | HTTP 413 (non-JSON body; Nginx `client_max_body_size 6m` is the likely rejecting layer, not confirmed) |
| Synthetic PDF of 5,242,881 bytes (1 byte over 5 MiB) | Rejected as too large | HTTP 413 `FILE_TOO_LARGE` |
| After the rejections, reload the profile | Saved résumé unchanged | Revision still 3 |

- **[Captured]** 413 × 2 and 415 × 1 appear in the production access log (`08-logs-insights.txt`).
- **Result:** PASS.

## Test F3 — automated workflow and validation tests (local)

- **Command and results:** `evidence/local-tests-2026-10-03.md`. Backend 133 passed, including
  `test_local_async_journey_extract_save_embed_delete_and_session_reuse` (full extract → save → embed → delete
  journey against a disposable PostgreSQL/pgvector database) and stale-revision/idempotency tests. Frontend 223
  passed, including upload validation (`uploadValidation.test.ts`, 16 tests). PDF edge fixtures (encrypted,
  scanned, 11 pages, not-a-PDF) are rejected by the pipeline tests.
- **Result:** PASS, except 4 stale pipeline tests diagnosed in that record.

## Defects and limitations

- **Extraction quality:** the phrase "Cloud Computing" was classified as a person and redacted, and some text could
  not be placed in a section (warning shown). The student can correct the draft before saving, so the workflow
  completes; improvement: add domain terms to the protected technical vocabulary in
  `src/backend/app/processing/privacy.py` and add a regression fixture.
- **Not tested:** a valid PDF padded to exactly 5 MiB (positive boundary); behaviour when a response is lost after the
  server commits; the API Gateway 30 s timeout under a slow first save. The save timings above are single
  observations, not controlled benchmarks.
- Browser steps were observed by an AI agent and are recorded in text; no screen recording is included.

## Earlier run

The same journey passed on the earlier single-instance foundation on 2026-09-27 (operator-reported):
`evidence/cloud-foundation-run-2026-09-27.md`.
