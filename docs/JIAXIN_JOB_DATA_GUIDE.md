# Preparing job data for the internship matcher

This guide is for preparing a small, reviewable catalogue handoff for Jiaxin. It describes the current importer contract in `src/backend/app/catalogue/schema.py` and the current MiniLM pipeline. The example below is entirely synthetic. Do not treat it as a real vacancy or as permission to collect, retain, or redistribute any provider's listings.

## 1. Confirm the source before collecting

For real listings, first record the source owner/provider, the collection method and date, the applicable licence or written permission, whether storage and display are allowed, any expiry/refresh rule, and any limits on redistribution. Zhihao should review that provenance and permission before real records are added. A source flag only allows the importer to accept a source name; it does not establish permission.

Keep provenance in a separate sidecar such as `approved_jobs_provenance.md` or `approved_jobs_provenance.json`. The importer rejects unknown fields, so do not add `licence`, `collected_at`, `source_name`, or other provenance-only keys inside a job. Use the sidecar to identify the exact JSON batch and source name it covers. Do not commit raw provider snapshots unless their reuse terms permit it.

Use a stable `source` name and the provider's stable `source_job_id` for each record. The pair is the upsert identity. `company_name` must be the actual employer, not the publisher or job board. Use the original listing for `source_url` and the actual application destination for `apply_url`; both must be HTTPS. The importer does not fetch either URL.

## 2. Fill the version 1 job fields

The file root must contain exactly `schema_version` and `jobs`. Each job must contain the required fields below. Extra keys are rejected. Character limits are checked on the input strings; blank required text is invalid.

| Field | Required? | Accepted value and limit | Guidance/default |
|---|---|---|---|
| `source` | Yes | Non-empty string, up to 80 characters | Stable source/provider label. Only `SYNTHETIC` is accepted by default. A real source needs an explicit `--allow-source` flag after permission review. |
| `source_job_id` | Yes | Non-empty string, up to 200 characters | Stable provider listing ID; unique with `source` in a batch and in the database. |
| `title` | Yes | Non-empty string, up to 300 characters | Vacancy title from the listing. |
| `company_name` | Yes | Non-empty string, up to 200 characters | Actual employer. |
| `country_code` | Yes | Uppercase ISO 3166-1 alpha-2 code, or `ZZ` | Use `SG` for Singapore. `ZZ` means unknown; do not guess. |
| `location` | Yes | Non-empty string, up to 300 characters | Preserve the stated location; use a clear value such as `Singapore` only when supported by the listing. |
| `description` | Yes | Non-empty string, up to 50,000 characters | Plain text source description. Keep wording that supports extracted requirements and eligibility quotes. |
| `apply_url` | Yes | HTTPS URL, maximum 2,048 characters | Application link. URL credentials are rejected. |
| `source_url` | Yes | HTTPS URL, maximum 2,048 characters | Original listing/provenance page. URL credentials are rejected. |
| `job_type` | Yes | `INTERNSHIP`, `OTHER`, or `UNKNOWN` | Choose from explicit source facts; no inference from title alone. |
| `employment_time` | Yes | `FULL_TIME`, `PART_TIME`, or `UNKNOWN` | Choose from explicit source facts. |
| `work_arrangement` | Yes | `ON_SITE`, `HYBRID`, `REMOTE`, or `UNKNOWN` | Choose from explicit source facts. |
| `eligibility_notes` | No | Array of note objects; defaults to `[]` | See nested fields below. These are for the student to check, not scoring rules. |
| `posted_at` | No | ISO-8601 timestamp with timezone, or `null` | Defaults to `null`. Use the source posting date when available. |
| `last_verified_at` | No | ISO-8601 timestamp with timezone, or `null` | Defaults to `null`. Supply only when someone actually checked availability; importer never fills it. |
| `is_active` | No | Boolean; defaults to `true` | Set `false` explicitly when a source record is closed or should no longer appear in active catalogue/matches. |
| `requirements` | Yes | 1 to 30 requirement objects | Do not fabricate requirements. At least one row is schema-required; at least one `REQUIRED` row is also needed for the job to appear in Matches. |

