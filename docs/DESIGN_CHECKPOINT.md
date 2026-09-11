# Internship Matcher — design checkpoint

Status: consolidated implementation handoff prepared; application implementation has not started in this task.
Checkpoint date: 2026-09-11.

## Start here next session

Start implementation with [MVP PRD](handoff/MVP_PRD.md), [architecture](handoff/ARCHITECTURE.md),
[database/API contract](handoff/DATA_API_CONTRACT.md), and [implementation guide](handoff/IMPLEMENTATION_GUIDE.md).
These consolidate the approved scope and routine implementation defaults. This checkpoint
retains historical decisions and older proposals; the handoff resolves their pending details.
The user explicitly changed from field-by-field discussion to completing a practical handoff
within a three-week delivery window. Do not restart those approval loops.

Approved delivery direction: Docker Compose localhost first; one-VM initial cloud target
with persistent PostgreSQL, bounded processing, health/restart and backup/restore.
Managed database, load balancer, autoscaling and queue deferred. Cloud size/cost and
provisioning wait for local acceptance and deployment approval. No cloud resources created.

## Goal and team

The team chose Internship Matcher over RiskShield for INF2006.
Build a complete student-facing app with login/logout, onboarding, persistent
data and semantic internship recommendations. Produce a detailed PRD, architecture
decision rationale, database/API contracts and teammate/coding-agent guides as
decisions are agreed.

| Person | Confirmed responsibility |
|---|---|
| Jiaxin | Backend |
| Chuying | Backend |
| Xue E | Frontend |
| Nasya | Frontend |
| Zhihao | Moderator, system design understanding and reviewer |

Suggested individual feature/file ownership is now in the implementation guide. Do not copy the different
team assignments from the INF2003 reference project.

## Confirmed direction

- Google sign-in selected for the MVP. Zhihao prefers existing Google accounts to
  another app password. Do not implement a parallel email/password signup or
  password-recovery flow by default.
- Direct Google integration approved: Google Identity Services on the frontend,
  official Python google-auth verification in FastAPI, then find/create the local
  student account and establish an app session. Use Google's stable subject, not
  email alone, to link identities. Cognito/authentication broker not selected.
- Rationale: only Google login is required and the app already has FastAPI and
  PostgreSQL. Avoid an additional identity service; application session management,
  verification/CSRF controls and authorisation remain our integration responsibility.
- Server-side app sessions in PostgreSQL approved. Browser holds a random session
  token in a protected cookie (HttpOnly, Secure for HTTPS); backend validates the
  session for authenticated requests. Cookie-based state changes require CSRF
  protection. Exact schema and library remain to be selected.
- MVP session expiry approved: 30 minutes inactive or 8 hours from session creation,
  whichever comes first, enforced by the server. Reauthenticate through Google
  after expiry. Background polling must not extend an otherwise idle session;
  define qualifying activity precisely in the eventual API/session contract.
- Closing a tab does not log out; server expiry still applies. Saved profile and
  resume data survive expiry. Unsaved-edit handling remains undecided. These are
  initial MVP limits, not requirements imposed by the module.
- Logout invalidates this browser's app session on the server, clears the cookie
  and client personal-data caches, and preserves saved profile/resume data. It does
  not sign the student out of Google. Tabs sharing this cookie share the session.
- Rationale: immediate server-side invalidation for subsequent requests, shared
  session access across backend instances and no additional session datastore.
  Trade-off: authenticated requests require a database session lookup. Logout
  does not retroactively cancel an already-authorised in-flight operation.
- Rationale: reduce student login friction and avoid application password handling
  and recovery. This requires adapting the template's existing authentication;
  do not claim it is already integrated or necessarily faster to implement.
- Architectural starting point approved: adapt Full Stack FastAPI Template with
  React frontend → Python/FastAPI backend → PostgreSQL plus pgvector.
  Exact template revision and dependency versions remain
  undecided. Approval selects the architecture; it does not start implementation.
- Rationale: reuse app/account/API-client/test foundations; Python directly hosts
  extraction/privacy/embedding libraries; one database supports structured data
  and vectors. Frontend/backend pairs can work against shared API contracts.
- Trade-off: inherited template conventions need review; Python/ML compatibility
  and login/logout semantics must be verified before selecting a revision.
- PDF upload through drag-and-drop or a local file picker; both use one pipeline.
- PDF-only MVP, one text-based PDF at a time, up to 5 MB. Define the exact byte
  limit in the eventual API contract.
- Scanned, password-protected and unreadable PDFs should receive clear errors.
- Do not retain the original PDF when it has no further product purpose.
- Remove unnecessary personal details before embedding, including phone numbers,
  addresses and other contact/identity information. Cleanup is a requirement.
- Embeddings and semantic search are central to this project and need an
  understandable, efficient and credibly evaluated design.
- Agreed conceptual split: cleaned relevant resume content for semantic ranking;
  confirmed skills separately for explicit skill-gap explanations.
- Onboarding approved: Google sign-in → confirm display name → upload PDF →
  review/correct cleaned information → confirm → generate embedding → matches.
  Prefill display name from Google where available and allow editing; keep the name
  outside embedding input. Returning users with completed profiles go to dashboard.
- Students edit human-readable skills, project/experience descriptions and other
  extracted content, never vector numbers. Generate embeddings only after review
  and confirmation; regenerate when approved matching content changes later.
  Do not trigger regeneration merely for a display-name edit.
