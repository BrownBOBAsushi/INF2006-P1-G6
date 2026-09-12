import type { ApiErrorEnvelope } from './contractTypes';

/**
 * A response was received and it carried a server error envelope.
 * The outcome is DEFINITE: the server decided this.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly requestId: string;
  readonly details: Record<string, unknown>;
  /** Seconds from a Retry-After header, when the server supplied one. */
  readonly retryAfterSeconds: number | null;

  constructor(args: {
    status: number;
    code: string;
    message: string;
    retryable: boolean;
    requestId: string;
    details?: Record<string, unknown>;
    retryAfterSeconds?: number | null;
  }) {
    super(args.message);
    this.name = 'ApiError';
    this.status = args.status;
    this.code = args.code;
    this.retryable = args.retryable;
    this.requestId = args.requestId;
    this.details = args.details ?? {};
    this.retryAfterSeconds = args.retryAfterSeconds ?? null;
  }
}

/**
 * No usable response was received (network failure, client timeout, aborted request),
 * OR the response indicates the server may have been interrupted mid-commit.
 *
 * For an unsafe request this means the outcome is UNKNOWN. The UI must not claim the
 * profile is unchanged; it must resolve the outcome through idempotent replay or by
 * reading current state. See DATA_API_CONTRACT.md "Save transaction and retries" step 6.
 */
export class UnknownOutcomeError extends Error {
  readonly cause: unknown;
  /** Present when the server did answer but with a status that does not settle the outcome. */
  readonly status: number | null;

  constructor(message: string, options?: { cause?: unknown; status?: number | null }) {
    super(message);
    this.name = 'UnknownOutcomeError';
    this.cause = options?.cause;
    this.status = options?.status ?? null;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

export function isUnknownOutcome(e: unknown): e is UnknownOutcomeError {
  return e instanceof UnknownOutcomeError;
}

/** Narrow an arbitrary parsed body to the contract error envelope, defensively. */
export function parseErrorEnvelope(body: unknown): ApiErrorEnvelope['error'] | null {
  if (typeof body !== 'object' || body === null) return null;
  const outer = body as Record<string, unknown>;
  const inner = outer['error'];
  if (typeof inner !== 'object' || inner === null) return null;
  const e = inner as Record<string, unknown>;
  if (typeof e['code'] !== 'string') return null;
  return {
    code: e['code'],
    message: typeof e['message'] === 'string' ? e['message'] : 'Request failed.',
    request_id: typeof e['request_id'] === 'string' ? e['request_id'] : '',
    retryable: e['retryable'] === true,
    details:
      typeof e['details'] === 'object' && e['details'] !== null
        ? (e['details'] as Record<string, unknown>)
        : {},
  };
}