Each `eligibility_notes` entry contains exactly:

| Field | Constraint |
|---|---|
| `text` | Non-empty string, maximum 2,000 characters; a plain-language condition for the student to verify. |
| `source_quote` | Non-empty string, maximum 2,000 characters; whitespace-normalized text must occur in `description`. Keep the quote's case and wording faithful because matching is case-sensitive after whitespace normalization. |

Each `requirements` entry contains exactly:

| Field | Required? | Constraint and meaning |
|---|---|---|
| `requirement_text` | Yes | Non-empty, maximum 2,000 characters. One logical requirement in concise language. |
| `importance` | Yes | `REQUIRED` or `PREFERRED`, based on the listing's meaning. Do not promote a preference just to make a listing appear in Matches. |
| `alternatives` | No | Up to 10 non-empty strings, each maximum 2,000 characters; defaults to `[]`. These are OR alternatives for this one requirement. Duplicate alternatives after whitespace/case normalization are rejected. |
| `source_quote` | Yes | Non-empty, maximum 2,000 characters; whitespace-normalized text must occur in the job `description`. |
| `evidence_skills` | No | Up to 20 non-empty strings, each maximum 100 characters; defaults to `[]`. These are canonical, explicitly named skills accepted as evidence for this requirement. They are any-of: a match to one listed skill satisfies the named-skill evidence group. Empty means no explicit-skill claim. |

An AND belongs in separate requirement rows. For example, if a listing requires both Python and SQL, write two `REQUIRED` rows. If it says Python or JavaScript, write one row with `alternatives: ["Python", "JavaScript"]`. The ranker takes the best alternative for a row, then averages scores over REQUIRED rows. PREFERRED rows do not affect ranking. Eligibility notes are displayed separately and are not scored or automatically checked. Evidence skills support the explicit-skill explanation; they do not verify competence.

Keep `source_quote` faithful and independently traceable to the description. Do not create a quote by rewriting a requirement, combining distant sentences, or converting `preferred` language into a requirement. Similarity scoring uses the requirement text or alternative strings, not the full description.

## 3. Understand what the importer creates

Do not author database IDs, hashes, timestamps, embeddings, or rows for generated tables. The importer creates `job_id` UUIDs, `content_hash`, `created_at`, `updated_at`, and `last_imported_at`; it creates `requirement_id` values and ordinal positions; and it creates an embedding for each alternative string or, when there are no alternatives, one embedding for `requirement_text`. Those embeddings are 384-dimensional unit vectors for the pinned `sentence-transformers/all-MiniLM-L6-v2` model revision and are stored with the embedding version.

The relationships are `jobs.job_id` → `job_requirements.job_id` → `requirement_embeddings.requirement_id`. Job identity is unique on `(source, source_job_id)`. Each requirement has an ordinal within its job; each generated embedding has an `alternative_index` within its requirement. Updates replace the changed job's requirement rows and their vectors together. Re-importing unchanged content is idempotent and reuses matching vectors.

Every text sent for an embedding must fit the model's 240 tokenizer-token limit, including tokenizer special tokens. The importer rejects an over-limit requirement/alternative; it does not split a job or a requirement automatically. Shorten a requirement while preserving its meaning and source evidence, or split a genuine AND into separate rows. Do not manually insert vectors with SQL: import through the CLI so the model version, vector dimensions, normalization, relationships, and catalogue revision stay consistent.

## 4. Synthetic schema illustration

This complete one-job file is an example of valid shape only. The employer, listing, IDs, text, and URLs are fictional placeholders; do not import it as a real opportunity. The quotes are present verbatim in the synthetic description to demonstrate validation.

