# Frontend reference redesign

Review milestone on `xue`, 21 September 2026. No commit, push, branch switch, merge,
backend changes, or dependency changes were made.

## Scope and reference

The supplied `internship_matcher_reference.html` informed the visual hierarchy,
nav, search dock, cards, login and detail layouts. `DEVELOPER_HANDOFF.md` and the
user's implementation boundaries governed which interactions could be adapted.
The standalone reference's hash router, demo authentication, scores and data were
not copied. The existing React Router, API client, session/CSRF recovery, URL
query state and teammate-owned resume implementation remain in use.

The earlier `docs/frontend-prototype.html` is a separate, pre-existing untracked
artifact. It was not modified or wired into this app. No `/preview/naysa` code
was reintroduced.

## Implemented

- Navy/blue/teal tokens, rounded panels, system font fallbacks, responsive compact
  navbar with active tabs and actual profile initials, and a shared footer.
- Two-column login with a slow mesh and a finite keyword sequence. Reduced-motion
  preference stops both. The actual Google Identity Services control is unchanged.
- Centered onboarding with display name, optional resume handoff, Skip for now,
  and Continue to jobs. Both jobs actions use the existing name-confirmation flow.
- Catalogue hero, search dock, accessible multi-select disclosure dropdowns,
  selected checkmarks, reset, quick search chips, `/` focus and Enter submission.
  Native checkbox keyboard behavior and Escape/outside-click/focus-leaving
  dismissal are preserved. OR within a group, AND between groups and keywords,
  literal punctuation, pagination and catalogue-revision handling remain intact.
- Pinning follows the measured navbar height. Only the optional, non-sensitive
  `internshipMatcher.searchDockPinned` boolean is stored. Storage denial does not
  prevent use; nothing is written on initial render. Mobile defaults to unpinned
  unless the reviewer has already set a preference. Short viewports suspend pinning
  without changing that preference so results remain reachable. Dropdowns use the
  available space above or below their controls.
- Job cards use source-backed title, company, location, categories and dates.
  `Imported listing` does not assert verification or current live availability.
- Job Detail has a company/title hero, summary taken from the description, metadata
  grid, description, requirement alternatives/quotes, eligibility notes, and a
  desktop action/source rail. Closed listings stay readable with Apply disabled.
  HTTPS-only external links retain noopener/noreferrer and no-referrer behavior.
- Resume gets shared outer spacing/card framing only. Matches gets a matching
  shell with an explicit unavailable state and links to existing routes.
- Loading, failed request/retry, empty results and not-found states retain real
  application behavior. Reduced motion and visible keyboard focus are supported.

## Deliberately absent / integration limits

- Match scores, animated rings/bars, personal statistics and the navbar match count
  are absent because the current API contract supplies none. Matches remains the
  existing placeholder; no recommendation workflow was invented.
- Save/Share, password login, document parsing and a second resume editor were not
  added. Real resume preparation/saving still depend on the existing services.
- Current `JobDetail` has no start/end dates, deadline, allowance, department,
  vacancies or programme fields. These are not fabricated or added to the wire
  contract. `calculateContractDuration` is tested for future source date integration
  but is deliberately not displayed or connected to the API yet. It accepts strict
  YYYY-MM-DD dates, clamps month anniversaries at month end, uses elapsed UTC days
  (end date excluded), and returns null for missing/invalid/reversed pairs.
  The reference example calculates to 11 months 4 days / 340 total days.
- Manrope/Inter are preferred in the font stack; no external fonts were downloaded
  or added. Available system fonts can look slightly different from the reference.
- The real Google button remains Google's rendered control. Fixture mode displays
  its existing synthetic sign-in control, not a fake Google button.
- Resume internals retain Nasya's existing layout and behaviors. This milestone
  does not claim a full accessibility audit of that component or the whole app.
- Live Google authentication, backend cookies/CSRF enforcement and end-to-end real
  API flows still require the configured Google client and backend services.

## Changed files

Existing files modified:

