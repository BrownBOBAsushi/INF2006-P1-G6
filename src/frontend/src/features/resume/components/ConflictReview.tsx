import type { ResumeConflict } from '../hooks/useResumeWorkspace';

export function ConflictReview({ conflict, onRefresh, onResolve }: {
  conflict: ResumeConflict;
  onRefresh: () => void;
  onResolve: (choice: 'KEEP_DRAFT' | 'USE_CURRENT') => void;
}): React.ReactElement {
  const { profile, revision } = conflict;
  return (
    <section aria-label="Current saved version">
      <h2>Review the current saved version</h2>
      {profile === undefined || revision === null ? (
        <>
          <p>The current version could not be loaded. Your draft is still below. Saving is paused until you can review the current version.</p>
          <button type="button" onClick={onRefresh}>Retry loading current version</button>
        </>
      ) : (
        <>
          {profile === null ? <p>Your resume was deleted elsewhere.</p> : (
            <>
              <h3>Skills</h3>
              <p>{profile.content.skills.join(', ') || 'None'}</p>
              {(['projects', 'experience'] as const).map(section => (
                <div key={section}>
                  <h3>{section === 'projects' ? 'Projects' : 'Experience'}</h3>
                  {profile.content[section].map((entry, index) => (
                    <article key={index}><h4>{entry.title}</h4><p>{entry.description}</p><p>{entry.technologies.join(', ')}</p></article>
                  ))}
                </div>
              ))}
              <h3>Education</h3>
              {profile.content.education.map((entry, index) => (
                <article key={index}><h4>{entry.qualification}</h4><p>{entry.details}</p></article>
              ))}
            </>
          )}
          <p>Keeping your draft means your next save will replace this version. No changes are saved by choosing below.</p>
          <button type="button" onClick={() => onResolve('USE_CURRENT')}>Discard my draft and use current version</button>
          <button type="button" onClick={() => onResolve('KEEP_DRAFT')}>I reviewed this version; keep my draft</button>
        </>
      )}
    </section>
  );
}
