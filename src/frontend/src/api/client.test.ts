import { ApiClient } from './client';

function response(body: unknown, status = 200, headers = {}) {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers });
}
test('same-origin cookies, no-store, CSRF rotation, JSON and multipart use Nasya transport', async () => {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => response({ ok: true }, 200, { 'Retry-After': '3' }));
  const client = new ApiClient(fetcher);
  client.setCsrf('first');
  await client.send({ method: 'PUT', path: '/api/resume', json: { expected_revision: 0 }, headers: { 'Idempotency-Key': 'stable-key', 'X-CSRF-Token': 'wrong' } });
  let init = fetcher.mock.calls[0]![1]!;
  expect(init.credentials).toBe('same-origin');
  expect(init.cache).toBe('no-store');
  expect(init.redirect).toBe('error');
  expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('first');
  expect(new Headers(init.headers).get('Idempotency-Key')).toBe('stable-key');
  expect(new Headers(init.headers).get('Content-Type')).toBe('application/json');
  client.setCsrf('rotated');
  const file = new FormData(); file.append('file', new Blob(['synthetic']), 'synthetic.pdf');
  const result = await client.send({ method: 'POST', path: '/api/resume/prepare', formData: file });
  init = fetcher.mock.calls[1]![1]!;
  expect(init.body).toBe(file);
  expect(new Headers(init.headers).has('Content-Type')).toBe(false);
  expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('rotated');
  expect(result.header('retry-after')).toBe('3');
});
test('invokes a receiver-sensitive fetcher without the ApiClient receiver', async () => {
  const receiverSensitive: typeof fetch = function (this: unknown) {
    if (this !== undefined) throw new TypeError('Illegal invocation');
    return Promise.resolve(response({ ok: true }));
  };
  const client = new ApiClient(receiverSensitive);
  await expect(client.send({ method: 'GET', path: '/api/me' })).resolves.toMatchObject({ status: 200 });
});
test.each(['https://example.com/api/me', '//example.com/api/me', '/api/../outside', '/api/../../api/../outside'])('rejects API path escape %s before sending', async path => {
  const fetcher = vi.fn<typeof fetch>();
  await expect(new ApiClient(fetcher).send({ method: 'GET', path })).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});
test('unsafe requests need CSRF; expired-session logout still reaches server', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(null, 204));
  const client = new ApiClient(fetcher);
  await expect(client.send({ method: 'PATCH', path: '/api/me', json: {} })).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
  expect((await client.send({ method: 'POST', path: '/api/auth/logout' })).status).toBe(204);
});
test('401 notifies shell and clears token without converting feature HTTP outcomes into throws', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response({ error: { code: 'SESSION_EXPIRED' } }, 401));
  const client = new ApiClient(fetcher); client.setCsrf('session-token');
  const expired = vi.fn(); client.onAuthenticationRequired(expired);
  expect((await client.send({ method: 'GET', path: '/api/me' })).status).toBe(401);
  expect(expired).toHaveBeenCalledOnce();
  await expect(client.send({ method: 'PUT', path: '/api/resume', json: {} })).rejects.toThrow();
});
test('network failures remain unknown and are never automatically retried', async () => {
  const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError('network'));
  const client = new ApiClient(fetcher); client.setCsrf('session-token');
  await expect(client.send({ method: 'PUT', path: '/api/resume', json: {} })).rejects.toThrow();
  expect(fetcher).toHaveBeenCalledOnce();
});
test('client timeout aborts in-flight request without fabricating HTTP failure', async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn<typeof fetch>().mockImplementation((_url, init) => new Promise((_resolve, reject) => {
    init!.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
  }));
  try {
    const client = new ApiClient(fetcher, 100); client.setCsrf('session-token');
    const result = client.send({ method: 'PUT', path: '/api/resume', json: {} });
    const assertion = expect(result).rejects.toThrow('Aborted');
    await vi.advanceTimersByTimeAsync(100); await assertion;
    expect(fetcher).toHaveBeenCalledOnce();
  } finally { vi.useRealTimers(); }
});
test('non-JSON gateway errors retain status and do not expose raw response', async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('private server diagnostic', { status: 502 }));
  const result = await new ApiClient(fetcher).send({ method: 'GET', path: '/api/me' });
  expect(result.status).toBe(502); expect(result.body).toBeNull();
});
