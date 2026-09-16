import type { Me } from '../api/contracts';
import type { SignInProps } from '../App';
import { cataloguePage, jobs } from './catalogue';

export function MockSignIn({ onCredential }: SignInProps) {
  return <button onClick={() => void onCredential('synthetic-preview-credential')}>Enter synthetic preview</button>;
}
/** Explicit dev entry only; never intercepts browser fetch or reaches a real service. */
export function createMockFetch(): typeof fetch {
  let signedIn = false;
  let name: string | null = null;
  const csrf = 'synthetic-session-csrf';
  const me = (): Me => ({
    user: { user_id: '20000000-0000-4000-8000-000000000001', display_name: name },
    resume_revision: 0, has_resume: false, has_matchable_resume: false, csrf_token: csrf,
  });
  const reply = (body: unknown, status = 200) => new Response(status === 204 ? null : JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
  const error = (code: string, status: number) => reply({ error: {
    code, message: 'Synthetic fixture response.', request_id: 'synthetic-request', retryable: false, details: {},
  } }, status);
  return (async (input, init) => {
    if (init?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const url = new URL(String(input), window.location.origin);
    const method = init?.method ?? 'GET';
    const token = new Headers(init?.headers).get('X-CSRF-Token');
    if (url.pathname === '/api/auth/bootstrap' && method === 'GET') return reply({ csrf_token: 'synthetic-bootstrap-csrf' });
    if (url.pathname === '/api/auth/google' && method === 'POST') {
      if (token !== 'synthetic-bootstrap-csrf') return error('CSRF_INVALID', 403);
      signedIn = true; return reply({ user: me().user, csrf_token: csrf });
    }
    if (url.pathname === '/api/auth/logout' && method === 'POST') { signedIn = false; name = null; return reply(null, 204); }
    if (!signedIn) return error('AUTH_REQUIRED', 401);
    if (method !== 'GET' && token !== csrf) return error('CSRF_INVALID', 403);
    if (url.pathname === '/api/me' && method === 'GET') return reply(me());
    if (url.pathname === '/api/me' && method === 'PATCH') {
      const body = JSON.parse(String(init?.body)) as { display_name: string };
      name = body.display_name; return reply({ user: me().user });
    }
    if (url.pathname === '/api/jobs' && method === 'GET') {
      try { return reply(cataloguePage(url.searchParams)); }
      catch (cause) { return error(cause instanceof Error ? cause.message : 'INVALID_CONTENT', cause instanceof Error && cause.message === 'RESULTS_CHANGED' ? 409 : 422); }
    }
    if (url.pathname.startsWith('/api/jobs/') && method === 'GET') {
      const job = jobs.find(item => item.job_id === url.pathname.split('/').at(-1));
      return job ? reply(job) : error('JOB_NOT_FOUND', 404);
    }
    if (url.pathname === '/api/resume' && method === 'GET') return error('RESUME_NOT_FOUND', 404);
    // Missing processing and matching are not simulated as successful work.
    return error('SERVICE_UNAVAILABLE', 503);
  }) as typeof fetch;
}
