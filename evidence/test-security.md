# Cloud security test record

Status: PARTIAL PASS — user-reported live checks on 2026-09-27. Results were transcribed from user-provided terminal output, screenshots, and confirmations; no independent penetration test was performed.

- Objective: Check deployed authentication, unauthenticated API rejection, and basic user-data separation.
- Environment: AWS us-east-1, `https://internshipmatcher.duckdns.org`, tested source snapshot SHA-256 `f18034f19af1d8781d5b05667e2da64041df0c9706c906e186a96522a20bd968` (commit `4a9b781e3ae9afcc36b7d104449c131d81e115ac`).
- Results (user-executed/user-reported):
  - Google sign-in succeeded in the browser.
  - Opening `/resume` while signed out redirected to login.
  - A request to `GET /api/resume` without login cookies returned HTTP 401; the user supplied the status only, with response body suppressed.
  - A second Google account showed an empty resume state while the first account's synthetic saved resume remained present when the user returned to the original account.
  - HTTPS was enabled for the DuckDNS hostname and the user reported the app remained accessible after refresh.
- Interpretation: The observed unauthenticated gate and basic UI-level account separation behaved as expected for these requests/accounts.
- Limitations: This is not a complete cross-user authorization/IDOR test. No direct authenticated API calls were made as both identities to probe object ownership, and CSRF, cookie attributes, token/session expiry, rate limits, and broader privacy controls are not proven by these observations. Do not claim comprehensive security validation.
- Secret handling: Secret values, session cookies, and resume text are intentionally omitted. Screenshots contain personal account display names/student context and must be redacted before being copied into a submission bundle.
- Evidence source: `evidence/cloud-foundation-run-2026-09-27.md`; original sanitized CLI outputs and redacted screenshots still need to be exported for formal evidence.
