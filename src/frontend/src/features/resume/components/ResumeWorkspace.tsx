import { useState } from 'react';
import { ConflictReview } from './ConflictReview';
import type { KeyFactory } from '../model/idempotency';
import type { ResumeApiPort } from '../api/resumeApi';
import { useResumeWorkspace } from '../hooks/useResumeWorkspace';
import { ResumeReviewForm } from './ResumeReviewForm';
import { ResumeUploadPanel } from './ResumeUploadPanel';
import { SaveStatusBanner } from './SaveStatusBanner';
import { UnassignedTextPanel } from './UnassignedTextPanel';

/**
 * Feature root for the resume route.
 *
 * Xue E's router mounts this and supplies `api` built from the shared client. This
 * component owns no routing, no session handling and no navigation.
 */
export interface ResumeWorkspaceProps {
  api: ResumeApiPort;
  sleep?: (seconds: number) => Promise<void>;
  keyFactory?: KeyFactory;
  onAuthenticationRequired?: () => void;
}

export function ResumeWorkspace(props: ResumeWorkspaceProps): React.ReactElement {
  const state = useResumeWorkspace({
    api: props.api,
    ...(props.sleep ? { sleep: props.sleep } : {}),
    ...(props.keyFactory ? { keyFactory: props.keyFactory } : {}),
    ...(props.onAuthenticationRequired
      ? { onAuthenticationRequired: props.onAuthenticationRequired }
      : {}),
  });

  const { phase, profile, actions } = state;
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  if (phase === 'LOADING') {
    return (
      <section className="resume-workspace" aria-busy="true">
        <p className="resume-loading" role="status">Loading your resume…</p>
      </section>
    );
  }

  return (
    <section className="resume-workspace">
      <h1>Your resume</h1>
      {state.loadError !== null && <div role="alert"><p>{state.loadError}</p><button type="button" className="button-secondary" onClick={() => void actions.reload()}>Retry loading resume</button></div>}
      <SaveStatusBanner
        status={state.saveStatus}
        onCheck={state.pendingIdempotencyKey === null ? undefined : () => void actions.checkSaveStatus()}
      />

      {phase === 'NO_RESUME' && (
        <>
          <p className="resume-lead" data-testid="no-resume-state">
            You have not added a resume yet. You can still browse every internship without one.
          </p>
          <ResumeUploadPanel
            selectedFile={state.selectedFile}
            rejection={state.uploadRejection}
            preparing={state.preparing || state.saving}
            onSelectFiles={actions.selectFiles}
            onClearSelection={actions.clearSelection}
            onPrepare={() => void actions.prepare()}
            onSkip={actions.startManualEntry}
          />
        </>
      )}

      {phase === 'PROFILE' && profile !== null && (
        <>
          <section className="panel resume-summary" aria-labelledby="saved-heading" data-testid="saved-profile">
            <h2 id="saved-heading">Saved resume details</h2>
            <p className="resume-revision">Revision {profile.revision}.</p>
            {!profile.has_matchable_resume && (
              <p className="resume-hint" data-testid="no-chunks-state">
                Your saved details do not yet include a project or experience entry, so we cannot
                produce recommendations. Add one to get personalised results.
              </p>
            )}
            {profile.content.skills.length > 0 && (
              <ul className="resume-skill-pills">
                {profile.content.skills.map((skill) => (
                  <li key={skill}>{skill}</li>
                ))}
              </ul>
            )}
            <p className="muted">
              {profile.content.projects.length} project(s), {profile.content.experience.length}{' '}
              experience entry/entries, {profile.content.education.length} education entry/entries.
            </p>
            <div className="resume-summary-actions">
              <button type="button" className="button-secondary" onClick={actions.editSavedProfile} disabled={state.preparing || state.saving}>
                Edit details
              </button>
              {confirmingDelete ? (
                <span className="resume-confirm" role="group" aria-label="Confirm deleting resume details">
                  <span className="resume-confirm-text">Delete your saved resume details?</span>
                  <button
                    type="button"
                    className="button-danger"
                    onClick={() => {
                      setConfirmingDelete(false);
                      void actions.deleteProfile();
                    }}
                    disabled={state.saving || state.preparing}
                  >
                    Yes, delete
                  </button>
                  <button type="button" className="button-quiet" onClick={() => setConfirmingDelete(false)} disabled={state.saving || state.preparing}>
                    Keep it
                  </button>
                </span>
              ) : (
                <button type="button" className="button-danger" onClick={() => setConfirmingDelete(true)} disabled={state.saving || state.preparing}>
                  Delete resume details
                </button>
              )}
            </div>
          </section>
          <ResumeUploadPanel
            selectedFile={state.selectedFile}
            rejection={state.uploadRejection}
            preparing={state.preparing || state.saving}
            onSelectFiles={actions.selectFiles}
            onClearSelection={actions.clearSelection}
            onPrepare={() => void actions.prepare()}
            onSkip={actions.editSavedProfile}
          />
        </>
      )}

      {phase === 'REVIEW' && (
        <fieldset className="resume-review-shell" disabled={state.saving}>
          <div className="resume-review">
            {state.prepareWarnings.map((warning) => (
              <p key={warning.code} className="resume-warning" role="note" data-testid="prepare-warning">
                {warning.message}
              </p>
            ))}
            <UnassignedTextPanel
              paragraphs={state.unassignedParagraphs}
              onAssign={actions.assignParagraph}
              onDismiss={actions.dismissParagraph}
            />
            {state.conflict && <ConflictReview conflict={state.conflict} onRefresh={() => void actions.refreshConflict()} onResolve={actions.resolveConflict} />}
            <ResumeReviewForm
              draft={state.draft}
              validation={state.validation}
              dispatch={state.dispatchDraft}
              saving={state.saving}
              onConfirm={() => void actions.confirmSave()}
              onCancel={actions.cancelReview}
            />
          </div>
        </fieldset>
      )}
    </section>
  );
}
