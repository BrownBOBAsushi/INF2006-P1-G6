# Implementation guide — three-week MVP

Start with [PRD](MVP_PRD.md), [architecture](ARCHITECTURE.md), [contract](DATA_API_CONTRACT.md). The checkpoint is historical context, not a second set of conflicting contracts. This guide specifies work to build; commands below are targets implementers must supply, not commands verified to work today.

## Ownership and coding-agent instructions

Frontend/backend membership is user-confirmed. The feature split below is a suggested working assignment so implementation can start; teammates may swap ownership explicitly. Do not silently edit another owner's contracts. All agents share a repository: do not revert other people's edits. No production deployment, merge or credentials are authorised by this documentation task.

| Owner | Files/modules to own | Deliverable |
|---|---|---|
| Jiaxin | src/backend/app/auth, api, db, migrations; auth/ownership tests | Google sessions, schema, profile CRUD, revision/idempotency transactions, API integration |
| Chuying | src/backend/app/processing, matching, catalogue; analytics and associated tests | PDF/privacy, isolated processing slot, MiniLM/chunks, exact ranking, JSON importer, evaluation |
| Xue E | src/frontend auth, catalogue, job-detail routes/components | Login/onboarding skip, browsing/search/filters/pagination, closed details and external Apply |
| Nasya | src/frontend resume and recommendations routes/components | Upload/review/edit, in-memory drafts, retries/progress/error states, evidence view |
| Zhihao | Design contracts, review checklist and acceptance decisions | Review evidence, scope control, team coordination and rationale |

Choose one backend owner for application wiring/OpenAPI (Jiaxin) and one frontend owner for root router/shared API client (Xue E) to avoid collisions. Chuying exposes typed processing/ranking functions; Nasya uses shared client. Assign deployment/backup wiring to Jiaxin with Chuying's resource tests; Zhihao reviews. Do not fabricate contributions before work exists.

### Agent kickoff text

“Build only your assigned slice of docs/handoff. Inspect existing files first. You are not alone in this codebase: preserve others' edits and coordinate shared-file changes. Use DATA_API_CONTRACT as the shared interface. Reuse the approved upstream libraries with attribution. Keep secrets and student content out of commits/logs. Write meaningful tests for your boundary and report actual commands/results. Do not add deferred features or cloud resources. If a requirement is inconsistent or impossible, report the concrete issue rather than silently weakening security or privacy.”

## Stack and reuse checklist

Bootstrap defaults: Python 3.11 for ML compatibility; PostgreSQL 16 with pgvector; React/TypeScript frontend; Docker Compose. These are compatibility targets, not a verified lockfile. Pick supported exact dependency/container revisions at bootstrap, test imports on teammate OS and cloud CPU architecture, then commit lockfiles/digests. Do not install latest packages independently on every machine. Check template Python requirements before importing its dependency manifests.

| Reuse | Source | Scope / caution |
|---|---|---|
| App foundation | https://github.com/fastapi/full-stack-fastapi-template | MIT. Adapt React/FastAPI/Postgres layout and generated client; replace password/JWT-localStorage auth. Do not blindly inherit latest Python minimum. |
| File selection | https://github.com/react-dropzone/react-dropzone | MIT. Picker/drop UX only; server enforces file/content limits. |
| PDF extraction | https://github.com/jsvine/pdfplumber | MIT. Text PDFs only; own and close input memory/file handles. No OCR fallback. |
| PII detection/redaction | https://github.com/data-privacy-stack/presidio | MIT. Configure Singapore recognizers; defaults do not guarantee SG phone/address detection. |
| Embeddings/evaluation | https://github.com/huggingface/sentence-transformers | Apache 2.0. Batch encoding and evaluation helpers; pin model separately. |
| Model | https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 | Apache 2.0; pin immutable revision, normalize, enforce final token budget. |
| Vector persistence | https://github.com/pgvector/pgvector | PostgreSQL licence. Exact cosine aggregation first. |
| Optional upload reference | https://github.com/srbhr/Resume-Matcher | Apache 2.0; selectively inspect upload cancellation tests. Do not adopt raw-resume storage or backend ownership assumptions. |
| Optional skill alias reference | https://github.com/Muskanbawistale/semantic-resume-ranking-system | MIT; boundary/alias ideas only. Do not inherit arbitrary weights, score-percentage mapping or per-resume FAISS construction. |

Before copying code record repository URL, commit, path, licence, modifications in AI_USE_DECLARATION and attribution file. Research found features in sources, not proven compatibility. Prefer direct dependencies over copied internals. Full Stack FastAPI Template and optional references have changed; verify actual adopted revision. No need to clone all shortlisted projects.

## Build order and milestones

### Week 1 — working vertical slice

- Day 1: lock dependencies, Compose, migrations, synthetic catalogue fixture, generated OpenAPI/client. Agree mock response fixtures with frontend before parallel work.
- Days 2–3: real Google login/session/CSRF; browse/detail/filter API and screens. Backend matching can initially use seeded vectors only in tests; do not call it complete.
- Days 3–5: PDF preparation/review, privacy fixtures, real MiniLM save, atomic profile replacement, first recommendations screen.
- End-week gate: from clean checkout, login → browse → prepare synthetic resume → confirm → obtain real ranked results → external Apply. Save and reload must preserve approved content. Fix this slice before optional work.

### Week 2 — correctness and resilience

Finish deletion, stale-tab conflicts, idempotent retries, model version checks, one-slot process isolation and timeouts. Evaluate on independently labelled fixtures; implement browse-under-load and failure recovery. Add backup/restore and health/restart behaviour. Frontend verifies all empty/error/unknown-outcome states. Freeze API breaking changes by end of week.

### Week 3 — deployment and evidence

