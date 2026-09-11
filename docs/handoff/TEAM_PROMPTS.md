# Teammate starting prompts

Copy the relevant prompt into a coding-agent task opened in this repository. Assignments below follow the proposed feature split; coordinate any swaps. Start after the handoff branch has been shared through the team’s normal review process.

## Jiaxin

```text
I’m Jiaxin, responsible for backend authentication, PostgreSQL schema/migrations, API wiring and safe profile transactions.

My first milestone is the shared local backend foundation: Docker Compose with persistent PostgreSQL/pgvector, one API process, migrations, health endpoints and typed API schemas. Coordinate Compose/runtime choices with Chuying and the frontend origin/client with Xue E. Then implement Google verification, session cookies/CSRF, /me and profile revision/idempotency handling. Own src/backend/app/auth, api, db and migrations; coordinate shared application wiring. Use Chuying’s processing/matching interfaces rather than implementing a second pipeline. Document exact startup/migration/test commands. Identify required Google client configuration without requesting secret values in chat.

Read docs/handoff/MVP_PRD.md, ARCHITECTURE.md, DATA_API_CONTRACT.md, IMPLEMENTATION_GUIDE.md and TEAM_SETUP.md first. Inspect the existing repository before changing anything. The handoff is the current contract; DESIGN_CHECKPOINT.md is historical context. Work on a feature branch. You are not alone in this codebase: preserve teammates’ edits and coordinate shared files. Build only the local MVP; do not provision AWS or add deferred features. Use synthetic data, preserve source licences and pin dependencies. Never expose secrets or real resume contents. Begin implementing the first bounded milestone below, test it, and report files changed, actual commands/results and remaining blockers. If another teammate’s component is missing, use contract-shaped test fixtures rather than modifying their ownership area.
```

## Chuying

```text
I’m Chuying, responsible for PDF extraction/privacy, embeddings, matching, catalogue import and AI/load evaluation.

My first milestone is a tested synthetic-data processing slice: verify pinned Python/ML dependencies, prepare a synthetic PDF, produce a cleaned review draft and generate MiniLM vectors from approved structured content. Own processing, matching and catalogue modules plus analytics and related tests. Coordinate database fields/migrations and process-slot integration with Jiaxin; do not independently change API/auth wiring. Follow the 240-token input limit, requirement OR scoring and privacy restrictions. Provide mocked responses for Nasya early. Then implement validated manual JSON import and exact pgvector aggregation. No hosted LLM, live provider calls or background queue in student workflows.

Read docs/handoff/MVP_PRD.md, ARCHITECTURE.md, DATA_API_CONTRACT.md, IMPLEMENTATION_GUIDE.md and TEAM_SETUP.md first. Inspect the existing repository before changing anything. The handoff is the current contract; DESIGN_CHECKPOINT.md is historical context. Work on a feature branch. You are not alone in this codebase: preserve teammates’ edits and coordinate shared files. Build only the local MVP; do not provision AWS or add deferred features. Use synthetic data, preserve source licences and pin dependencies. Never expose secrets or real resume contents. Begin implementing the first bounded milestone below, test it, and report files changed, actual commands/results and remaining blockers. If another teammate’s component is missing, use contract-shaped test fixtures rather than modifying their ownership area.
```

## Xue E

```text
I’m Xue E, responsible for the frontend foundation, login/onboarding, job browsing, search/filtering and job details.

My first milestone is the React/TypeScript shell with routing, shared API client and contract-shaped catalogue fixtures, so Nasya can work in parallel. Own shared frontend router/client and auth/catalogue/detail components; coordinate with Nasya before shared changes and with Jiaxin for OpenAPI/CSRF. Implement optional resume onboarding, keyword AND semantics, filter OR-within/AND-between rules, paging resets and active/closed details. External Apply opens the source without sending our resume. No direct database access. Do not wait for all backend endpoints to exist: isolate mock fixtures from production builds, then connect the real API.

Read docs/handoff/MVP_PRD.md, ARCHITECTURE.md, DATA_API_CONTRACT.md, IMPLEMENTATION_GUIDE.md and TEAM_SETUP.md first. Inspect the existing repository before changing anything. The handoff is the current contract; DESIGN_CHECKPOINT.md is historical context. Work on a feature branch. You are not alone in this codebase: preserve teammates’ edits and coordinate shared files. Build only the local MVP; do not provision AWS or add deferred features. Use synthetic data, preserve source licences and pin dependencies. Never expose secrets or real resume contents. Begin implementing the first bounded milestone below, test it, and report files changed, actual commands/results and remaining blockers. If another teammate’s component is missing, use contract-shaped test fixtures rather than modifying their ownership area.
```

## Nasya

```text
I’m Nasya, responsible for resume upload/review/editing and personalised recommendation screens.

My first milestone is the PDF upload and editable review flow using contract-shaped fixtures, coordinated with Xue E’s router/client. Own resume and recommendation components. Keep drafts only in memory; handle unassigned cleaned text, review-required responses, processing busy, session expiry, uncertain save outcomes and stale revision conflicts. Preserve idempotency keys across network retries and refresh current profile after a replay. Connect Chuying/Jiaxin endpoints as they become available. Show ranked jobs with closest passages and separate skill evidence/eligibility, without match-percentage claims. Cover empty/no-resume/no-chunks/closed-job states in tests.

Read docs/handoff/MVP_PRD.md, ARCHITECTURE.md, DATA_API_CONTRACT.md, IMPLEMENTATION_GUIDE.md and TEAM_SETUP.md first. Inspect the existing repository before changing anything. The handoff is the current contract; DESIGN_CHECKPOINT.md is historical context. Work on a feature branch. You are not alone in this codebase: preserve teammates’ edits and coordinate shared files. Build only the local MVP; do not provision AWS or add deferred features. Use synthetic data, preserve source licences and pin dependencies. Never expose secrets or real resume contents. Begin implementing the first bounded milestone below, test it, and report files changed, actual commands/results and remaining blockers. If another teammate’s component is missing, use contract-shaped test fixtures rather than modifying their ownership area.
```

## Short version for subsequent sessions

“I’m [name]. Read docs/handoff/TEAM_PROMPTS.md and follow my role. Inspect current implementation and teammates’ changes, identify my next unfinished milestone, then implement and test it within my ownership. Report real results and coordinate contract changes.”

## Zhihao review prompt

```text
I’m Zhihao, the moderator and reviewer. Read the handoff and inspect the current diff. Review scope, contract consistency, authentication/ownership/privacy, atomic saves, retry behaviour and actual test evidence. Explain concrete issues and their impact; don’t implement unrelated features, change teammates’ work or deploy resources. Distinguish missing implementation from failed verification. Prioritise blockers to the local end-to-end MVP.
```
