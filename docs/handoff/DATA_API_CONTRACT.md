# Database, API and import contract

Implementation defaults resolved 2026-09-11. This is a specification; migrations/OpenAPI must be generated and tested by implementers. Read [PRD](MVP_PRD.md) and [architecture](ARCHITECTURE.md).

## Common conventions

UUID primary keys generated server-side; UTC timestamptz timestamps, ISO-8601 JSON. Required unless marked nullable. API prefix /api. Enums are uppercase strings. Parameterized SQL only. Apply DB constraints as well as request validation. Never return vectors, google_sub, session hashes or internal ranking scores to the browser. All student data derives from the authenticated session.

## Schema

### users

`user_id uuid PK; google_sub text UNIQUE; display_name varchar(100) NULL; resume_revision bigint DEFAULT 0 CHECK >=0; created_at; updated_at`.

resume_revision is a monotonic account-level counter. Increment on successful changed save and deletion, never reset when a profile is deleted. This small addition prevents old-tab saves from resurrecting deleted/recreated profiles. Display name trims whitespace and rejects controls; 1–100 characters when set. Do not persist Google email or token.

### sessions

`token_hash char(64) PK; user_id FK users ON DELETE CASCADE; csrf_token text; created_at; last_active_at; expires_at`.

Generate 32 random bytes each for opaque token and CSRF token; store SHA-256 of the session token, and the session-bound CSRF token in this restricted table (never log either). Absolute expires_at = created_at +8h; idle expiry = last_active_at +30m. Reject when either is reached. Index user_id and expires_at. Cookie: HttpOnly, Secure, SameSite=Lax, Path=/, no Domain; use __Host-session in HTTPS. Local loopback HTTP may use a different cookie name with Secure=false, allowed only in explicit development mode. No localStorage credentials.

### resume_profiles

`user_id PK FK users CASCADE; revision bigint; content jsonb; content_hash char(64); embedding_version text; created_at; updated_at`.

revision equals users.resume_revision at commit. One active profile; no history. Canonical content serialization hash covers approved matching content. Save identical content/config as a no-op, retaining revision and vectors. content contains the following fixed JSON shape (extra fields rejected):

```json
{
  "skills": ["Python", "PostgreSQL"],
  "projects": [{"title": "Course project", "description": "Built an API using Python.", "technologies": ["Python"]}],
  "experience": [{"title": "Software intern", "description": "Implemented API tests.", "technologies": ["Python"]}],
  "education": [{"qualification": "BSc Computer Science", "details": "Currently studying"}]
}
```

All arrays may be empty; not all content may be blank. Limits: 100 unique skills, 100 chars each; at most 20 projects, 20 experience entries, 10 education entries; titles/qualifications 200 chars; descriptions/details 5,000 chars each; technologies at most 30 ×100 chars; whole canonical text <=50,000 characters. JSON request body <=256 KiB. Entries have no names/contact fields. Only projects/experience produce semantic chunks. Blank entries removed with validation feedback; do not invent missing projects.

### resume_chunks

`chunk_id uuid PK; user_id FK resume_profiles(user_id) CASCADE; profile_revision bigint; section text CHECK IN ('PROJECT','EXPERIENCE'); entry_index int; chunk_index int; text text; embedding vector(384); embedding_version text`.

UNIQUE(user_id, section, entry_index, chunk_index). Index user_id. Require nonempty text, nonzero finite normalized vector, version matching profile. All chunks replaced in same transaction as profile. Stable source indexes enable evidence display. Safety cap 100 chunks/profile; reject overflow with instructions to shorten content, never silently discard it.

### jobs

`job_id uuid PK; source varchar(80); source_job_id text; title varchar(300); company_name varchar(200); country_code char(2); location varchar(300); description text; apply_url text; source_url text; job_type text; employment_time text; work_arrangement text; eligibility_notes jsonb; posted_at NULL; last_verified_at NULL; last_imported_at; is_active boolean DEFAULT true; content_hash char(64); created_at; updated_at`.

UNIQUE(source, source_job_id). country_code uppercase ISO code or ZZ unknown. Enums: job_type INTERNSHIP/OTHER/UNKNOWN; employment_time FULL_TIME/PART_TIME/UNKNOWN; arrangement ON_SITE/HYBRID/REMOTE/UNKNOWN. Eligibility JSON array: objects with `text` and `source_quote`, both strings, no automatic eligibility decisions. URLs: HTTPS, no embedded credentials, max 2,048 chars; importer does not fetch arbitrary URLs. description <=50,000 chars. Index active/posting date/job_id and evaluate filter indexes with query plans. Last imported is not last verified.

