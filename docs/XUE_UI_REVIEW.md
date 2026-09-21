# Xue's standalone UI review

Open **[xue-ui-review.html](xue-ui-review.html)** directly in a modern browser.
Share that file by itself: no React installation, server, internet access, Google
account or backend is required. This is a UI/UX review artifact. The React source
on branch `xue` remains authoritative.

Current handoff: [FRONTEND_HANDOFF.md](../src/frontend/FRONTEND_HANDOFF.md).
This guide describes the completed review presentation verified on 21 September
2026, including the work resumed after the interrupted check.

## Scope evidence

Git history, source and staged/unstaged diffs were inspected. Branch `xue` remains
at `9444006052d11cfae73957a009ef4a80a1c88cc6`; the follow-up presentation changes
and review artifacts are uncommitted.

- `1fc366b`: Xue's shared client, shell, authentication/onboarding, catalogue and
  detail foundation.
- `e6487ea`: catalogue/session recovery milestone. It also carries pre-existing
  teammate resume files; commit authorship alone does not establish their ownership.
- `ed4d7cc`: historical merge of the session recovery work into `xue`.
- `9444006`: visual redesign with shared components, login layout, search dock,
  dropdown filters, cards and detail presentation.
- `git diff 62004d9 HEAD -- src/frontend/src/features/resume` is empty, and there
  is no working-tree diff in that feature. Nasya's implementation is excluded.
- Scope also follows the frontend README, redesign/session handoffs and
  `docs/handoff/IMPLEMENTATION_GUIDE.md`. `TEAM_CONTRIBUTIONS.md` records planned
  roles, not completed-work evidence. The repository spells Naysa's name **Nasya**.

## Included pages and components

Source paths below are relative to `src/frontend/src/`.

| Area | Source | Reviewable presentation |
| --- | --- | --- |
| Shared shell | `App.tsx`, `components/{Brand,Navbar,Footer}.tsx`, `styles.css` | Active navigation, profile initials, logout, footer, skip link, responsive framing and not-found state |
| Login | `features/auth/LoginLayout.tsx`, temporary review login markup | Original two-column composition, finite keyword animation/reduced motion; clearly non-authenticating Google-style action and labelled account scenarios |
| Onboarding | `features/auth/Onboarding.tsx` | Name validation, confirmation/error/retry, Skip for now, Continue to jobs and optional resume handoff |
| Recovery/logout | `features/auth/SessionRecovery.tsx`, temporary adapter | Focus confinement, inert background, session-ended/refresh/reconnection-error and signing-out/unconfirmed states |
| Catalogue | `features/catalogue/{Catalogue,SearchDock,FilterDropdown,JobCard}.tsx` | Search, native checkbox multiselect, quick chips, reset, pinning, pagination, loading/error/empty/query-validation/revision-change states |
| Job Detail | Temporary copy of `features/catalogue/JobDetails.tsx`; `jobPresentation.ts` | Open/closed, descriptions, metadata, requirements/alternatives/source quotes, eligibility, compact source summary, safe/disabled Apply, loading/error/not-found/sparse/preferred states |
| Matches | Existing unavailable markup from `App.tsx`, plus a separate review-only component | Original hero/unavailable presentation and three explicitly synthetic example roles with expandable requirement evidence, skill tags and eligibility notes |

The actual catalogue/onboarding/shared components and complete source stylesheet
are bundled into the HTML. Temporary copies of App and JobDetails adapt only the
review wiring and the explicitly approved source-summary presentation. The
existing `query.ts` and synthetic `dev/catalogue.ts` are reused: 24 active jobs
and one separately accessible closed record. Keyword AND, OR within a filter
group, AND across groups, literal punctuation, ordering and pagination are retained.

## Using the review

The initial catalogue uses **Alex Preview**, an in-memory sample account. Use the
navbar, job links, profile, search, filters and pagination normally. **Review views**
opens additional loading/error/recovery/detail and account states. Loading examples
stay visible until another view is chosen; retries resolve locally.

Matches offers **Sample recommendations** and **Current unavailable state**.
The latter preserves the current production React hero and unavailable message.
Sample cards link to their corresponding existing synthetic Job Detail pages.

Choose **Google sign-in preview**, or log out, to inspect login. **Continue with
Google** only displays a notice that no account was authenticated. It neither
loads Google nor changes the account or page. Its supporting text is:

> Preview only — real Google sign-in integration pending

Separate **Browse sample jobs** and **Review sample onboarding** controls enter
local review scenarios without claiming successful Google authentication. The
existing real application's Google Identity Services component already exists;
the preview's pending wording does not mean that component was removed or replaced.

The subtle review strip identifies synthetic data and pending integrations.
No developer logs, request diagnostics or credentials appear in the UI.

## Explicit review-only differences

### Matches

The richer preview is a user-requested visual example, not an implementation of
Nasya's recommendations feature. Jobs, passages and skill evidence are fictional.
No backend recommendation request, ranking, calculated score or percentage is shown.
The examples are not ranked. Named-skill alternatives remain alternatives
(e.g. Python **or** JavaScript), not separate mandatory requirements.

The written API contract describes recommendation evidence, but the current React
Matches route does not fetch it. Actual matching, resume analysis and recommendation
integration remain outside this artifact. Production Matches is unchanged.

### Compact source information

The review replaces the prominent “Source and freshness” card with a quiet summary:

- Source: `source`, linked using `source_url` when safe.
- Posted: `posted_at`; missing dates use the existing display fallback.
- Imported: `last_imported_at`.
- “Availability may have changed. Confirm on the source website.”

