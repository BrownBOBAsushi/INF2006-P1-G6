import type { HttpRequest, HttpResponse, HttpTransport } from '../features/resume';

// Extends Nasya's port without changing her feature-owned interface.
export type Request = Omit<HttpRequest, 'method'> & { method: HttpRequest['method'] | 'PATCH' };
export class ApiError extends Error {
  constructor(public status: number, public code: string, public retryAfter: string | null) {
    super(code);
  }
}

export class ApiClient implements HttpTransport {
  private csrf: string | null = null;
  private listeners = new Set<() => void>();
  constructor(private fetcher: typeof fetch = fetch, private timeoutMs = 100_000) {}

  setCsrf(token: string | null) { this.csrf = token; }
  clearSession() { this.csrf = null; }
  onAuthenticationRequired(listener: () => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  async send(request: Request): Promise<HttpResponse> {
    const url = new URL(request.path, window.location.origin);
    if (!request.path.startsWith('/api/') || url.origin !== window.location.origin ||
        !url.pathname.startsWith('/api/') || url.hash) {
      throw new Error('Only same-origin /api/ paths are allowed.');
    }
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
    const abort = () => controller.abort();
    if (request.signal?.aborted) abort();
    request.signal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(abort, this.timeoutMs);
    try {
      const response = await this.fetcher(url.pathname + url.search, {
        method: request.method, headers,
        body: request.formData ?? (request.json !== undefined ? JSON.stringify(request.json) : undefined),
        credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
      });
      if (response.status === 401) {
        this.clearSession();
        this.listeners.forEach(listener => listener());
      }
      const raw = response.status === 204 ? '' : await response.text();
      // Non-JSON gateway responses remain HTTP outcomes for Nasya's status handling.
      let body: unknown = null;
      if (raw) { try { body = JSON.parse(raw); } catch { /* no raw server text exposed */ } }
      return { status: response.status, body, header: name => response.headers.get(name) };
    } finally {
      clearTimeout(timer);
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
