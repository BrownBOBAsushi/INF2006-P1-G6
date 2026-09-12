import {
  ERROR_CODES,
  type DeleteResumeResponse,
  type OperationStatusResponse,
  type PrepareResumeResponse,
  type ResumeProfileResponse,
  type SaveResumeRequest,
  type SaveResumeResponse,
} from './contractTypes';
import { ApiError, UnknownOutcomeError, parseErrorEnvelope } from './errors';
import type { HttpResponse, HttpTransport } from './httpTransport';

/**
 * The resume endpoints this feature consumes, expressed as a port so the UI and the
 * save controller can be tested without a network or a backend.
 */
export interface ResumeApiPort {
  /** POST /api/resume/prepare (multipart). */
  prepare(file: File, signal?: AbortSignal): Promise<PrepareResumeResponse>;
  /** GET /api/resume. Returns null for 404 RESUME_NOT_FOUND (a normal empty state). */
  getProfile(): Promise<ResumeProfileResponse | null>;
  /** GET /api/me after a missing profile; reject concurrent recreation. */
  getAccountRevision(): Promise<number>;
  /** PUT /api/resume with a caller-supplied Idempotency-Key. */
  save(request: SaveResumeRequest, idempotencyKey: string): Promise<SaveResumeResponse>;
  /** DELETE /api/resume. */
  deleteProfile(expectedRevision: number): Promise<DeleteResumeResponse>;
  /** GET /api/resume/operations/{id}. */
  getOperation(operationId: string): Promise<OperationStatusResponse>;
}

/**
 * Statuses that do NOT settle whether an unsafe request took effect.
 * 504 is a proxy/client-side deadline: the server request may still be running.
 * 500 may in principle be raised after a commit, so it is resolved by replay rather
 * than reported as a definite failure. Both are cheap to resolve: replaying the same
 * idempotency key returns the stored terminal outcome without saving again.
 */
const UNSETTLED_STATUSES = new Set([500, 502, 504]);

function retryAfterSeconds(response: HttpResponse): number | null {
  const raw = response.header('retry-after');
  if (raw === null) return null;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function toApiError(response: HttpResponse): ApiError {
  const envelope = parseErrorEnvelope(response.body);
  return new ApiError({
    status: response.status,
    code: envelope?.code ?? 'INTERNAL_ERROR',
    message: envelope?.message ?? 'The server returned an unexpected error.',
    retryable: envelope?.retryable ?? false,
    requestId: envelope?.request_id ?? '',
    details: envelope?.details ?? {},
    retryAfterSeconds: retryAfterSeconds(response),
  });
}

function ok(response: HttpResponse): boolean {
  return response.status >= 200 && response.status < 300;
}

/**
 * Sends a request whose effect on server state matters. A transport rejection or an
 * unsettled status becomes UnknownOutcomeError so callers cannot accidentally report
 * "nothing was saved".
 */
async function sendUnsafe(
  transport: HttpTransport,
  request: Parameters<HttpTransport['send']>[0],
): Promise<HttpResponse> {
  let response: HttpResponse;
  try {
    response = await transport.send(request);
  } catch (cause) {
    throw new UnknownOutcomeError(
      'The request did not complete, so its outcome is unknown.',
      { cause },
    );
  }
  if (UNSETTLED_STATUSES.has(response.status)) {
    const envelope = parseErrorEnvelope(response.body);
    throw new UnknownOutcomeError(
      envelope?.message ?? 'The server did not confirm the outcome of this request.',
      { status: response.status },
    );
  }
  return response;
}

export function createResumeApi(transport: HttpTransport): ResumeApiPort {
  return {
    async prepare(file, signal) {
      const formData = new FormData();
      formData.append('file', file);
      // Preparation writes no durable domain state, so a transport failure here is a
      // plain failure the student can retry without idempotency concerns.
      let response: HttpResponse;
      try {
        response = await transport.send({
          method: 'POST',
          path: '/api/resume/prepare',
          formData,
          ...(signal ? { signal } : {}),
        });
      } catch (cause) {
        throw new UnknownOutcomeError('The upload did not complete.', { cause });
      }
      if (!ok(response)) throw toApiError(response);
      return response.body as PrepareResumeResponse;
    },

    async getProfile() {
      let response: HttpResponse;
      try {
        response = await transport.send({ method: 'GET', path: '/api/resume' });
      } catch (cause) {
        throw new UnknownOutcomeError('Could not read the saved profile.', { cause });
      }
      if (response.status === 404) {
        const envelope = parseErrorEnvelope(response.body);
        if (envelope === null || envelope.code === ERROR_CODES.RESUME_NOT_FOUND) return null;
        throw toApiError(response);
      }
      if (!ok(response)) throw toApiError(response);
      return response.body as ResumeProfileResponse;
    },

    async getAccountRevision() {
      let response: HttpResponse;
      try {
        response = await transport.send({ method: 'GET', path: '/api/me' });
      } catch (cause) {
        throw new UnknownOutcomeError('Could not read the account revision.', { cause });
      }
      if (!ok(response)) throw toApiError(response);
      const account = response.body as { resume_revision?: unknown; has_resume?: unknown } | null;
      // The caller just read a missing profile. Never adopt a newer revision for
      // unseen content created by another tab between these two reads.
      if (account?.has_resume !== false) {
        throw new UnknownOutcomeError('The resume changed while loading. Reload its current version.');
      }
      const revision = account.resume_revision;
      if (typeof revision !== 'number' || !Number.isSafeInteger(revision) || revision < 0) {
        throw new UnknownOutcomeError('The account revision could not be read.');
      }
      return revision;
    },

    async save(request, idempotencyKey) {
      const response = await sendUnsafe(transport, {
        method: 'PUT',
        path: '/api/resume',
        json: request,
        headers: { 'Idempotency-Key': idempotencyKey },
      });
      if (!ok(response)) throw toApiError(response);
      return response.body as SaveResumeResponse;
    },

    async deleteProfile(expectedRevision) {
      const response = await sendUnsafe(transport, {
        method: 'DELETE',
        path: '/api/resume',
        json: { expected_revision: expectedRevision },
      });
      if (!ok(response)) throw toApiError(response);
      return response.body as DeleteResumeResponse;
    },

    async getOperation(operationId) {
      let response: HttpResponse;
      try {
        response = await transport.send({
          method: 'GET',
          path: `/api/resume/operations/${encodeURIComponent(operationId)}`,
        });
      } catch (cause) {
        throw new UnknownOutcomeError('Could not read the save status.', { cause });
      }
      if (!ok(response)) throw toApiError(response);
      return response.body as OperationStatusResponse;
    },
  };
}
