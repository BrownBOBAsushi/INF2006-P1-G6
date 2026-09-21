# AI use declaration

Status: living declaration, not final submission.

| Tool | Use so far | Verification / limitation |
|---|---|---|
| OpenAI Codex | Assisted architecture discussion, source research, PRD/API/schema handoff and repository scaffold | Compared against supplied brief and user decisions; document checks only. No application implemented/tested/deployed by this scaffold. |
| Claude (Anthropic, Claude Code) | 2026-09-20: wrote `analytics/evaluate.py`, its unit tests, the 30 synthetic jobs, 10 synthetic profiles and the **draft** relevance labels/criteria under `data/evaluation/`, ran the evaluation, generated the synthetic resume PDFs (`tests/fixtures/`), and on 2026-09-21 implemented `src/backend/app/{processing,matching,catalogue}` (PDF extraction, privacy, chunking, embeddings, catalogue import, requirement-level matching, skill gaps, explanations), one migration, `tests/pipeline`, and `tests/load/run.py`; on 2026-09-21 also the isolated processing child and slot (`app/processing/slot.py`, `worker.py`), an HTTP reference harness and the API-level load script (`tests/load/harness_app.py`, `api_load.py`) and the integration guide for Jiaxin, on request of Chuying | Labels are AI-drafted and **not yet human-reviewed** (see `data/evaluation/LABELLING_CRITERIA.md`); results are provisional. Code checked by unit/integration tests (see `tests/pipeline/README.md`, run against the real pinned model, Presidio and a real PostgreSQL) and by running the harness (`evidence/data-ai-eval-2026-09-20.md`); labels were written before any model output existed (git history). |

Implementation agents and other tools must be added as used. Do not claim Claude/ChatGPT extracted a dataset until the team actually does it. Record prompt/task scope, changed files, human checks and actual tests.

## Baselines and licences

The reuse checklist in docs/handoff/IMPLEMENTATION_GUIDE.md identifies FastAPI Template, react-dropzone, pdfplumber, Presidio, Sentence Transformers, MiniLM, pgvector and optional code references. These are selected/reference candidates; no upstream code is imported by this scaffold.

Before copying/installing: record exact repository/model revision, file paths used, licence, retained notices and team modifications. Update this declaration with tested dependencies. Provider API use is different from an open-source code licence; record data permission separately.