### job_requirements

`requirement_id uuid PK; job_id FK jobs CASCADE; ordinal int; requirement_text text; importance text CHECK IN ('REQUIRED','PREFERRED'); alternatives jsonb; source_quote text; evidence_skills jsonb`.

UNIQUE(job_id,ordinal). At most 30 requirements/job, requirement text <=2,000 chars, source quote must appear in the normalised description. `alternatives` is 0–10 contextualized text strings. Empty means embed requirement_text once. Multiple alternatives mean OR; split AND into rows. `evidence_skills` is 0–20 canonical strings representing acceptable explicitly named skills, e.g. ["Python","JavaScript","Java"]. Empty means no automatic explicit-skill claim. `such as` examples do not become hard qualification checks; no such exclusions exist in MVP. Deduplicate normalized identical requirements during import; semantic duplicates require team review.

### requirement_embeddings

`embedding_id uuid PK; requirement_id FK job_requirements CASCADE; alternative_index int; text text; embedding vector(384); embedding_version text`.

UNIQUE(requirement_id,alternative_index), index requirement_id. Nonempty/finite/nonzero/normalized vectors. For no alternatives, one index=0 vector from requirement_text. Required and preferred may both be embedded for closest-passage display, but only required affects ranking.

### save_operations (technical support table, not a new user feature)

`user_id FK users CASCADE; operation_id uuid; payload_hash char(64); state text; expected_revision bigint; result_revision bigint NULL; failure_code text NULL; created_at; updated_at; expires_at; PRIMARY KEY(user_id,operation_id)`.

States PROCESSING/SUCCEEDED/FAILED. Retention 24h; retain metadata only, no content. FK users, not profile, so operations survive profile deletion without storing deleted text. Index expires_at. Table is needed for approved durable idempotency; seven domain tables alone did not cover it.

### app_state

Singleton row `id int PK CHECK id=1; catalogue_revision bigint DEFAULT 0`. Increment on successful changed import. Supports detecting catalogue changes between pagination requests. This is metadata, not another service.

## Authentication and CSRF

- GET /api/auth/bootstrap: unauthenticated; issues short-lived pre-login cookie and synchronizer CSRF token for Google exchange. Validate configured Origin on all unsafe requests. Implementation default: random nonce and expiry signed with APP_SIGNING_KEY in an HttpOnly pre-login cookie; return the nonce as csrf_token, then verify signature, expiry and header equality on exchange. Expire cookie after successful exchange. Use a maintained signing library; do not log token/cookie.
- POST /api/auth/google body {credential}; bootstrap CSRF header required. Verify signature, issuer, expiry and exact configured audience with google-auth; never decode without verification. Find/create by verified sub; rotate app session. Return current user and a new CSRF token; erase credential.
- GET /api/me returns {user:{user_id,display_name},resume_revision,has_resume,has_matchable_resume,csrf_token}. Read the session-bound CSRF token from the restricted sessions row. It is stable for this session so tabs do not invalidate one another. The opaque session credential remains HttpOnly; CSRF token alone cannot authenticate. Rotate both on a new login, not on each GET.
- PATCH /api/me body {display_name}; no embedding changes.
- POST /api/auth/logout invalidates current session, clears cookies, returns 204; already-expired session also returns 204 after Origin validation.

All other endpoints require session. Unsafe requests require X-CSRF-Token constant-time match plus exact Origin allowlist. GET does not mutate domain data; session activity timestamp maintenance is allowed. Qualifying user-initiated domain reads/writes update last_active_at. /health, auth bootstrap, /me and operation-status checks do not extend inactivity; no automated domain polling. Throttle DB activity updates to once/minute without weakening absolute expiry. Local test-auth dependency override must fail startup in non-test deployment.

## Endpoint table