`last_verified_at` **does exist** as a nullable field in the current TypeScript
JobDetail and written API contract. It is omitted from the review to reduce
prominence and avoid implying a real verification event for fictional listings;
it was not removed because the contract lacks it. The catalogue identifier is also
omitted because it is unnecessary for UI review. Imported time is not proof of
availability. No field, contract or production JobDetails code was changed.
Production still renders its original source card and “Not verified” for null data.

### Offline and scope adaptations

- Hash navigation supports local-file use and browser Back/Forward. Production
  BrowserRouter and route guards are unchanged.
- The preview uses its own local account/data adapter. Production auth/session
  hooks and Google controls are not bundled or called.
- Normal clicks on synthetic source/Apply links open a local sample notice and
  submit nothing. Source link safety attributes are retained.
- Resume links stop at an explicit scope notice with a return link. No resume
  component, upload, parser, editor, save/delete workflow or teammate implementation
  is bundled.
- The earlier `docs/frontend-prototype.html` is separate and unchanged.
- Preferred/sparse detail scenarios exercise existing rendering branches.
  `contractDuration.ts` is not rendered or included.
- Account/name changes stay in memory. Refresh resets them; only the original
  non-sensitive search-dock pin preference may persist.
- Fonts use the source system fallback stack. CSS, JavaScript and dependency
  license notices are embedded. Content Security Policy blocks external resources
  and network connections.

## Production presentation corrections already agreed

These three persisted production edits predate the final handoff:

- `styles.css`: shared 42px filter height, 188px minimum width and 260px desktop
  width; fixed label/value/chevron columns with 8px gaps. Mobile controls stack at
  full width with the same internal alignment.
- `FilterDropdown.tsx`: reference-style decorative chevron and selected-value
  tooltip. Native checkboxes, event handlers and filtering behavior are unchanged.
- `JobCard.tsx`: remove catalogue company-initial badges. Detail-page initials stay.

The subsequent Matches examples, compact source summary, Google preview and
scenario-transition repair exist **only in the standalone artifact**. No production
source was edited during that review-only work or final wrap-up.

## Latest confirmed validation

Fresh final validation on 21 September 2026:

| Check | Result |
| --- | --- |
| `npm run typecheck` | Passed |
| `npm test` | 189 tests passed across 15 files, including all 100 existing resume tests |
| `npm run build` | Passed; 74 modules, production fixture-exclusion guard passed |
| Standalone browser suite | 98 assertions passed in hidden Chrome with networking disabled |
| Actual React in existing mock mode | 30 browser assertions passed |
| `git diff --check` | Passed at final handoff |

Standalone checks cover navigation/onboarding, search semantics, native multiselect,
keyboard dismissal/focus, pagination/revisions, retries, recovery focus, closed/sparse
details, scope boundaries, sample Matches/evidence, original unavailable Matches,
compact source fields and a Google click that performs no authentication.

Catalogue, detail, onboarding, login and both Matches presentations were checked at
1440, 768, 390 and 320px without horizontal overflow. All three filters have matching
heights/widths, selected-value offsets and chevron alignment for All and multiple
selections. Dropdown bounds, reduced motion and short-screen pinning at 320 × 568
passed. No uncaught exceptions, browser errors or HTTP(S) requests occurred in the
standalone suite. Desktop Matches/detail and narrow-screen review screenshots were
visually inspected.

The actual React checks exercise its existing fixture login/onboarding/logout,
catalogue multiselect and URL query behavior, original detail source card, original
Matches unavailable state, filter geometry and responsive layouts at the same widths.
The existing React dev page requests a missing `/favicon.ico` (404); this cosmetic
asset gap is recorded separately. No uncaught JavaScript exceptions, other browser
errors or external requests occurred. This is not live Google/API testing or a full
cross-browser/accessibility audit.

## Interruption recovery and artifact provenance

At the start of wrap-up, the three React presentation edits and a complete HTML
export were already saved. However, the latest browser check had stopped after
56 assertions at the login-to-sample-onboarding transition, and this guide was stale.
That run was **not** treated as successful.

The temporary adapter changed the sample account before the deferred navigation,
allowing the existing login redirect to win. Keeping those review updates in the
same React transition fixes the scenario selector without modifying production
routing. The HTML was regenerated and the full 98-assertion suite then passed.

Build/adaptation/browser helpers remain under
`%TEMP%/xue-standalone-review/`, including `build.mjs`,
`preview-runtime.tsx`, `review-presentation.tsx`, `review-presentation.css`,
temporary App/JobDetails copies, `check.mjs` and `check-react.mjs`.
They are local generation tools, not tracked production source or required files
for opening this HTML. Browser results/screenshots are in temporary
`xue-review-browser-*` and `xue-react-handoff-*` folders.
The completed HTML is the portable artifact; there is no checked-in regeneration
command. Future regeneration must preserve the documented review-only boundaries.

No unfinished temporary implementation was copied into production. No API,
backend, auth/session, Google, router, resume, dependency or lock file was changed.
Nothing was committed, pushed or merged during this handoff.

After the manual travel pause, the saved HTML, both successful browser result files
and unchanged tracked source diff were verified again. The completed production
build was still present. Only the remaining handoff documentation was finished;
the HTML was not regenerated and the tests/build were not rerun because the
validated implementation had not changed. See the consolidated handoff for the
current seven-file working-tree inventory and next integration steps.
