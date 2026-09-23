import { act, renderHook, waitFor } from '@testing-library/react';
import { ApiClient } from '../../api/client';
import { useSession } from './useSession';
import { accountResponse } from './authApi';

const firstAccount = {
  user: { user_id: '20000000-0000-4000-8000-000000000001', display_name: 'Synthetic One' },
  resume_revision: 0, has_resume: false, has_matchable_resume: false, csrf_token: 'synthetic-first-csrf',
};
const secondAccount = {
  ...firstAccount, user: { user_id: '20000000-0000-4000-8000-000000000002', display_name: 'Synthetic Two' },
  csrf_token: 'synthetic-second-csrf',
};
function reply(body: unknown, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(body), { status });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

test('a slow reconnect cannot restore private UI after logout completes', async () => {
  const delayed = deferred<Response>();
  let reads = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (path, init) => {
    if (path === '/api/me') return ++reads === 1 ? reply(firstAccount) : delayed.promise;
    if (path === '/api/auth/logout' && init?.method === 'POST') return reply(null, 204);
    throw new Error('Unexpected synthetic request');
  });
  const client = new ApiClient(fetcher);
  const { result } = renderHook(() => useSession(client));
  await waitFor(() => expect(result.current.me?.user.user_id).toBe(firstAccount.user.user_id));
  let reconnect!: Promise<void>;
  act(() => { reconnect = result.current.refresh().catch(() => {}); });
  await waitFor(() => expect(reads).toBe(2));
  await act(() => result.current.logout());
  expect(result.current.me).toBeNull();
  await act(async () => { delayed.resolve(reply(firstAccount)); await reconnect; });
  expect(result.current.me).toBeNull();
  expect(result.current.logoutPending).toBe(false);
});

