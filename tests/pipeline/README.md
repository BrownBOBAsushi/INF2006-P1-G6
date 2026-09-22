# Pipeline tests (processing, matching, catalogue)

Owner: Chuying. Synthetic data only; all personal details in tests are fictional (`example.com`, `9000 00NN`, `S000000NZ`, postal `000000`).

```bash
# environment: src/backend/requirements-processing.txt (short venv path on Windows), plus the cached spaCy and MiniLM models
python -m pytest tests/pipeline -q -p no:cacheprovider
```

Real components, not mocks: the pinned MiniLM model, Presidio with spaCy, pdfplumber on the PDFs in `tests/fixtures/pdf/`, and a real
PostgreSQL 16 + pgvector started by the `pgserver` package (loopback, temporary directory, no Docker). The database fixture applies
Alembic to head, so the full migration chain is exercised. A tiny deterministic fake embedder is used only for importer bookkeeping tests
that do not care about vector values.

| File | Covers |
|---|---|
| `test_pdf_extract.py` | valid/multi-page/encrypted/non-PDF/scanned/empty/corrupt/oversized/11-page PDFs; no content in errors or logs |
| `test_privacy.py` | each PII type removed, technical terms kept, generic words kept, determinism, no PII in logs, privacy re-check |
| `test_sections_and_prepare.py` | 10 fixture PDFs round-trip to their source profiles; unfamiliar headings; limits; malformed inputs; content validation |
| `test_chunking_tokens.py` | 240-token limit below/at/above/very long/empty, measured with the model's own tokenizer; equality with `analytics/evaluate.py` chunker |
| `test_embeddings.py` | pinned model, 384 dimension, empty/over-limit rejection, bitwise reproducibility, batching, no silent download |
| `test_scoring.py` | best/weak, AND, OR, multi-requirement, preferred, ties, near-ties, <5 and >5 jobs, determinism, aggregation before top-k, omission rules |
| `test_skill_gap_explain.py` | matched vs missing (PRD example), OR groups, aliases, whole-skill matching, explanation traceability, no suitability claims |
| `test_catalogue.py` | schema validation, dedup, hashing; importer on real PostgreSQL: valid/duplicate/update/invalid/dry-run/rollback/real-model vectors |
| `test_db_ranking.py` | SQL ranking == in-memory == `evaluate.py` for all 10 profiles; AND/OR/ties/pagination/omissions/user scoping in SQL; indexes; migration up/down/up |
| `test_processing_slot.py` | single non-blocking slot, immediate busy, 60 s deadline (a real 60 s test), terminate-and-join before release, child recreation, crash, disconnect safety, network guard, production child (real models) |
| `test_api_harness.py` | the slot behind real HTTP via the reference harness (503 + Retry-After, browse during processing, 504, 500, recovery) and the load script's own logic (probe refuses missing endpoints/session) |
| `test_end_to_end.py` | PDF -> privacy -> chunks -> embeddings -> import -> top 5 -> skill gaps -> explanation |

Jiaxin's `tests/backend` suite was also run against a database migrated to the new head (32 passed); `tests/backend/test_migrations.py`
hard-codes the Docker path `/app` and cannot run outside the container.