```json
{
  "schema_version": 1,
  "jobs": [
    {
      "source": "SYNTHETIC",
      "source_job_id": "SYNTH-EXAMPLE-001",
      "title": "Example Software Intern",
      "company_name": "Example Fictional Studio",
      "country_code": "SG",
      "location": "Singapore",
      "description": "Example listing for schema illustration only. The successful candidate has experience building small software projects with Python or JavaScript. Applicants must be currently enrolled in a university degree programme. This fictional role is a full-time, on-site internship.",
      "apply_url": "https://example.com/apply/synthetic-001",
      "source_url": "https://example.com/jobs/synthetic-001",
      "job_type": "INTERNSHIP",
      "employment_time": "FULL_TIME",
      "work_arrangement": "ON_SITE",
      "eligibility_notes": [
        {
          "text": "Check that you are currently enrolled in a university degree programme.",
          "source_quote": "Applicants must be currently enrolled in a university degree programme."
        }
      ],
      "posted_at": null,
      "last_verified_at": null,
      "is_active": true,
      "requirements": [
        {
          "requirement_text": "Experience building small software projects with Python or JavaScript.",
          "importance": "REQUIRED",
          "alternatives": [
            "Experience building small software projects with Python.",
            "Experience building small software projects with JavaScript."
          ],
          "source_quote": "The successful candidate has experience building small software projects with Python or JavaScript.",
          "evidence_skills": ["Python", "JavaScript"]
        }
      ]
    }
  ]
}
```

This row represents Python **or** JavaScript. If both were required, use two requirement objects. A job with only PREFERRED rows can pass schema validation, but it is omitted from Matches because the current ranker needs at least one REQUIRED row. Do not change the source's meaning to work around that behavior; flag a genuinely ambiguous or non-matchable record for review.

## 5. Validate, then import in a maintenance window

Prepare the UTF-8 JSON file and the provenance sidecar locally. A batch must contain 1–1,000 jobs. Duplicate `(source, source_job_id)` pairs within one file are rejected; cross-source duplicates are not automatically merged. The importer validates the whole batch before writing anything.

Jiaxin should sync the approved project branch using the team's agreed Git workflow, then run these commands from the repository root. Check `git status --short` first and preserve any existing work. Apply the import separately to each independent database/environment that needs the catalogue; importing one local database does not update another teammate's database. Keep the prepared file on the Docker host and ensure its path is readable by Docker.

For real data, replace the sample paths and source value below with the approved handoff. Set `SOURCE_NAME` to the exact value used in each JSON record. Keep the prepared file outside Git unless its licence permits committing it.

```sh
JOB_FILE="$PWD/path/to/approved_jobs.json"
SOURCE_NAME="APPROVED_PROVIDER"
dc() { docker compose --env-file src/.env "$@"; }

# Start PostgreSQL and wait until its health check passes before the DB-aware dry-run.
dc up -d --wait db || exit $?
dc ps db

# Stop traffic before model loading and embedding validation; PostgreSQL stays up.
dc stop api web
stop_status=$?
if [ "$stop_status" -ne 0 ]; then
  echo "Could not stop api and web; import aborted. Attempting service restart."
  dc up -d api web
  exit "$stop_status"
fi

# Confirm the pinned model is available locally, then validate against the DB.
dc run --rm --no-deps api python -c 'from app.processing.embeddings import EmbeddingModel; m = EmbeddingModel(); print(m.version)'
model_status=$?
if [ "$model_status" -eq 0 ]; then
  dc run --rm --no-deps \
    -v "$JOB_FILE:/tmp/approved_jobs.json:ro" \
    api python -m app.catalogue.import_jobs \
    --file /tmp/approved_jobs.json --dry-run --allow-source "$SOURCE_NAME"
  dry_run_status=$?
else
  dry_run_status=2
fi

# Import only after both checks pass. Repeat this command before restart to check idempotency.
if [ "$model_status" -eq 0 ] && [ "$dry_run_status" -eq 0 ]; then
  dc run --rm --no-deps \
    -v "$JOB_FILE:/tmp/approved_jobs.json:ro" \
    api python -m app.catalogue.import_jobs \
    --file /tmp/approved_jobs.json --allow-source "$SOURCE_NAME"
  import_status=$?
else
  import_status=2
fi

# Always attempt to restore both services, even after validation/import failure.
dc up -d api web
restart_status=$?
if [ "$restart_status" -ne 0 ]; then
  echo "Checks/import exit: $import_status. Service restart failed; inspect docker compose ps and logs."
  exit "$restart_status"
fi
if [ "$import_status" -ne 0 ]; then
  echo "Checks/import failed with exit $import_status; api and web restart was attempted."
  exit "$import_status"
fi
```