- Review lets students fix extraction errors and remove missed personal details;
  it does not guarantee all sensitive information was detected. Final submitted
  content still needs server validation/cleanup before embedding, including edits.
- Saved-resume lifecycle approved: one current matching profile per student; no
  user-facing version history for MVP. First upload is reviewed and confirmed,
  then its embedding is generated and the profile saved.
- Replacement uploads or approved edits prepare new cleaned matching content and
  its embedding before replacing the current pair atomically. On failure preserve
  the previous working pair and offer retry. Matching uses the last successfully
  saved pair; do not present new text as active with an old embedding.
- Deleting the resume profile removes its matching content and embedding while
  retaining the login account. Retain cleaned matching information, not the PDF.
  Draft behaviour is approved below; concurrency and detailed transaction mechanics
  remain implementation-contract decisions. Atomic replacement does not require keeping
  a database transaction open during model inference.
- Reuse existing open-source implementations, potentially from several repos,
  before deciding what remains to build. Do not rebuild existing machinery merely
  to claim team contribution.
- Single-database MVP confirmed after discussing scaling: PostgreSQL plus pgvector;
  no additional MongoDB/document database. Relational columns, text, JSONB and vectors
  can serve the different data shapes. Resume-profile fields are approved below;
  the exact nested JSON content schema remains to be specified.
- Rationale: a second document store does not remove internship-vector search cost
  and complicates atomic replacement of matching content and embeddings. Reconsider
  datastore separation only for a measured workload benefit.
- Scaling approach approved: measure record lookups, vector retrieval, embedding
  work and concurrent demand separately. Reuse embeddings on unchanged content;
  inspect query plans/indexes; compare exact vector search with HNSW when justified.
  Measure p95 latency and retrieval quality as catalogue size and concurrency grow.
  Exact search as an initial baseline is the intended starting approach; no HNSW
  deployment, workload numbers, latency targets or completed benchmarks are claimed.

## Approved resume processing and error handling — 2026-09-11

- Stage 1: validate PDF, extract text, remove unnecessary personal information,
  prepare editable content. Student sees preparing state, then review screen.
- Stage 2: student confirms; backend validates/cleans edits, chunks and embeds,
  then saves profile and vectors atomically. Student sees saving, then matches.
- Unreadable/scanned/password-protected PDF: actionable request for text-based PDF.
  Extraction/cleanup failure must not proceed using uncleaned text.
- Embedding/save failure retains the reviewed browser draft for retry. Previous
  saved profile remains usable until successful replacement.
- Unsaved drafts stay in browser memory, not persistent browser storage. Refresh
  or closure loses drafts; warn on navigation where supported. Browser exit warnings
  are best-effort, not guaranteed recovery. Saved profiles persist in PostgreSQL.
- Disable repeat Save clicks during submission; backend duplicate-submission and
  concurrent-update protection is required, with approved rules below.
- Common error pattern across endpoints: stable error code, safe student-facing
  explanation/next action, request reference ID, and whether retry is useful.
- Restricted developer logs use the same ID and record failed stage, timestamp,
  duration, retryability, relevant model version and sanitised diagnostics/stack trace.
- Never log PDF/resume contents, vectors, session cookies or API keys. Sanitise
  exception messages too; do not echo request bodies into logs or error responses.
- Expected errors get specific safe explanations; unexpected errors get a generic
  actionable message. Never claim an operation failed or old profile is unchanged
  merely because the client timed out: commit outcome may be unknown until checked.
- Exact HTTP codes, response schema, log retention/access and timeout/retry execution
  design remain implementation contracts. No code implemented by these decisions.

### Approved save retries and concurrency — 2026-09-11

- Reuse one idempotency key for retries of the same logical save attempt, distinct
  from per-request diagnostic reference IDs. A completed attempt returns its prior
  outcome rather than saving again. Backend enforcement required, not just disabled UI.
- Check expected profile revision when committing. A stale tab cannot overwrite
  a newer saved profile; return a conflict prompting reload/reconciliation.
- A timeout means the outcome may be unknown. UI says it could not confirm saving,
  not that saving definitely failed; retry/status resolution must establish outcome.
- Detailed contract must scope keys by authenticated user and operation, bind them
  to the payload, define retention and in-progress behaviour, and coordinate outcome
  persistence with the profile commit. Replays must not regress the displayed profile
  if another save has since completed. Exact implementation remains pending.

### Local-first budget and assessment constraints — 2026-09-11

User states AWS budget is $50. Develop/debug and run initial tests locally; do not
deploy until the local workflow is clean. No cloud resources authorised/created here.
Re-read project brief pp. 2 and 5: expected workload and cost controls required;
implement at least one scaling/resilience mechanism and report a scale, resilience
or recovery test. No mandated 100-user test or mandatory load balancer. Working
cloud deployment and persistent cloud data are still required; cloud resources may
be decommissioned after collecting dated, redacted evidence/configuration.

Request-waiting processing is now approved below. User approved
bounded expensive processing, controlled overload responses and retries,
then local stepped load tests with synthetic PDFs (upload/extraction and confirmed
save/embedding separately). Increasing concurrency is an experiment, not a promise
of 100 simultaneous inferences. Record p95 latency, throughput, failures, CPU/memory
and recovery; local results do not establish AWS capacity. Pick explicit implemented
assessment mechanism and test; do not assume overload rejection alone proves scaling.

