# Local frontend/backend integration plan

**Goal:** Run the complete existing Internship Matcher product through the real backend on localhost, remove disconnected production UI, and collect honest acceptance evidence before cloud hosting.

**Authority:** User request on 2026-09-22; `docs/handoff/MVP_PRD.md`, `ARCHITECTURE.md`, `DATA_API_CONTRACT.md`. This implements the existing architecture rather than changing product scope.

**Architecture:** One same-origin web entry point serves the built React app and proxies `/api` to one FastAPI process. PostgreSQL/pgvector persists sessions, approved profiles, vectors and imported jobs. One bounded processing child handles PDF/privacy/embeddings. Production paths have no fake data fallback or test identity. Synthetic catalogue data is imported explicitly through the real database for local acceptance.

**Execution:** JARVIS builder is the sole code writer on `codex/local-integration`; root coordinates and verifies. Freeze writes for an independent reviewer. Do not commit, push, merge or deploy as part of this implementation without a separate instruction.

## Constraints and decisions

- Preserve the existing visual design and working resume draft/retry behaviour.
- Google-only authentication, as already specified; remove email/password/create/reset previews from the normal application.
- Remove the recommendations placeholder by implementing the contract feature; do not replace it with fabricated matches.
- Keep test fixtures isolated from production bundles. Keep useful static copy and enum labels; static UI text is not fake application data.
- Use `details.cleaned_draft` for REVIEW_REQUIRED and `details.current_revision` for REVISION_CONFLICT. Update both ends and the handoff.
- Serve frontend/API under `http://localhost:8080` for local browser validation. Never use a production authentication bypass.
- No hosted LLM, provider request on student workflows, queue, extra datastore or cloud provisioning.
- Enforce contract limits: PDF 5,242,880 bytes / 10 pages, request multipart cap 6 MiB, JSON 256 KiB; chunks 240 tokens; processing 60 seconds; browser 100 seconds; proxy 90 seconds.
- Secrets and protected `.env` files must not be read. Configuration examples may contain placeholders only. Do not test against an existing database whose ownership/data is unknown.
- A passing mock or reference harness does not establish real-API acceptance. Real Google login and independent human-labelled AI evaluation remain separate gates.

## Baseline and graph

Graphify code-only refresh at `323cccd43865548b3bf913d1eb03f14f8d59414f`: 1,231 nodes, 2,583 edges, 155 unchanged code files. Inspect actual callers as well as graph edges; static graph extraction does not prove an HTTP route works.

Current connections: App -> useSession/shared ApiClient; Catalogue/JobDetails -> shared client; ResumeWorkspace -> resumeApi -> scoped shared transport. Backend main registers auth/me/resume reads/delete/status only. Processing/matching/catalogue modules exist but prepare/save/matches/catalogue routes are absent. AuthPreview is imported by the normal app; `/matches` is a placeholder. Compose has no web service and the API image lacks processing dependencies/model preparation.

Baseline checks from this task: frontend typecheck/build pass; 192 frontend tests pass with bundled Node 24.19.0, four loopback HTTP tests blocked by `listen EPERM`; declared Node is 24.21.0. Backend test runtime lacks pytest/ML dependencies. Docker socket is permission-denied even after escalation; GitHub/PyPI/npm/Hugging Face/Google DNS currently fails. These are verification blockers, not permission to claim success.

## Batch 1: Backend contract, catalogue and security

Files: `src/backend/app/main.py`, `app/core/{config,errors}.py`, `app/auth/{router,dependencies}.py`, `app/api/{me,resume,jobs,matches}.py`, API schema/service helpers as needed, `tests/backend/`, `docs/handoff/DATA_API_CONTRACT.md`.

- [ ] Add regression coverage for top-level error envelope, validation errors without rejected values, CSRF on every mutation, logout cookie deletion and session expiry/ownership.
- [ ] Wire consistent exception handling; no private response caching or sensitive request/body logging.
- [ ] Implement typed catalogue list/detail responses with literal AND search, escaped LIKE wildcards, repeated OR-within/AND-between filters, stable paging, active-only lists, closed details and consistent snapshot/revision checks.
- [ ] Implement SQL-backed matches with current user/revision/version checks, complete requirement aggregation, page-only explanations, explicit skill evidence and no public numeric score. Preserve empty/no-resume/no-chunks distinctions.
- [ ] Use typed OpenAPI responses and test their shapes against frontend contract expectations.

Regression example:

```python
response = client.patch('/api/me', json={'display_name': 'Student'})
assert response.status_code == 403
assert response.json()['error']['code'] == 'CSRF_INVALID'
assert 'detail' not in response.json()
```

