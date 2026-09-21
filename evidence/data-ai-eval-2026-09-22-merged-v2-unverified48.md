# AI/data evaluation report

Generated 2026-09-21T20:25:03Z by `analytics/evaluate.py` (script sha256 `44d1a047527a`, git `1006a30087`).

> **Custom label file labels_merged_v2_unverified48.csv: provenance/review status is not verified by this script.**

Subset(s) evaluated: **development, held_out**. Labels: `labels_merged_v2_unverified48.csv`. Fixtures: 30 jobs, 10 profiles; sha256 jobs.json `7b32914c674e`, profiles.json `136303808954`, labels_merged_v2_unverified48.csv `0a5e8ed989bc`.

- Model `sentence-transformers/all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, 384 dimensions, default max_seq_length 256; requirement prefix: ''; wall time 14.1s.
- Model `BAAI/bge-small-en-v1.5` revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, 384 dimensions, default max_seq_length 512; requirement prefix: ''; wall time 11.8s.
- Environment: Python 3.11.9, Windows-10-10.0.26200-SP0, AMD64 Family 25 Model 117 Stepping 2, AuthenticAMD; torch threads 1; packages: sentence-transformers 6.1.0, transformers 5.17.0, torch 2.14.0, numpy 2.4.6, tokenizers 0.23.2.

## Development subset (debugging only, NOT the reported result)
5 profiles x 30 jobs. Ceilings: strict P@5 0.520, lenient P@5 0.880, NDCG@5 1.000. Small sample: point estimates only.

| Method | all-MiniLM-L6-v2: P@5 strict / lenient / NDCG@5 | bge-small-en-v1.5: P@5 strict / lenient / NDCG@5 |
|---|---|---|
| Requirement-level (contract method) | 0.440 / 0.640 / 0.818 | 0.520 / 0.640 / 0.865 |
| Baseline A: keyword / BM25 | 0.520 / 0.600 / 0.868 | 0.520 / 0.600 / 0.868 |
| Baseline B: pooled-chunk embedding | 0.520 / 0.600 / 0.854 | 0.520 / 0.640 / 0.891 |
| Baseline B2: whole-resume vector (TRUNCATES) | 0.480 / 0.680 / 0.873 | 0.520 / 0.680 / 0.910 |

Baseline A uses no embedding model, so its row is identical across models by construction.

### Per-profile, `all-MiniLM-L6-v2` (development): strict P@5 / NDCG@5

| Profile | Chunks | Requirement-level (contract method) | Baseline A | Baseline B | Baseline B2 |
|---|---|---|---|---|---|
| P01 | 4 | 0.600 / 0.839 | 0.600 / 0.839 | 0.600 / 0.839 | 0.600 / 0.839 |
| P02 | 4 | 0.400 / 0.817 | 0.600 / 0.915 | 0.600 / 0.924 | 0.600 / 1.000 |
| P03 | 4 | 0.400 / 0.778 | 0.600 / 0.908 | 0.600 / 0.860 | 0.400 / 0.695 |
| P04 | 4 | 0.400 / 0.881 | 0.400 / 0.897 | 0.400 / 0.778 | 0.400 / 0.870 |
| P05 | 4 | 0.400 / 0.778 | 0.400 / 0.778 | 0.400 / 0.870 | 0.400 / 0.958 |

Top-5 ranked jobs as `job(label)`:

- P01 Requirement-level (contract method): J02(2) J07(2) J01(2) J29(0) J11(0)
- P01 Baseline A: J02(2) J01(2) J07(2) J04(0) J24(0)
- P01 Baseline B: J01(2) J07(2) J02(2) J25(0) J11(0)
- P01 Baseline B2: J01(2) J02(2) J07(2) J25(0) J11(0)
- P02 Requirement-level (contract method): J06(2) J10(2) J07(1) J17(0) J25(1)
- P02 Baseline A: J06(2) J11(2) J10(2) J15(0) J25(1)
- P02 Baseline B: J06(2) J10(2) J11(2) J25(1) J26(0)
- P02 Baseline B2: J06(2) J10(2) J11(2) J25(1) J07(1)
- P03 Requirement-level (contract method): J08(2) J09(2) J29(0) J27(0) J07(1)
- P03 Baseline A: J11(2) J08(2) J09(2) J06(0) J05(0)
- P03 Baseline B: J08(2) J09(2) J29(0) J16(0) J11(2)
- P03 Baseline B2: J08(2) J09(2) J29(0) J16(0) J12(0)
- P04 Requirement-level (contract method): J21(1) J20(2) J03(2) J27(1) J25(0)
- P04 Baseline A: J03(2) J20(2) J21(1) J29(0) J16(0)
- P04 Baseline B: J20(2) J03(2) J30(0) J29(0) J05(0)
- P04 Baseline B2: J03(2) J20(2) J29(0) J30(0) J27(1)
- P05 Requirement-level (contract method): J12(2) J28(2) J14(0) J29(0) J24(0)
- P05 Baseline A: J28(2) J12(2) J06(0) J01(0) J27(0)
- P05 Baseline B: J12(2) J28(2) J14(0) J13(0) J07(1)
- P05 Baseline B2: J12(2) J07(1) J28(2) J01(0) J04(1)

### Per-profile, `bge-small-en-v1.5` (development): strict P@5 / NDCG@5

| Profile | Chunks | Requirement-level (contract method) | Baseline A | Baseline B | Baseline B2 |
|---|---|---|---|---|---|
| P01 | 4 | 0.600 / 0.812 | 0.600 / 0.839 | 0.600 / 0.839 | 0.600 / 0.839 |
| P02 | 4 | 0.600 / 0.794 | 0.600 / 0.915 | 0.600 / 0.839 | 0.600 / 0.915 |
| P03 | 4 | 0.600 / 0.879 | 0.600 / 0.908 | 0.600 / 0.908 | 0.600 / 0.908 |
| P04 | 4 | 0.400 / 0.969 | 0.400 / 0.897 | 0.400 / 0.897 | 0.400 / 0.897 |
| P05 | 4 | 0.400 / 0.870 | 0.400 / 0.778 | 0.400 / 0.973 | 0.400 / 0.990 |

Top-5 ranked jobs as `job(label)`:

- P01 Requirement-level (contract method): J02(2) J07(2) J29(0) J01(2) J24(0)
- P01 Baseline A: J02(2) J01(2) J07(2) J04(0) J24(0)
- P01 Baseline B: J01(2) J07(2) J02(2) J11(0) J03(0)
- P01 Baseline B2: J01(2) J02(2) J07(2) J11(0) J03(0)
- P02 Requirement-level (contract method): J06(2) J11(2) J17(0) J18(0) J10(2)
- P02 Baseline A: J06(2) J11(2) J10(2) J15(0) J25(1)
- P02 Baseline B: J06(2) J10(2) J11(2) J26(0) J15(0)
- P02 Baseline B2: J06(2) J11(2) J10(2) J01(0) J07(1)
- P03 Requirement-level (contract method): J08(2) J11(2) J29(0) J09(2) J27(0)
- P03 Baseline A: J11(2) J08(2) J09(2) J06(0) J05(0)
- P03 Baseline B: J08(2) J11(2) J09(2) J15(0) J29(0)
- P03 Baseline B2: J08(2) J11(2) J09(2) J01(0) J15(0)
- P04 Requirement-level (contract method): J20(2) J21(1) J03(2) J27(1) J22(0)
- P04 Baseline A: J03(2) J20(2) J21(1) J29(0) J16(0)
- P04 Baseline B: J20(2) J03(2) J27(1) J15(0) J01(0)
- P04 Baseline B2: J20(2) J03(2) J27(1) J29(0) J30(0)
- P05 Requirement-level (contract method): J12(2) J28(2) J24(0) J14(0) J04(1)
- P05 Baseline A: J28(2) J12(2) J06(0) J01(0) J27(0)
- P05 Baseline B: J12(2) J28(2) J01(0) J04(1) J07(1)
- P05 Baseline B2: J12(2) J28(2) J07(1) J01(0) J04(1)

## HELD-OUT subset (the reported result)
5 profiles x 30 jobs. Ceilings: strict P@5 0.680, lenient P@5 0.880, NDCG@5 1.000. Small sample: point estimates only.

| Method | all-MiniLM-L6-v2: P@5 strict / lenient / NDCG@5 | bge-small-en-v1.5: P@5 strict / lenient / NDCG@5 |
|---|---|---|
| Requirement-level (contract method) | 0.640 / 0.760 / 0.919 | 0.680 / 0.720 / 0.925 |
| Baseline A: keyword / BM25 | 0.640 / 0.680 / 0.881 | 0.640 / 0.680 / 0.881 |
| Baseline B: pooled-chunk embedding | 0.560 / 0.640 / 0.758 | 0.560 / 0.640 / 0.777 |
| Baseline B2: whole-resume vector (TRUNCATES) | 0.560 / 0.640 / 0.774 | 0.600 / 0.640 / 0.791 |

Baseline A uses no embedding model, so its row is identical across models by construction.

### Per-profile, `all-MiniLM-L6-v2` (held_out): strict P@5 / NDCG@5

| Profile | Chunks | Requirement-level (contract method) | Baseline A | Baseline B | Baseline B2 |
|---|---|---|---|---|---|
| P06 | 4 | 0.600 / 0.794 | 0.600 / 0.924 | 0.600 / 0.888 | 0.600 / 0.915 |
| P07 | 4 | 0.600 / 0.908 | 0.600 / 0.879 | 0.600 / 0.908 | 0.600 / 0.908 |
| P08 | 6 | 0.600 / 0.967 | 0.400 / 0.765 | 0.400 / 0.765 | 0.400 / 0.765 |
| P09 | 4 | 0.600 / 1.000 | 0.600 / 0.839 | 0.400 / 0.443 | 0.200 / 0.282 |
| P10 | 10 | 0.800 / 0.927 | 1.000 / 1.000 | 0.800 / 0.786 | 1.000 / 1.000 |

Top-5 ranked jobs as `job(label)`:

- P06 Requirement-level (contract method): J04(2) J03(2) J27(0) J02(0) J01(2)
- P06 Baseline A: J03(2) J01(2) J04(2) J14(1) J07(0)
- P06 Baseline B: J03(2) J04(2) J29(0) J01(2) J14(1)
- P06 Baseline B2: J03(2) J04(2) J01(2) J29(0) J14(1)
- P07 Requirement-level (contract method): J10(2) J06(2) J07(2) J25(0) J18(0)
- P07 Baseline A: J07(2) J06(2) J01(0) J10(2) J17(0)
- P07 Baseline B: J06(2) J10(2) J07(2) J25(0) J11(0)
- P07 Baseline B2: J07(2) J06(2) J10(2) J01(0) J25(0)
- P08 Requirement-level (contract method): J13(2) J30(2) J07(0) J01(2) J27(0)
- P08 Baseline A: J13(2) J30(2) J07(0) J28(0) J15(0)
- P08 Baseline B: J13(2) J30(2) J09(0) J12(0) J27(0)
- P08 Baseline B2: J13(2) J30(2) J12(0) J09(0) J20(0)
- P09 Requirement-level (contract method): J17(2) J15(2) J25(2) J26(1) J18(1)
- P09 Baseline A: J17(2) J15(2) J25(2) J06(0) J01(0)
- P09 Baseline B: J06(0) J10(0) J25(2) J15(2) J27(1)
- P09 Baseline B2: J06(0) J10(0) J25(2) J27(1) J11(0)
- P10 Requirement-level (contract method): J05(2) J02(2) J01(2) J14(1) J30(2)
- P10 Baseline A: J02(2) J05(2) J03(2) J30(2) J01(2)
- P10 Baseline B: J03(2) J29(0) J30(2) J02(2) J05(2)
- P10 Baseline B2: J05(2) J02(2) J03(2) J01(2) J30(2)

### Per-profile, `bge-small-en-v1.5` (held_out): strict P@5 / NDCG@5

| Profile | Chunks | Requirement-level (contract method) | Baseline A | Baseline B | Baseline B2 |
|---|---|---|---|---|---|
| P06 | 4 | 0.600 / 0.879 | 0.600 / 0.924 | 0.600 / 0.924 | 0.600 / 0.893 |
| P07 | 4 | 0.600 / 0.908 | 0.600 / 0.879 | 0.600 / 0.879 | 0.600 / 0.823 |
| P08 | 6 | 0.600 / 1.000 | 0.400 / 0.765 | 0.600 / 0.947 | 0.400 / 0.651 |
| P09 | 4 | 0.600 / 0.839 | 0.600 / 0.839 | 0.400 / 0.349 | 0.400 / 0.591 |
| P10 | 10 | 1.000 / 1.000 | 1.000 / 1.000 | 0.600 / 0.788 | 1.000 / 1.000 |

Top-5 ranked jobs as `job(label)`:

- P06 Requirement-level (contract method): J04(2) J03(2) J02(0) J12(1) J01(2)
- P06 Baseline A: J03(2) J01(2) J04(2) J14(1) J07(0)
- P06 Baseline B: J03(2) J01(2) J04(2) J14(1) J29(0)
- P06 Baseline B2: J03(2) J01(2) J14(1) J29(0) J04(2)
- P07 Requirement-level (contract method): J06(2) J07(2) J10(2) J17(0) J11(0)
- P07 Baseline A: J07(2) J06(2) J01(0) J10(2) J17(0)
- P07 Baseline B: J07(2) J10(2) J01(0) J06(2) J11(0)
- P07 Baseline B2: J07(2) J01(0) J10(2) J06(2) J11(0)
- P08 Requirement-level (contract method): J13(2) J30(2) J01(2) J24(0) J22(0)
- P08 Baseline A: J13(2) J30(2) J07(0) J28(0) J15(0)
- P08 Baseline B: J13(2) J30(2) J14(0) J09(0) J01(2)
- P08 Baseline B2: J13(2) J09(0) J27(0) J29(0) J30(2)
- P09 Requirement-level (contract method): J17(2) J15(2) J25(2) J06(0) J07(0)
- P09 Baseline A: J17(2) J15(2) J25(2) J06(0) J01(0)
- P09 Baseline B: J10(0) J11(0) J15(2) J06(0) J17(2)
- P09 Baseline B2: J17(2) J06(0) J15(2) J10(0) J11(0)
- P10 Requirement-level (contract method): J02(2) J05(2) J30(2) J03(2) J01(2)
- P10 Baseline A: J02(2) J05(2) J03(2) J30(2) J01(2)
- P10 Baseline B: J01(2) J03(2) J02(2) J29(0) J14(1)
- P10 Baseline B2: J05(2) J03(2) J02(2) J01(2) J30(2)

## Diagnostics

### `sentence-transformers/all-MiniLM-L6-v2`

- Largest chunk: 108 tokens (limit 240, including heading and special tokens); no chunk or requirement text was truncated (the harness raises otherwise).
- Chunks per profile: P01=4, P02=4, P03=4, P04=4, P05=4, P06=4, P07=4, P08=6, P09=4, P10=10.
- Entries that needed sentence/token splitting: 0 profile entries and 0 jobs. If 0, the splitter was not exercised by these fixtures (it is covered by unit tests only).
- Baseline B2 truncation at the encoder's default 256 tokens: 4/10 whole-resume inputs and 0/30 job inputs exceeded the limit and were truncated (longest job 112 tokens; whole-resume token counts: P01=248, P02=201, P03=289, P04=219, P05=242, P06=297, P07=234, P08=366, P09=221, P10=773).
- Mean requirement-level job score per profile (length-bias check against chunk count): P01=0.212, P02=0.219, P03=0.194, P04=0.216, P05=0.185, P06=0.218, P07=0.250, P08=0.226, P09=0.237, P10=0.271.
- Mean requirement_level score by label (development): label 0=0.182 (n=127), label 1=0.290 (n=10), label 2=0.367 (n=13).
- Mean requirement_level score by label (held_out): label 0=0.212 (n=124), label 1=0.295 (n=9), label 2=0.420 (n=17).
- Mean pooled_chunk score by label (development): label 0=0.246 (n=127), label 1=0.355 (n=10), label 2=0.509 (n=13).
- Mean pooled_chunk score by label (held_out): label 0=0.279 (n=124), label 1=0.372 (n=9), label 2=0.516 (n=17).

### `BAAI/bge-small-en-v1.5`

- Largest chunk: 108 tokens (limit 240, including heading and special tokens); no chunk or requirement text was truncated (the harness raises otherwise).
- Chunks per profile: P01=4, P02=4, P03=4, P04=4, P05=4, P06=4, P07=4, P08=6, P09=4, P10=10.
- Entries that needed sentence/token splitting: 0 profile entries and 0 jobs. If 0, the splitter was not exercised by these fixtures (it is covered by unit tests only).
- Baseline B2 truncation at the encoder's default 512 tokens: 1/10 whole-resume inputs and 0/30 job inputs exceeded the limit and were truncated (longest job 112 tokens; whole-resume token counts: P01=248, P02=201, P03=289, P04=219, P05=242, P06=297, P07=234, P08=366, P09=221, P10=773).
- Mean requirement-level job score per profile (length-bias check against chunk count): P01=0.587, P02=0.591, P03=0.573, P04=0.586, P05=0.572, P06=0.587, P07=0.596, P08=0.594, P09=0.590, P10=0.611.
- Mean requirement_level score by label (development): label 0=0.569 (n=127), label 1=0.617 (n=10), label 2=0.677 (n=13).
- Mean requirement_level score by label (held_out): label 0=0.582 (n=124), label 1=0.617 (n=9), label 2=0.685 (n=17).
- Mean pooled_chunk score by label (development): label 0=0.616 (n=127), label 1=0.671 (n=10), label 2=0.741 (n=13).
- Mean pooled_chunk score by label (held_out): label 0=0.641 (n=124), label 1=0.682 (n=9), label 2=0.744 (n=17).

## Limitations (read before quoting these numbers)

- Fixtures and labels were authored by one AI author; label review by a human team member is pending unless the banner above says otherwise.
- Job requirements are hand-authored (no extraction errors); only the requirement-level method sees them.
- 5 profiles per subset. No confidence intervals or significance claims. Scores are internal similarities, not probabilities of suitability.
- Baseline B2 truncates its inputs by design and is not an equivalent full-context encoder.
- Synthetic text is cleaner than real resumes; results do not transfer to real data without further evaluation.
- This report expresses no preference between models; that decision belongs to the team.
