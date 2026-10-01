# data-ai test record

Status: original run 2026-09-20, provenance and subset results updated 2026-10-01. The 300-row source labels
are AI-drafted. A team member supplied labels for P06-P08 (90/300 pairs); the process was recorded as blind,
but its independence and blinding have not been independently verified. The original submission is preserved
as `data/evaluation_reviewed_subset/labels_human.csv`. After its first evaluation, a rubric inconsistency was
corrected in a separate AI-assisted, user-authorized audit copy `labels_audited.csv` (one pair, P06-J29, 2 to 0).
That is a post-result correction, not new human labelling or ratification. Manifest status remains `PARTIAL`;
the remaining 210 labels are AI-drafted. All label-dependent results are provisional and scoped to their stated
label file. See `data/evaluation/LABEL_REVIEW_LOG.md` and `AI_USE_DECLARATION.md`.

- **Objective:** Measure ranking quality (Precision@5, NDCG@5) of the contract's requirement-level embedding
  ranking against two baselines (keyword/BM25, pooled-chunk embedding; plus a truncating whole-resume
  variant) on synthetic labelled fixtures, for `sentence-transformers/all-MiniLM-L6-v2` (current contract model) and
  `BAAI/bge-small-en-v1.5` (candidate), using identical fixtures, labels and dev/held-out split. This record reports
  numbers only; it does not recommend a model.
- **Date:** 2026-09-20
- **Owner:** Chuying (run and harness implemented with AI assistance, see `AI_USE_DECLARATION.md`)
- **Commit / dependency / model versions:** harness at git `de082b2` on branch `feature/ai-evaluation-harness`
  (script sha256 `44d1a047527a...`); Python 3.11.9, sentence-transformers 6.1.0, transformers 5.17.0, torch 2.14.0
  (CPU), numpy 2.4.6, tokenizers 0.23.2 (all 44 packages pinned in `analytics/requirements.txt`).
  Models pinned by revision: MiniLM `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` (Apache-2.0),
  bge-small `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` (MIT); both 384-dimensional.
- **Setup / hardware / fixture counts:** Windows 11, AMD Ryzen 9 8945HS (8 cores/16 threads), 31.3 GB RAM, CPU
  only, torch threads = 1, weights cached locally (first run downloaded them). 10 synthetic profiles
  (5 development P01-P05, 5 held-out P06-P10) x 30 synthetic jobs = 300 labels. Fixture sha256 (first 12):
  jobs.json `7b32914c674e`, profiles.json `136303808954`, labels.csv `acaa94703cc0`. Protocol and label criteria:
  `data/evaluation/README.md`, `data/evaluation/LABELLING_CRITERIA.md`.
- **Command (documented in IMPLEMENTATION_GUIDE.md):**
  `python analytics/evaluate.py --fixtures data/evaluation` (defaults to MiniLM; reproduced, see run log).
  Side-by-side evidence run:
  `python analytics/evaluate.py --fixtures data/evaluation --model sentence-transformers/all-MiniLM-L6-v2 --model BAAI/bge-small-en-v1.5 --out-dir evidence`
- **Expected result:** Measurable Precision@5 and NDCG@5 for every method and both models, comparable with the
  keyword baseline (PRD Test 3). No pass/fail threshold was defined and none is defined after the fact.
- **Actual result (HELD-OUT, 5 profiles x 30 jobs; the reported result).** Cells are strict P@5 / lenient P@5 /
  NDCG@5. Strict counts label 2 only, lenient counts label >= 1. Ceilings: strict P@5 0.680, lenient 0.880.

| Method | all-MiniLM-L6-v2 | bge-small-en-v1.5 |
|---|---|---|
| Requirement-level (contract method) | 0.640 / 0.760 / 0.922 | 0.640 / 0.720 / 0.912 |
| Baseline A: keyword / BM25 (no model; identical) | 0.640 / 0.720 / 0.910 | 0.640 / 0.720 / 0.910 |
| Baseline B: pooled-chunk embedding | 0.560 / 0.640 / 0.771 | 0.520 / 0.680 / 0.798 |
| Baseline B2: whole-resume single vector (TRUNCATES; see below) | 0.560 / 0.680 / 0.808 | 0.600 / 0.680 / 0.826 |

  Development subset (used only for debugging; not the result). Ceilings: strict 0.560, lenient 0.920.

