import { useId, useRef, useState } from 'react';
import { LIMITS } from '../api/contractTypes';
import { formatMebibytes, type UploadRejection } from '../model/uploadValidation';

/**
 * PDF selection by drag/drop or local picker (PRD P05).
 *
 * Drag and drop is implemented with native DnD events rather than react-dropzone.
 * react-dropzone is on the approved reuse list, but dependency locking is Xue E's
 * bootstrap task and this needs about thirty lines; swapping it in later touches only
 * this component. Recorded in the feature README so the choice is reviewable.
 *
 * The upload is never sent anywhere except POST /api/resume/prepare, and the selection
 * is retained when preparation fails so a busy response does not lose the student's file.
 */
export interface ResumeUploadPanelProps {
  selectedFile: File | null;
  rejection: UploadRejection | null;
  preparing: boolean;
  onSelectFiles: (files: readonly File[]) => void;
  onClearSelection: () => void;
  onPrepare: () => void;
  onSkip: () => void;
}

export function ResumeUploadPanel(props: ResumeUploadPanelProps): React.ReactElement {
  const { selectedFile, rejection, preparing, onSelectFiles, onClearSelection, onPrepare, onSkip } =
    props;
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    onSelectFiles(Array.from(event.dataTransfer?.files ?? []));
  };

  return (
    <section aria-labelledby={`${inputId}-heading`}>
      <h2 id={`${inputId}-heading`}>Add your resume</h2>
      <p>
        Upload one text-based PDF, up to {formatMebibytes(LIMITS.MAX_PDF_BYTES)}. We remove personal
        contact details before showing you the result. The file itself is not stored.
      </p>

      <div
        data-testid="dropzone"
        data-drag-active={dragActive ? 'true' : 'false'}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
      >
        <label htmlFor={inputId}>Choose a PDF resume</label>
        <input
          id={inputId}
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          disabled={preparing}
          onChange={(event) => {
            onSelectFiles(Array.from(event.target.files ?? []));
            // Allow re-selecting the same filename after a failure.
            event.target.value = '';
          }}
        />
        <p>or drop it here</p>
      </div>

      {rejection !== null && (
        <p role="alert" data-testid="upload-error" data-code={rejection.code}>
          {rejection.message}
        </p>
      )}

      {selectedFile !== null && (
        <div data-testid="selected-file">
          <p>
            Selected: {selectedFile.name} ({formatMebibytes(selectedFile.size)})
          </p>
          <button type="button" onClick={onPrepare} disabled={preparing}>
            {preparing ? 'Preparing…' : 'Prepare for review'}
          </button>
          <button type="button" onClick={onClearSelection} disabled={preparing}>
            Remove file
          </button>
        </div>
      )}

      <p>
        <button type="button" onClick={onSkip}>
          Enter my details without a PDF
        </button>
      </p>
    </section>
  );
}