User explicitly requires our own architecture diagram as a final deliverable.
Build it around the implemented system: users/frontend, authentication, backend,
bounded PDF/embedding processing, PostgreSQL/pgvector, manual catalogue import,
external application links, trust boundaries and observability. AWS service names
must follow approved deployment decisions; distinguish proposed from implemented
components. Include normal data flow and overload behaviour, with local-first
development and $50 AWS budget reflected in the rationale. Reference image supplied
at /Users/desmondchyezhihao/Downloads/IMG_1319.HEIC could not be decoded by image
viewer or sips; its contents have not been inspected. Do not infer its architecture.

### Approved bounded request processing baseline — 2026-09-11

- Start with one shared expensive-processing slot per backend instance, covering
  extraction/cleanup and embedding operations. This is a conservative baseline to
  tune with measured memory, CPU and latency, not a demonstrated capacity limit.
- Request waits for its result when admitted. If the slot is busy, return a safe
  temporary busy response with retry guidance; no application waiting queue in MVP.
- Release slot after processing finishes/fails. Do not release early solely because
  a client disconnects if the underlying computation is still running.
- Expensive computation runs outside the main request-handling loop. Browsing and
  login should remain responsive; shared CPU/memory contention must be tested.
- Slot limit is instance-wide: multiple API processes must not each create an
  independent allowance. Exact process/executor topology is pending.
- Retry respects approved idempotency/revision protection; preserve browser draft.
- Pending execution details: bounded upload/body handling, processing timeouts,
  cancellation, busy HTTP response and retry delay, model lifecycle, and tuning.
- Replacing slot count with more parallelism requires measurements. No load balancer,
  queue, autoscaling service or cloud provisioning was authorised by this approval.

### Approved initial local load-test criteria — 2026-09-11

- One valid synthetic resume completes processing successfully.
- Concurrent submissions admit at most one expensive operation per instance;
  excess requests receive controlled retry guidance rather than unbounded waiting.
- Browse requests remain responsive while expensive processing runs; numeric
  responsiveness targets must be set before final acceptance after baseline profiling.
- Processing failure releases capacity once computation has stopped; next request
  can succeed. Test extraction and embedding stages separately.
- Retried saves do not duplicate effects or overwrite a newer profile revision.
- After load ends, normal requests succeed without a manual service restart.
- Record setup, concurrency, input sizes, durations/p95, throughput, accepted/busy/
  unexpected-error counts, CPU, memory and recovery. Busy responses are expected
  overload handling, not successful processing throughput; report them separately.
- These are approved test criteria, not completed tests or proof of AWS capacity.
  Use synthetic resumes; final numeric targets and AWS verification remain pending.

## Proposed, not yet explicitly agreed

- Remaining section handling, extraction contracts and
  detailed embedding constraints remain undecided. Table starting structures and
  project/experience chunking are approved below. Compare the initial algorithm
  against whole-resume and keyword baselines before claiming benefits.
- Store only approved cleaned content and embeddings; raw extracted text is
  temporary and excluded from database, logs and queues.
- AWS services and dataset are undecided; final scoring acceptance depends on evaluation.

## Approved initial matching experiment

For each distinct required technical requirement of a job, compute cosine similarity
against the student's approved resume chunks and take the highest similarity.
Average those best similarities equally across that job's required technical
requirements. Rank using this semantic score as the initial experiment.

Formula: score(job, resume) = mean over requirements of max over resume chunks of
cosine(requirement_embedding, chunk_embedding). Remove duplicate requirements.
Preferred skills are informational only for MVP (approved below). Employer eligibility
conditions are shown for student checking, not automated exclusion (approved below).
Missing/empty required requirements or resume chunks need an explicit unavailable
score policy; do not invent a successful score or divide by zero.

Retain which chunk supported each requirement comparison for traceable explanations.
Similarity is not proof a requirement is met and is not hiring probability. Keep
explicit confirmed-skill evidence separate (e.g. deployment similarity does not
establish AWS knowledge). Do not sum all chunk matches: duplication must not
automatically add score. Longer resumes can still benefit from more chances at a
high maximum; evaluate this limitation. Values shown in chat were illustrative.

Reuse embeddings until their content/model configuration changes. This approval is
for a first algorithm to test, not approval to start implementing or evidence that
it outperforms the baseline. It also does not establish that a single vector index
query can compute the complete multi-requirement aggregation; retrieval and scaling
must be designed for this actual scoring function.

## Approved database design — users

Conceptual schema approved; no migration or live database has been created.

| Field | Type / constraint | Purpose |
|---|---|---|
| user_id | UUID primary key | Internal account identifier for related records |
| google_sub | Text, unique, non-null | Stable Google subject from a verified token |
| display_name | Text, nullable initially | Prefilled where available, confirmed during onboarding |
| created_at | Timestamp | Account creation time |
| updated_at | Timestamp | Last account-details update |

One row per student account. No password or stored email field for this MVP;
there is no approved email-based feature. Keep display_name outside matching input.
Use google_sub to find/create the account after verified Google login; the unique
constraint prevents duplicate accounts under retries/concurrent login requests.
Use user_id in application relationships so other tables do not depend directly
on Google's identifier. Exact defaults, timestamp timezone, name validation and
conflict-handling SQL will be specified in the database/API contract.

## Approved database design — sessions

Conceptual schema approved; implementation/library integration remains pending.

| Field | Type / constraint | Purpose |
|---|---|---|
| token_hash | Hash value, primary key | Lookup for the random browser session token; store hash only |
| user_id | UUID foreign key to users.user_id | Session owner |
| created_at | Timestamp | Session creation time |
| last_active_at | Timestamp | Last qualifying activity for the 30-minute idle limit |
| expires_at | Timestamp | Fixed deadline, 8 hours after creation |

