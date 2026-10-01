# Human relevance-label review log

**Date:** 2026-10-01
**Scope:** A team member supplied labels for 90 profile-job pairs (profiles P06,
P07, P08 x all 30 jobs each). The process was recorded as blind, but its
independence and blinding were not independently verified. This superseded the
earlier non-blind adjudication (12 pairs) and unverified-origin label set (48
pairs) described in `AI_USE_DECLARATION.md`. See `LABELLING_CRITERIA.md` for the
fixed rubric and `data/evaluation_reviewed_subset/labels_human.csv` for the
preserved original submission.

## Process

- The recorded process says a reviewer worked from `labelling_sheet_P06-P08.xlsx`, a spreadsheet built
  from `jobs.json` and `profiles.json` that showed each profile's skills,
  projects and experience text alongside each job's required and preferred
  requirements, with a 0/1/2 relevance dropdown and a free-text rationale
  column.
- The spreadsheet reportedly did not include the AI-drafted labels from `labels.csv`.
  This process description is retained as reported; it has not been independently verified.
- All 90 rows were completed with a relevance score and a rationale.

## Agreement with the original AI-drafted labels (`labels.csv`)

Comparing the 90 submitted labels against the AI-drafted labels for the same
pairs (not a correctness or independence test, since neither set is ground truth):

- **Agreement: 72 / 90 (80.0%)**
- **Disagreement: 18 / 90 (20.0%)**

All 18 disagreements in the original comparison are cases where the submitted
label is *more* relevant than the AI draft; none went the other way. Directional
agreement patterns do not establish whether the submission was blind or
independent, nor whether either label set is correct.

| Profile | Job | AI draft | Human |
|---|---|---|---|
| P06 | J06 | 0 | 1 |
| P06 | J07 | 0 | 1 |
| P06 | J10 | 0 | 1 |
| P06 | J14 | 1 | 2 |
| P06 | J20 | 0 | 1 |
| P06 | J27 | 0 | 1 |
| P06 | J28 | 0 | 1 |
| P06 | J29 | 0 | 2 |
| P07 | J04 | 0 | 1 |
| P07 | J11 | 0 | 1 |
| P07 | J25 | 0 | 1 |
| P07 | J26 | 0 | 1 |
| P07 | J27 | 0 | 1 |
| P07 | J29 | 0 | 1 |
| P08 | J07 | 0 | 1 |
| P08 | J22 | 0 | 1 |
| P08 | J28 | 0 | 1 |
| P08 | J29 | 0 | 1 |

## Original-submission evaluation results

Precision@5 and NDCG@5 computed against the preserved `labels_human.csv` are
recorded in `evidence/test-data-ai.md` and the generated
`evidence/data-ai-eval-2026-10-01-human_review_P06_P08.*` report. The evaluator
does not authenticate label provenance.

## Post-result rubric audit — 2026-10-01

After the original-submission evaluation, review against the fixed
`LABELLING_CRITERIA.md` found that P06-J29 was labelled 2 even though the
rationale inferred an ability to explain code from software-development
experience. J29 is explicitly a no-code technical-writing keyword trap; its
required duty is writing clear technical explanations. P06's profile contains
no evidence of writing technical documentation or explanations. Under the
pre-existing keyword-trap rule, the label is 0.

At the user's direction, an AI-assisted audit copy was made at
`data/evaluation_reviewed_subset/labels_audited.csv` on this date. It changes
only P06-J29 (2 to 0) and replaces its rationale with one limited to the
profile evidence and fixed criterion. The original human submission remains
unchanged. This is a post-result correction, not a new human label, independent
review, or human ratification. Original and audited metrics are reported as
separate runs in `evidence/test-data-ai.md`.

## Scope and limitations

- This review covers 3 of the 5 held-out profiles (P06, P07, P08) and 0 of
  the 5 development profiles. It does not re-label the full 300-pair set.
  `manifest.json`'s `label_review.status` should reflect this partial scope
  rather than being marked fully complete.
- The submitter was a member of the project team, not an independent
  third-party rater; inter-rater reliability (e.g. a second reviewer and a
  kappa statistic) was out of scope given time constraints. The post-result
  audit used AI assistance and does not improve independence evidence.