- `src/frontend/src/styles.css`
- `src/frontend/src/App.tsx`
- `src/frontend/src/App.test.tsx` (labels/selectors adapted; existing assertions retained)
- `src/frontend/src/features/auth/Onboarding.tsx` (presentation only)
- `src/frontend/src/features/catalogue/Catalogue.tsx`
- `src/frontend/src/features/catalogue/JobDetails.tsx`
- `src/frontend/README.md`

New components and helpers:

- `src/frontend/src/components/Brand.tsx`
- `src/frontend/src/components/Navbar.tsx`
- `src/frontend/src/components/Footer.tsx`
- `src/frontend/src/features/auth/LoginLayout.tsx`
- `src/frontend/src/features/catalogue/FilterDropdown.tsx`
- `src/frontend/src/features/catalogue/SearchDock.tsx`
- `src/frontend/src/features/catalogue/JobCard.tsx`
- `src/frontend/src/features/catalogue/jobPresentation.ts`
- `src/frontend/src/features/catalogue/contractDuration.ts`

New regression tests and documentation:

- `src/frontend/src/features/catalogue/SearchDock.test.tsx`
- `src/frontend/src/features/catalogue/JobDetails.test.tsx`
- `src/frontend/src/features/catalogue/contractDuration.test.ts`
- `src/frontend/FRONTEND_REDESIGN.md` (this document)

No changes to `src/api/**`, `src/features/resume/**`, auth/session hooks,
`GoogleSignIn.tsx`, `SessionRecovery.tsx`, `main.tsx`, query validation, mock
fixtures, dependency/lock files or Vite configuration.

## Validation

Staged checks completed:

| Stage | Relevant checks | Result |
|---|---|---|
| 1: shell | App regression tests | 10 passed |
| 2: login/onboarding | App + useSession | 20 passed |
| 3: catalogue | Typecheck; App + catalogue | Passed; 38 tests passed |
| 4: detail/duration | Typecheck; catalogue | Passed; 47 tests passed |
| 5: resume/matches shell | App + resume feature | 110 passed |

Final checks on 21 September 2026:

- `npm run typecheck`: passed.
- `npm test`: **189 tests passed across 15 files**. Existing auth/session, client,
  loopback HTTP, catalogue and all teammate resume tests passed. The milestone
  adds 26 tests (7 search interactions, 5 detail behaviors, 14 duration cases).
- `npm run build`: passed; 74 modules transformed. Production assets: 24.05 kB CSS
  (6.14 kB gzip), 339.06 kB JS (105.20 kB gzip). The existing fixture-exclusion
  build guard passed. No new packages were added.
- `git diff --check`: passed. Protected API/auth/resume/runtime paths have no diff.
- Headless Chrome: jobs/detail/resume/matches/onboarding checked at widths 1440,
  768, 390 and 320, with no horizontal overflow. Login checked at desktop and
  narrow mobile sizes. Pin/unpin, measured navbar offset, outside-click dismissal,
  dropdown bounds after scrolling, reduced motion, empty results, closed detail
  and not-found passed with no uncaught browser exceptions.
- An additional 320x568 check passed: a remembered pin preference cannot trap the
  results below a tall dock, and the dropdown stays within the viewport.
- Regular dev `/login` showed the actual unconfigured-Google/reconnect state and
  no fixture fallback. No real credentials, resumes or applications were used.

Browser checks used `react-redesign-review.mjs` in the Windows temporary folder,
not a production/test dependency. It launched a fresh headless Chrome profile,
exercised the existing in-memory fixtures, saved screenshots to a temporary
folder and inspected the regular login entry. The final screenshot directory was
`%TEMP%/react-redesign-review-5jBA9P`. This is temporary review evidence, not a
committed artifact. Screenshots of login, catalogue, detail and the short-phone
menu were visually inspected. This was targeted browser review, not a claim of
full browser, screen-reader or live-backend coverage.

Vitest/build require esbuild subprocesses; these were run with permission outside
this environment's subprocess-restricting sandbox. No repository runtime or
package versions were changed. The pinned Node 24.21.0/npm 11.19.0 runtime already
available in the temporary directory was used because Node was absent from PATH.

