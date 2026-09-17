// @vitest-environment node
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import { ApiClient } from './client';
import { csrfToken, getAccount } from '../features/auth/authApi';
import { cataloguePage, jobs } from '../dev/catalogue';

let server: Server, origin: string, client: ApiClient;
let cookie = '', name: string | null, saves: number, rejectCsrf: boolean;
const received: { path: string; method: string; headers: IncomingMessage['headers']; body: string }[] = [];
const nativeFetch = globalThis.fetch;
const account = () => ({
  user: { user_id: '20000000-0000-4000-8000-000000000001', display_name: name },
  resume_revision: 0, has_resume: false, has_matchable_resume: false, csrf_token: 'synthetic-http-session-csrf',
});
function reply(response: ServerResponse, body: unknown, status = 200, extra = {}) {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...extra });
  response.end(status === 204 ? undefined : JSON.stringify(body));
}
function failure(response: ServerResponse, code: string, status: number) {
  reply(response, { error: { code, message: 'Synthetic fixture response.', request_id: 'synthetic-http', retryable: false, details: {} } }, status);
}
beforeEach(async () => {
  cookie = ''; name = null; saves = 0; rejectCsrf = false; received.length = 0;
  // Test-only contract responses over real loopback HTTP; this is not backend auth.
  server = createServer((request, response) => {
    void (async () => {
      const parts: Buffer[] = [];
      for await (const part of request) parts.push(Buffer.from(part));
      const body = Buffer.concat(parts).toString('utf8');
      const url = new URL(request.url!, origin);
      received.push({ path: request.url!, method: request.method!, headers: request.headers, body });
      if (url.pathname === '/api/auth/bootstrap') {
        reply(response, { csrf_token: 'synthetic-http-bootstrap' }, 200, { 'Set-Cookie': 'prelogin=synthetic; HttpOnly; SameSite=Lax; Path=/' }); return;
      }
      if (request.method !== 'GET' && request.headers.origin !== origin) { failure(response, 'CSRF_INVALID', 403); return; }
      if (url.pathname === '/api/auth/google') {
        if (request.headers.cookie !== 'prelogin=synthetic' || request.headers['x-csrf-token'] !== 'synthetic-http-bootstrap') {
          failure(response, 'CSRF_INVALID', 403); return;
        }
        reply(response, { user: account().user, csrf_token: account().csrf_token }, 200, { 'Set-Cookie': 'session=synthetic; HttpOnly; SameSite=Lax; Path=/' }); return;
      }
      if (request.headers.cookie !== 'session=synthetic') { failure(response, 'AUTH_REQUIRED', 401); return; }
      if (request.method !== 'GET' && (rejectCsrf || request.headers['x-csrf-token'] !== account().csrf_token)) {
        failure(response, 'CSRF_INVALID', 403); return;
      }
      if (url.pathname === '/api/me') {
        if (request.method === 'PATCH') { name = JSON.parse(body).display_name; reply(response, null, 204); }
        else reply(response, account());
        return;
      }
      if (url.pathname === '/api/jobs') { reply(response, cataloguePage(url.searchParams)); return; }
      if (url.pathname.startsWith('/api/jobs/')) {
        const job = jobs.find(item => item.job_id === url.pathname.split('/').at(-1));
        if (job) reply(response, job); else failure(response, 'JOB_NOT_FOUND', 404);
        return;
      }
      if (url.pathname === '/api/resume/prepare') {
        reply(response, { error: { code: 'PROCESSING_BUSY', message: 'Synthetic busy response.', request_id: 'synthetic-http', retryable: true, details: {} } }, 503, { 'Retry-After': '3' }); return;
      }
      if (url.pathname === '/api/resume' && request.method === 'PUT') {
        saves++; response.destroy(); return; // Deliberate unknown outcome, never auto-replayed.
      }
      if (url.pathname === '/api/auth/logout') { reply(response, null, 204, { 'Set-Cookie': 'session=; Max-Age=0; Path=/' }); return; }
      failure(response, 'JOB_NOT_FOUND', 404);
    })().catch(() => { if (!response.destroyed) failure(response, 'INTERNAL_ERROR', 500); });
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Test listener unavailable');
  origin = 'http://127.0.0.1:' + address.port;
  vi.stubGlobal('window', { location: { origin } });
  // Node has no browser cookie jar. Explicitly emulate only cookie/Origin forwarding;
  // these tests do NOT establish browser HttpOnly/SameSite enforcement or Google validity.
  client = new ApiClient(async (path, init) => {
    const headers = new Headers(init?.headers);
    if (cookie) headers.set('Cookie', cookie);
    if (init?.method !== 'GET') headers.set('Origin', origin);
    const response = await nativeFetch(new URL(String(path), origin), { ...init, headers });
    const setCookie = response.headers.get('set-cookie');
    if (setCookie) cookie = setCookie.split(';')[0]!;
    return response;
  });
});
afterEach(async () => {
  client.clearSession();
  server.closeAllConnections();
  await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  vi.unstubAllGlobals();
});
async function authenticate() {
  client.pausePrivateRequests();
  client.setCsrf(csrfToken(await client.json({ method: 'GET', path: '/api/auth/bootstrap' })));
  client.setCsrf(csrfToken(await client.json({ method: 'POST', path: '/api/auth/google', json: { credential: 'synthetic-http-credential' } })));
  const me = await getAccount(client);
  client.setCsrf(me.csrf_token); client.resumePrivateRequests();
}
test('real HTTP uses bootstrap/session CSRF, literal repeated filters and closed details', async () => {
  await authenticate();
  await client.json({ method: 'PATCH', path: '/api/me', json: { display_name: 'Synthetic HTTP Student' } });
  expect((await getAccount(client)).user.display_name).toBe('Synthetic HTTP Student');
  const result = await client.json<{ total: number }>({ method: 'GET', path: '/api/jobs?q=C%2B%2B+100%25&work_arrangement=REMOTE&work_arrangement=HYBRID' });
  expect(result.total).toBe(1);
  expect(received.at(-1)?.path).toContain('work_arrangement=REMOTE&work_arrangement=HYBRID');
  const closed = await client.json<{ is_active: boolean }>({ method: 'GET', path: '/api/jobs/' + jobs[24]!.job_id });
  expect(closed.is_active).toBe(false);
  await client.json({ method: 'POST', path: '/api/auth/logout' });
  expect(cookie).toBe('session=');
});
test('multipart and Retry-After reach Nasya transport without status conversion', async () => {
  await authenticate();
  const file = new FormData(); file.append('file', new Blob(['synthetic PDF fixture'], { type: 'application/pdf' }), 'synthetic.pdf');
  const result = await client.scopedTransport().send({ method: 'POST', path: '/api/resume/prepare', formData: file });
  expect(result.status).toBe(503); expect(result.header('retry-after')).toBe('3');
  expect(received.at(-1)?.headers['content-type']).toMatch(/^multipart\/form-data; boundary=/);
  expect(received.at(-1)?.body).toContain('name="file"');
  expect(received.at(-1)?.headers['x-csrf-token']).toBe('synthetic-http-session-csrf');
});
test('HTTP CSRF rejection requires explicit recovery and does not replay writes', async () => {
  await authenticate(); rejectCsrf = true;
  const recovery = vi.fn(); client.onAuthenticationRequired(recovery);
  const result = await client.send({ method: 'PATCH', path: '/api/me', json: { display_name: 'Synthetic' } });
  expect(result.status).toBe(403);
  expect(recovery).toHaveBeenCalledWith('CSRF_INVALID');
  expect(received.filter(request => request.method === 'PATCH')).toHaveLength(1);
});
test('lost HTTP save response stays unknown with one submitted idempotency key', async () => {
  await authenticate();
  await expect(client.scopedTransport().send({
    method: 'PUT', path: '/api/resume', json: { expected_revision: 0, content: { skills: ['Python'], projects: [], experience: [], education: [] } },
    headers: { 'Idempotency-Key': '30000000-0000-4000-8000-000000000001' },
  })).rejects.toThrow();
  expect(saves).toBe(1);
  expect(received.at(-1)?.headers['idempotency-key']).toBe('30000000-0000-4000-8000-000000000001');
});