One user has zero or many sessions; separate devices may have separate sessions.
Backend hashes the presented token and checks the row plus both expiry limits.
Logout deletes the current session row; subsequent use fails while other sessions
remain unaffected. Expired-row cleanup is separate from request-time rejection.
Token-generation/hash details, cookie settings, session-library choice, qualifying
activity, cleanup schedule and database delete rules remain contract details.

## Approved database design — resume_profiles

Conceptual fields approved; no migration created. Embedding storage remains open
until granularity and model are selected.

| Field | Type / constraint | Purpose |
|---|---|---|
| user_id | UUID primary key and foreign key to users.user_id | One current profile per student |
| content | JSONB | Approved cleaned skills, projects, experience and education |
| revision | Integer | Associate embeddings with the matching content version |
| created_at | Timestamp | Initial profile creation |
| updated_at | Timestamp | Last approved content change |

Relationship: users 1 → 0..1 resume_profiles. JSONB holds variable-length resume
sections; define and validate an exact nested schema rather than accepting arbitrary
JSON. Load personal profiles by user_id; keep bulk job filters in their appropriate
queryable fields. revision does not imply a history feature. Replacement must still
save content and corresponding embeddings atomically; stale-request conflict rules
and delete/recreate revision behaviour remain to be specified.

## Open-source reuse shortlist

Three subagents inspected source and tests. This was static research: no installs,
execution, passing-test claims, runtime benchmarks or integrated security audit.
Only the application foundation and stack above are approved; other shortlisted
components remain candidates. Pin compatible versions and preserve licence
notices before incorporating code. Model weights have separate licences.

### 1. Application base: Full Stack FastAPI Template — approved starting point

- Repo: https://github.com/fastapi/full-stack-fastapi-template
- Licence: MIT.
- Inspected snapshot: `cb740b656d7a0a6c5e12c7bf8e50343ec94ee9c7`.
- Existing email/password signup/login, password recovery, account settings,
  password hashing, JWT authentication, PostgreSQL, React/TypeScript, generated
  API client and test infrastructure.
- Owner-scoped example records and negative permission tests can be adapted.
- Logout currently removes a localStorage token and navigates; this is not
  server-side token revocation. Define our desired session and cache-clearing policy.
- Superuser access needs explicit consideration for private resume data.
- Inspected latest template requires Python >=3.14. Compatibility with ML packages
  is unverified; do not blindly adopt latest or merge unrelated lockfiles.
- Student onboarding, resume models and our domain behaviour remain adaptations.

Source anchors at the inspected snapshot:

