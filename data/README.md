# Data and provenance

Field definitions: [DATA_DICTIONARY.md](DATA_DICTIONARY.md). Import contract and bounds:
[../docs/handoff/DATA_API_CONTRACT.md](../docs/handoff/DATA_API_CONTRACT.md).

## Packaged data (synthetic only)

| Path | Contents | Provenance |
|---|---|---|
| `synthetic_jobs.json` | 30 synthetic internship listings (`source: SYNTHETIC`, import schema v1); SHA-256 `7b32914c…aef51a42` (identical to `evaluation/jobs.json`) | Authored with AI assistance on 2026-09-20; fictional employers and text |
| `evaluation/` | 30 jobs, 10 synthetic résumé profiles (5 development, 5 held-out), 300 relevance labels (0/1/2), labelling criteria, review log | Fixtures AI-authored; 210 labels AI-drafted, 90 (profiles P06–P08) supplied by a team member — see `evaluation/LABEL_REVIEW_LOG.md` |
| `evaluation_reviewed_subset/` | The team member's 90 original labels and a separate audit copy with one post-result correction | See `evaluation_reviewed_subset/README.md` |
| `../tests/fixtures/pdf/` | Synthetic résumé PDFs with fictional PII, plus edge cases (encrypted, scanned, 11 pages, not-a-PDF) | Generated for testing; no real person |

Load the synthetic catalogue locally with the importer commands in
[../docs/LOCAL_INTEGRATION.md](../docs/LOCAL_INTEGRATION.md) (dry run first; the import validates the whole batch
before writing).

## Deployed demonstration catalogue (not packaged)

The cloud deployment was loaded with **247 real Singapore internship listings** so the matching could be
demonstrated on realistic text. The 30 synthetic jobs were not loaded into the cloud database.

| Source | Collected | Collection method | Records kept |
|---|---|---|---|
| JSearch (OpenWeb Ninja job-search API, query "internship in Singapore") | 2026-10-01, three reviewed batches | API search; results cached locally | 78 |
| LinkedIn public job listings | 2026-10-01 13:39–13:41 UTC | Apify actor `curious_coder/linkedin-jobs-scraper` (keyword "internship", location Singapore, posted in the past week), 200 candidates | 169 of 200 |

Preprocessing: each record was reviewed source-by-source (AI-assisted, with recorded reasons) and excluded when it
was not an internship, was a duplicate, had no candidate requirements, lacked a Singapore work location, or had an
expired date. Original descriptions are kept verbatim; requirements are extracted as quoted substrings of the source
description; vague posting times are stored as null rather than invented. Each batch has a provenance file
recording query, timestamps, raw-file SHA-256, selected and excluded indices with reasons.

**Why it is excluded from the submission:** redistribution rights for these listings are not established (JSearch
data is subject to the provider's terms; LinkedIn content was collected by a third-party scraper). The records and
their provenance files are kept outside version control (`private-data/`, git-ignored). The brief forbids
proprietary datasets in the package, so markers can reproduce every result with the synthetic data above;
cloud-side counts (247 jobs, 1,588 requirement embeddings, an idempotent re-import) are recorded in
[../evidence/cloud-acceptance-2026-10-03.md](../evidence/cloud-acceptance-2026-10-03.md).

## Responsible use

- No real student résumés are stored in the repository or used in evidence; cloud tests used synthetic PDFs.
- Uploaded PDFs are held only temporarily (S3, 1-day expiry, deleted after extraction); names, emails and phone
  numbers, Singapore addresses, NRIC/FIN-style IDs and URLs are replaced with placeholders (Presidio plus
  app-specific rules) before the student reviews the draft, and only student-approved content is
  embedded.
- Job listings are public postings; the matcher ranks and explains, it does not decide eligibility. Scores are
  similarities, not probabilities of success, and the UI shows the evidence behind each match.
