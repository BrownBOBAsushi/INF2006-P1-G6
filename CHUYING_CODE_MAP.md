# Map of Chuying's code (processing, matching, catalogue, evaluation)

Start here if you need to find something. Owner: Chuying. Everything below is Python and has no FastAPI/session dependency; Jiaxin's API layer
calls it (see `src/backend/JIAXIN_INTEGRATION.md`). None of it is wired into a route yet.

## Where things live

| Folder | What it does | Main entry points |
|---|---|---|
| `src/backend/app/processing/` | Turns an uploaded PDF into a reviewed draft, then into 240-token chunks and vectors | `pipeline.py`: `prepare_resume(pdf_bytes)`, `recheck_privacy(content)`, `embed_resume(content, model)` |
| ... `pdf_extract.py`, `privacy.py`, `sections.py`, `content.py`, `chunking.py`, `embeddings.py` | PDF text (pdfplumber), Presidio redaction, section parsing, content validation and hash, chunker (max 240 tokens), local MiniLM | `extract_pdf`, `Redactor.redact_lines`, `parse_sections`, `validate_resume_content`, `chunk_resume_content`, `EmbeddingModel` |
| ... `errors.py`, `config.py`, `vocab.py` | Contract error codes, pinned model/limits, word lists | `ProcessingError`, `EMBEDDING_VERSION` |
| ... `slot.py`, `worker.py` | Isolated child process, one processing slot, 60 s deadline | `ProcessingService`, `try_acquire()`, `Lease.run()`, `run_async()` |
| `src/backend/app/catalogue/` | Validates and imports the internship catalogue into PostgreSQL | `importer.py`: `import_catalogue`; CLI `python -m app.catalogue.import_jobs`; `models.py` (tables) |
| `src/backend/app/matching/` | Requirement-level ranking, skill gaps, explanations | `scoring.py`: `rank_jobs`; `sql.py`: `rank_jobs_sql` (pgvector); `skill_gap.py`: `analyse_skill_gap`; `explain.py`: `explain_job`; `recommend.py` |
| `src/backend/migrations/versions/c1a7d3f09b52_add_catalogue_tables.py` | The one migration I added (jobs, requirements, vectors, app_state) | run with Alembic |
| `analytics/` | Evaluation harness comparing MiniLM and bge-small with two baselines | `python analytics/evaluate.py --fixtures data/evaluation` |
| `data/evaluation/` | Synthetic jobs, profiles and labels, plus criteria and provenance | see the label-file table in `data/evaluation/README.md` |
| `data/synthetic_jobs.json` | Same 30 jobs in the importer's format | used by the catalogue CLI |
| `tests/pipeline/` | 185 tests on the real model, Presidio and a real PostgreSQL | `python -m pytest tests/pipeline -q` |
| `tests/analytics/`, `tests/fixtures/` | Evaluation-script tests and 15 synthetic resume PDFs with their generator | `python -m pytest tests/analytics tests/fixtures -q` |
| `tests/load/` | Component load tests and the HTTP load script (with a throwaway reference harness) | `python tests/load/run.py --scenario all --out-dir evidence` |
| `evidence/` | Dated results: `test-data-ai.md`, `test-processing-matching.md`, `test-processing-isolation.md`, `load-*.md/.json`, `data-ai-eval-*.md/.json` | read the `.md` first |

## Documents to read, in order
1. `src/backend/PIPELINE.md`: module table, how the API layer should call it, known gaps.
2. `src/backend/JIAXIN_INTEGRATION.md`: what Jiaxin must do to wire it up.
3. `evidence/test-processing-matching.md` and `evidence/test-processing-isolation.md`: what was tested and measured.
4. `evidence/test-data-ai.md`: ranking quality results and the label-provenance section.
5. `AI_USE_DECLARATION.md`: what AI wrote and how the labels were made.

## What is not done
- No route calls this code; `ACTIVE_EMBEDDING_VERSION` in `me.py` is still a stub.
- Labels are AI-drafted; only 12 pairs were decided by a team member. Results are provisional.
- The HTTP load numbers come from the reference harness, not the real API.
- The processing child is not an OS sandbox (no memory or CPU limit).
