# Team contributions

Commit counts and areas are taken from `git shortlog -sne --all` and `git log --author=<name> --name-only` on
2026-10-03. Commit counts measure activity, not effort: some members pushed fewer, larger commits, and AI-agent work
run by a member is committed under that member's account (see [AI_USE_DECLARATION.md](AI_USE_DECLARATION.md)).

> **TEAM INPUT REQUIRED before submission:** each member confirms their row, adds student ID in
> `project_manifest.yaml`, and writes their own 2–4 sentence reflection. Do not let anyone else write it for you.

| Member (git identity) | Role | Artefacts / commits | Test / evidence ownership | Reflection |
|---|---|---|---|---|
| Jiaxin (`Goh Jia Xin`) | Backend: authentication, sessions, database, API | 8 commits, 2026-09-13 → 09-30; `src/backend/` (auth, sessions, models, migrations), `tests/backend/`, `docker-compose.yml`, `src/.env.example` | Backend auth/CSRF/session and migration tests (`tests/backend/`); security test inputs | _TEAM INPUT_ |
| Chuying (`Verarich888` — **confirm mapping**) | Backend: PDF processing, privacy, embeddings, matching, evaluation | 4 commits, 2026-09-22 → 10-01; `src/backend/` processing/matching, `tests/pipeline/`, `tests/fixtures/`, `tests/load/`, `data/evaluation/` | Data/AI evaluation (`evidence/test-data-ai.md`); 90 human relevance labels; load measurements | _TEAM INPUT_ |
| Xue E (`2501777-XueE`) | Frontend: login, catalogue, job details | 5 commits, 2026-09-16 → 09-21; `src/frontend/` (catalogue, details, shared client), UI review (`docs/xue-ui-review.html`) | Frontend catalogue/search tests; UI review | _TEAM INPUT_ |
| Nasya (`nova`) | Frontend: résumé upload/review, recommendations | 35 commits, 2026-09-12; `src/frontend/` résumé workspace types, upload validation and empty-state tests, Vitest setup | Frontend upload-validation and résumé UI tests | _TEAM INPUT_ |
| Zhihao (`BrownBOBAsushi`) | System design, integration, cloud deployment, review | 38 commits, 2026-09-10 → 10-03; architecture and handoff docs, `src/infra/` (CloudFormation, Nginx, bootstrap), async processing/outbox, frontend integration, evidence records | Cloud deployment and acceptance, functional/security/resilience/monitoring records, cloud capture | _TEAM INPUT_ |