Use a valid synthetic authenticated fixture for that test, then assert cross-account requests cannot access another profile or operation. Backend fixtures must create an isolated disposable database before any TRUNCATE.

## Batch 2: Real prepare/save processing lifecycle

Files: `app/api/resume.py`, focused profile transaction/service helpers, `app/processing/{slot,worker,content,pipeline}.py`, `app/catalogue/{schema,importer}.py`, related backend/pipeline tests.

- [ ] Fix blank-entry validation, requirement deduplication evidence loss, and ISO country validation with targeted regression cases.
- [ ] Start exactly one ProcessingService, reuse the pinned model, stop cleanly and include schema/model/child readiness. Busy capacity is not a false dependency failure.
- [ ] Authenticate and acquire admission before consuming uploads. Parse one PDF in bounded memory without unnoticed disk spooling; enforce streamed body caps and sanitized failures.
- [ ] Implement PUT save with user-scoped UUID idempotency, canonical payload/version hash, replay and mismatch behaviour, no operation on PROCESSING_BUSY, privacy reconfirmation and bounded inference outside transactions.
- [ ] Atomically replace content/chunks, increment revision and mark operation succeeded in the same short transaction. Recheck revision under user-row lock. Preserve old content on failed inference; recover IN_PROGRESS state after restart without replaying writes blindly.
- [ ] Test same-key retry after lost response, changed-payload reuse, concurrent saves/deletes, stale revision, no-op save, privacy REVIEW_REQUIRED, child timeout/crash, disconnect and no chunks.

Regression cases use a valid Python skill plus an entirely blank project, and identical PREFERRED/REQUIRED rows with different evidence metadata. Assert blank entries receive validation feedback and REQUIRED provenance is retained deterministically.

## Batch 3: Frontend integration and localhost runtime

Files: `src/frontend/src/App.tsx`, auth component/tests, new `features/matches/`, shared API contracts, resume error-field parser/tests only where required, Footer, frontend/backend Dockerfiles, web proxy config, Compose, dependency manifests, setup documentation, integration test harness.

- [ ] Replace AuthPreview with real Google-only sign-in while preserving accessibility, focus restoration, error recovery and styling.
- [ ] Build recommendations using GET /api/matches with filters/paging/revision recovery, closest passages, separate skill evidence and eligibility notes. Cover no-profile, no-chunks, zero results, stale results, closed job navigation, session expiry and account switching.
- [ ] Remove unsupported preview actions/copy and unrelated inactive frontend code after checking callers. Keep explicit test/dev fixtures outside the production bundle.
- [ ] Pin and reconcile the real backend/ML runtime; pre-cache the pinned models for the offline child. Separate test-only packages where practical. Never fabricate an install result.
- [ ] Provide production-style local Compose with a built frontend, same-origin proxy, one API worker, private database, persistent volume, health/startup/migration ordering and bounded uploads/timeouts. Keep development conveniences explicit.
- [ ] Document exact setup, explicit synthetic import, reset/recovery and clean-checkout commands. Avoid commands that silently remove database volumes.

Frontend regression intent:

```tsx
expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
expect(screen.queryByText('Not available yet')).not.toBeInTheDocument();
```

Mount authenticated and unauthenticated states separately; assert actual success/error behaviour, not just absent strings.

## Final acceptance and evidence

- [ ] Re-run typecheck, frontend tests/build, backend/pipeline tests and migrations on isolated PostgreSQL/pgvector.
- [ ] Run real backend HTTP contract tests with controlled synthetic identity verification in test-only dependency overrides, never a deployable bypass.
- [ ] Launch built frontend and real API/database/model; browser-check login -> onboarding -> browse/filter/detail -> prepare -> edit -> save -> recommendations -> reload -> delete -> logout.
- [ ] Separately verify real Google login with the user's configured public client ID and approved localhost origin.
- [ ] Verify persistence across restart, invalid/oversized PDF, missing CSRF, cross-account access, stale save, uncertain commit recovery, busy response while browse remains responsive, child timeout and recovery.
- [ ] Run existing real API load script against the assembled application; record hardware, fixture sizes, p95, errors and memory. Do not substitute reference-harness figures.
- [ ] Freeze edits; fresh independent review; repair material findings through the builder; report actual passes, failures and blocked checks.

Completion requires the local gate above, not merely compilation. Cloud release still requires deployment-specific HTTPS, credentials, backup/restore, networking, budget and human release approval. Human-independent ranking labels are a distinct outstanding evaluation task and must remain honestly marked pending.