- [Account routes](https://github.com/fastapi/full-stack-fastapi-template/blob/cb740b656d7a0a6c5e12c7bf8e50343ec94ee9c7/backend/app/api/routes/users.py)
- [Authentication hook](https://github.com/fastapi/full-stack-fastapi-template/blob/cb740b656d7a0a6c5e12c7bf8e50343ec94ee9c7/frontend/src/hooks/useAuth.ts)
- [Owner-scoped records](https://github.com/fastapi/full-stack-fastapi-template/blob/cb740b656d7a0a6c5e12c7bf8e50343ec94ee9c7/backend/app/api/routes/items.py)
- [Permission tests](https://github.com/fastapi/full-stack-fastapi-template/blob/cb740b656d7a0a6c5e12c7bf8e50343ec94ee9c7/backend/tests/api/routes/test_items.py)
- [Dependencies](https://github.com/fastapi/full-stack-fastapi-template/blob/cb740b656d7a0a6c5e12c7bf8e50343ec94ee9c7/backend/pyproject.toml)

### 2. Upload UI: choose one existing approach

**react-dropzone** — MIT: https://github.com/react-dropzone/react-dropzone

Existing drag/drop, file picker, type/size/count checks and tests. This handles
selection, not API transport or trusted server validation. The inspected main
implementation is `src/index.tsx`; verify paths at the chosen release.

**Resume-Matcher upload hook** — Apache-2.0:
https://github.com/srbhr/Resume-Matcher

Inspected snapshot: `3a3186eaacbb2819639ccbb8d336ad8d9cbeaa84`.

- [Hook](https://github.com/srbhr/Resume-Matcher/blob/3a3186eaacbb2819639ccbb8d336ad8d9cbeaa84/apps/frontend/hooks/use-file-upload.ts)
- [Lifecycle tests](https://github.com/srbhr/Resume-Matcher/blob/3a3186eaacbb2819639ccbb8d336ad8d9cbeaa84/apps/frontend/tests/use-file-upload.test.tsx)

Handles cancellation and stale completions; adapt API imports and PDF-only/5 MB
configuration. Its dialog is coupled to tailored resumes and translations.
Do not adopt both upload abstractions without a reason.

**Correction to earlier research:** its current inspected backend uses SQLAlchemy
and SQLite, with TinyDB migration support; the README-based TinyDB description was
outdated. The inspected resume model/routes do not provide our user ownership.
The upload pipeline retains raw markdown and can send it to an LLM parser before
our cleanup step. Do not reuse that backend unchanged.

- [Database](https://github.com/srbhr/Resume-Matcher/blob/3a3186eaacbb2819639ccbb8d336ad8d9cbeaa84/apps/backend/app/database.py)
- [Resume routes](https://github.com/srbhr/Resume-Matcher/blob/3a3186eaacbb2819639ccbb8d336ad8d9cbeaa84/apps/backend/app/routers/resumes.py)

### 3. PDF extraction: pdfplumber — recommended dependency

- Repo: https://github.com/jsvine/pdfplumber — MIT.
- [PDF lifecycle](https://github.com/jsvine/pdfplumber/blob/stable/pdfplumber/pdf.py)
- [Existing tests](https://github.com/jsvine/pdfplumber/blob/stable/tests/test_basics.py)
- Accepts byte streams and extracts text from text-based PDFs.
- Application must enforce upload/resource limits, reject unusable extraction and
  map parser errors. Closing pdfplumber does not close caller-owned byte streams.
- Close upload/stream resources on both success and failure. Framework buffering
  may touch temporary disk; do not promise memory-only handling without verification.

### 4. Privacy cleanup: Presidio — recommended dependency

- Repo: https://github.com/data-privacy-stack/presidio — MIT; formerly Microsoft Presidio.
- Use Analyzer and Anonymizer libraries inside our backend; separate HTTP services
  are unnecessary for the proposed MVP.
- Existing email/phone and NLP name/location recognisers; existing `redact` operator.
- Singapore `SG_NRIC_FIN` recogniser exists but is disabled by default. Its inspected
  implementation is pattern-based, not checksum validation.
- Default phone regions omit SG: configure Singapore support and test +65/local forms.
- Generic LOCATION recognition does not establish complete home-address removal.
  Address/contact-block rules and false-positive tests may still be needed.
- Never claim guaranteed anonymisation. Avoid destroying project/education/work
  evidence by indiscriminately stripping dates or organisations.

Source anchors:

- [Default recognisers](https://github.com/data-privacy-stack/presidio/blob/main/presidio-analyzer/presidio_analyzer/conf/default_recognizers.yaml)
- [Singapore recogniser](https://github.com/data-privacy-stack/presidio/blob/main/presidio-analyzer/presidio_analyzer/predefined_recognizers/country_specific/singapore/sg_fin_recognizer.py)
- [Phone recogniser](https://github.com/data-privacy-stack/presidio/blob/main/presidio-analyzer/presidio_analyzer/predefined_recognizers/generic/phone_recognizer.py)
- [Redaction operator](https://github.com/data-privacy-stack/presidio/blob/main/presidio-anonymizer/presidio_anonymizer/operators/redact.py)
- [Limitations](https://github.com/data-privacy-stack/presidio/blob/main/docs/faq.md)

### 5. Embeddings and evaluation: Sentence Transformers — recommended dependency

- Repo: https://github.com/huggingface/sentence-transformers — Apache-2.0.
- [Encoding implementation](https://github.com/huggingface/sentence-transformers/blob/main/sentence_transformers/sentence_transformer/model.py)
- [Retrieval evaluator](https://github.com/huggingface/sentence-transformers/blob/main/sentence_transformers/sentence_transformer/evaluation/information_retrieval.py)
- Existing batched encoding and vector normalisation. No custom neural network or
  generic metric implementation needed.
- `InformationRetrievalEvaluator` supports Precision/Recall@K, NDCG, MRR and MAP.
  Our team supplies independently justified labels. Embedding evaluation alone does
  not test all production filters, explanation logic or any reranking.
- Select model using measured quality/latency; decide token limits and long-text
  handling. Query/document prompts depend on the model, not just API naming.
- Proposed efficiency: store embeddings with content/model versions; recompute on
  relevant changes rather than every search. This lifecycle is our integration work.
- Source paths reflect inspected main and may differ in released versions.

### 6. Persistent vector search: pgvector — recommended dependency

- Repo: https://github.com/pgvector/pgvector — PostgreSQL licence.
- [Vector implementation](https://github.com/pgvector/pgvector/blob/master/src/vector.c)
- [Regression tests](https://github.com/pgvector/pgvector/blob/master/test/sql/vector_type.sql)
- Provides vector columns, cosine distance, exact and approximate search in Postgres.
- Can combine owner/eligibility filters and relational records with vector queries.
- Proposed MVP: exact search first, measured before adding approximate indexes.
- No separate FAISS service or hand-built cosine implementation required.

### 7. Selective algorithm reference only: Semantic Resume Ranking System

- Repo: https://github.com/Muskanbawistale/semantic-resume-ranking-system — MIT.
- [Skill matcher](https://github.com/Muskanbawistale/semantic-resume-ranking-system/blob/main/src/ranking/matcher.py)
- [Matcher tests](https://github.com/Muskanbawistale/semantic-resume-ranking-system/blob/main/tests/test_matcher.py)
- [Scorer](https://github.com/Muskanbawistale/semantic-resume-ranking-system/blob/main/src/ranking/scorer.py)

Boundary/alias matching and tests are possible reuse. They do not understand
negation; ordinary “go” can be confused with Go. Prefer confirmed skill data and
describe absence as “not evidenced”, not proof a student lacks a skill.

Do not inherit the scorer wholesale: it ranks many resumes against one job,
re-embeds the job for each resume, creates per-resume FAISS indexes and maps cosine
0.2→0 / 0.8→1 using fixed constants. These are not validated probabilities.
Section-heading rules may help, but are not a long-text token/chunking strategy.
Selective reuse avoids inheriting its entire Streamlit/Groq/FAISS/PyMuPDF stack.

## Remaining design and integration work

### Approved MVP catalogue preparation — 2026-09-11

The user accepted team-prepared catalogue imports to avoid overengineering:
- Team members may use Claude/ChatGPT manually to draft structured requirements,
  inspect the original descriptions and correct the output, then prepare JSON.
- Backend provides a validated import script into PostgreSQL. No runtime hosted
  LLM integration/API key and no admin panel required for this workflow.
- This does not remove resume/job embeddings or semantic matching from the app.
- Updates are team-triggered imports for the initial MVP. Earlier background,
  periodic multi-provider ingestion is a future option, not required MVP scope.
- The importer should reject invalid records, preserve provenance and source
  evidence, update existing source records instead of duplicating them, and only
  regenerate embeddings when matching inputs change. Exact contracts pending.
- Human checking means checking against source text, not merely accepting a
  second model's answer. Independently labelled evaluation examples remain needed.
- JSearch remains a candidate source; storage and redistribution permissions,
  freshness and sufficient catalogue coverage remain unresolved. Manual processing
  does not remove these constraints. Use synthetic fixtures for repeatable tests.

### Approved jobs record and requested filters — 2026-09-11

User accepted the proposed jobs fields and requested job type (part-time/full-time/
internship) and work arrangement (hybrid/remote/on-site) filters.

Accepted fields: job_id; source; source_job_id; title; company_name; country_code;
location; description; apply_url; nullable posted_at; nullable last_verified_at;
is_active; created_at; updated_at. Import time does not prove availability.
Source identity supports repeatable updates; exact uniqueness constraints pending.

Implementation recommendation for the requested filters: separate internship status
from hours, because internships can be full-time or part-time. Use job_type
(INTERNSHIP, OTHER, UNKNOWN), employment_time (FULL_TIME, PART_TIME, UNKNOWN), and
work_arrangement (ON_SITE, HYBRID, REMOTE, UNKNOWN). Exact enum scope/UI pending;
the filter request does not by itself expand the internship catalogue to all jobs.
Do not infer ON_SITE from job_is_remote=false: it does not distinguish hybrid.
Missing source evidence remains UNKNOWN. Different filter dimensions combine with
AND; filter eligible catalogue records before semantic ranking.

### Approved job_requirements starting structure — 2026-09-11

User accepted: requirement_id; job_id; requirement_text; importance (required or
preferred); alternatives (JSONB); source_quote. Each row represents one technical
requirement. Education and duration remain separate eligibility conditions.
Alternatives in a row mean OR, not separate mandatory requirements. Exact JSON
schema and validation remain pending. Vector table structure is approved below;
model revision pin and exact database constraints remain pending. Model and dimensions
are approved below.

Approved initial scoring rule to evaluate (2026-09-11): represent each alternative in
its requirement context (e.g. experience programming in Python), compare each to
resume chunks, and take the maximum across alternatives and chunks as this row's
single semantic score. A row with no alternatives uses requirement_text. Average
required-row scores using the previously agreed initial formula; preferred rows
are informational only and do not affect ranking. Similarity alone does not prove an
explicit alternative is evidenced; show confirmed-skill evidence separately.
Do not flatten AND into OR. Lists introduced by 'such as' can be illustrative rather
than exhaustive; preserve source meaning and flag ambiguous extraction rather than
treating examples as hard eligibility exclusions. Measure the extra maximum-choice
bias introduced by larger alternative sets during evaluation.

### Approved embedding table starting structures — 2026-09-11

- resume_chunks: chunk_id, user_id, profile_revision, text, embedding,
  embedding_version. Each row is one meaningful chunk of approved resume content.
- requirement_embeddings: embedding_id, requirement_id, text, embedding,
  embedding_version. Each row is the requirement matching text or one contextualised
  OR alternative. These rows belong to one logical requirement for scoring.
- Both live in the same PostgreSQL database using pgvector. embedding_version
  identifies model and input-processing configuration; only compatible vectors
  may be compared. Exact version metadata representation and migration are pending.
- Prepare new resume chunks/embeddings first, then atomically replace the profile
  and its chunks. Failed generation preserves the previously usable profile.
- Separate rows support multiple chunks/alternatives and evidence attribution.
  Model and chunk policy are approved below; revision pin, constraints and indexes
  remain pending.

Approved chunking approach (2026-09-11): one project or experience entry per chunk,
retaining its heading and relevant technologies. Skills use a separate explicit
evidence representation; handling skills-only profiles needs a defined policy.
Oversized entries split at bullet/sentence boundaries within the selected model's
token limit, retaining context; do not silently truncate. No personal contact details
in any embedding input.

### Approved initial embedding model and token budget — 2026-09-11

- Use sentence-transformers/all-MiniLM-L6-v2 via Sentence Transformers as the first
  model to evaluate, not a claim of validated matching quality or latency.
- Run downloaded weights in our backend environment, with no hosted embedding API
  required. Hosting compute still has a cost. Model licence: Apache 2.0.
- Both embedding columns use vector(384). Use the same pinned model revision for
  requirements and resumes; the exact revision and dependencies still need pinning.
- Chunk input budget: at most 240 tokens using this model's tokenizer, including
  repeated heading/context. For an unambiguous implementation, count the final
  input with special tokens included. Split long entries at sentence/bullet boundaries;
  oversized individual sentences need tokenizer-bounded splitting. Do not silently
  truncate. Apply input validation to requirement alternatives too.
- Official model card documents 384 dimensions and default truncation beyond 256
  wordpieces: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- A model change requires regenerating both vector sets; matching dimensions alone
  do not make embeddings compatible. Quality and resource usage need evaluation.

### Approved preferred-skill policy — 2026-09-11

Required technical requirements alone determine the MVP semantic ranking.
Preferred requirements are shown separately as additional evidence; no weighting,
bonus points or tie-breaking contribution. Absence is described as not evidenced
in the resume, not proof the student lacks the skill. Semantic similarity alone
must not label a named preferred skill as explicitly evidenced. Exact evidence
matching and display contracts remain pending. This keeps the initial score
interpretable without introducing unvalidated required/preferred weights.

### Approved job details and catalogue freshness — 2026-09-11

Details show description, employer, arrangement, requirements and source link.
Apply opens the original application page in a new tab; our app does not submit
resumes or implement application forms/tracking. Explicitly closed listings are
excluded from browsing/matches; existing detail links show "No longer available"
with Apply disabled. Missing IDs show "Job not found".

Browsing, matching, opening details and clicking Apply do not call job-provider
APIs. Updates are team-triggered imports, with no automatic status polling or
refresh schedule in MVP. Show "Last imported" and explain that availability is
confirmed on the original application page. Store the import time separately from
last_verified_at; exact schema pending. Never infer closure from a partial import.

### Approved ranking presentation boundary — 2026-09-11

User approved relevance-ordered jobs with supporting resume evidence and no headline
match-percentage badge. Numeric semantic scores remain internal for evaluation.
Required technical requirement similarity determines ordering after user filters;
preferred skills and eligibility do not affect ranking. Similarity is neither proof
of qualification nor hiring probability. Closest passages must not automatically
be labelled proof of a required skill. Frontend team owns layout, styling and visual
hierarchy; prior section labels were examples, not mandated UI.
Unavailable-score behaviour is approved below; precise response schemas remain pending.

### Approved matching endpoint behaviour — 2026-09-11

GET /api/matches accepts selected catalogue filters and pagination. Backend resolves
the student from their session, uses their saved resume embeddings, and returns
ordered jobs, supporting passages, preferred-skill evidence and eligibility notes.
Filter changes reuse stored vectors; no PDF re-upload or re-embedding required.
- No saved resume: resume-required response.
- Saved resume with no usable chunks: insufficient-resume-information response.
- No jobs satisfying filters: empty list.
- Job without usable required technical requirements: exclude from ranked matches
  but retain for ordinary browsing. Unavailable score is not a poor-match score.
Precise JSON schemas, HTTP status codes, pagination stability/tie-breaking, query
limits, evidence calculation and compatible-vector failure handling remain pending.
### Approved browsing and product direction — 2026-09-11

User approved separation of ordinary browsing and personalised recommendations.
Product reference is an Indeed-like job browsing experience with embeddings/vector
search added for resume-based recommendations. This is a product direction, not
approval to reproduce all Indeed features or expand beyond the internship MVP.
- GET /api/jobs: active catalogue with filters, no resume required.
- GET /api/matches: personalised ranking, usable saved resume required.
- GET /api/jobs/{job_id}: description, requirements and application link, no resume
  required. Closed-job detail behaviour is approved above.
- All three require login for MVP. Browsing remains possible before resume upload
  and after resume deletion. Earlier upload-first onboarding must allow deferring
  upload for browsing; upload/review/embedding is required for recommendations.
- Browse sort: posted_at descending, null dates last, stable job_id tie-breaker.
- Frontend owns how users switch views. Employer posting, in-app applications and
  application tracking have not been approved by this reference to Indeed.
- Keyword search approved: optional query parameter on GET /api/jobs covering title,
  company and description, combined with existing filters. Ordinary search does not
  require resume embeddings. Exact matching semantics and implementation pending.
- Approved search semantics (2026-09-11): case-insensitive literal keyword matching; all
  whitespace-separated query terms must occur somewhere across those three fields.
  Blank query applies filters only. OR within a multi-select filter, AND between
  dimensions and keyword search. Keep previously approved newest-first browsing
  order; no semantic re-ranking in this endpoint. Exact length limits, punctuation
  handling, escaping and query/index implementation remain contract work.

### Approved eligibility presentation — 2026-09-11

Show employer eligibility conditions (e.g. degree and commitment duration) separately
from semantic similarity as "Check before applying" information. Students check
these conditions themselves for MVP. Do not infer eligibility from embeddings,
award eligibility points, or hide jobs because student information is missing.
No additional eligibility onboarding fields or automated eligibility engine needed
for MVP. User-selected catalogue filters still apply before ranking. Preserve the
source wording; exact eligibility storage and API representation remain pending.

### Job API ingestion discussion — 2026-09-10

User requested consolidation of listings into our database to avoid external API
latency during matching, and authorised provider validation. Architecture direction:
background import from approved providers; student matching reads PostgreSQL.
Provider selection, refresh interval and retention rules remain undecided.

- JSearch: official page explicitly supports `sg`, exposes descriptions/application
  links and advertises 200 requests/month on its direct free plan. Candidate only;
  user activated the free plan and supplied a successful authenticated response;
  initial sample did not validate Singapore internship coverage (see below).
  https://www.openwebninja.com/api/jsearch
- JSearch storage/embedding/redistribution permission is not established by its
  general public terms. Clarify intended academic catalogue use before bulk import.
  https://www.openwebninja.com/terms
- Adzuna standard search returns only description snippets, a poor basis for
  complete requirement extraction. Its terms restrict other ongoing academic uses
  beyond a 14-day validation trial without written consent. Do not assume unrestricted
  aggregation or export. https://developer.adzuna.com/docs/search
  https://developer.adzuna.com/docs/terms_of_service
- Greenhouse Job Board API provides unauthenticated GET and descriptions using
  `content=true`, scoped to employer boards; not a Singapore-wide aggregator.
  https://docs.greenhouse.io/job-board.html
  Live endpoint retrieval was attempted but failed in this environment (web fetch
  unavailable; shell DNS resolution failed). No coverage or result counts verified.

Proposed ingestion safeguards: common job fields, source/provider IDs and links,
  source attribution, fetched/last-seen timestamps, content hashes, idempotent
  upserts and cross-provider deduplication. Re-embed changed requirements only.
  Handle expiry explicitly; a failed/partial import must not mark all unseen jobs
  closed. Maintain last successful catalogue during upstream failures within
  provider retention limits. Keep API credentials server-side; send no resumes.
  Start with one validated provider and add another only for measured coverage gaps.
  Keep reproducible synthetic evaluation fixtures separate from licensed live data.

User-provided live response reviewed on 2026-09-10:
- Request: `query=software internship`, `country=sg`, `language=en`, one page.
- `status=OK`, two jobs under `data.jobs`, with a pagination cursor under `data.cursor`.
- Both jobs have `job_country=US` and US locations: IBM Rochester and Medtronic
  St Paul. Zero Singapore jobs in this page; do not extrapolate to all API coverage.
  The request query omitted explicit Singapore. Country parameter alone did not
  enforce job location in this sample. Next test: query `software internship in Singapore`.
- IBM title/description identify an internship but employment type is FULLTIME;
  do not use the INTERN tag as the sole admission criterion.
- IBM description includes separate required/preferred sections. Medtronic text
  ends mid-phrase at `housing assist`, with no technical requirements visible;
  flag as incomplete instead of inventing or embedding missing requirements.
- Both `job_highlights` objects are empty; structured requirements are not supplied
  in these records. Both application links are indirect; links not independently tested.
- Save only these observations, not account credentials or the raw response.

Second user-provided live response reviewed on 2026-09-10:
- Explicit query `software internship in Singapore`, country sg, language en,
  one page: HTTP 200/status OK; two Singapore records, both country SG, plus cursor.
  Confirms the API can return relevant SG internships, not broad catalogue coverage.
- Asurion Full Stack Engineer Intern: substantive description, but technical tools
  appear under Learning Outcomes; do not promote those to required candidate skills.
  Employment type FULLTIME despite internship title; posting date null. Opening
  sentence invites exploring other opportunities, so current availability needs checking.
- Point Star Developer Intern: clear technical requirements and minimum six-month
  commitment. `employer_name` is Skills Ignition SG - Outplacement Hub; distinguish
  actual employer from publishing intermediary rather than trusting this field blindly.
- Preserve alternatives: experience with at least one of Python, JavaScript or Java
  is one OR requirement, not three mandatory requirements. Eligibility (degree,
  duration) stays separate from technical similarity. This is a concrete extraction
  test case; exact representation is pending design.
- Both highlights empty; application destinations and current availability were not
  independently checked. Do not infer location from `/us/en/` in Asurion's URL.

Validation still needed: broader SG internship yield, complete requirement text,
duplicate/expired listing rates, application links, quotas and explicit permitted
storage/embedding/assessment redistribution. Do not report documentation review as
a passed live integration test.

1. App foundation and dependency versions; login method, sessions, logout and cache isolation.
2. Onboarding fields and resume lifecycle, cleanup/review/replacement/deletion behaviour.
3. Database schema, ownership, API contracts and errors; exact frontend/backend responsibilities.
4. Internship catalogue source and provenance, ingestion/update behaviour, structured requirements.
5. Embedding model, input fields, token/chunking policy, model/content versioning and invalidation.
6. Eligibility filtering, semantic ranking, skill-gap evidence and honest score presentation.
7. Independently labelled evaluation data, baseline and full-pipeline quality/performance tests.
8. AWS deployment, secrets/network controls, monitoring and a measured scale/recovery mechanism.
9. Submission packaging, attribution and teammate build/review guides.

These are not all necessarily custom code: keep checking existing implementations
before building. Do not invent a weighted formula or claim similarity is hiring probability.

## Assessment and reference context

The supplied INF2006 brief permits an open-source baseline; it does not require one.
Assessment is evidence-led: functioning cloud application/API, persistent data,
meaningful data/AI feature, security, operations and an implemented scaling/resilience
mechanism. Four test categories: functional, security, data/AI, scale/resilience/recovery.
Preserve the required manifest, evidence paths, report headings and declarations when
creating final deliverables. Re-read the brief before final packaging.

Original supplied inputs:

- `INF2006_Team_Project_Brief_2026.pdf`
- `Internship_Resume_Semantic_Matcher_PRD.md`

The initial PRD is a proposal, not proof features exist. It leaves important choices
open; this discussion refines it. AWS is preferred, not a selected service architecture.

Reference task: “Create PRD and handoff files”, task ID
`01a08166-a998-7d60-b924-11a2b0ab3786`, INF2003 Jobless Simulator.
Useful patterns: persistent accounts, onboarding, shared API contracts, per-person
coding-agent guides and retry/reload considerations. Do not automatically import its
Google/Supabase login, SQL+Mongo split, swipe/tracker scope or team assignments.

## Checkpoint maintenance

When an agreement changes, update the confirmed/proposed sections explicitly.
Record why a repository/component was selected or rejected. Do not describe a
source-inspected feature as tested in our app. Keep this document portable and free
of credentials or personal resume data. No project implementation was created by
the research captured here.
