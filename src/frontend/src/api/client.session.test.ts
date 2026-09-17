import { ApiClient } from './client';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
test('a delayed 401 from the previous login cannot clear the current session', async () => {
  const delayed = deferred<Response>();
  const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => delayed.promise)
    .mockImplementation(async () => new Response('{}'));
  const client = new ApiClient(fetcher);
  const recovery = vi.fn(); client.onAuthenticationRequired(recovery);
  client.setCsrf('synthetic-old-session');
  const pending = client.send({ method: 'GET', path: '/api/jobs' });
  client.setCsrf('synthetic-current-session');
  delayed.resolve(new Response('{"error":{"code":"SESSION_EXPIRED"}}', { status: 401 }));
  await expect(pending).rejects.toThrow();
  expect(recovery).not.toHaveBeenCalled();
  await client.send({ method: 'PATCH', path: '/api/me', json: { display_name: 'Synthetic' } });
  expect(new Headers(fetcher.mock.calls[1]![1]!.headers).get('X-CSRF-Token')).toBe('synthetic-current-session');
});
test('CSRF_INVALID pauses private work and notifies the shell without replaying the write', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response(
    '{"error":{"code":"CSRF_INVALID"}}', { status: 403 },
  ));
  const client = new ApiClient(fetcher); client.setCsrf('synthetic-stale-csrf');
  const recovery = vi.fn(); client.onAuthenticationRequired(recovery);
  const response = await client.send({ method: 'PATCH', path: '/api/me', json: { display_name: 'Synthetic' } });
  expect(response.status).toBe(403);
  expect(recovery).toHaveBeenCalledWith('CSRF_INVALID');
  await expect(client.send({ method: 'PATCH', path: '/api/me', json: {} })).rejects.toThrow();
  expect(fetcher).toHaveBeenCalledOnce();
});

test('a delayed successful body is discarded after private state is cleared', async () => {
  const body = deferred<string>();
  const response = new Response('{}');
  vi.spyOn(response, 'text').mockImplementation(() => body.promise);
  const client = new ApiClient(vi.fn<typeof fetch>().mockResolvedValue(response));
  client.setCsrf('synthetic-session');
  const pending = client.send({ method: 'GET', path: '/api/resume' });
  await Promise.resolve();
  client.clearSession();
  body.resolve('{"content":{"skills":["synthetic-private-content"]}}');
  await expect(pending).rejects.toThrow();
});
test('revoked account adapters cannot submit scheduled retries under another account', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response('{}'));
  const client = new ApiClient(fetcher); client.setCsrf('synthetic-first');
  const oldAccount = client.scopedTransport();
  client.clearSession(); client.setCsrf('synthetic-second'); client.resumePrivateRequests();
  await expect(oldAccount.send({ method: 'PUT', path: '/api/resume', json: { content: 'synthetic draft' } })).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
  await client.scopedTransport().send({ method: 'PUT', path: '/api/resume', json: {} });
  expect(new Headers(fetcher.mock.calls[0]![1]!.headers).get('X-CSRF-Token')).toBe('synthetic-second');
});
test('same-account CSRF rotation retains the feature adapter and caller idempotency key', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response('{}'));
  const client = new ApiClient(fetcher); client.setCsrf('synthetic-first');
  const account = client.scopedTransport();
  client.setCsrf(null); client.setCsrf('synthetic-rotated');
  await account.send({ method: 'PUT', path: '/api/resume', json: {}, headers: { 'Idempotency-Key': 'same-operation' } });
  expect(new Headers(fetcher.mock.calls[0]![1]!.headers).get('Idempotency-Key')).toBe('same-operation');
});
test('unrelated 403 does not discard a valid session', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response('{"error":{"code":"FORBIDDEN"}}', { status: 403 }));
  const client = new ApiClient(fetcher); client.setCsrf('synthetic-session');
  const recovery = vi.fn(); client.onAuthenticationRequired(recovery);
  expect((await client.send({ method: 'PATCH', path: '/api/me', json: {} })).status).toBe(403);
  expect(recovery).not.toHaveBeenCalled();
  await client.send({ method: 'PATCH', path: '/api/me', json: {} });
  expect(fetcher).toHaveBeenCalledTimes(2);
});
test('already-aborted requests are not sent', async () => {
  const fetcher = vi.fn<typeof fetch>();
  const controller = new AbortController(); controller.abort();
  await expect(new ApiClient(fetcher).send({ method: 'GET', path: '/api/me', signal: controller.signal })).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});

test('private calls stay blocked during identity exchange even after new CSRF arrives', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => new Response('{}'));
  const client = new ApiClient(fetcher); client.setCsrf('synthetic-old-session');
  const scope = client.scopedTransport();
  client.pausePrivateRequests(); client.setCsrf('synthetic-new-session');
  await expect(scope.send({ method: 'PUT', path: '/api/resume', json: {} })).rejects.toThrow();
  await expect(client.send({ method: 'GET', path: '/api/jobs' })).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
  await client.send({ method: 'GET', path: '/api/me' });
  client.resumePrivateRequests();
  await scope.send({ method: 'PUT', path: '/api/resume', json: {} });
  expect(fetcher).toHaveBeenCalledTimes(2);
});