| Method/path | Request | Success |
|---|---|---|
| GET /api/jobs | q, filter arrays, limit, offset, catalogue_revision optional | 200 JobPage |
| GET /api/jobs/{id} | UUID | 200 JobDetail, including closed records |
| POST /api/resume/prepare | multipart file | 200 {draft:ResumeContent,unassigned_text:string,warnings:[{code,message}]} |
| GET /api/resume | none | 200 {revision,content,embedding_version,has_matchable_resume}, or 404 |
| PUT /api/resume | {expected_revision,content}; Idempotency-Key UUID | 200 {operation_id,result_revision,changed} |
| DELETE /api/resume | {expected_revision} | 200 {resume_revision,has_resume:false} |
| GET /api/resume/operations/{id} | UUID | 200 {operation_id,state,result_revision,failure_code} |
| GET /api/matches | filters, limit, offset, catalogue_revision/profile_revision optional | 200 MatchPage |
| GET /health/live | none | 200 process alive |
| GET /health/ready | none | 200 dependencies/model ready, else 503; no details exposed |

No user_id parameter on private endpoints. DELETE locks users row and checks revision; if no profile exists and expected_revision is current, return unchanged revision. Otherwise delete profile/chunks and increment users.resume_revision atomically. Old save operations cannot recreate content. On uncertain delete outcome GET /me and /resume establishes current state.

### Search, filters and pagination

q <=200 chars and <=10 whitespace-delimited terms; trim/casefold for search, literal substring terms (punctuation preserved); parameterize and escape SQL LIKE wildcards %, _ and backslash. All terms must occur across concatenated title/company/description. It is literal matching, not fuzzy/full-text stemming. Limit default20, range1–50; offset0–10,000. Reject invalid enum/query with422.

Filters: job_type[], employment_time[], work_arrangement[]; omitted is unrestricted, OR within array, AND across dimensions. Unknown values only match if selected or dimension unrestricted. Both views use active jobs; initial imports are curated SG internships, OTHER does not imply planned non-intern expansion. Browsing sorts posted_at DESC NULLS LAST, job_id ASC. Matches sort internal score DESC, job_id ASC. Reset offset on filter changes.

Every page returns catalogue_revision and matches also profile_revision. Subsequent pages send these; changed revisions return409 RESULTS_CHANGED to restart pagination. No saved result cache needed. Calculate a page and its revision in one consistent DB snapshot. Mid-list consistency is detected, not promised indefinitely.

### Public response shapes

JobSummary: job_id,title,company_name,country_code,location,job_type,employment_time,work_arrangement,posted_at,last_imported_at,is_active.

JobDetail extends summary with description,apply_url,source,source_url,last_verified_at,eligibility_notes,requirements[{requirement_id,requirement_text,importance,alternatives,source_quote}]. Treat content as text, never render unsanitized provider HTML. Closed detail response has is_active=false. Source links and apply links open with noopener/noreferrer.

JobPage: {items:[JobSummary],total,limit,offset,catalogue_revision}.

MatchPage: {items:[{job:JobSummary,requirements:[{requirement_id,importance,closest_passage:{text,section,entry_index},explicit_skill_evidence:[string],named_skills_not_evidenced:[string]}],eligibility_notes}],total,limit,offset,catalogue_revision,profile_revision}.

For an OR evidence group, if any acceptable confirmed skill matches, return it in explicit_skill_evidence and an empty not-evidenced list; otherwise list its named alternatives as one group, never separate missing mandatory requirements. Normalize case/whitespace and a small versioned alias map; use whole skills from the approved skills array, not substring scan of prose (avoids “go” confusion). Exact skill evidence is self-reported, not competence verification. Requirements without evidence_skills only show closest passage. Do not return numeric cosine or invent strength labels.

## Ranking implementation contract

Use pgvector cosine distance (`1 - distance`) and exact aggregation: filter jobs first; join REQUIRED requirements and their vectors to only the authenticated user's current chunks; max across alternatives/chunks per requirement; mean across required requirements per job. No early vector top-k truncation before averaging. Preferred comparisons only for returned page. Exclude zero-required jobs; require complete expected compatible vectors for a job, otherwise omit that job and emit diagnostic count (do not average just available requirements). Mixed/unavailable active profile version returns503 MODEL_VERSION_UNAVAILABLE. Profile with no chunks returns422 INSUFFICIENT_RESUME_INFORMATION. Duplicate logical requirements must not count twice.

## Save transaction and retries

