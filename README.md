# INF2006-P1-G6

## Internship Matcher — implementation handoff

The team is building a local-first internship browsing app with resume-based semantic recommendations.
Application code and cloud deployment are not supplied by this documentation handoff.

Read in order:

1. [MVP PRD](docs/handoff/MVP_PRD.md) — scope and acceptance criteria.
2. [Architecture and decisions](docs/handoff/ARCHITECTURE.md) — editable diagram, reasoning and deployment boundary.
3. [Database/API contract](docs/handoff/DATA_API_CONTRACT.md) — schemas, endpoints, matching and safe retries.
4. [Implementation guide](docs/handoff/IMPLEMENTATION_GUIDE.md) — suggested ownership, three-week sequence and evidence gates.

[Design checkpoint](docs/DESIGN_CHECKPOINT.md) preserves the discussion history; the handoff consolidates its decisions.
The optional [JSearch research script](docs/JSEARCH_RESEARCH.md) is not the MVP. Do not commit credentials, real resumes or unlicensed provider data.

## Team and current state

Jiaxin and Chuying: backend. Xue E and Nasya: frontend. Zhihao: moderation, design and review. Proposed detailed ownership and environment preparation: [team setup](docs/handoff/TEAM_SETUP.md).

Planned stack: React/TypeScript, FastAPI/Python, PostgreSQL/pgvector, pdfplumber, Presidio, Sentence Transformers/MiniLM, Docker Compose. Application/dependency locks are not implemented yet. There is no verified application quick-start command; bootstrap is the first implementation milestone. Each teammate will run their own local DB from shared migrations.

![Planned architecture — not deployed](evidence/architecture.svg)

## Submission scaffold

| Path | Current status |
|---|---|
| project_manifest.yaml | Required keys present; official group ID/student IDs and actual results pending |
| src/ | Backend/frontend/infra boundaries and placeholder .env.example |
| data/ | Provenance instructions and data dictionary; dataset pending |
| analytics/ | Evaluation instructions; implementation pending |
| evidence/ | Planned figure and explicitly NOT RUN test templates |
| tests/ | Backend/frontend/fixtures/load boundaries; tests pending |
| TEAM_CONTRIBUTIONS.md | Planned roles, no fabricated completed contributions |
| AI_USE_DECLARATION.md | Documentation assistance declared; update during implementation |
| report.pdf | Not yet produced; working outline at docs/REPORT_DRAFT.md |
| video_link.txt | Optional; omitted until a real link exists |

Before final packaging, replace all pending results, export the 8–12 page report.pdf, and verify manifest paths against real artefacts. This scaffold is not submission-ready. No cloud resources created; no credentials required to read these documents. Do not include local scratch scripts in the final package without review.

Copy-paste coding-agent prompts: [teammate prompts](docs/handoff/TEAM_PROMPTS.md).
