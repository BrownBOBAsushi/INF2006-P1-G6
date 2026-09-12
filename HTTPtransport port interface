/**
 * Integration seam between Nasya's resume feature and Xue E's shared API client.
 *
 * Nasya's feature does NOT own session handling, CSRF, base URLs or cookie policy.
 * It depends only on this narrow port. Xue E's shared client supplies an
 * implementation that is responsible for:
 *
 *   - same-origin base path (the contract's `/api` prefix and the dev proxy),
 *   - sending the session cookie (credentials: 'same-origin'),
 *   - attaching `X-CSRF-Token` on every unsafe request, sourced from GET /api/me,
 *   - NOT persisting any credential to localStorage/sessionStorage.
 *
 * The resume feature deliberately never sets those headers itself, so there is one
 * owner for auth transport. If Xue E changes the client's signature, only the
 * adapter that produces an HttpTransport needs to change, not this feature.
 */

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

export interface HttpRequest {
  method: HttpMethod;
  /** Contract path including the /api prefix, e.g. '/api/resume'. */
  path: string;
  /** JSON request body. Mutually exclusive with `formData`. */
  json?: unknown;
  /** Multipart body, used only by POST /api/resume/prepare. */
  formData?: FormData;
  /** Feature-specific headers only (e.g. Idempotency-Key). Never auth headers. */
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export interface HttpResponse {
  status: number;
  /** Parsed JSON body, or null for 204/empty bodies. */
  body: unknown;
  /** Lower-cased header lookup; at minimum `retry-after` must be exposed. */
  header(name: string): string | null;
}

export interface HttpTransport {
  /**
   * Resolves for any HTTP status, including 4xx/5xx — status mapping is the
   * feature's job. Rejects only when no usable response was obtained (network
   * failure, abort, client-side timeout). Rejections are treated as
   * UNKNOWN OUTCOME for unsafe methods, never as failure.
   */
  send(request: HttpRequest): Promise<HttpResponse>;
}
