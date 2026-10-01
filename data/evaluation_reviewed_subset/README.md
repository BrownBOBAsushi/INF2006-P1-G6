# Human-submitted subset and audited label set (P06, P07, P08)

Scope: 3 of the 5 held-out profiles (P06, P07, P08), all 30 jobs each = 90 pairs.
`labels_human.csv` is the original human-submitted file and is preserved byte-for-byte.
The recorded process describes blind completion, but that independence and blinding
were not independently verified. After the first evaluation, a rubric inconsistency
was found in P06-J29. `labels_audited.csv` is a separately named copy with one
AI-assisted, user-authorized correction (2 to 0) on 2026-10-01. It is not a new
human label, independent review, or human ratification. See
`data/evaluation/LABEL_REVIEW_LOG.md` and `AI_USE_DECLARATION.md`.

This is a **separate fixture directory**, not a replacement for `data/evaluation/`.
`analytics/evaluate.py` requires every profile in `profiles.json` to have every job
labelled, so a partial (90-row) label set cannot run against the full 10-profile
`data/evaluation/profiles.json` without erroring. Scoping it here keeps the result
honest: it is reported as "3 of 5 held-out profiles, human-reviewed," not blended
into or presented as the full headline result.

P01-P05 (development) and P09-P10 (held-out) remain AI-drafted only, tracked in
`data/evaluation/`.

## How to run the audited set

Run the audited set with:

```bash
analytics/.venv/bin/python analytics/evaluate.py --fixtures data/evaluation_reviewed_subset \
  --labels data/evaluation_reviewed_subset/labels_audited.csv --subset held_out \
  --out-dir evidence --tag audited_P06_P08
```

To reproduce the earlier result from the preserved original human submission, use
`--labels data/evaluation_reviewed_subset/labels_human.csv --subset held_out` and a
different output tag. Both runs cover only P06-P08. The generated evaluator report
does not verify the label file's provenance; consult the dated review log and this
README. Neither file completes the other seven profiles or establishes third-party
inter-rater agreement.
