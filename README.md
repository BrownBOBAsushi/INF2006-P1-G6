# INF2006-P1-G6

## Internship Matcher — implementation handoff

The team is building a local-first internship browsing app with resume-based semantic recommendations.
The frontend local milestone is implemented below; backend integration and cloud deployment remain pending.

Read in order:

1. [MVP PRD](docs/handoff/MVP_PRD.md) — scope and acceptance criteria.
2. [Architecture and decisions](docs/handoff/ARCHITECTURE.md) — editable diagram, reasoning and deployment boundary.
3. [Database/API contract](docs/handoff/DATA_API_CONTRACT.md) — schemas, endpoints, matching and safe retries.
4. [Implementation guide](docs/handoff/IMPLEMENTATION_GUIDE.md) — suggested ownership, three-week sequence and evidence gates.

[Design checkpoint](docs/DESIGN_CHECKPOINT.md) preserves the discussion history; the handoff consolidates its decisions.
The optional [JSearch research script](docs/JSEARCH_RESEARCH.md) is not the MVP. Do not commit credentials, real resumes or unlicensed provider data.

## Team and current state

Jiaxin and Chuying: backend. Xue E and Nasya: frontend. Zhihao: moderation, design and review. Proposed detailed ownership and environment preparation: [team setup](docs/handoff/TEAM_SETUP.md).

Planned stack: React/TypeScript, FastAPI/Python, PostgreSQL/pgvector, pdfplumber, Presidio, Sentence Transformers/MiniLM, Docker Compose. Frontend dependency locks and local commands are available below; backend bootstrap remains pending. Each teammate will run their own local DB from shared migrations.

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

## Frontend local milestone

The React/TypeScript shell now runs against isolated synthetic catalogue fixtures.
Use Node 24.21.0 and npm 11.19.0:

```sh
cd src/frontend
npm install
npm run typecheck
npm test
npm run build
npm run dev:mock
```

Open http://localhost:8080, enter the synthetic preview, confirm a synthetic display
name and skip the optional resume step. Existing Nasya resume components are mounted;
preparation/saving and recommendations still need backend integration.

`npm run dev` uses the real API proxy at 127.0.0.1:8000. Configure only the public
Google client ID in src/frontend/.env.local. Production builds exclude fixtures.
Backend/Compose/OpenAPI and real Google sign-in are still pending; the complete
local MVP gate has not passed.

See [frontend integration and ownership](src/frontend/README.md),
[actual commands/results](src/frontend/MILESTONE_VALIDATION.md) and
[dependency notices](src/frontend/THIRD_PARTY_NOTICES.md).