| Method | all-MiniLM-L6-v2 | bge-small-en-v1.5 |
|---|---|---|
| Requirement-level (contract method) | 0.480 / 0.640 / 0.827 | 0.560 / 0.640 / 0.856 |
| Baseline A: keyword / BM25 | 0.560 / 0.640 / 0.871 | 0.560 / 0.640 / 0.871 |
| Baseline B: pooled-chunk embedding | 0.520 / 0.640 / 0.842 | 0.520 / 0.680 / 0.877 |
| Baseline B2: whole-resume single vector (TRUNCATES) | 0.480 / 0.680 / 0.842 | 0.520 / 0.680 / 0.879 |

  Declared supplementary sensitivity run (bge-small only; query instruction
  "Represent this sentence for searching relevant passages: " prepended to requirement texts, baselines unchanged),
  held-out requirement-level: 0.600 / 0.640 / 0.869 (development: 0.560 / 0.640 / 0.866). It was declared before any bge
  result was seen and is reported for transparency, not used to choose a setting.

  **Baseline B2 truncates by design.** The whole resume and whole job posting are each encoded as one vector at the
  encoder's default limit (MiniLM 256 tokens, bge 512). MiniLM truncated 4 of 10 whole-resume inputs (P03, P06, P08, P10;
  token counts 289/297/366/773); bge truncated 1 of 10 (P10). No job posting exceeded either limit (longest 112 tokens).
  It is not an equivalent full-context encoder and is included only as a disclosed simple baseline.
- **Output artefact paths:**
  - `evidence/data-ai-eval-2026-09-20.md` and `.json`: headline run, both models, both subsets (per-profile scores, top-5 lists, diagnostics, all scores).
  - `evidence/data-ai-eval-2026-09-20-dev-debug.md` and `.json`: development-only debugging run.
  - `evidence/data-ai-eval-2026-09-20-bge-query-prefix-sensitivity.md` and `.json`: sensitivity run.
- **Interpretation / limitations** (measured facts first, then caution):
  - On the held-out subset the requirement-level method and the keyword baseline are indistinguishable: identical
    strict P@5 (0.640) and NDCG@5 within 0.012 (MiniLM 0.922, bge 0.912, BM25 0.910). This run does not show a
    measurable advantage of semantic matching over the keyword baseline. Per profile the difference goes both ways
    (MiniLM NDCG@5: BM25 higher on P06, P07, P10; requirement-level higher on P08, P09), which 5 profiles cannot
    resolve; no significance is claimed.
  - Both embedding-only baselines (B, B2) scored lower NDCG@5 than requirement-level and BM25 on held-out. Much of that
    gap comes from P09 (business profile with no coding content; pooled-chunk NDCG 0.408 MiniLM / 0.322 bge).
  - MiniLM and bge-small do not separate: identical strict P@5 on held-out requirement-level; lenient P@5 and NDCG@5
    differ by 0.040 and 0.010; on development, bge is higher (strict 0.560 vs 0.480). The direction is not consistent
    across subsets and metrics. No model preference is drawn here; that decision belongs to the team.
  - The query instruction lowered bge's held-out requirement-level NDCG@5 (0.912 to 0.869) in this small sample; one
    observation, not a general claim.
  - Mean requirement-level score rises with label for both models (MiniLM held-out: label 0 = 0.212, label 1 = 0.291,
    label 2 = 0.420), so the scores do carry signal even though rankings do not beat BM25 here.
  - Length bias (PRD asks for this): P10, the longest resume (10 chunks vs 4-6), has the highest mean requirement score
    for both models (MiniLM 0.271 vs 0.185-0.250 for others; bge 0.611 vs 0.572-0.596). This is consistent with more
    chunks giving more chances at a high maximum, but P10 is also the broadest profile (5 relevant jobs), so the two
    effects are confounded and this data cannot separate them.
  - The no-code technical-writing job J29 was designed as a keyword/negation trap; embedding methods place it in a
    top-5 in several cases (see top-5 lists in the report).
  - **Labels were AI-drafted at the time of this 2026-09-20 run.** Fixtures and labels have the same AI author and the criteria refer
    to required requirements, which structurally favours the requirement-level method; job requirements are hand-authored
    (no extraction error); only the requirement-level method sees them. Synthetic text is cleaner than real resumes.
  - **Splitter coverage gap:** no fixture entry or job exceeded 240 tokens (largest chunk 108 tokens), so the
    sentence/token-boundary splitter was **not exercised by this evaluation**; it is verified only by unit tests
    (`tests/analytics/test_evaluate.py`, 16 passed).
  - At the time, human labelling via `data/evaluation/labelling_sheet_blank.csv` was the planned next step. The later
    90-pair submission and separate post-result audit are described below. Any changed label requires a separate rerun.
