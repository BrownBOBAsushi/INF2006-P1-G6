import { ERROR_CODES, LIMITS } from '../api/contractTypes';

/**
 * Client-side pre-checks for the selected PDF.
 *
 * The server enforces the real limits (size, page count, encryption, text content) in
 * a restricted child process. These checks exist only so an obviously-wrong file is
 * rejected without spending an upload and a processing slot. Codes match the server's
 * error codes so the student sees consistent wording either way.
 */

export interface UploadRejection {
  code: string;
  message: string;
}

export type UploadCheck = { ok: true; file: File } | { ok: false; rejection: UploadRejection };

function looksLikePdf(file: File): boolean {
  if (file.type === 'application/pdf') return true;
  // Some browsers/OSes report an empty or generic type; fall back to the extension.
  if (file.type === '' || file.type === 'application/octet-stream') {
    return file.name.toLowerCase().endsWith('.pdf');
  }
  return false;
}

export function validateUploadSelection(files: readonly File[]): UploadCheck {
  if (files.length === 0) {
    return {
      ok: false,
      rejection: { code: 'NO_FILE', message: 'Choose a PDF file to upload.' },
    };
  }
  if (files.length > 1) {
    return {
      ok: false,
      rejection: {
        code: 'TOO_MANY_FILES',
        message: 'Upload one PDF at a time.',
      },
    };
  }

  const file = files[0] as File;

  if (!looksLikePdf(file)) {
    return {
      ok: false,
      rejection: {
        code: ERROR_CODES.PDF_REQUIRED,
        message: 'That file is not a PDF. Upload a text-based PDF resume.',
      },
    };
  }

  if (file.size === 0) {
    return {
      ok: false,
      rejection: {
        code: ERROR_CODES.PDF_UNREADABLE,
        message: 'That file is empty.',
      },
    };
  }

  if (file.size > LIMITS.MAX_PDF_BYTES) {
    return {
      ok: false,
      rejection: {
        code: ERROR_CODES.FILE_TOO_LARGE,
        message: `That PDF is ${formatMebibytes(file.size)}. The limit is ${formatMebibytes(LIMITS.MAX_PDF_BYTES)}.`,
      },
    };
  }

  return { ok: true, file };
}

export function formatMebibytes(bytes: number): string {
  const mib = bytes / (1024 * 1024);
  return `${mib.toFixed(1)} MiB`;
}

/**
 * Student-facing wording for server-side preparation failures.
 * Deliberately generic: the contract forbids surfacing parser exception text.
 */
export function prepareFailureMessage(code: string): string {
  switch (code) {
    case ERROR_CODES.PDF_REQUIRED:
      return 'That file is not a PDF. Upload a text-based PDF resume.';
    case ERROR_CODES.FILE_TOO_LARGE:
      return `That PDF is larger than ${formatMebibytes(LIMITS.MAX_PDF_BYTES)}.`;
    case ERROR_CODES.PDF_ENCRYPTED:
      return 'That PDF is password-protected. Remove the password and upload it again.';
    case ERROR_CODES.PDF_UNREADABLE:
      return 'That PDF could not be read. It may be damaged or exceed the page limit.';
    case ERROR_CODES.TEXT_REQUIRED:
      return 'No selectable text was found. Scanned or image-only PDFs are not supported; export a text PDF instead.';
    case ERROR_CODES.PROCESSING_BUSY:
      return 'Resume processing is busy right now. Your file is still selected — try again shortly.';
    case ERROR_CODES.PROCESSING_TIMEOUT:
      return 'Preparing the PDF took too long and was stopped. Try a shorter document.';
    case ERROR_CODES.MODEL_VERSION_UNAVAILABLE:
      return 'Resume processing is temporarily unavailable. Browsing still works.';
    default:
      return 'The PDF could not be prepared. Try again, or edit your details manually.';
  }
}
