# Evaluation fixtures and protocol

Synthetic data only. Owner: Chuying. Run: `python analytics/evaluate.py --fixtures data/evaluation`
(see `analytics/README.md` for environment setup).

| File | Content |
|---|---|
| `jobs.json` | 30 synthetic internship postings in the import-contract shape (`schema_version: 1`). `source_job_id` (`J01`..`J30`) is the job identity used in labels. Every requirement `source_quote` appears in its description. |
| `profiles.json` | 10 synthetic resume profiles (`P01`..`P10`) in the contract's `ResumeContent` shape, each tagged `development` or `held_out`. No names or contact details. |
| `labels.csv` | 300 labels (10 x 30): `profile_id, job_id, relevance (0/1/2), split, rationale`. |
| `labelling_sheet_blank.csv` | Same pairs with an empty `relevance` column for independent human labelling. |
| `LABELLING_CRITERIA.md` | Judgement criteria, provenance and human-review workflow. |
| `manifest.json` | Counts, split, label provenance and review status. |

## Split

Profiles are split before any model run: **development** = P01-P05, **held-out** = P06-P10. Jobs are shared.
All five methods below have fixed definitions; nothing is tuned. The development subset is used only for
debugging the pipeline. Held-out numbers are the reported result and were produced once per model after the
code was frozen (see `evidence/test-data-ai.md` for the run log, including any reruns).

## Metrics (defined before running)

- **Precision@5 (strict, primary):** relevant = label 2. `P@5 = (# label-2 jobs in top 5) / 5`.
- **Precision@5 (lenient, secondary):** relevant = label >= 1.
- **NDCG@5:** linear gain (0/1/2), discount `1/log2(rank+1)`, ideal ranking taken over all 30 labelled jobs
  for the profile. Note that some profiles have fewer than 5 label-2 jobs, so strict P@5 has a ceiling
  below 1.0; the "ceiling" column in the report shows it.
- Macro average over the profiles in the subset. Ties broken by `job_id` ascending (matches the contract).
- With only 5 profiles per subset these are small-sample point estimates; no significance is claimed.

## Methods compared (identical fixtures, labels and split for every model)

1. **Requirement-level (contract method, "proposed")**: `requirement_score = max cosine(alternative, chunk)`
   over the profile's chunks, `job_score = mean over REQUIRED requirements`. Preferred requirements do not
   affect ranking. Requirement text (or its alternatives) is embedded exactly as given in `jobs.json`.
2. **Baseline A, keyword/literal**: Okapi BM25 (`k1=1.5, b=0.75`, unmodified defaults), query = distinct
   lower-cased terms of the whole profile (skills, projects, experience, education), document = job title +
   description. No stemming, no synonyms, small fixed stop-word list.
3. **Baseline B, pooled-chunk**: the profile's chunks and the job's chunks (same chunker, same 240-token
   budget) are each mean-pooled to one vector; `score = cosine`. No requirement structure.
4. **Baseline B2 (supplementary), whole-resume single vector**: the entire profile text as one input and the
   job title + description as one input, each encoded with the model's default `max_seq_length`
   (256 for all-MiniLM-L6-v2, 512 for bge-small-en-v1.5). **Long inputs are truncated by the encoder here**;
   the report lists how many profiles and jobs exceeded the limit and it is not an equivalent
   full-context encoder.

Chunking follows the PRD: entries (projects, experience) become chunks with a heading; long entries are split by
bullet/sentence, then at token boundaries; every chunk is at most 240 tokenizer tokens including heading and
special tokens, and the harness raises rather than truncating. Education and skills lists are not embedded in
methods 1 and 3 (matching the contract); they are included in methods 2 and 4.

## Known limitations of this fixture set

- Labels and fixtures were authored by the same (AI) author with criteria that reference required
  requirements, which structurally favours requirement-level scoring over the baselines. Human review of
  labels is pending (see `LABELLING_CRITERIA.md`).
- Job requirements are hand-authored (perfect extraction); extraction quality is not evaluated.
- 10 profiles x 30 jobs; not statistically representative. Some profile/job pairs are borderline (1 vs 2).
- Synthetic text is cleaner and more uniform than real resumes.
- The proposed method sees the structured requirements; baselines A/B/B2 see only description text.

## Declared supplementary sensitivity run (declared before any bge-small-en-v1.5 result was seen)

BAAI's documentation recommends prefixing *queries* with "Represent this sentence for searching relevant passages: "
for short-query-to-passage retrieval. The headline comparison uses **no prefix for either model** (the contract
embeds both sides identically). To show how much that choice matters, one extra run applies the prefix to
requirement texts only for bge-small (`--requirement-prefix`); baselines are unchanged. It is reported as a
labelled sensitivity analysis alongside, not instead of, the headline run; it is not a selection step and no
setting is chosen from it.
