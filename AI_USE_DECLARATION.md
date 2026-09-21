# AI use declaration

Status: living declaration, not final submission.

| Tool | Use so far | Verification / limitation |
|---|---|---|
| OpenAI Codex | Assisted architecture discussion, source research, PRD/API/schema handoff and repository scaffold | Compared against supplied brief and user decisions; document checks only. No application implemented/tested/deployed by this scaffold. |
| Claude (Anthropic, Claude Code) | 2026-09-20: wrote `analytics/evaluate.py`, its unit tests, the 30 synthetic jobs, 10 synthetic profiles and the **draft** relevance labels/criteria under `data/evaluation/`, ran the evaluation, generated the synthetic resume PDFs (`tests/fixtures/`), and on 2026-09-21 implemented `src/backend/app/{processing,matching,catalogue}` (PDF extraction, privacy, chunking, embeddings, catalogue import, requirement-level matching, skill gaps, explanations), one migration, `tests/pipeline`, and `tests/load/run.py`; on 2026-09-21 also the isolated processing child and slot (`app/processing/slot.py`, `worker.py`), an HTTP reference harness and the API-level load script (`tests/load/harness_app.py`, `api_load.py`) and the integration guide for Jiaxin, on request of Chuying | Labels are AI-drafted and **not yet human-reviewed** (see `data/evaluation/LABELLING_CRITERIA.md`); results are provisional. Code checked by unit/integration tests (see `tests/pipeline/README.md`, run against the real pinned model, Presidio and a real PostgreSQL) and by running the harness (`evidence/data-ai-eval-2026-09-20.md`); labels were written before any model output existed (git history). |

Implementation agents and other tools must be added as used. Do not claim Claude/ChatGPT extracted a dataset until the team actually does it. Record prompt/task scope, changed files, human checks and actual tests.

## Label provenance (added 2026-09-22; written by Chuying, awaiting review by Zhihao)

- The 300 relevance labels in `data/evaluation/labels.csv` were drafted by Claude before any model output existed. They are AI-drafted.
- Chuying decided 12 disputed pairs personally, **after seeing the AI labels** (adjudication, not blind labelling), and changed 6 of them
  (P04-J16, P04-J21, P06-J26, P07-J01, P07-J26, P08-J01). Record: `data/evaluation/labels_human_adjudication12.csv`.
- A further 48 labels were supplied by a team member as `data/evaluation/labels_48.csv`. **Their origin has not been verified**; they agree with the
  AI draft on 45 of 48 pairs. They are used only in one evaluation run (`evidence/data-ai-eval-2026-09-22-merged-v2-unverified48.md`, see `data/evaluation/README.md`) and are not claimed as human ground truth.
- The other pairs are AI-drafted and unreviewed. No label set is claimed to be independent human labelling; `manifest.json` `label_review.status` stays `PENDING`.
- Other label files supplied during review were checked and not used. All metrics that depend on labels are provisional (`evidence/test-data-ai.md`).

## Baselines and licences

The reuse checklist in docs/handoff/IMPLEMENTATION_GUIDE.md identifies FastAPI Template, react-dropzone, pdfplumber, Presidio, Sentence Transformers, MiniLM, pgvector and optional code references. These are selected/reference candidates; no upstream code is imported by this scaffold.

Before copying/installing: record exact repository/model revision, file paths used, licence, retained notices and team modifications. Update this declaration with tested dependencies. Provider API use is different from an open-source code licence; record data permission separately.
