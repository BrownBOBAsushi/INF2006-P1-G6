# AI/data evaluation report

Generated 2026-10-01T13:11:54Z by `analytics/evaluate.py` (script sha256 `44d1a047527a`, git `1ee8627652` + uncommitted changes).

> **Custom label file labels_audited.csv: provenance/review status is not verified by this script.**

Subset(s) evaluated: **held_out**. Labels: `labels_audited.csv`. Fixtures: 30 jobs, 3 profiles; sha256 jobs.json `7b32914c674e`, profiles.json `056fb0777452`, labels_audited.csv `5b7eb0750823`.

- Model `sentence-transformers/all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, 384 dimensions, default max_seq_length 256; requirement prefix: ''; wall time 3.1s.
- Environment: Python 3.11.9, macOS-26.5.2-arm64-arm-64bit, arm; torch threads 1; packages: sentence-transformers 6.1.0, transformers 5.17.0, torch 2.14.0, numpy 2.4.6, tokenizers 0.23.2.

## HELD-OUT subset (the reported result)
3 profiles x 30 jobs. Ceilings: strict P@5 0.600, lenient P@5 1.000, NDCG@5 1.000. Small sample: point estimates only.

| Method | all-MiniLM-L6-v2: P@5 strict / lenient / NDCG@5 |
|---|---|
| Requirement-level (contract method) | 0.533 / 0.800 / 0.888 |
| Baseline A: keyword / BM25 | 0.600 / 0.867 / 0.942 |
| Baseline B: pooled-chunk embedding | 0.600 / 0.733 / 0.867 |
| Baseline B2: whole-resume vector (TRUNCATES) | 0.600 / 0.733 / 0.875 |

Baseline A uses no embedding model, so its row is identical across models by construction.

### Per-profile, `all-MiniLM-L6-v2` (held_out): strict P@5 / NDCG@5

| Profile | Chunks | Requirement-level (contract method) | Baseline A | Baseline B | Baseline B2 |
|---|---|---|---|---|---|
| P06 | 4 | 0.600 / 0.823 | 0.800 / 1.000 | 0.800 / 0.889 | 0.800 / 0.914 |
| P07 | 4 | 0.600 / 0.924 | 0.600 / 0.910 | 0.600 / 1.000 | 0.600 / 1.000 |
| P08 | 6 | 0.400 / 0.916 | 0.400 / 0.916 | 0.400 / 0.712 | 0.400 / 0.712 |

Top-5 ranked jobs as `job(label)`:

- P06 Requirement-level (contract method): J04(2) J03(2) J27(1) J02(0) J01(2)
- P06 Baseline A: J03(2) J01(2) J04(2) J14(2) J07(1)
- P06 Baseline B: J03(2) J04(2) J29(0) J01(2) J14(2)
- P06 Baseline B2: J03(2) J04(2) J01(2) J29(0) J14(2)
- P07 Requirement-level (contract method): J10(2) J06(2) J07(2) J25(1) J18(0)
- P07 Baseline A: J07(2) J06(2) J01(1) J10(2) J17(0)
- P07 Baseline B: J06(2) J10(2) J07(2) J25(1) J11(1)
- P07 Baseline B2: J07(2) J06(2) J10(2) J01(1) J25(1)
- P08 Requirement-level (contract method): J13(2) J30(2) J07(1) J01(1) J27(0)
- P08 Baseline A: J13(2) J30(2) J07(1) J28(1) J15(0)
- P08 Baseline B: J13(2) J30(2) J09(0) J12(0) J27(0)
- P08 Baseline B2: J13(2) J30(2) J12(0) J09(0) J20(0)

## Diagnostics

### `sentence-transformers/all-MiniLM-L6-v2`

- Largest chunk: 108 tokens (limit 240, including heading and special tokens); no chunk or requirement text was truncated (the harness raises otherwise).
- Chunks per profile: P06=4, P07=4, P08=6.
- Entries that needed sentence/token splitting: 0 profile entries and 0 jobs. If 0, the splitter was not exercised by these fixtures (it is covered by unit tests only).
- Baseline B2 truncation at the encoder's default 256 tokens: 2/3 whole-resume inputs and 0/30 job inputs exceeded the limit and were truncated (longest job 112 tokens; whole-resume token counts: P06=297, P07=234, P08=366).
- Mean requirement-level job score per profile (length-bias check against chunk count): P06=0.218, P07=0.250, P08=0.226.
- Mean requirement_level score by label (held_out): label 0=0.193 (n=62), label 1=0.274 (n=19), label 2=0.405 (n=9).
- Mean pooled_chunk score by label (held_out): label 0=0.236 (n=62), label 1=0.314 (n=19), label 2=0.535 (n=9).

## Limitations (read before quoting these numbers)

- Fixtures and labels were authored by one AI author; label review by a human team member is pending unless the banner above says otherwise.
- Job requirements are hand-authored (no extraction errors); only the requirement-level method sees them.
- 5 profiles per subset. No confidence intervals or significance claims. Scores are internal similarities, not probabilities of suitability.
- Baseline B2 truncates its inputs by design and is not an equivalent full-context encoder.
- Synthetic text is cleaner than real resumes; results do not transfer to real data without further evaluation.
- This report expresses no preference between models; that decision belongs to the team.
