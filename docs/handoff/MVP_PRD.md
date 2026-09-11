# Internship Matcher — MVP PRD

Status: implementation handoff, 2026-09-11. Design specification, not a claim of implemented or tested software.

## Read first

Read this document, [architecture](ARCHITECTURE.md), [database/API contract](DATA_API_CONTRACT.md), then [implementation guide](IMPLEMENTATION_GUIDE.md). These consolidated documents govern implementation where the chronological DESIGN_CHECKPOINT contains older proposals. User decisions remain authoritative. Routine defaults below were resolved under the user's instruction to finish the handoff without further field-by-field approvals.

## Product and scope

Build a familiar, internship-focused job browsing app with personalised recommendations from approved resume content. Team: Jiaxin and Chuying backend; Xue E and Nasya frontend; Zhihao system design/moderation/review. Three-week implementation window. Local MVP first; $50 total AWS budget constraint. No resources are deployed by this specification.

### Included

- Google login, server-side sessions, logout, display-name confirmation.
- Browse active jobs, literal keyword search, job type/hours/arrangement filters, pagination and job details.
- Optional PDF upload by drag/drop or local picker; cleaned editable review; confirm/save, edit, replace and delete matching profile.
- Requirement-level semantic ranking, closest supporting passages, separate explicit skill evidence and eligibility notices.
- Team-prepared JSON catalogue, validated command-line import and reusable job embeddings.
- Controlled overload, safe retries, restricted diagnostics, functional/security/AI/recovery tests.

### Deferred

Password login, employer accounts/posting, in-app applications, saved jobs, application tracking, runtime LLM extraction, admin panel, scheduled provider ingestion, OCR, multilingual guarantees, fine-tuning, queues, load balancing, autoscaling and managed database. Referencing Indeed does not import its full feature set.

## User journeys and acceptance

| ID | Journey | Acceptance |
|---|---|---|
| P01 | Sign in | Verify Google identity server-side; stable subject maps to one account. Display name is editable and excluded from matching input. |
| P02 | Browse without resume | Authenticated student may skip upload. Blank keyword shows filtered active catalogue; newest known posting date first, unknown dates last. |
| P03 | Search | Case-insensitive literal terms across title/company/description; all query terms required; OR within a filter, AND across dimensions. No embedding generation. |
| P04 | View/apply | Details include source and import date. Apply opens external source in a new tab, without sending our resume. Closed details remain visible with Apply disabled; unknown ID is not found. |
| P05 | Prepare PDF | One text PDF up to 5 MiB; reject scanned/encrypted/unreadable files clearly. Remove unnecessary PII before returning review content. Original file and raw extraction are transient only. |
| P06 | Review/save | Edit content, not vectors. Confirm triggers another privacy check, chunking and embedding. Save content and vectors atomically. Existing profile survives failed preparation. |
| P07 | Retry | Repeated save has one effect. Stale revision cannot overwrite newer work; timeout is an unknown outcome until resolved. Draft remains in browser memory while the page is open. |
| P08 | Delete | Delete current resume content/chunks and clear UI caches; account remains and browsing still works. Re-upload can create a new profile. |
| P09 | Recommend | Apply filters, score required technical requirements, order descending. Preferred skills and eligibility do not change score. No headline percentage or hiring-probability claim. |
| P10 | Missing information | No profile and no usable chunks have distinct actionable states. Unscorable jobs stay browsable but are excluded from recommendations. No matching jobs is a normal empty list. |
| P11 | Overload | One expensive operation per instance; extra work receives a bounded busy response. Browsing must still work; failure releases capacity only when work has stopped. |
| P12 | Session ends | 30-minute inactivity / 8-hour absolute expiry. Logout invalidates browser session and clears private caches. Refresh/closing loses unsaved drafts; saved data persists. |

## Matching behaviour

Initial model: sentence-transformers/all-MiniLM-L6-v2, 384 dimensions, same pinned revision for both sides. Normalize vectors. Input limit is 240 tokenizer tokens including heading and special tokens. Project and experience entries are meaningful chunks; split long entries by sentence/bullet, then token boundaries as necessary, retaining context. Do not silently truncate.

For required requirement r, contextual alternatives A(r), and resume chunks C:

`requirement_score(r) = max(cosine(a, c) for a in A(r), c in C)`

`job_score = mean(requirement_score(r) for each required r)`

A requirement without alternatives has one matching text. Deduplicate identical requirements. OR counts once; AND becomes separate requirements. Examples introduced by “such as” are not hard eligibility exclusions. All scores are internal. Ranking is experimental until independently evaluated. Longer resumes and larger alternative sets can gain more chances at a high maximum; include this in evaluation.

Skills-only profiles may be saved but do not produce semantic recommendations until a project/experience entry exists. Education remains visible in profile but is not embedded in this MVP. Skills are user-confirmed claims, not verified competence. Named-skill evidence uses exact normalized matches against confirmed skills, not cosine thresholds. Closest passages are always labelled as closest passages, not proof the requirement is fulfilled.

## Data and freshness

Team may use chat tools to draft job requirements, then check against source text. No runtime LLM key. Preserve source wording, OR meaning, required/preferred classification, and learning outcomes. Only import data with permitted use; JSearch has returned two relevant SG internships, but catalogue coverage and storage/export permissions are unresolved. Synthetic fixtures unblock all local work. Do not submit provider data without appropriate rights.

No user request calls the provider API. Show last imported time, not “live”. Closing a listing is explicit; absence from a partial import does not close it. Students confirm availability on the external application page.

## Delivery gates

1. Local vertical slice works with synthetic catalogue and real Google login; deterministic test auth is isolated to test configuration.
2. Tests and evaluation produce honest dated evidence; unknowns/failures are documented.
3. After local pass: choose VM size from observed peak memory and current verified estimate, then obtain deployment approval. Persistent cloud data, health/recovery and redacted evidence are required.
4. Final brief packaging is reproducible without a live cloud account. No invented performance results or team contributions.
