# Processing, matching and catalogue modules (Chuying)

Pure Python modules with no FastAPI/session dependency, called by the API layer through the existing contract.
The API routes now reuse the processing slot and pipeline; runtime model/database verification remains a separate
environment gate.

| Module | Purpose |
|---|---|
| `app/processing/pdf_extract.py` | pdfplumber extraction with font hints; every failure mapped to a contract error code (413/415/422). Limits: 5,242,880 bytes, 10 pages. No OCR. |
| `app/processing/privacy.py` | Presidio + spaCy `en_core_web_sm` + Singapore recognizers (phone, NRIC/FIN, Blk/street/unit/postal address) + resume-header rule; technical-term allow-list. |
| `app/processing/sections.py` | Deterministic heading/bullet parsing into the contract `ResumeContent`; anything unplaced goes to `unassigned_text` with `SECTION_REVIEW_NEEDED`. |
| `app/processing/chunking.py` | Entry -> chunks, every chunk <= 240 tokenizer tokens incl. heading/special tokens; sentence then token-boundary splitting; raises rather than truncates. |
| `app/processing/embeddings.py` | Pinned all-MiniLM-L6-v2 (revision in `config.py`), dimension read from the model (384), local cache only. |
| `app/processing/content.py` | `ResumeContent` validation (contract limits) and canonical `content_hash`. |
| `app/processing/pipeline.py` | `prepare_resume(pdf)`, `recheck_privacy(content)`, `embed_resume(content, model)`. |
| `app/processing/slot.py`, `worker.py` | Isolated child process, single non-blocking processing slot, 60 s deadline (terminate + join, recreate), safe release on disconnect. Integration guide: `JIAXIN_INTEGRATION.md`. |
| `app/catalogue/schema.py`, `importer.py`, `import_jobs.py`, `loader.py`, `models.py` | Validated JSON import (whole batch first), content hashes, embedding reuse, atomic upsert, CLI. |
| `app/matching/scoring.py` | Exact requirement-level scoring (max over alternatives x chunks, mean over REQUIRED), ranking, top-K after aggregation. |
| `app/matching/sql.py` | The same computation in one PostgreSQL/pgvector statement (`<=>`), LIMIT only after aggregation. |
| `app/matching/skill_gap.py`, `explain.py`, `recommend.py` | Exact whole-skill evidence with a small alias map, gaps, evidence-based explanations, recommendation page. |

## How the API layer should call it

```python
from app.processing.pipeline import prepare_resume, recheck_privacy, embed_resume
from app.processing.errors import ProcessingError, CONTRACT_ERRORS   # .code, .status_code, .message are contract-safe
from app.processing.config import EMBEDDING_VERSION                 # use this for ACTIVE_EMBEDDING_VERSION (me.py stub)

result = prepare_resume(pdf_bytes)              # -> {draft, unassigned_text, warnings}; raises ProcessingError
changed, cleaned = recheck_privacy(content)     # at PUT: if changed -> 422 REVIEW_REQUIRED with `cleaned`
emb = embed_resume(content, model)              # -> chunks [{section, entry_index, chunk_index, text}] + vectors (n, 384)
```

Ranking: `app.matching.sql.rank_jobs_sql(session, user_id=..., profile_revision=..., embedding_version=..., limit=5, offset=0, ...)`
returns `job_id, score, total`; the explanation for a page comes from `app.matching.recommend.recommend` (in-memory) or
`closest_passages_sql` plus `analyse_skill_gap`. **Scores are internal**: only `MatchExplanation.to_public()` may be sent to the browser.

The embedding model must be loaded once per process (`EmbeddingModel()`, about 5 s) and reused. It loads from the local Hugging
Face cache only; fetch it once with `python -m app.processing.embeddings --download` (and `python -m spacy download en_core_web_sm`).

## Database

One forward migration, `migrations/versions/c1a7d3f09b52_add_catalogue_tables.py` (down_revision `e378f7a1a884`), adds
`jobs`, `job_requirements`, `requirement_embeddings` (vector(384)) and `app_state` exactly as in DATA_API_CONTRACT.md. No existing
table is touched. `migrations/env.py` gained one import line so autogenerate sees the new models (`alembic check` reports no drift).

## Commands

```bash
# environment: see the header of requirements-processing.txt
python -m pytest tests/pipeline -q                                   # 152 tests, real model, real Presidio, real PostgreSQL (pgserver)
python -m app.catalogue.import_jobs --file data/synthetic_jobs.json --dry-run     # from src/backend, needs the cached model
DATABASE_URL=postgresql+psycopg://... python -m app.catalogue.import_jobs --file data/synthetic_jobs.json
python tests/load/run.py --scenario all --out-dir evidence
python analytics/evaluate.py --fixtures data/evaluation              # unchanged evaluation harness (analytics environment)
```

## Known gaps (read before relying on this)

- **Runtime gate.** The API starts one processing child and exposes readiness only after the pinned model and database
  schema are ready. A missing local model cache leaves `/health/ready` at 503; it must not be replaced with a fallback.
- **Process isolation.** `app/processing/slot.py` + `worker.py` provide the one-slot, 60 s-deadline isolated child.
  Its restrictions are best effort (no OS sandbox, no memory limit).
- **Privacy is best-effort.** spaCy's small model produces false positives on capitalised words (mitigated with allow-lists, see
  `vocab.py`) and can miss unfamiliar names. It was checked only on synthetic PII in 10 generated PDFs plus unit cases, so no
  recall/precision figure on real resumes exists. The student must review the draft.
- **Section parsing is heuristic** and was verified on PDFs produced by our own generator (simple single-column layout), so the
  exact round-trip result there is optimistic. Multi-column or graphical resumes are untested.
- **Page-limit error code.** The contract lists no code for "more than 10 pages"; the module returns `PDF_UNREADABLE` with an internal
  reason `page_limit`. Jiaxin/Zhihao should decide whether to add a dedicated code.
- **The evaluation harness keeps its own copy of the chunker** (`analytics/evaluate.py`); a test asserts the two are identical. Merging
  them would change the script hash of a recorded evaluation, so it was left alone.
- **pgvector version.** Tests ran on PostgreSQL 16.2 with pgvector 0.6.2 (embedded server); the compose image may ship a newer pgvector.
  Only the `<=>` operator and `vector(384)` are used.