## Local review

From the repo root, with Node 24.21.0/npm 11.19.0 on PATH:

```sh
cd src/frontend
npm ci
npm run dev:mock
```

Default address is `http://localhost:8080`. During this review 8080 was already
occupied, so the fixture preview was started with `npm run dev:mock -- --port 8090`
at `http://localhost:8090`. Choose **Enter synthetic preview**, enter a display
name and choose **Skip for now** or **Continue to jobs**.

| Route | Review |
|---|---|
| `/login` | Login (use Logout first when already signed in) |
| `/onboarding` | Display name + optional resume handoff |
| `/jobs` | Search, multi-select filters, reset, pin/unpin, cards, pagination |
| `/jobs?q=nonexistent` | Empty search results |
| `/jobs/00000000-0000-4000-8000-000000000001` | Open fixture detail |
| `/jobs/00000000-0000-4000-8000-000000000025` | Closed fixture detail |
| `/jobs/not-a-job` | Not-found |
| `/resume` | Existing resume workspace in shared framing |
| `/matches` | Explicit recommendations placeholder |

Fixtures are in-memory and reset on a hard reload. Sign in again if opening a
fresh deep link. No backend or Google login is needed in fixture mode, but actual
resume preparation/saving is intentionally unavailable there. Use the existing
feature tests for richer saved/review/conflict responses.

Regular `npm run dev` uses the actual same-origin API and Google integration,
with no fixture fallback. It was also launched as `npm run dev -- --port 8091`
for an entry-screen check. A live sign-in review should use the configured Google
origin (normally port 8080), its public client ID, and Jiaxin's backend.

## Presentation follow-up: review consistency

Following the standalone review, the user requested these presentation-only
corrections on 21 September 2026:

- Catalogue filters share a 42px height, 188px minimum width and 260px desktop
  width. A fixed label column, flexible selected-value column and 13px chevron
  column preserve alignment with 8px gaps and reference-style horizontal padding.
  On mobile all three controls use full-width rows with the same height and
  alignment. Long selections truncate visually and expose their text on hover.
- The decorative chevron now uses the reference glyph and rotates on disclosure.
  Native checkbox multi-select, keyboard/focus behavior, dismissal, query state,
  filtering and menu-placement calculations remain unchanged.
- Catalogue cards no longer render a leading company-initial badge. The existing
  detail-page company context and initials are unchanged.
- `docs/xue-ui-review.html` is regenerated directly from the updated components
  and stylesheet. It restores the existing React Matches hero/unavailable state,
  without adding recommendation data or scores. Resume remains outside the HTML
  review scope; no teammate-owned component is bundled.

Production source edits are limited to `styles.css`, `FilterDropdown.tsx` and
`JobCard.tsx`. No changes to production routes/App, API contracts/client, backend,
auth/session code, resume code, filter handlers, query logic or dependencies.
Scope and preview adaptations are recorded in `docs/XUE_UI_REVIEW.md`.

Validation using the existing Node 24.21.0/npm 11.19.0 runtime:

- `npm run typecheck`: passed.
- `npm test`: **189 tests passed across 15 files**.
- `npm run build`: passed; production fixture-exclusion guard passed.
- Headless Chrome opened the HTML directly with networking disabled: **84 browser
  assertions passed**, with no uncaught exceptions, browser errors or HTTP(S)
  requests. Existing flows and native multi-select behavior passed.
- At widths 1440, 768, 390 and 320, filter dimensions and value/chevron alignment
  passed for All and multiple selections. Catalogue/detail/onboarding/login/Matches
  had no horizontal overflow. Dropdown bounds and the 320 × 568 pin suspension
  check passed. Desktop catalogue/Matches and mobile catalogue were visually inspected.
- `git diff --check`: passed. Protected behavior paths have no diff.

Build/browser helpers remain in the Windows temporary folder. Vitest/Vite/esbuild
and hidden headless Chrome required the existing subprocess sandbox escalation.
No production deployment, commit, push, dependency install or backend change.
