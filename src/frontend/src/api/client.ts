import type { HttpRequest, HttpResponse, HttpTransport } from '../features/resume';

export type Request = Omit<HttpRequest, 'method'> & { method: HttpRequest['method'] | 'PATCH' };
export type RecoveryReason = 'SESSION_EXPIRED' | 'CSRF_INVALID';
export class ApiError extends Error {
  constructor(public status: number, public code: string, public retryAfter: string | null) {
    super(code);
  }
}
export class StaleSessionError extends Error {
  constructor() { super('This operation belongs to an earlier session.'); }
}
export class ApiClient implements HttpTransport {
  private csrf: string | null = null;
  private requestVersion = 0;
  private privateVersion = 0;
  private privatePaused = false;
  private activeRequests = new Set<AbortController>();
  private listeners = new Set<(reason: RecoveryReason) => void>();
  constructor(private fetcher: typeof fetch = fetch, private timeoutMs = 100_000) {}

  private invalidateRequests(except?: AbortController) {
    this.requestVersion++;
    this.activeRequests.forEach(controller => { if (controller !== except) controller.abort(); });
  }
  setCsrf(token: string | null) {
    if (token !== this.csrf) {
      this.csrf = token;
      this.invalidateRequests();
    }
  }
  pausePrivateRequests() {
    this.privatePaused = true;
    this.invalidateRequests();
  }
  /** Call only after GET /me has confirmed the account behind the current cookie. */
  resumePrivateRequests() { this.privatePaused = false; }
  /** Revoke old feature adapters, retaining CSRF only so logout can still be sent. */
  clearPrivateState() {
    this.privateVersion++;
    this.pausePrivateRequests();
  }
  clearSession() {
    this.csrf = null;
    this.clearPrivateState();
  }
  /** An account-bound adapter prevents a delayed feature retry using a new account. */
  scopedTransport(): HttpTransport {
    const version = this.privateVersion;
    return { send: request => {
      if (version !== this.privateVersion) return Promise.reject(new StaleSessionError());
      return this.send(request);
    } };
  }
  onAuthenticationRequired(listener: (reason: RecoveryReason) => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  async send(request: Request): Promise<HttpResponse> {
    const url = new URL(request.path, window.location.origin);
    if (!request.path.startsWith('/api/') || url.origin !== window.location.origin ||
        !url.pathname.startsWith('/api/') || url.hash) {
      throw new Error('Only same-origin /api/ paths are allowed.');
    }
    const sessionRequest = (request.method === 'GET' && url.pathname === '/api/me') ||
      ['/api/auth/bootstrap', '/api/auth/google', '/api/auth/logout'].includes(url.pathname);
    if (this.privatePaused && !sessionRequest) throw new StaleSessionError();
    if (request.json !== undefined && request.formData) throw new Error('Choose JSON or multipart.');
    const headers = new Headers(request.headers);
    headers.delete('Authorization');
    headers.delete('X-CSRF-Token');
    if (request.method !== 'GET') {
      if (!this.csrf && request.path !== '/api/auth/logout') throw new Error('Refresh sign-in before submitting.');
      if (this.csrf) headers.set('X-CSRF-Token', this.csrf);
    }
    headers.set('Accept', 'application/json');
    if (request.json !== undefined) headers.set('Content-Type', 'application/json');
    if (request.formData) headers.delete('Content-Type');
    const controller = new AbortController();
    const version = this.requestVersion;
    this.activeRequests.add(controller);
    const abort = () => controller.abort();
    if (request.signal?.aborted) abort();
    request.signal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(abort, this.timeoutMs);
    try {
      controller.signal.throwIfAborted();
      const response = await this.fetcher(url.pathname + url.search, {
        method: request.method, headers,
        body: request.formData ?? (request.json !== undefined ? JSON.stringify(request.json) : undefined),
        credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
      });
      if (version !== this.requestVersion) throw new StaleSessionError();
      const raw = response.status === 204 ? '' : await response.text();
      // Check again after body consumption, even when a test transport ignores abort.
      if (version !== this.requestVersion) throw new StaleSessionError();
      controller.signal.throwIfAborted();
      let body: unknown = null;
      if (raw) { try { body = JSON.parse(raw); } catch { /* never expose raw server diagnostics */ } }
      const envelope = body as { error?: { code?: string } } | null;
      const reason = response.status === 401 ? 'SESSION_EXPIRED'
        : response.status === 403 && envelope?.error?.code === 'CSRF_INVALID' ? 'CSRF_INVALID' : null;
      if (reason) {
        this.privatePaused = true;
        this.csrf = null;
        this.invalidateRequests(controller);
        this.listeners.forEach(listener => listener(reason));
      }
      // Preserve the triggering HTTP status for Nasya's definite-outcome handling.
      return { status: response.status, body, header: name => response.headers.get(name) };
    } finally {
      clearTimeout(timer);
      this.activeRequests.delete(controller);
      request.signal?.removeEventListener('abort', abort);
    }
  }

  async json<T>(request: Request): Promise<T> {
    const response = await this.send(request);
    if (response.status < 200 || response.status >= 300) {
      const envelope = response.body as { error?: { code?: string } } | null;
      throw new ApiError(response.status, envelope?.error?.code ?? 'SERVICE_UNAVAILABLE', response.header('retry-after'));
    }
    if (response.status !== 204 && response.body === null) throw new Error('Invalid API response.');
    return response.body as T;
  }
}