1. Authenticate, CSRF and schema check; canonicalize content. Key scope is user + PUT resume. Payload hash includes expected_revision, content and embedding_version.
2. Lookup key before admission: hash mismatch409 IDEMPOTENCY_CONFLICT; SUCCEEDED replay returns original result_revision without saving; frontend then GETs current profile and never installs stale replay content. PROCESSING returns409 SAVE_IN_PROGRESS with Retry-After:3. FAILED returns stored failure; new explicit attempt gets new key. Never automatically retry deterministic validation failures.
3. If new key, attempt nonblocking processing admission. Busy503 PROCESSING_BUSY/Retry-After:3; no operation row created so same attempt can retry. Insert PROCESSING row under unique constraint; duplicate insert releases slot and follows replay path.
4. Recheck privacy. On changes return422 REVIEW_REQUIRED with only cleaned replacement draft; do not persist raw body. Persist terminal failure code but not draft. New confirmation creates new key.
5. For identical canonical content and embedding version, skip generation; still check expected revision and mark the no-op outcome transactionally. Otherwise prepare vectors outside transaction. In a short transaction lock users row, verify expected_revision, upsert profile and replace chunks; increment revision only on changed content/version. Mark operation SUCCEEDED in that SAME transaction. First save expects revision0 or current post-delete revision.
6. Failure before commit preserves profile and records sanitized FAILED. Database connection loss during commit is unknown: consult operation after reconnect; do not assert failure or overwrite a possibly committed success. On single-instance startup after old process is certainly dead, recover remaining PROCESSING rows as FAILED/PROCESS_INTERRUPTED (successful commit would have stored SUCCEEDED atomically).
7. Release admission only after child ends and transaction outcome handling completes. Operation status never returns prior content. Expired operation lookup404 OPERATION_EXPIRED; client fetches current profile before proposing another save. Expected revision prevents blind stale replay after key expiry.

## Error envelope

```json
{"error":{"code":"PROCESSING_BUSY","message":"Resume processing is busy. Please retry shortly.","request_id":"server-generated-id","retryable":true,"details":{}}}
```

400 malformed request;401 AUTH_REQUIRED/SESSION_EXPIRED;403 CSRF_INVALID;404 JOB_NOT_FOUND/RESUME_NOT_FOUND/OPERATION_EXPIRED;409 REVISION_CONFLICT/RESULTS_CHANGED/IDEMPOTENCY_CONFLICT/SAVE_IN_PROGRESS;413 FILE_TOO_LARGE/BODY_TOO_LARGE;415 PDF_REQUIRED;422 PDF_UNREADABLE/PDF_ENCRYPTED/TEXT_REQUIRED/REVIEW_REQUIRED/INVALID_CONTENT/RESUME_REQUIRED/INSUFFICIENT_RESUME_INFORMATION;503 PROCESSING_BUSY/MODEL_VERSION_UNAVAILABLE/SERVICE_UNAVAILABLE;504 PROCESSING_TIMEOUT;500 INTERNAL_ERROR.

Only whitelist details: safe field names, current revision, or cleaned draft for REVIEW_REQUIRED. Never embed parser exception text or rejected sensitive values. Retryable false for validation/auth/conflict requiring user correction; true for busy and transient infrastructure. Browser timeout is a client unknown-outcome state, not a fabricated server error. Backoff should be user-visible; no tight automatic polling.

## Catalogue import contract

CLI accepts UTF-8 JSON {schema_version:1,jobs:[...]}; each job includes jobs fields except generated IDs/timestamps/hash, and requirements/eligibility_notes. Allowed sources SYNTHETIC or a provenance-labelled approved provider. last_verified_at optional explicit team evidence, never auto-filled by import. Validate whole batch before writes, including matching source_quote, HTTPS URLs, bounds, enums and duplicate source identities. Review company_name separately from publisher. Max batch1,000 jobs; split larger imports deliberately.

Dry-run prints counts/errors without descriptions. Compute matching-input hashes; reuse unchanged embeddings. Changing display/source timestamps alone does not regenerate vectors. Generate required vectors first, then upsert affected records and increment catalogue_revision atomically; an invalid batch/embedding failure leaves prior catalogue intact. Reconcile requirements by ordinal inside changed jobs; no external clients rely on retained requirement IDs after catalogue revision changes. No deletion from absence; is_active=false is explicit. Cross-provider duplicates are flagged for manual curation using employer/title/location/apply URL, not automatically merged by an unreliable heuristic.

Run import offline or in a maintenance window, not simultaneously as an unbounded second embedding process beside student traffic. No provider credentials needed for importing synthetic/prepared JSON. Raw job provider snapshots are not committed without reuse permission. Include original source and license/provenance manifest in submitted sample data.
