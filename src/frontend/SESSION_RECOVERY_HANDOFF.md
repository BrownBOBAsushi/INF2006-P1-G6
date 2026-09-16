# Session recovery integration handoff — 2026-09-16

Owner: Xue E. Bounded milestone after the fixture-backed frontend foundation:
make authentication/session recovery ready for real API integration, without
changing backend contracts or Nasya's resume feature.

## Inspected teammate work

- `origin/dev` / `feature/xue-frontend-foundation`: `62004d9`, including Nasya's
  resume feature and documented `HttpTransport` interface.
- `origin/jiaxin`: `638177c`. Read `JIAXIN_NEXT_STEPS.md` and backend application
  wiring from that branch. It exposes health endpoints; Google auth, /me,
  catalogue routes and generated OpenAPI are not present.
- `git fetch origin` succeeded before inspection. No backend files were imported,
  edited, or replaced.

The starting `xue` checkout had three stash conflicts and was missing the files
that had been integrated from origin/dev in the previous session. Current user
work and the original Git index were backed up to
`$env:TEMP/inf2006-frontend-recovery-20260915-211838`.
The conflict resolution retains the frontend implementation and its dependency
pins. A new branch, `feature/xue-session-recovery`, preserves the current staged
work. Thirty missing files (Nasya's feature, tsconfig and Vitest setup) were
restored from origin/dev with matching Git blob hashes. No commit was created.

## Behavior supplied by the shell/client

- A 401 or an exact 403 CSRF_INVALID opens session recovery, stops private calls,
  and clears stale CSRF. Other 403 errors remain ordinary HTTP errors.
- GET /me explicitly confirms identity and CSRF before private work resumes.
  Failed or malformed account responses do not unlock the UI. There is no
  automatic session polling and no automatic write replay.
- Late responses from an invalidated session are discarded, including delayed
  body reads. Abort/network/timeout outcomes remain uncertain for unsafe writes;
  cancellation is not a claim that backend work stopped.
- Nasya receives `createResumeApi(client.scopedTransport())` from the router.
  The existing HttpTransport signature is unchanged. The adapter survives
  same-account reauthentication, retaining the draft and caller's idempotency key.
  Logout or a confirmed account change revokes older adapters, so a scheduled
  old feature retry cannot submit the prior account's draft with a new cookie.
- Private calls stay paused while Google exchange is in progress, even if its
  response has supplied new CSRF; GET /me must confirm the account first.
- A delayed /me cannot reinstall an account after logout. Failed logout clears
  local private UI immediately, reports the server outcome as unconfirmed, and
  requires an explicit retry before reconnect/sign-in.
- Recovery keeps the resume workspace mounted and limits keyboard focus to its
  dialog. Same-account recovery retains the draft; account changes remount it.
  Catalogue/detail reads refresh after successful recovery with URL query state
  preserved. Writes always require the user's next explicit action.

## Coordination notes for Nasya

No files in `src/features/resume/**` were edited. Its 100 baseline tests remain
part of the suite. Keep consuming the supplied ResumeApiPort/HttpTransport; do not
construct a new unscoped shared client inside a resume or recommendations feature.
The root adapter is replaced only when its account lifecycle changes.

REVIEW_REQUIRED and conflict-detail field names remain unresolved as already
documented in your feature README. This milestone does not rename those fields,
change save/idempotency logic or implement recommendation UI. Unsaved-navigation
registration remains a separate router/feature integration to agree.

## Coordination notes for Jiaxin

No endpoint, header, request payload or public response contract changed.
Implement the published bootstrap -> Google exchange -> /me flow, exact Origin
checks, stable session-bound X-CSRF-Token and the documented 401/403 envelopes.
GET /me must not extend idle lifetime. Logout should return 204 for an already
expired session after Origin validation. The frontend retains CSRF for an
explicit retry of an unconfirmed server logout.

Pending inputs: generated OpenAPI/types, real local auth/catalogue endpoints and
Google public client configuration. The repeated filter query convention remains
`work_arrangement=REMOTE&work_arrangement=HYBRID`; confirm it in OpenAPI.
Do not send secret values or real resume data in review/chat.

The branch documentation is a concrete integration handoff, not a claim that
either teammate has reviewed or approved these changes. No external messages
were sent.

## Test boundary

`src/api/client.http.test.ts` runs the production ApiClient against a temporary
loopback HTTP server with synthetic contract responses. It tests actual fetch,
JSON/multipart serialization, cookie/Origin forwarding, CSRF transitions,
closed catalogue records, retry headers and lost-response handling.

Node does not supply a browser cookie jar: the harness explicitly models Cookie
and Origin forwarding. These tests do not prove Google identity verification,
browser HttpOnly/SameSite enforcement, server idle expiry, SQL search semantics,
or a real backend end-to-end journey. The fixture server binds loopback on an
ephemeral port and shuts down after each test; it is never a production endpoint.

Runtime dependencies and previous lockfile entries are unchanged. The only new
direct package is `@types/node@24.13.4` for the HTTP tests, with
`undici-types@7.18.2` as its locked type dependency.

API reference used: [AbortController](https://developer.mozilla.org/en-US/docs/Web/API/AbortController/abort)
for canceling fetch/body reads; server outcomes still require the handoff's
idempotency resolution. Google integration follows the
[official JavaScript API](https://developers.google.com/identity/gsi/web/reference/js-reference).