The `--allow-source` flag is required for every non-`SYNTHETIC` source, on both dry-run and import. A dry-run without a loaded model can fall back to counts-only validation and still exit successfully. The model preflight must succeed, and the dry-run output should report expected create/update counts and embedding counts before treating it as evidence that token limits and vector generation work. Dry-run writes nothing. The repository contract calls for import offline or in a maintenance window rather than running a second embedding process beside student traffic.

The temporary `run --no-deps` container receives `DATABASE_URL` from the Compose API service environment and can reach the still-running `db` service. Do not run this against production or any shared environment without the responsible human's explicit authorization.

To verify idempotency, repeat the same import invocation inside the maintenance sequence after the first one, before the services restart. For an unchanged batch, expect `created=0 updated=0 unchanged=<number of jobs>` and normally `embeddings_computed=0`. The importer does not create duplicate identities on re-import. Keep the successful output from the first import as well as the re-import output.

Importing a file never removes database rows absent from that file. Existing synthetic rows therefore remain active unless they are explicitly updated. To close a listing, include its identity with `is_active: false` in an approved update; do not delete rows manually. The importer changes only listed identities and updates the catalogue revision when records change.

## 6. Handoff acceptance

Send Zhihao and Jiaxin the JSON and provenance sidecar together with the source permission decision, a short note of transformations, and the dry-run, import, and re-import summaries. Keep the output lines containing created/updated/unchanged counts, computed/reused embeddings, deduplication count, and catalogue revision. Do not share raw listing text through dry-run logs; validation output is designed to report field paths and error codes instead.

After import, confirm with Jiaxin that:

1. Each expected source identity is present once and active/closed state is correct; record totals for jobs, requirements, and requirement embeddings agree with the submitted batch and alternatives.
2. Each requirement/alternative has a vector at the active embedding version, with 384 dimensions. Check embedding counts from the importer and database relationships; do not manually repair missing vectors.
3. The API is healthy after restart and a reviewer can open representative records in the Jobs UI, follow the source/application links, and see eligibility notes.
4. With a matchable synthetic/test resume, representative active jobs with REQUIRED rows appear in Matches and show requirement evidence. A job with only PREFERRED rows is absent by design; eligibility remains a note for the student to verify. Matching order is resume-dependent, so a listing's presence in Jobs alone does not guarantee it ranks on a particular profile.
5. Jiaxin records the exact validation/import outputs and any records deliberately excluded or left inactive, then Zhihao reviews the finished provenance and UI behavior.

## Repository references

- Import validation and field bounds: `src/backend/app/catalogue/schema.py`
- Database relationships and generated columns: `src/backend/app/catalogue/models.py`
- Upsert, embedding, and absence/deactivation behavior: `src/backend/app/catalogue/importer.py`
- CLI and `--allow-source`: `src/backend/app/catalogue/import_jobs.py`
- Model revision, 240-token cap, and 384 dimensions: `src/backend/app/processing/config.py`, `src/backend/app/processing/embeddings.py`
- OR/AND, REQUIRED/PREFERRED, and omission rules: `src/backend/app/matching/scoring.py`, `src/backend/app/catalogue/loader.py`
- Full project contract: `docs/handoff/DATA_API_CONTRACT.md`
