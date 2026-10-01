# Human-reviewed subset (P06, P07, P08)

Scope: 3 of the 5 held-out profiles (P06, P07, P08), all 30 jobs each = 90 pairs,
independently blind-labelled by a human team member (not Chuying's earlier non-blind
adjudication, which was removed — see `AI_USE_DECLARATION.md`).

This is a **separate fixture directory**, not a replacement for `data/evaluation/`.
`analytics/evaluate.py` requires every profile in `profiles.json` to have every job
labelled, so a partial (90-row) label set cannot run against the full 10-profile
`data/evaluation/profiles.json` without erroring. Scoping it here keeps the result
honest: it is reported as "3 of 5 held-out profiles, human-reviewed," not blended
into or presented as the full headline result.

P01-P05 (development) and P09-P10 (held-out) remain AI-drafted only, tracked in
`data/evaluation/`.

## How to run

1. Put your completed `labels_human.csv` (from `labelling_tool.html`) in this folder.
2. `python analytics/evaluate.py --fixtures data/evaluation_reviewed_subset --labels data/evaluation_reviewed_subset/labels_human.csv --out-dir evidence`
3. This produces real P@5/NDCG@5 for P06-P08 only, computed by evaluate.py exactly as
   defined (requirement-level cosine matching vs BM25/pooled-chunk/whole-resume
   baselines), from human-reviewed labels, not AI-drafted ones.