test('failed logout clears private adapters and must resolve before reconnect/sign-in', async () => {
  let logoutCount = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async path => {
    if (path === '/api/me') return reply(firstAccount);
    if (path === '/api/auth/logout') {
      if (++logoutCount === 1) throw new TypeError('Synthetic lost response');
      return reply(null, 204);
    }
    throw new Error('Unexpected synthetic request');
  });
  const client = new ApiClient(fetcher);
  const { result } = renderHook(() => useSession(client));
  await waitFor(() => expect(result.current.me).not.toBeNull());
  const oldScope = client.scopedTransport();
  await act(() => result.current.logout());
  expect(result.current.me).toBeNull();
  expect(result.current.logoutPending).toBe(true);
  expect(result.current.error).toContain('unconfirmed');
  await expect(oldScope.send({ method: 'PUT', path: '/api/resume', json: {} })).rejects.toThrow();
  await expect(result.current.refresh()).rejects.toThrow();
  await act(() => result.current.signIn('synthetic-credential'));
  expect(fetcher).toHaveBeenCalledTimes(2);
  await act(() => result.current.logout());
  expect(result.current.logoutPending).toBe(false);
  expect(result.current.me).toBeNull();
});
test('CSRF-invalid logout retry refreshes only the token and keeps private content cleared', async () => {
  let reads = 0;
  let logoutCount = 0;
  const freshAccount = { ...firstAccount, csrf_token: 'synthetic-fresh-csrf' };
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (path, init) => {
    if (path === '/api/me') return reply(++reads === 1 ? firstAccount : freshAccount);
    if (path === '/api/auth/logout') {
      logoutCount++;
      if (logoutCount === 1) {
        expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe(firstAccount.csrf_token);
        return reply({ error: { code: 'CSRF_INVALID' } }, 403);
      }
      expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe(freshAccount.csrf_token);
      return reply(null, 204);
    }
    throw new Error('Unexpected synthetic request');
  });
  const client = new ApiClient(fetcher);
  const { result } = renderHook(() => useSession(client));
  await waitFor(() => expect(result.current.me?.user.user_id).toBe(firstAccount.user.user_id));
  const oldScope = client.scopedTransport();
  await act(() => result.current.logout());
  expect(result.current.me).toBeNull();
  expect(result.current.logoutPending).toBe(true);
  expect(result.current.error).toContain('unconfirmed');
  await act(() => result.current.logout());
  expect(result.current.logoutPending).toBe(false);
  expect(result.current.me).toBeNull();
  expect(reads).toBe(2);
  expect(logoutCount).toBe(2);
  await expect(oldScope.send({ method: 'PUT', path: '/api/resume', json: {} })).rejects.toThrow();
  await expect(client.scopedTransport().send({ method: 'PUT', path: '/api/resume', json: {} })).rejects.toThrow();
});
test('expired logout completes locally after the server has already discarded the session', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async path => {
    if (path === '/api/me') return reply(firstAccount);
    if (path === '/api/auth/logout') return reply({ error: { code: 'SESSION_EXPIRED' } }, 401);
    throw new Error('Unexpected synthetic request');
  });
  const client = new ApiClient(fetcher);
  const { result } = renderHook(() => useSession(client));
  await waitFor(() => expect(result.current.me).not.toBeNull());
  await act(() => result.current.logout());
  expect(result.current.me).toBeNull();
  expect(result.current.logoutPending).toBe(false);
  expect(fetcher.mock.calls.filter(([path]) => path === '/api/me')).toHaveLength(1);
});
test('successful same-account sign-in gets a fresh scope while the old scope stays revoked', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async (path, init) => {
    if (path === '/api/me') return reply(firstAccount);
    if (path === '/api/auth/bootstrap') return reply({ csrf_token: 'synthetic-bootstrap-csrf' });
    if (path === '/api/auth/google') return reply({ user: firstAccount.user, csrf_token: firstAccount.csrf_token });
    if (path === '/api/auth/logout' && init?.method === 'POST') return reply(null, 204);
    if (path === '/api/resume') return reply({ revision: 0 });
    throw new Error('Unexpected synthetic request');
  });
  const client = new ApiClient(fetcher);
  const { result } = renderHook(() => useSession(client));
  await waitFor(() => expect(result.current.me).not.toBeNull());
  const oldScope = client.scopedTransport();

  await act(() => result.current.logout());
  await act(() => result.current.signIn('synthetic-credential'));
  const freshScope = client.scopedTransport();

  await expect(oldScope.send({ method: 'GET', path: '/api/resume' })).rejects.toThrow();
  await expect(freshScope.send({ method: 'GET', path: '/api/resume' })).resolves.toMatchObject({ status: 200 });
});
test('CSRF logout retry does not submit logout for a replacement account', async () => {
  let reads = 0;
  let logoutCount = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async path => {
    if (path === '/api/me') return reply(++reads === 1 ? firstAccount : secondAccount);
    if (path === '/api/auth/logout') {
      logoutCount++;
      return logoutCount === 1 ? reply({ error: { code: 'CSRF_INVALID' } }, 403) : reply(null, 204);
    }
    throw new Error('Unexpected synthetic request');
  });
  const client = new ApiClient(fetcher);
  const { result } = renderHook(() => useSession(client));
  await waitFor(() => expect(result.current.me).not.toBeNull());
  await act(() => result.current.logout());
  await act(() => result.current.logout());
  expect(result.current.me).toBeNull();
  expect(result.current.logoutPending).toBe(false);
  expect(reads).toBe(2);
  expect(logoutCount).toBe(1);
});
test('duplicate credential callbacks cause one exchange and /me confirms the account', async () => {
  const delayed = deferred<Response>();
  let reads = 0;
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async path => {
    if (path === '/api/me') return ++reads === 1 ? reply({ error: { code: 'AUTH_REQUIRED' } }, 401) : reply(firstAccount);
    if (path === '/api/auth/bootstrap') return delayed.promise;
    if (path === '/api/auth/google') return reply({ user: firstAccount.user, csrf_token: firstAccount.csrf_token });
    throw new Error('Unexpected synthetic request');
  });
  const client = new ApiClient(fetcher);
  const { result } = renderHook(() => useSession(client));
  await waitFor(() => expect(result.current.loading).toBe(false));
  let first!: Promise<void>, second!: Promise<void>;
  act(() => {
    first = result.current.signIn('synthetic-credential');
    second = result.current.signIn('synthetic-credential');
  });
  await act(async () => { delayed.resolve(reply({ csrf_token: 'synthetic-bootstrap' })); await Promise.all([first, second]); });
  expect(fetcher.mock.calls.filter(([path]) => path === '/api/auth/google')).toHaveLength(1);
  expect(result.current.me?.user.user_id).toBe(firstAccount.user.user_id);
  const exchange = fetcher.mock.calls.find(([path]) => path === '/api/auth/google')!;
  expect(new Headers(exchange[1]!.headers).get('X-CSRF-Token')).toBe('synthetic-bootstrap');
});
test('a verified account change revokes old feature adapters and advances the private mount', async () => {
  let reads = 0;
  const client = new ApiClient(vi.fn<typeof fetch>().mockImplementation(async () => reply(++reads === 1 ? firstAccount : secondAccount)));
  const { result } = renderHook(() => useSession(client));
  await waitFor(() => expect(result.current.me).not.toBeNull());
  const oldScope = client.scopedTransport();
  const previousEpoch = result.current.accountEpoch;
  await act(() => result.current.refresh());
  expect(result.current.accountEpoch).toBe(previousEpoch + 1);
  expect(result.current.me?.user.user_id).toBe(secondAccount.user.user_id);
  await expect(oldScope.send({ method: 'PUT', path: '/api/resume', json: {} })).rejects.toThrow();
});
test('malformed account data never unlocks the application or exposes the payload', async () => {
  const client = new ApiClient(vi.fn<typeof fetch>().mockImplementation(async () => reply({ user: 'synthetic-sensitive-diagnostic' })));
  const { result } = renderHook(() => useSession(client));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.me).toBeNull();
  expect(result.current.error).toContain('Could not reconnect');
  expect(result.current.error).not.toContain('synthetic-sensitive-diagnostic');
});
test.each([
  { ...firstAccount, csrf_token: '' },
  { ...firstAccount, resume_revision: -1 },
  { ...firstAccount, resume_revision: Number.MAX_SAFE_INTEGER + 1 },
  { ...firstAccount, has_matchable_resume: true },
  { ...firstAccount, user: { user_id: 'invalid', display_name: 'Synthetic' } },
])('rejects malformed session response %#', payload => {
  expect(() => accountResponse(payload)).toThrow('Invalid account response.');
});
