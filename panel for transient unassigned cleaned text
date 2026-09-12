import type { EntrySection } from '../model/draftReducer';

/**
 * Cleaned paragraphs the extractor could not classify.
 *
 * ARCHITECTURE.md requires these to be shown rather than silently dropped, and states
 * that `unassigned_text` is not part of saved ResumeContent and is never embedded
 * directly. The only way this text can reach the server is if the student copies it
 * into a project or experience entry here, which makes it ordinary reviewed content.
 *
 * Dismissing a paragraph discards it from memory. Nothing here is persisted.
 */
export interface UnassignedTextPanelProps {
  paragraphs: string[];
  onAssign: (index: number, section: EntrySection) => void;
  onDismiss: (index: number) => void;
}

export function UnassignedTextPanel(props: UnassignedTextPanelProps): React.ReactElement | null {
  const { paragraphs, onAssign, onDismiss } = props;
  if (paragraphs.length === 0) return null;

  return (
    <section aria-labelledby="unassigned-heading" data-testid="unassigned-panel">
      <h3 id="unassigned-heading">Not placed in a section</h3>
      <p>
        We could not tell which section these belong to. Add one to a project or experience entry to
        include it, or leave it out. Text left here is not saved.
      </p>
      <ul>
        {paragraphs.map((paragraph, index) => (
          <li key={`${index}-${paragraph.slice(0, 24)}`} data-testid="unassigned-paragraph">
            <p>{paragraph}</p>
            <button type="button" onClick={() => onAssign(index, 'projects')}>
              Add as project
            </button>
            <button type="button" onClick={() => onAssign(index, 'experience')}>
              Add as experience
            </button>
            <button type="button" onClick={() => onDismiss(index)}>
              Leave out
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
