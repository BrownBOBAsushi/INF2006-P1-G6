# Local user journey verification — 2026-09-23

This report records the local integration journey checked against the current
build. It contains no resume content or account identifiers.

## Verified

- Google sign-in, logout, and re-login completed in the local app.
- The existing resume was saved, reloaded, edited, and saved again; the
  resulting content matched the prior saved content across the observed 53
  fields.
- A two-tab stale-revision save was rejected with a revision conflict. Keeping
  the draft explicitly resolved the conflict, and the original content was
  restored at revision 4.
- Saving unchanged content was a no-op and kept the revision unchanged.
- The profile confirmation flow continued into the resume view.
- Jobs search returned four Python results. Remote filtering returned one
  result; combined filters and reset worked; empty jobs and matches states were
  displayed.
- Matches pagination reached page 2 with 30 results, and matches search and
  filtering worked.
- An invalid job identifier returned the not-found response.
- Source apply links opened with `_blank`, `noopener`, and `noreferrer` using a
  synthetic example.com target; no real application was submitted.
- The re-login stale-resume adapter issue was fixed by making the final account
  epoch update in `useSession` observable. The latest frontend suite passed 209 tests
  across 17 files, excluding four tests that require an HTTP server.
- The focused frontend review suite passed 26 tests using the existing local
  context.
- After rebuilding the web bundle, reloading the current bundle, logging out,
  and signing in again on the same tab, the Resume view loaded saved profile
  revision 4 without alerts and without a page refresh. The editor showed the
  same 53 values as the original draft; discarding an unchanged edit left the
  profile unchanged. Matches loaded 30 results without alerts. This confirms
  the rebuilt stale-resume adapter fix in the core existing-account journey.
- With explicit approval, deleting the saved resume cleared the profile and
  recommendations at revision 5. The same 53 original fields were then
  restored at revision 6; refresh persisted the expected eight projects, two
  experience entries, and four education entries, the editor values matched,
  and Matches again showed 30 results.
- Malformed PDFs were rejected, scanned PDFs without selectable text were
  rejected, encrypted PDFs returned the password-protected error, and a file
  over 5 MiB was rejected client-side. A synthetic valid PDF prepared for
  review; cancelling did not save a replacement and the restored revision 6
  remained intact.
- A successful delete previously showed the generic save-failure banner. The
  frontend now uses a dedicated `DELETED` success status and has a regression
  test; 55 focused frontend tests, TypeScript/build checks, and review checks
  passed. A rebuilt web retest of this banner fix is pending.
- The disposable PostgreSQL backend suite passed 71 tests with 40 warnings in
  1.22 seconds after the fixture insert-order fix.
- After restarting the database, API, and web services, both browser tabs
  loaded the saved revision 6 profile with eight projects, two experience
  entries, and four education entries without alerts. Matches loaded 30
  results; the editor values still matched the original 53-field draft and an
  unchanged edit was discarded. This verifies browser-observable restart
  persistence, without claiming a backup/restore or direct vector audit.

## Pending or intentionally unperformed

- Session expiry and processing overload were not forced live.
- Cloud TLS, secure-cookie deployment, backup/restore, live-data provenance,
  load testing, OpenAPI validation, and proxy mismatch checks remain outside
  this local journey evidence.