- **Run log (nothing overwritten; all runs on 2026-09-20, no run failed):**
  1. Development-only MiniLM debug run (console only, script before diagnostics were added) to check the pipeline.
  2. Fixes from that run: replaced a deprecated method call; added split-coverage diagnostics (no scoring change).
  3. `pytest tests/analytics`: 16 passed.
  4. Development-only run, both models (`-dev-debug` artefact). Held-out was not scored before this point.
  5. Headline run, both models, both subsets (first time held-out was scored; code frozen at `de082b2`, not changed afterwards).
  6. Sensitivity run (bge + query prefix).
  7. Reproducibility rerun of the documented default command: MiniLM numbers identical to run 5 in all 24 cells; tests passed again (16).
## Original submission and audited subset results (2026-10-01)

**Scope:** P06, P07, P08 only: 3 profiles x 30 jobs, all held-out. The process accompanying the original
submission describes blind completion; this has not been independently verified. The original human-submitted
file was scored first, then retained byte-for-byte. Review against the pre-existing J29 keyword-trap criterion
found P06-J29 inconsistent: the rationale inferred technical-writing ability from coding experience, with no
profile evidence of writing technical explanations or documentation. The user authorized an AI-assisted audit
copy on 2026-10-01. It changes only P06-J29 from 2 to 0 and replaces its rationale. It is not a second human
label, independent review, or human ratification. See `data/evaluation/LABEL_REVIEW_LOG.md`.

The original 90-row submission agreed with the AI draft on 72/90 (80.0%) pairs; the audited copy agrees on
73/90 (81.1%). This count is descriptive only. Agreement direction does not establish correctness, blinding,
or independence.

**Re-scored** with MiniLM on the same 3 profiles and fixtures. Cells are strict P@5 / lenient P@5 / NDCG@5.
Ceilings: original submission strict 0.667, audited set strict 0.600; lenient 1.000 for both. These are point
estimates on three profiles. The generated reports carry generic caveats about human provenance and a 5-profile
subset; those template caveats do not describe this specific run's 3-profile scope. Provenance and scope here
come from this dated evidence record and review log, not from the evaluator.

| Method | AI-drafted labels (same 3 profiles, from 09-20 run) | Original human submission | Audited copy (2026-10-01) |
|---|---|---|---|
| Requirement-level (contract method) | 0.533 / 0.600 / 0.895 | 0.533 / 0.800 / 0.870 | 0.533 / 0.800 / 0.888 |
| Baseline A: keyword / BM25 | 0.533 / 0.667 / 0.925 | 0.600 / 0.867 / 0.920 | 0.600 / 0.867 / 0.942 |
| Baseline B: pooled-chunk embedding | 0.533 / 0.600 / 0.888 | 0.667 / 0.800 / 0.904 | 0.600 / 0.733 / 0.867 |
| Baseline B2: whole-resume (truncates) | 0.533 / 0.667 / 0.927 | 0.667 / 0.800 / 0.904 | 0.600 / 0.733 / 0.875 |

The AI-drafted column is from `evidence/data-ai-eval-2026-09-20.json`, re-averaged over P06-P08 so each column
uses the same three profiles. Original-submission results are in the preserved
`evidence/data-ai-eval-2026-10-01-human_review_P06_P08.*` outputs. Audited-copy results are in
`evidence/data-ai-eval-2026-10-01-audited_P06_P08.*` outputs. The audit changes only the relevance value for
P06-J29 from 2 to 0; because J29 appears in multiple top-5 lists, that changes the label-based evaluation metrics,
not the model rankings.

**Reading this cautiously:** changing one relevance label affects strict counts, graded NDCG, and the J29 top-5
contributions. The audited requirement-level strict P@5 remains 0.533; pooled-chunk and whole-resume strict P@5
fall from 0.667 on the original submission to 0.600. BM25 strict P@5 remains 0.600. NDCG changes are shown in
the table. These are small-sample point estimates, with no significance claim. The 10-profile AI-drafted run
remains a separate result; this 3-profile audit neither replaces it nor completes review of the full set.

**Output artefacts:** original submission `evidence/data-ai-eval-2026-10-01-human_review_P06_P08.md` and `.json`;
audited copy `evidence/data-ai-eval-2026-10-01-audited_P06_P08.md` and `.json`.

- **Failure diagnosis / rerun:** the first run without offline flags could not resolve the cached pinned model
  because network name resolution failed. The same requested run succeeded with `HF_HUB_OFFLINE=1
  TRANSFORMERS_OFFLINE=1`. The audit correction was made after the original result, recorded above, and rerun
  separately. Reproduction commands are in `data/evaluation_reviewed_subset/README.md`.
