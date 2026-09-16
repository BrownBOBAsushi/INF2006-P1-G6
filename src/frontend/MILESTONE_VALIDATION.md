# Frontend foundation validation — 2026-09-12

Scope: Xue E's first bounded local milestone. Branch:
`feature/xue-frontend-foundation`, based on existing `origin/dev` at `62004d9`.
Nasya's resume source and tests were preserved unchanged.

Environment: Windows x64, PowerShell; Node 24.21.0, npm 11.19.0.
Git was available at `C:/Program Files/Git/cmd/git.exe` but absent from PATH.
Node was downloaded from the official release URL to a task-specific temporary
directory and SHA-256 checked against that release's SHASUMS256.txt.
No system-wide package installation or cloud provisioning was performed.

## Exact runtime setup used

Working directory for npm commands: `src/frontend`.

```powershell
$env:PATH = (Join-Path $env:TEMP 'inf2006-node-24.21.0/node-v24.21.0-win-x64') + ';' + $env:PATH
$env:npm_config_cache = Join-Path $env:TEMP 'inf2006-npm-cache'
$env:npm_config_offline = 'false'
```

The normal developer commands are npm equivalents below; `npm.cmd` avoids
PowerShell script execution-policy differences.

## Actual commands and results

| Command | Result |
|---|---|
| `npm.cmd view react version --offline=false` | 19.3.0 |
| `npm.cmd view react-router@7 version --json --offline=false` | Verified available 7.x releases; selected 7.18.3 |
| `npm.cmd view vite@7 version --json --offline=false` | Confirmed existing 7.3.6 pin available |
| `npm.cmd view vitest@3 version --json --offline=false` | Confirmed existing 3.2.7 pin available |
| `npm.cmd install` | Exit 0; added 164 packages, audited 165 in 33 s; generated package-lock.json |
| `npm.cmd run typecheck` | Exit 0; TypeScript no-emit check passed |
| `npm.cmd test` | Final: exit 0; 9 test files, 138 tests passed; 13.47 s, start 21:29:31 SGT |
| `npm.cmd run build` | Final: exit 0; 63 modules, 937 ms; HTML 0.41 kB, CSS 2.89 kB, JS 316.43 kB (99.19 kB gzip) |
| `& ./node_modules/.bin/vite.cmd build --mode mock` | Exit 0; same production files/hashes, 843 ms; fixture exclusion guard passed |
| `npm.cmd run dev:mock` | Vite ready at http://localhost:8080 in 1782 ms |
| `Invoke-WebRequest -UseBasicParsing http://localhost:8080/` | HTTP 200; HTML root present |
| `Invoke-WebRequest -UseBasicParsing http://localhost:8080/jobs/00000000-0000-4000-8000-000000000025` | HTTP 200; SPA deep-link fallback |
| `Invoke-WebRequest -UseBasicParsing http://localhost:8080/src/main.tsx` | HTTP 200; explicit development fixture entry present |
| `git diff --exit-code origin/dev -- src/frontend/src/features/resume` | Exit 0; no changes to Nasya's feature |
| `git diff --check` | Exit 0; only Windows LF/CRLF informational warnings |

The preview process was stopped after smoke checks.

From the repository root:

```powershell
rg 'synthetic-preview-credential|synthetic-session-csrf|Synthetic Harbour Lab|Synthetic Orchard Studio|Enter synthetic preview|synthetic-application|synthetic-course' src/frontend/dist
```

No matches. The build plugin also inspects emitted module identities for dev,
fixtures and test modules. Both normal and mock-mode production builds passed it.

## Failures encountered and resolved

- Initial Git branch creation was blocked by read-only .git sandbox permissions;
  the approved retry created the feature branch. Existing origin/dev history was
  fast-forwarded into it after inspection.
- Node/npm network access initially failed in the sandbox (Node connection error,
  npm ENOTCACHED). Approved official release/registry access succeeded.
- Initial test/build startup failed with esbuild `spawn EPERM` in the sandbox.
  Approved execution outside the sandbox resolved this.
- First production build found a UTF-8 BOM in package.json written by PowerShell.
  Rewriting it as UTF-8 without BOM resolved the parser error.
- First expanded test run: 136 passed, one failed because a mocked Response body
  was reused after reading. The fixture now returns a fresh response each call.
  One additional session/draft regression test was then added; final result 138/138.

## Coverage and limits

The 38 new tests cover shared transport cookie/CSRF behavior, multipart boundaries,
idempotency header preservation, API-path restrictions, HTTP/error/timeout behavior,
literal keyword AND matching, punctuation, OR-within/AND-between filters, unknowns,
sorting, pagination/revision resets, stale response suppression, optional onboarding,
active/closed/not-found details, external Apply, resume route mounting, logout
clearing and draft retention across session expiry/reauthentication.

Nasya's 100 tests cover her existing resume workflow. No resume feature files were
modified to get them passing. Component tests run in jsdom; HTTP smoke checks do
not constitute a visual browser or real Google/backend end-to-end test.

Install warnings: two moderate vulnerability advisories and deprecated
whatwg-encoding. npm also reported esbuild's postinstall not yet covered by its
allowScripts policy; actual build/test execution succeeded. No automatic audit
fix, unrelated upgrade, global npm upgrade or fabricated lockfile was used.
Advisory remediation needs a separate scoped dependency decision.

Backend/OpenAPI, Google client configuration, real CSRF/session enforcement and
real catalogue integration remain pending Jiaxin's artifacts. Nasya's recommendation
component is absent and represented by an explicit route placeholder. Mock resume
preparation/saving deliberately returns unavailable. This is frontend milestone
evidence, not a completed local MVP or deployment claim.

## Files changed in this milestone

- AI_USE_DECLARATION.md
- README.md
- src/frontend/.env.example
- src/frontend/.npmrc
- src/frontend/.nvmrc
- src/frontend/index.html
- src/frontend/MILESTONE_VALIDATION.md
- src/frontend/package.json
- src/frontend/package-lock.json
- src/frontend/README.md
- src/frontend/src/api/client.test.ts
- src/frontend/src/api/client.ts
- src/frontend/src/api/contracts.ts
- src/frontend/src/App.test.tsx
- src/frontend/src/App.tsx
- src/frontend/src/dev/catalogue.ts
- src/frontend/src/dev/mockFetch.tsx
- src/frontend/src/dev/README.md
- src/frontend/src/env.d.ts
- src/frontend/src/features/auth/GoogleSignIn.tsx
- src/frontend/src/features/auth/Onboarding.tsx
- src/frontend/src/features/catalogue/catalogue.test.ts
- src/frontend/src/features/catalogue/Catalogue.tsx
- src/frontend/src/features/catalogue/JobDetails.tsx
- src/frontend/src/features/catalogue/query.ts
- src/frontend/src/main.tsx
- src/frontend/src/styles.css
- src/frontend/THIRD_PARTY_NOTICES.md
- src/frontend/vite.config.ts
