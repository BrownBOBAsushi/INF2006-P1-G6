# Resume upload and review (Nasya)

Owner: Nasya. Scope: `src/frontend/src/features/resume/**` only.

Implements the first milestone from `docs/handoff/TEAM_PROMPTS.md`: PDF upload and the
editable review flow, against contract-shaped fixtures. Recommendation screens are a
later milestone and are not started.

## What exists

| Area | Files | Covers |
|---|---|---|
| Contract types | `api/contractTypes.ts` | Resume endpoints, error codes and every numeric limit from `DATA_API_CONTRACT.md` |
| Error model | `api/errors.ts` | `ApiError` (definite server outcome) vs `UnknownOutcomeError` (outcome not established) |
| Integration seam | `api/httpTransport.ts` | The port Xue E's shared client implements |
| API port | `api/resumeApi.ts` | prepare / get / save / delete / operation status / account revision |
| Draft model | `model/draft.ts`, `model/draftReducer.ts` | In-memory editable draft with local render ids |
| Serialization | `model/serialize.ts` | Strict whitelist to the four contract fields |
| Validation | `model/validation.ts`, `model/uploadValidation.ts` | Client mirror of contract bounds and file limits |
| Save logic | `model/saveController.ts` | Idempotency, capped backoff, unknown-outcome resolution |
| UI | `components/**`, `hooks/useResumeWorkspace.ts` | Upload, unassigned text, review form, status banner |

Entry point for the router is `ResumeWorkspace`, exported from `index.ts`.

## Integration seam for Xue E

This feature owns no routing, session handling, CSRF or cookie policy. It depends only
on `HttpTransport`:

```ts
import { ResumeWorkspace, createResumeApi } from './features/resume';

<Route path="/resume" element={
  <ResumeWorkspace
    api={createResumeApi(sharedTransport)}
    onAuthenticationRequired={() => showSignIn()}
  />
} />
```

`sharedTransport` must: use the same-origin `/api` prefix, send the session cookie,
attach `X-CSRF-Token` from `GET /api/me` on every unsafe request, and persist no
credential to browser storage. A test asserts this feature sends only an
`Idempotency-Key` header of its own, so there is one owner for auth transport.

Fixtures are deliberately **not** exported from `index.ts`, so synthetic data cannot
reach a production bundle.

## Decisions worth reviewing

- **Idempotency keys are derived from payload identity**, not managed per call site.
  The server's `payload_hash` covers `expected_revision`, so retrying after a
  `REVISION_CONFLICT` necessarily changes the payload and must rotate the key. Modelling
  the key as a function of `(expected_revision, content signature)` makes both the reuse
  rule and the rotation rule fall out of one check.
- **503 `PROCESSING_BUSY` is reported as "nothing was saved"** — the contract states no
  operation row is created — while a lost response is reported as *unconfirmed*. These
  are different states and the UI wording differs.
- **A success arriving on any retry, including a manual retry, triggers `GET /api/resume`**, because it may be a
  replay of a commit whose response was lost. The replayed response is never treated as
  a description of current server content.
- **500/502/504 are treated as unsettled**, resolved by replaying the same key rather
  than reported as failures. Replay is cheap and safe; guessing is not.
- **Native drag-and-drop instead of `react-dropzone`.** The library is on the approved
  reuse list, but dependency locking is Xue E's bootstrap task and this needed about
  thirty lines. Swapping it in later touches one component. Flagging so the choice is
  reviewable rather than silent.
- **`accept="application/pdf,.pdf"`** means the OS picker already filters other types, so
  the client-side PDF check only matters for dropped files. Tested on the drop path.

## Review fixes

- Account revision is kept separately from the optional saved profile. An absent
  profile loads `resume_revision` from `GET /api/me`; successful deletion retains
  the response revision. Failed revision reads block saving until reloaded.
- A successful replay with a failed refresh keeps the draft and retry key. It
  reports the save as confirmed but does not present the draft as current server
  content. A replay followed by a deleted profile returns to the empty state.
- Revision conflicts show the current server content and require an explicit
  choice to discard or keep the local draft before another save. A failed refresh
  blocks saving and offers a retry.
- Review controls, including unassigned-text actions, are disabled while saving.
  Manual entry, editing and deletion are disabled while PDF preparation runs.

## Blockers and coordination needed

1. **`REVIEW_REQUIRED` envelope field is unnamed (blocks Jiaxin/Chuying).**
   `DATA_API_CONTRACT.md` says `details` may carry the "cleaned draft" for a 422
   `REVIEW_REQUIRED`, but never names the field. `extractCleanedContent` currently
   accepts `draft`, `cleaned_draft`, `content` or `cleaned_content` as a stopgap. One
   name must be fixed in the generated OpenAPI, and the contract updated.
2. **Revision field on conflict envelopes is also unnamed.** Same pattern:
   `current_revision`, `resume_revision` and `revision` are accepted.
3. **No backend, no OpenAPI.** Every response shape here is hand-transcribed from the
   written contract. When Jiaxin generates OpenAPI, `contractTypes.ts` should be
   replaced by generated types and this file reduced to view models. Until then a
   contract drift will surface as a runtime shape mismatch, not a type error.
4. **`src/frontend/package.json` is provisional and overlaps Xue E's ownership.** Nothing
   could be built or tested without a workspace. It pins React, TypeScript, Vite and
   Vitest only — no router, no styling, no state library. Reconcile at bootstrap.
5. **No styling.** Markup is semantic HTML with `data-testid` hooks. The design system
   is not decided; this should inherit whatever Xue E's shell establishes.
6. **Dependency installation needs re-verification.** The original contribution
   reported an npm/Vitest installation issue. This review could not verify the
   declared pins because registry DNS failed. See the frontend README for the
   actual local dependency versions used for testing.

## Not in this milestone

Recommendation screens, closest-passage and skill-evidence display, the closed-job
state, and connecting real endpoints. Delete is implemented minimally because it shares
the revision-locking path, but its failure modes are not yet fully tested.

## Commands

```bash
cd src/frontend
npm install
npm run typecheck
npm test
npm run build
```
