# Human relevance-label review log

**Date:** 2026-10-01
**Scope:** Independent blind human relevance labelling of 90 profile-job pairs
(profiles P06, P07, P08 x all 30 jobs each), replacing the earlier non-blind
adjudication (12 pairs) and unverified-origin label set (48 pairs) described in
`AI_USE_DECLARATION.md`. See `LABELLING_CRITERIA.md` for the labelling rubric
and `labels_human.csv` for the raw output.

## Process

- A reviewer worked from `labelling_sheet_P06-P08.xlsx`, a spreadsheet built
  from `jobs.json` and `profiles.json` that showed each profile's skills,
  projects and experience text alongside each job's required and preferred
  requirements, with a 0/1/2 relevance dropdown and a free-text rationale
  column.
- The spreadsheet did not include the AI-drafted labels from `labels.csv`, so
  the review was blind to the system's own output.
- All 90 rows were completed with a relevance score and a rationale.

## Agreement with the original AI-drafted labels (`labels.csv`)

Comparing the 90 new human labels against the AI-drafted labels for the same
pairs, purely as a sanity/independence check (not a correctness measure,
since the AI-drafted labels are not ground truth):

- **Agreement: 72 / 90 (80.0%)**
- **Disagreement: 18 / 90 (20.0%)**

All 18 disagreements are cases where the human reviewer rated a pair *more*
relevant than the AI draft had it; none went the other way. This is
consistent with an independent review rather than a copy of the AI draft, and
suggests the AI-drafted labels (drawn from the same methodology used
elsewhere in the project) were, if anything, conservative on this subset.

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

## Evaluation results

Precision@5 and NDCG@5 computed with `analytics/evaluate.py` against
`data/evaluation_reviewed_subset/` (jobs.json, a profiles.json filtered to
P06/P07/P08, and this review's `labels_human.csv`) are recorded in
`evidence/test-data-ai.md`.

## Scope and limitations

- This review covers 3 of the 5 held-out profiles (P06, P07, P08) and 0 of
  the 5 development profiles. It does not re-label the full 300-pair set.
  `manifest.json`'s `label_review.status` should reflect this partial scope
  rather than being marked fully complete.
- The reviewer was a member of the project team, not an independent
  third-party rater; inter-rater reliability (e.g. a second reviewer and a
  kappa statistic) was out of scope given time constraints.
