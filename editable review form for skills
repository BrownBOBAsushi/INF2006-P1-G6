import type { ResumeDraft } from '../model/draft';
import type { DraftAction, EntrySection } from '../model/draftReducer';
import type { ValidationResult } from '../model/validation';
import { willBeMatchable } from '../model/validation';

/**
 * The editable review screen (PRD P06).
 *
 * The student edits content, never vectors. Everything here lives in React state only.
 * Validation issues are shown next to the field they refer to using the stable paths
 * produced by validation.ts.
 */
export interface ResumeReviewFormProps {
  draft: ResumeDraft;
  validation: ValidationResult;
  dispatch: (action: DraftAction) => void;
  saving: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

function issuesFor(validation: ValidationResult, path: string) {
  return validation.issues.filter((issue) => issue.path === path);
}

function IssueList({
  validation,
  path,
}: {
  validation: ValidationResult;
  path: string;
}): React.ReactElement | null {
  const issues = issuesFor(validation, path);
  if (issues.length === 0) return null;
  return (
    <ul data-testid={`issues-${path}`}>
      {issues.map((issue) => (
        <li key={issue.code + issue.message} data-severity={issue.severity}>
          {issue.message}
        </li>
      ))}
    </ul>
  );
}

export function ResumeReviewForm(props: ResumeReviewFormProps): React.ReactElement {
  const { draft, validation, dispatch, saving, onConfirm, onCancel } = props;
  const matchable = willBeMatchable(validation.content);

  const renderEntries = (section: EntrySection, heading: string, addLabel: string) => (
    <section aria-labelledby={`${section}-heading`}>
      <h3 id={`${section}-heading`}>{heading}</h3>
      <IssueList validation={validation} path={section} />
      {draft[section].map((entry, index) => (
        <fieldset key={entry.localId} data-testid={`${section}-entry`}>
          <legend>
            {heading} {index + 1}
          </legend>

          <label htmlFor={`${entry.localId}-title`}>Title</label>
          <input
            id={`${entry.localId}-title`}
            value={entry.title}
            onChange={(event) =>
              dispatch({
                type: 'UPDATE_ENTRY',
                section,
                localId: entry.localId,
                field: 'title',
                value: event.target.value,
              })
            }
          />
          <IssueList validation={validation} path={`${section}.${index}.title`} />

          <label htmlFor={`${entry.localId}-description`}>Description</label>
          <textarea
            id={`${entry.localId}-description`}
            value={entry.description}
            onChange={(event) =>
              dispatch({
                type: 'UPDATE_ENTRY',
                section,
                localId: entry.localId,
                field: 'description',
                value: event.target.value,
              })
            }
          />
          <IssueList validation={validation} path={`${section}.${index}.description`} />

          <fieldset>
            <legend>Technologies</legend>
            {entry.technologies.map((tech, techIndex) => (
              <span key={tech.localId}>
                <label htmlFor={tech.localId}>
                  Technology {techIndex + 1} for {heading.toLowerCase()} {index + 1}
                </label>
                <input
                  id={tech.localId}
                  value={tech.value}
                  onChange={(event) =>
                    dispatch({
                      type: 'UPDATE_TECHNOLOGY',
                      section,
                      localId: entry.localId,
                      techLocalId: tech.localId,
                      value: event.target.value,
                    })
                  }
                />
                <button
                  type="button"
                  onClick={() =>
                    dispatch({
                      type: 'REMOVE_TECHNOLOGY',
                      section,
                      localId: entry.localId,
                      techLocalId: tech.localId,
                    })
                  }
                >
                  Remove technology {techIndex + 1}
                </button>
              </span>
            ))}
            <button
              type="button"
              onClick={() => dispatch({ type: 'ADD_TECHNOLOGY', section, localId: entry.localId })}
            >
              Add technology to {heading.toLowerCase()} {index + 1}
            </button>
            <IssueList validation={validation} path={`${section}.${index}.technologies`} />
          </fieldset>

          <button
            type="button"
            onClick={() => dispatch({ type: 'REMOVE_ENTRY', section, localId: entry.localId })}
          >
            Remove {heading.toLowerCase()} {index + 1}
          </button>
        </fieldset>
      ))}
      <button type="button" onClick={() => dispatch({ type: 'ADD_ENTRY', section })}>
        {addLabel}
      </button>
    </section>
  );

  return (
    <section aria-labelledby="review-heading">
      <h2 id="review-heading">Review your details</h2>
      <p>
        Check what we extracted, then confirm. Nothing is saved until you confirm, and this draft is
        only held in this browser tab.
      </p>

      <IssueList validation={validation} path="content" />

      <section aria-labelledby="skills-heading">
        <h3 id="skills-heading">Skills</h3>
        <p>
          Skills are your own confirmed claims. They are used to show where a job names a skill you
          listed; they are not a check of ability.
        </p>
        <IssueList validation={validation} path="skills" />
        <ul>
          {draft.skills.map((skill, index) => (
            <li key={skill.localId} data-testid="skill-item">
              <label htmlFor={skill.localId}>Skill {index + 1}</label>
              <input
                id={skill.localId}
                value={skill.value}
                onChange={(event) =>
                  dispatch({
                    type: 'UPDATE_SKILL',
                    localId: skill.localId,
                    value: event.target.value,
                  })
                }
              />
              <button
                type="button"
                onClick={() => dispatch({ type: 'REMOVE_SKILL', localId: skill.localId })}
              >
                Remove skill {index + 1}
              </button>
              <IssueList validation={validation} path={`skills.${index}`} />
            </li>
          ))}
        </ul>
        <button type="button" onClick={() => dispatch({ type: 'ADD_SKILL' })}>
          Add skill
        </button>
      </section>

      {renderEntries('projects', 'Project', 'Add project')}
      {renderEntries('experience', 'Experience', 'Add experience')}

      <section aria-labelledby="education-heading">
        <h3 id="education-heading">Education</h3>
        <p>Education is kept on your profile but is not used for matching in this version.</p>
        <IssueList validation={validation} path="education" />
        {draft.education.map((entry, index) => (
          <fieldset key={entry.localId} data-testid="education-entry">
            <legend>Education {index + 1}</legend>
            <label htmlFor={`${entry.localId}-qualification`}>Qualification</label>
            <input
              id={`${entry.localId}-qualification`}
              value={entry.qualification}
              onChange={(event) =>
                dispatch({
                  type: 'UPDATE_EDUCATION',
                  localId: entry.localId,
                  field: 'qualification',
                  value: event.target.value,
                })
              }
            />
            <IssueList validation={validation} path={`education.${index}.qualification`} />
            <label htmlFor={`${entry.localId}-details`}>Details</label>
            <input
              id={`${entry.localId}-details`}
              value={entry.details}
              onChange={(event) =>
                dispatch({
                  type: 'UPDATE_EDUCATION',
                  localId: entry.localId,
                  field: 'details',
                  value: event.target.value,
                })
              }
            />
            <IssueList validation={validation} path={`education.${index}.details`} />
            <button
              type="button"
              onClick={() => dispatch({ type: 'REMOVE_EDUCATION', localId: entry.localId })}
            >
              Remove education {index + 1}
            </button>
          </fieldset>
        ))}
        <button type="button" onClick={() => dispatch({ type: 'ADD_EDUCATION' })}>
          Add education
        </button>
      </section>

      {!matchable && (
        <p data-testid="not-matchable-hint">
          You can save this, but recommendations need at least one project or experience entry.
          Without one we can only show you the full internship list.
        </p>
      )}

      <button type="button" onClick={onConfirm} disabled={saving || !validation.canSave}>
        {saving ? 'Saving…' : 'Confirm and save'}
      </button>
      <button type="button" onClick={onCancel} disabled={saving}>
        Discard changes
      </button>
    </section>
  );
}
