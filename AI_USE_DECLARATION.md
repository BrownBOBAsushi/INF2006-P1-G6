# AI use declaration

Status: living declaration, not final submission.

| Tool | Use so far | Verification / limitation |
|---|---|---|
| OpenAI Codex | Assisted architecture discussion, source research, PRD/API/schema handoff, backend API integration and hardening review, synthetic PDF fixture restoration/regression-test assistance and repository scaffold; on 2026-09-22 implemented the approved frontend/runtime integration in `src/frontend/**`, Dockerfiles, Compose/proxy configuration and local runbook, then added explicit logout CSRF recovery and disposable test wiring | Frontend typecheck, 198 frontend tests and production build passed with the test/build harness using `envDir:false`; four HTTP loopback tests were excluded because listenEPERM blocked their local listener. Compose config parsing passed. Focused backend checks recorded 30 passed and 3 skipped; 40 PDF fixture/extraction checks passed under an alternate cached runtime, not the pinned production environment. Docker/model download, full disposable PostgreSQL/ML runtime, real Google login, browser end-to-end and load acceptance remain pending. |
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

## Frontend foundation assistance — 2026-09-12

OpenAI Codex assisted Xue E's requested local frontend milestone: React/TypeScript
routing, shared same-origin CSRF client, login and optional onboarding, synthetic
catalogue browsing/search/paging, active/closed details, tests and dependency locking.
Nasya's existing origin/dev resume feature was inspected and mounted without edits.

Scope/files and actual validation are recorded in
[src/frontend/MILESTONE_VALIDATION.md](src/frontend/MILESTONE_VALIDATION.md).
Final checks: typecheck passed, 138 tests passed, production and mock-mode production
builds passed, localhost HTTP smoke checks passed. Real Google/backend end-to-end
verification and human review remain pending. No cloud resources were created.

Only direct dependencies were used; no upstream template internals were copied.
Nasya's declared dependencies were preserved, react-router 7.18.3 was added, and
npm generated an integrity lockfile. Exact versions/licences and retained runtime
notices are in [src/frontend/THIRD_PARTY_NOTICES.md](src/frontend/THIRD_PARTY_NOTICES.md).
Synthetic fixtures contain no provider records, secrets or real resume contents.

## Frontend session recovery assistance — 2026-09-16

OpenAI Codex assisted Xue E's next frontend milestone after inspecting TEAM_PROMPTS,
the current handoff, Nasya's origin/dev feature and Jiaxin's backend branch.
Recovered the conflicted local frontend checkout while preserving its staged work
and restoring teammate files unchanged. Implemented session/CSRF recovery, stale
response and account isolation, and synthetic loopback HTTP integration tests.

Actual validation: typecheck passed; 163 tests passed (including Nasya's unchanged
100); normal and mock-mode production builds passed with fixture exclusion.
Added only pinned @types/node 24.13.4 and its required type dependency; existing
lockfile versions/integrities were preserved. No real Google/backend end-to-end
result, teammate approval, cloud deployment or human review is claimed.

See [session recovery validation](src/frontend/SESSION_RECOVERY_VALIDATION.md)
for commands, failures resolved, changed files and remaining integration dependencies.
No upstream implementation was copied and no real resume/credential data was used.
