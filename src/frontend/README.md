# Frontend

Owner: Xue E — application shell, routing, shared API client, auth/onboarding,
catalogue and job details. Nasya owns `src/features/resume/**` and the future
recommendation feature. Her existing resume implementation is mounted unchanged.

Read [PRD](../../docs/handoff/MVP_PRD.md) and
[API contract](../../docs/handoff/DATA_API_CONTRACT.md). The handoff governs;
types in `src/api/contracts.ts` are provisional, not generated OpenAPI.

## Run locally

Pinned runtime: Node **24.21.0**, npm **11.19.0** (`.nvmrc`, `engines`).
Nasya's existing direct dependency pins are preserved. The only added dependency
is `react-router@7.18.3`. Commit `package-lock.json`; use `npm ci` on subsequent
clean checkouts. Do not run an automatic dependency upgrade.

From the repository root:

```sh
cd src/frontend
npm install
npm run typecheck
npm test
npm run build
npm run dev:mock
```

Open **http://localhost:8080**. Choose **Enter synthetic preview**, confirm a
synthetic display name, and skip the optional resume step to browse 24 active jobs.
The 25th synthetic record is closed:
`/jobs/00000000-0000-4000-8000-000000000025`.

The fixture preview lives only in `src/dev/`, is imported dynamically only by
the explicitly selected development mode, and never patches global fetch.
Every build sets the mock switch false, including `vite build --mode mock`.
A build plugin rejects fixture/test modules in emitted JavaScript.
There is no mock server route or deployable test-auth dependency.

Fixture resume reads return the no-profile state. Preparation, saving and
matching return a clear unavailable response because those services are absent.
Nasya's feature tests supply richer synthetic resume responses independently;
no fabricated extraction or recommendation success is shown.

## Connect the real API

```sh
# Copy .env.example to .env.local and configure only the PUBLIC Google client ID.
npm run dev
```

Regular dev and production use real same-origin `/api` requests; there is no
fallback to fixtures when the API fails. Vite proxies to `http://127.0.0.1:8000`
and preserves Origin. Jiaxin must allow `http://localhost:8080` and provide the
auth/catalogue endpoints. Google must allow that same JavaScript origin.
No frontend DB credentials or direct database access exist.

Production static hosting must route non-API application paths to `index.html`
and proxy `/api` separately. Building is local only; infrastructure is not
provisioned by this milestone.

## Shared interfaces and teammate integration

- `src/App.tsx` owns routes: `/login`, `/onboarding`, `/jobs`, `/jobs/:id`,
  `/resume`, and a temporary `/matches` placeholder.
- `src/api/client.ts` implements Nasya's existing `HttpTransport`, exported
  from `src/features/resume/index.ts`. HTTP 4xx/5xx resolve for feature-specific
  handling; network/abort/100-second timeout rejects. No automatic write retries.
  Multipart keeps browser-generated boundaries; Idempotency-Key is preserved.
- Google exchange obtains bootstrap CSRF first; `GET /me` installs session CSRF.
  Unsafe requests use `X-CSRF-Token`. Cookies are same-origin, fetch caching is
  disabled, and tokens never go into browser storage or URLs.
- A 401 clears the CSRF token and opens sign-in without unmounting an existing
  draft. Same-account reauthentication retains that draft. Changing account or
  signing out remounts/clears private UI. Failed logout is reported as unconfirmed.
- Catalogue URL query state uses repeated keys, e.g.
  `work_arrangement=REMOTE&work_arrangement=HYBRID`. OR within each dimension,
  AND between dimensions. Keyword terms are literal AND terms. Production
  filtering/sorting occurs on the API before paging; the synthetic catalogue
  implements those rules for its English fixtures.
- Search/filter changes clear offset and catalogue revision. Subsequent pages
  send revision; RESULTS_CHANGED visibly restarts the first page.
- Details render source content as text. Closed details disable Apply. External
  HTTPS links use noopener/noreferrer and send no resume.

Coordination basis: the documented Nasya transport agreement from
`origin/dev` commit `62004d9` was inspected before shared configuration changes.
The feature branch was fast-forwarded to that history; no resume source/test files
were edited. No teammate message was sent or approval fabricated.

**Jiaxin integration pending:** generated OpenAPI; confirmation that FastAPI uses
the repeated query keys above (the handoff's `[]` denotes arrays); exchange and
PATCH success shapes; the exact names for cleaned-draft and conflict-revision
error details flagged in Nasya's README. Exchange is followed by GET /me and
PATCH by GET /me so neither assumes undocumented full-account success bodies.

**Nasya next step:** keep using `createResumeApi(sharedClient)`; replace the
`/matches` placeholder through a coordinated router change. Resume save and
processing behavior remain her and the backend owners' work.

## Verification and provenance

See [milestone validation](MILESTONE_VALIDATION.md) for dated actual results,
including sandbox failures. Component integration tests run in jsdom; real
Google sign-in, backend CSRF enforcement, cookie expiry and live API integration
remain unverified until those services/configuration exist.

All catalogue records are original synthetic examples using example.com links.
No provider data or real resumes are included. See
[third-party notices](THIRD_PARTY_NOTICES.md) for dependency attribution.
No template internals were copied. Runtime integration uses the official
[React Router declarative API](https://reactrouter.com/start/declarative/routing),
[Google Identity Services JavaScript API](https://developers.google.com/identity/gsi/web/reference/js-reference)
and [Vite build-time flags](https://vite.dev/guide/env-and-mode).

## Follow-up milestone: session recovery

The session recovery/client follow-up is documented in
[SESSION_RECOVERY_HANDOFF.md](SESSION_RECOVERY_HANDOFF.md), with current command
results in [SESSION_RECOVERY_VALIDATION.md](SESSION_RECOVERY_VALIDATION.md).
It adds stale-response protection, explicit CSRF recovery, account-bound resume
transport and real loopback HTTP tests. Backend OpenAPI/Google integration remains
pending. Existing dependency pins are retained; @types/node 24.13.4 is the added
development dependency for those HTTP tests.

## Reference UI redesign

The visual milestone, exact changed files, implementation boundaries, validation
and review routes are documented in [FRONTEND_REDESIGN.md](FRONTEND_REDESIGN.md).
The existing runtime, fixture isolation, API and teammate ownership rules above
remain in effect.
