# AI use declaration

Status: living declaration, not final submission.

| Tool | Use so far | Verification / limitation |
|---|---|---|
| OpenAI Codex | Assisted architecture discussion, source research, PRD/API/schema handoff and repository scaffold | Compared against supplied brief and user decisions; document checks only. No application implemented/tested/deployed by this scaffold. |

Implementation agents and other tools must be added as used. Do not claim Claude/ChatGPT extracted a dataset until the team actually does it. Record prompt/task scope, changed files, human checks and actual tests.

## Baselines and licences

The reuse checklist in docs/handoff/IMPLEMENTATION_GUIDE.md identifies FastAPI Template, react-dropzone, pdfplumber, Presidio, Sentence Transformers, MiniLM, pgvector and optional code references. These are selected/reference candidates; no upstream code is imported by this scaffold.

Before copying/installing: record exact repository/model revision, file paths used, licence, retained notices and team modifications. Update this declaration with tested dependencies. Provider API use is different from an open-source code licence; record data permission separately.
