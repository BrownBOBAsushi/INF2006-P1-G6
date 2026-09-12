# Frontend

Xue E coordinates root routing, shared client, auth and catalogue. Nasya owns resume review and recommendation views. Split is proposed for team coordination.

Read ../../docs/handoff/MVP_PRD.md and DATA_API_CONTRACT.md. Use generated OpenAPI types and shared mock fixtures; no direct PostgreSQL access. Private drafts stay in memory. Implement frontend tests here or in ../../tests/frontend/ with one documented runner.

## Resume feature workspace

The resume feature lives in `src/features/resume/`. Its README describes the shared
transport integration. The router, authentication shell and real backend remain
separate team work; this workspace builds an importable feature library, not a
standalone application.

From this directory:

```sh
npm install
npm run typecheck
npm test
npm run build
```

`build` produces `dist/resume.js`; React stays external and fixtures/tests are not
part of the public entry point. Run the feature through Xue E's shell for browser
integration; there is no standalone HTML entry page yet.

### Review fixes, 2026-09-12

Restored source/configuration/test filenames from the extensionless root files and
removed five byte-identical duplicates. Added regression coverage for post-deletion
revision tracking, manual save replay, failed refreshes, conflict reconciliation,
editing during save and editing during PDF preparation. Concurrent profile
recreation between an absent-profile read and the account read blocks saving
until the current profile has been loaded.

Verification used an isolated copy of locally installed dependencies because npm
registry DNS failed, including after an elevated retry. Actual versions: React and
React DOM 19.2.7, TypeScript 5.9.3, Vite 5.4.21, Vitest 2.1.9, jsdom 25.0.1,
@vitejs/plugin-react 4.7.0 and @testing-library/react 16.3.2. These differ from the
provisional manifest. The declared dependency pins and a clean installation still
need verification when registry access returns; no lockfile was fabricated.
