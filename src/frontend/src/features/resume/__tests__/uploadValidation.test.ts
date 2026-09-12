import { describe, expect, it } from 'vitest';
import { ERROR_CODES, LIMITS } from '../api/contractTypes';
import { prepareFailureMessage, validateUploadSelection } from '../model/uploadValidation';
import {
  attemptForPayload,
  attemptMatchesPayload,
  createIdempotencyKey,
} from '../model/idempotency';
import { syntheticPdfFile } from '../fixtures/resumeFixtures';

describe('validateUploadSelection', () => {
  it('accepts one PDF within the size limit', () => {
    const check = validateUploadSelection([syntheticPdfFile('resume.pdf', 2048)]);
    expect(check.ok).toBe(true);
  });

  it('rejects an empty selection', () => {
    const check = validateUploadSelection([]);
    expect(check).toMatchObject({ ok: false, rejection: { code: 'NO_FILE' } });
  });

  it('rejects more than one file', () => {
    const check = validateUploadSelection([syntheticPdfFile('a.pdf'), syntheticPdfFile('b.pdf')]);
    expect(check).toMatchObject({ ok: false, rejection: { code: 'TOO_MANY_FILES' } });
  });

  it('rejects a non-PDF content type', () => {
    const docx = syntheticPdfFile('resume.docx', 1024, 'application/vnd.openxmlformats');
    expect(validateUploadSelection([docx])).toMatchObject({
      ok: false,
      rejection: { code: ERROR_CODES.PDF_REQUIRED },
    });
  });

  it('accepts a .pdf file whose browser-reported type is empty', () => {
    const untyped = syntheticPdfFile('resume.pdf', 1024, '');
    expect(validateUploadSelection([untyped]).ok).toBe(true);
  });

  it('rejects a .txt file even when the type is empty', () => {
    const untyped = syntheticPdfFile('notes.txt', 1024, '');
    expect(validateUploadSelection([untyped])).toMatchObject({
      ok: false,
      rejection: { code: ERROR_CODES.PDF_REQUIRED },
    });
  });

  it('rejects an empty file', () => {
    expect(validateUploadSelection([syntheticPdfFile('resume.pdf', 0)])).toMatchObject({
      ok: false,
      rejection: { code: ERROR_CODES.PDF_UNREADABLE },
    });
  });

  it('accepts exactly the 5,242,880 byte limit', () => {
    const atLimit = syntheticPdfFile('resume.pdf', LIMITS.MAX_PDF_BYTES);
    expect(validateUploadSelection([atLimit]).ok).toBe(true);
  });

  it('rejects one byte over the limit', () => {
    const overLimit = syntheticPdfFile('resume.pdf', LIMITS.MAX_PDF_BYTES + 1);
    expect(validateUploadSelection([overLimit])).toMatchObject({
      ok: false,
      rejection: { code: ERROR_CODES.FILE_TOO_LARGE },
    });
  });
});

describe('prepareFailureMessage', () => {
  it('explains encrypted, scanned and busy cases distinctly', () => {
    const encrypted = prepareFailureMessage(ERROR_CODES.PDF_ENCRYPTED);
    const scanned = prepareFailureMessage(ERROR_CODES.TEXT_REQUIRED);
    const busy = prepareFailureMessage(ERROR_CODES.PROCESSING_BUSY);
    expect(new Set([encrypted, scanned, busy]).size).toBe(3);
    expect(busy).toMatch(/still selected/i);
  });

  it('never leaks a raw error code to the student', () => {
    expect(prepareFailureMessage('SOME_INTERNAL_PARSER_EXPLOSION')).not.toMatch(/SOME_INTERNAL/);
  });
});

describe('idempotency key lifecycle', () => {
  const keys = () => {
    let n = 0;
    return () => `key-${(n += 1)}`;
  };

  it('generates UUID-shaped keys', () => {
    expect(createIdempotencyKey()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  });

  it('reuses the key when revision and content are unchanged (network retry)', () => {
    const factory = keys();
    const first = attemptForPayload(null, 3, 'sig-a', factory);
    const second = attemptForPayload(first, 3, 'sig-a', factory);
    expect(second.key).toBe(first.key);
  });

  it('rotates the key when the content changes (new logical attempt)', () => {
    const factory = keys();
    const first = attemptForPayload(null, 3, 'sig-a', factory);
    const second = attemptForPayload(first, 3, 'sig-b', factory);
    expect(second.key).not.toBe(first.key);
  });

  it('rotates the key when expected_revision changes, because it is part of the payload hash', () => {
    const factory = keys();
    const first = attemptForPayload(null, 3, 'sig-a', factory);
    const second = attemptForPayload(first, 4, 'sig-a', factory);
    expect(second.key).not.toBe(first.key);
  });

  it('never matches a null attempt', () => {
    expect(attemptMatchesPayload(null, 1, 'sig')).toBe(false);
  });
});
