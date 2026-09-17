# AI use declaration

Status: living declaration, not final submission.

| Tool | Use so far | Verification / limitation |
|---|---|---|
| OpenAI Codex | Assisted architecture discussion, source research, PRD/API/schema handoff and repository scaffold | Compared against supplied brief and user decisions; document checks only. No application implemented/tested/deployed by this scaffold. |

Implementation agents and other tools must be added as used. Do not claim Claude/ChatGPT extracted a dataset until the team actually does it. Record prompt/task scope, changed files, human checks and actual tests.

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
