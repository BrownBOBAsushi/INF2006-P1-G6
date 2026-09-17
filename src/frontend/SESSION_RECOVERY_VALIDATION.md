# Session recovery validation — 2026-09-16

Scope: Xue E's next bounded frontend milestone, after the initial shell/fixtures:
session and CSRF recovery, old-account isolation, and real HTTP client tests.
See [integration/coordination notes](SESSION_RECOVERY_HANDOFF.md).

## Repository recovery and ownership

The turn began on `xue` at `fe74056` with unresolved stash conflicts in
frontend README, package.json and vite.config.ts. The earlier frontend changes
were staged, while Nasya's source and test configuration were missing.

The original frontend files, root README/AI declaration and Git index were
backed up to `$env:TEMP/inf2006-frontend-recovery-20260915-211838`.
The conflicts were resolved preserving the implementation and pins, and branch
`feature/xue-session-recovery` was created without discarding staged work.
These are local, uncommitted changes; staging from the original checkout is
retained, with new work/restored files also present in the working tree.

Commands used (Git executable was `C:/Program Files/Git/cmd/git.exe`):

```text
git fetch origin
git add -- src/frontend/README.md src/frontend/package.json src/frontend/vite.config.ts
git switch -c feature/xue-session-recovery
git restore --source=origin/dev --worktree -- src/frontend/src/features/resume src/frontend/tsconfig.json src/frontend/vitest.setup.ts
```

Fetch first failed because .git/FETCH_HEAD was read-only in the sandbox; the
approved retry succeeded. Restored files were verified using
`git ls-tree`, `git rev-parse origin/dev:<path>` and
`git hash-object --path=<path> <path>`: **30 files, 0 mismatches**.
`git ls-files -u` is empty. No backend, database, infrastructure, handoff contract
or resume feature source changes were made.

## Runtime and exact validation commands

Windows x64, PowerShell, Node 24.21.0, npm 11.19.0. Existing temporary runtime
and installed frontend dependencies were reused; no system installation.

Run from `src/frontend`:

```powershell
$env:PATH = (Join-Path $env:TEMP 'inf2006-node-24.21.0/node-v24.21.0-win-x64') + ';' + $env:PATH
$env:npm_config_cache = Join-Path $env:TEMP 'inf2006-npm-cache'
npm.cmd view @types/node@24 version --json
npm.cmd install --save-dev --save-exact @types/node@24.13.4 --offline=false
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
& ./node_modules/.bin/vite.cmd build --mode mock
```

| Check | Actual result |
|---|---|
| Node type version lookup | Exit 0; verified 24.13.4 available |
| Pinned type dependency install | Exit 0; 2 packages added, 167 audited |
| Typecheck | Exit 0 |
| Final test run | Exit 0; **12 files, 163 tests passed**, 20.82 s; started 2026-09-16 10:59:01 SGT |
| Production build | Exit 0; 66 modules, 723 ms |
| Production build with mode mock | Exit 0; 66 modules, 699 ms; same output hashes |
| Bundle files | HTML 0.41 kB; CSS 2.89 kB; JS 321.47 kB (100.68 kB gzip) |
| Fixture exclusion build guard | Passed in both builds |
| git diff --check | Exit 0; only LF/CRLF informational warnings |

Vite/Vitest used approved execution outside the sandbox because this environment
blocks esbuild child processes. HTTP tests bind an ephemeral loopback listener and
close it after each test. No persistent test server or cloud resources were left.

Package-lock comparison against the pre-recovery snapshot used Node JSON parsing:
**zero existing package version or integrity changes**. Added entries only:
`@types/node@24.13.4` and `undici-types@7.18.2`.
An earlier PowerShell ConvertFrom-Json comparison could not parse the lockfile's
empty root key and was replaced by the successful Node check.

From the repository root:

```powershell
rg -l 'synthetic-preview-credential|synthetic-session-csrf|synthetic-http|Synthetic Harbour Lab|Synthetic Orchard Studio|Enter synthetic preview|synthetic-application' src/frontend/dist
```

No matches (rg exit 1 as expected); the enclosing verification returned success.

## Failures found and resolved

1. Before the fix,
   `npm.cmd test -- src/api/client.session.test.ts` failed **2/2** regressions:
   a delayed old-session 401 cleared current authentication, and CSRF_INVALID
   did not trigger shell recovery. Both now pass.
2. The new HTTP tests initially failed typecheck because Node test types were
   absent. The exact pinned dev dependency above resolved it. The sandbox install
   attempt without `--offline=false` failed ENOTCACHED on undici-types; the
   approved registry retry succeeded.
3. The expanded suite initially passed 162/163. Its catalogue-expiry fixture
   fired during onboarding navigation and was correctly discarded as a cancelled
   request. Expiry is now triggered by a search after the catalogue has loaded;
   the final test verifies the recovery dialog, unchanged route and refreshed
   catalogue.
4. npm still reports **two moderate advisories**, as in the previous milestone.
   No automatic audit fix or unrelated upgrade was applied. npm also notes
   esbuild's install script is not covered by allowScripts; actual builds pass.

## Coverage and limits

25 added regressions beyond the previous 138:
8 transport/session tests, 10 auth hook/schema tests, 4 real loopback HTTP tests,
and 3 shell recovery tests. Nasya's unchanged 100 tests remain included.

Covers delayed 401/response-body rejection, CSRF recovery without write replay,
account-bound adapters, blocked private calls during identity exchange, duplicate
Google callbacks, logout uncertainty/races, malformed account responses, draft
retention and clearing, recovery focus, catalogue resumption, HTTP cookies/Origin
forwarding, JSON/multipart headers, repeated literal filter queries, closed details,
Retry-After and lost-response/idempotency behavior.

The HTTP server is a synthetic contract fixture, not Jiaxin's API. Its harness
explicitly forwards cookies and Origin because Node has no browser cookie jar.
No real Google identity, browser cookie-security enforcement, server idle/absolute
expiry, database search, resume processing or backend end-to-end pass is claimed.
Generated OpenAPI and real auth/catalogue endpoints remain the next integration
dependency. No wire contract changes were made; coordination notes are prepared
for Nasya and Jiaxin, without claiming their approval.

## Files changed for this follow-up

Implementation and regressions:

- src/frontend/src/App.tsx
- src/frontend/src/App.test.tsx
- src/frontend/src/api/client.ts
- src/frontend/src/api/client.session.test.ts
- src/frontend/src/api/client.http.test.ts
- src/frontend/src/features/auth/authApi.ts
- src/frontend/src/features/auth/useSession.ts
- src/frontend/src/features/auth/useSession.test.tsx
- src/frontend/src/features/auth/SessionRecovery.tsx
- src/frontend/src/features/catalogue/Catalogue.tsx
- src/frontend/src/features/catalogue/JobDetails.tsx

Dependency/documentation changes:

- src/frontend/package.json
- src/frontend/package-lock.json
- src/frontend/THIRD_PARTY_NOTICES.md
- src/frontend/README.md
- src/frontend/SESSION_RECOVERY_HANDOFF.md
- src/frontend/SESSION_RECOVERY_VALIDATION.md
- AI_USE_DECLARATION.md (append this milestone's actual assistance/results)

Recovery also restores the 28 existing files under
`src/frontend/src/features/resume/**`, `src/frontend/tsconfig.json` and
`src/frontend/vitest.setup.ts` unchanged from origin/dev.
Earlier staged foundation files and root README changes were preserved; they are
not represented as new implementation in this follow-up.