After local acceptance, verify account access, current total estimate and VM memory headroom; seek deployment approval. Deploy one VM and persistent cloud database volume, HTTPS/private DB, monitoring and backup destination. Run bounded smoke/recovery tests, export redacted evidence, resolve blockers, prepare report and manifest. Avoid adding services just to make diagram look larger. Review final diagram against actual implementation, then decommission when safe after evidence capture.

## Required local commands to implement

```text
docker compose up --build
# Services: localhost frontend/proxy, private API/DB network, persistent named DB volume.
# migrations: one documented command, never implicit destructive resets.
python -m app.catalogue.import_jobs --file data/synthetic_jobs.json --dry-run
python -m app.catalogue.import_jobs --file data/synthetic_jobs.json
pytest
npm run test
npm run build
python analytics/evaluate.py --fixtures data/evaluation
python tests/load/run.py --scenario browse-during-processing
# Backup/restore scripts must name their destination explicitly and never restore over
# the running database without an explicit operator-selected disposable target.
```

Exact working-directory/Compose wrappers belong in root README once implemented. Supply .env.example with placeholders for GOOGLE_CLIENT_ID, DATABASE_URL, APP_SIGNING_KEY and app origin; no provider key needed for synthetic imports. Google sign-in needs a configured client ID and permitted local origin. No mock login route in a deployable build. No raw real resumes in fixtures; generate synthetic text PDFs.

## Integration checklist

- OpenAPI is generated from Pydantic models after implementation; frontend client and fixtures follow it. Contract changes update all four handoff documents where relevant.
- UI controls never send another user's identity. Same-origin proxy avoids unnecessary cross-origin cookie complexity.
- Browser retains draft only in memory; warns on leaving where supported; authentication expiry leaves in-memory draft visible but requires reauthentication before save.
- Poll only an uncertain/in-progress operation using capped backoff (3,6,12 seconds, then manual retry). Status reads do not refresh session idle lifetime.
- Do not rotate idempotency key on a network retry. Changed draft is a new logical attempt; refresh current revision before retry after conflict.
- Handle early503 busy without discarding upload selection or reviewed draft. No false “old profile unchanged” after unknown network outcome.
- Deletion while saving must be tested through revision locking; error messages avoid displaying removed content from a replay.
- Only final sanitized approved inputs reach model; pdf parser has size/page/time limits. Kill/join child on hard timeout.
- Exact search must aggregate every required requirement of candidate jobs before pagination. SQL query plan and concurrency measurement matter more than adding an ANN index by name.

## Tests and evidence

| Category | Minimum meaningful tests | Evidence target |
|---|---|---|
| Functional | Complete journey, filtered search semantics including punctuation/unknowns, closed job, skip upload, delete/reupload, atomic failure | evidence/test-functional.md |
| Security | Invalid Google audience/signature, missing CSRF, cross-account profile/operation access, expired session, PII fixtures, upload limits, no sensitive logs | evidence/test-security.md |
| AI/data | 10 synthetic profiles ×30 jobs independently labelled by team; ranking metrics, OR/AND, negation, missing named skills, long resume bias, learning-outcome extraction | evidence/test-data-ai.md |
| Scale/recovery | Concurrent1/5/10/25 requests; browse simultaneously; child failure/recovery; safe replay after simulated lost response; backup restore into separate DB | evidence/test-resilience.md |
| Operations | Health and restricted logs show failure and subsequent recovery using request IDs | evidence/monitoring.md |

AI fixture counts are initial delivery targets, not statistically representative claims. Label 0 irrelevant, 1 partly relevant, 2 relevant before inspecting model rankings; record judgement criteria. Tune on a separate development subset and report held-out results (e.g. 5 profiles development, 5 held out). Precision@5 and NDCG@5; compare keyword baseline and whole-resume baseline. Whole-resume model truncation must be disclosed or use documented pooled-chunk baseline, not presented as an equivalent full-context encoder. Explain per-requirement evidence limits. Never use another LLM's agreement as sole ground truth. Report actual scores; don't invent a quality threshold retrospectively.

Set timing targets before acceptance runs (see architecture) and record hardware, process/thread count, model revision, data counts and warm/cold status. Busy503 is a controlled rejection, not useful throughput. Document failed targets and remedies. One test result does not establish large-scale production readiness.

## Reviewer gate

Zhihao checks scope first, then real end-to-end behaviour, authorization/privacy, scoring formula and evidence correctness, failure recovery and deployment bill. A runnable local MVP is more valuable than unfinished extra services. Require actual output paths and clean-checkout steps; no “tests should pass” claims.

Remaining deployment-only decisions: concrete VM SKU/region, complete current price estimate, credit eligibility, TLS hostname/certificate setup and restricted external backup destination. They do not block localhost implementation. Live-data licence approval blocks using that data, not development with synthetic jobs. Baseline/library revision locks are the first implementation task, not another product-design meeting.

## Submission packaging

Follow the supplied brief: README.md, project_manifest.yaml, report.pdf (8–12 pages), src/, data/ with dictionary/provenance, analytics/, evidence/, tests/, TEAM_CONTRIBUTIONS.md, AI_USE_DECLARATION.md; optional video_link.txt. Required manifest evidence paths: functional_test, security_test, data_ai_test, scale_resilience_test, monitoring. Preserve required keys from the brief; validate against the actual PDF when creating the manifest. Final archive Group_Gxxx_INF2006_Project.zip uses actual group identifier.

Architecture Mermaid in ARCHITECTURE.md is editable source; export evidence/architecture.png or equivalent supported report figure after diagram matches deployed system. Include cloud boundaries, model/data flows, security, observability and overload. No credentials/personal data/private URLs. Dated evidence allows resources to be decommissioned. Reports and contributions describe what the team actually did.
