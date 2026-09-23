import type { SaveStatus } from '../model/saveController';

/**
 * Renders the save outcome.
 *
 * The wording rules matter as much as the markup:
 *   - an unknown outcome must never be reported as "not saved",
 *   - a busy rejection must say that nothing was saved and the draft is intact,
 *   - a conflict must say nothing was overwritten.
 * The messages come from the controller so the same words are asserted in its tests.
 */
export function SaveStatusBanner({
  status,
  onCheck,
}: {
  status: SaveStatus;
  onCheck?: () => void;
}): React.ReactElement | null {
  if (status.kind === 'IDLE') return null;

  const tone = bannerTone(status);
  return (
    <div role="status" aria-live="polite" data-testid="save-status" data-tone={tone}>
      <strong>{bannerHeading(status)}</strong>
      <p>{bannerBody(status)}</p>
      {status.kind === 'OUTCOME_UNKNOWN' && onCheck && (
        <button type="button" onClick={onCheck}>
          Check save status
        </button>
      )}
    </div>
  );
}

function bannerTone(status: SaveStatus): 'progress' | 'success' | 'warning' | 'error' {
  switch (status.kind) {
    case 'SAVING':
    case 'WAITING_TO_RETRY':
      return 'progress';
    case 'SAVED':
    case 'DELETED':
      return 'success';
    case 'SAVED_REFRESH_REQUIRED':
    case 'REVIEW_REQUIRED':
    case 'REVISION_CONFLICT':
    case 'OUTCOME_UNKNOWN':
    case 'AUTH_REQUIRED':
      return 'warning';
    default:
      return 'error';
  }
}

function bannerHeading(status: SaveStatus): string {
  switch (status.kind) {
    case 'SAVING':
      return 'Saving your resume…';
    case 'WAITING_TO_RETRY':
      return 'Waiting to try again';
    case 'SAVED':
      return status.refreshedFromServer ? 'Earlier save confirmed' : status.changed ? 'Resume saved' : 'No changes to save';
    case 'DELETED':
      return 'Resume details deleted';
    case 'SAVED_REFRESH_REQUIRED':
      return 'Save confirmed; current version unavailable';
    case 'REVIEW_REQUIRED':
      return 'Review the corrected version';
    case 'REVISION_CONFLICT':
      return 'Your resume changed elsewhere';
    case 'OUTCOME_UNKNOWN':
      return 'Save result unconfirmed';
    case 'AUTH_REQUIRED':
      return 'Sign in again to save';
    default:
      return 'Could not save';
  }
}

function bannerBody(status: SaveStatus): string {
  switch (status.kind) {
    case 'SAVING':
      return status.attempt === 1
        ? 'Sending your reviewed details.'
        : `Checking the result of your earlier attempt (attempt ${status.attempt}).`;
    case 'WAITING_TO_RETRY':
      return `Trying again in ${status.waitSeconds} seconds. Your draft is still here.`;
    case 'SAVED':
      if (status.profileDeleted) return 'Your earlier save completed, but the resume has since been deleted.';
      if (status.refreshedFromServer) return `Your earlier save completed. The current saved resume is revision ${status.currentRevision}.`;
      return status.changed
        ? `Saved as revision ${status.revision}.${status.refreshedFromServer ? ' Reloaded from the server to confirm.' : ''}`
        : `Your saved resume already matched this content. It is still revision ${status.revision}.`;
    case 'DELETED':
      return status.message;
    case 'IDLE':
      return '';
    default:
      return status.message;
  }
}
