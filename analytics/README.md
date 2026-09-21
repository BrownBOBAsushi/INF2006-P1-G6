# Analytics and evaluation

Owner: Chuying. Status: `evaluate.py` implemented and executed; see `../evidence/test-data-ai.md` for the dated
run record and results. **Labels are AI-drafted and pending human review, so all scores are provisional.**

## What it does

`evaluate.py` ranks 30 synthetic internships for each of 10 synthetic resume profiles and scores the rankings
against pre-recorded labels (0/1/2) with Precision@5 (strict = label 2, lenient = label >= 1) and NDCG@5.
Compared methods, identical fixtures/labels/split for every model:

1. Requirement-level max-cosine mean over REQUIRED requirements (the method in `MVP_PRD.md`).
2. Baseline A: keyword/literal BM25.
3. Baseline B: pooled-chunk embedding.
4. Baseline B2 (supplementary): whole-resume single vector, which **truncates at the encoder limit** (disclosed in the report).

Chunks/requirements are limited to 240 tokenizer tokens (heading and special tokens included); over-long entries
are split by bullet/sentence, then at token boundaries, and the harness raises instead of truncating.
Protocol, metric definitions, split and limitations: `../data/evaluation/README.md` and `LABELLING_CRITERIA.md`.

## Setup (Python 3.11, CPU only, no API keys, no hosted LLM)

```bash
python -m venv analytics/.venv
analytics/.venv/Scripts/python -m pip install -r analytics/requirements.txt   # Windows; use analytics/.venv/bin/python on Linux/macOS
```

Every dependency is pinned in `requirements.txt`. Model weights are downloaded once from the Hugging Face Hub at the
pinned revisions in `evaluate.py` (`PINNED_REVISIONS`); afterwards runs are offline.

## Run

```bash
# documented command (defaults to all-MiniLM-L6-v2, the current contract model)
python analytics/evaluate.py --fixtures data/evaluation

# side-by-side comparison, dated evidence written to evidence/
python analytics/evaluate.py --fixtures data/evaluation \
  --model sentence-transformers/all-MiniLM-L6-v2 --model BAAI/bge-small-en-v1.5 --out-dir evidence

# debugging: development profiles only (held-out profiles are never scored)
python analytics/evaluate.py --fixtures data/evaluation --subset development

# unit tests
python -m pytest tests/analytics
```

`--model` is repeatable; an unpinned model must be given an explicit `--revision`. The script prints the
comparison and expresses no preference between models; choosing a model is a team decision.
