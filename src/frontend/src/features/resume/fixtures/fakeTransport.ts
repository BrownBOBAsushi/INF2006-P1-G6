import type { HttpRequest, HttpResponse, HttpTransport } from '../api/httpTransport';

/**
 * A scripted HttpTransport. Each queued step is consumed in order, so a test can
 * describe a whole retry sequence declaratively:
 *
 *   queue(networkFailure(), busy(), jsonResponse(200, {...}))
 *
 * It records every request, which is how the tests assert that the Idempotency-Key is
 * reused across retries and that no auth headers or extra content fields are sent.
 */

export type TransportStep =
  | { type: 'response'; status: number; body: unknown; headers?: Record<string, string> }
  | { type: 'reject'; error: unknown };

export interface FakeTransport extends HttpTransport {
  readonly requests: HttpRequest[];
  /** Parsed Idempotency-Key headers in the order they were sent. */
  readonly idempotencyKeys: (string | undefined)[];
  queue(...steps: TransportStep[]): void;
  /** Step used when the queue is exhausted. Defaults to a 500. */
  setFallback(step: TransportStep): void;
}

export function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): TransportStep {
  return { type: 'response', status, body, headers };
}

export function networkFailure(message = 'network down'): TransportStep {
  return { type: 'reject', error: new TypeError(message) };
}

export function createFakeTransport(): FakeTransport {
  const steps: TransportStep[] = [];
  const requests: HttpRequest[] = [];
  let fallback: TransportStep = jsonResponse(500, {
    error: {
      code: 'INTERNAL_ERROR',
      message: 'unscripted request',
      request_id: 'fake',
      retryable: false,
    },
  });

  const transport: FakeTransport = {
    requests,
    get idempotencyKeys() {
      return requests.map((r) => r.headers?.['Idempotency-Key']);
    },
    queue(...next: TransportStep[]) {
      steps.push(...next);
    },
    setFallback(step: TransportStep) {
      fallback = step;
    },
    async send(request: HttpRequest): Promise<HttpResponse> {
      requests.push(request);
      const step = steps.shift() ?? fallback;
      if (step.type === 'reject') throw step.error;
      const headers = step.headers ?? {};
      return {
        status: step.status,
        body: step.body,
        header(name: string) {
          const key = Object.keys(headers).find((h) => h.toLowerCase() === name.toLowerCase());
          return key === undefined ? null : (headers[key] as string);
        },
      };
    },
  };

  return transport;
}
