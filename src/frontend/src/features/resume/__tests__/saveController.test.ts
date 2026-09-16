import { beforeEach, describe, expect, it } from 'vitest';
import { createResumeApi } from '../api/resumeApi';
import {
  createFakeTransport,
  jsonResponse,
  networkFailure,
  type FakeTransport,
} from '../fixtures/fakeTransport';
import {
  errorEnvelope,
  syntheticCleanedContent,
  syntheticPreparedContent,
  syntheticSavedProfile,
} from '../fixtures/resumeFixtures';
import { ResumeSaveController, type SaveStatus } from '../model/saveController';

/**
 * Every wait is injected, so the 3/6/12 second schedule is asserted from
 * controller.lastWaits without any test actually sleeping.
 */
function build() {
  const transport: FakeTransport = createFakeTransport();
  const statuses: SaveStatus[] = [];
  let keyCounter = 0;
  const controller = new ResumeSaveController({
    api: createResumeApi(transport),
    sleep: async () => {},
    keyFactory: () => `key-${(keyCounter += 1)}`,
    onStatusChange: (status) => statuses.push(status),
  });
  return { transport, controller, statuses };
}

const savedOk = (revision = 5, changed = true) =>
  jsonResponse(200, { operation_id: 'op-1', result_revision: revision, changed });

const profileOk = () => jsonResponse(200, syntheticSavedProfile);

const putRequests = (t: FakeTransport) => t.requests.filter((r) => r.method === 'PUT');
const getRequests = (t: FakeTransport) => t.requests.filter((r) => r.method === 'GET');

let ctx: ReturnType<typeof build>;
beforeEach(() => {
  ctx = build();
});

describe('successful saves', () => {
  it('sends expected_revision, content and an Idempotency-Key, and reports the new revision', async () => {
    ctx.transport.queue(savedOk(5, true));
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);

    expect(outcome.status).toMatchObject({ kind: 'SAVED', revision: 5, changed: true });
    const put = putRequests(ctx.transport)[0];
    expect(put?.path).toBe('/api/resume');
    expect(put?.json).toEqual({ expected_revision: 4, content: syntheticPreparedContent });
    expect(put?.headers?.['Idempotency-Key']).toBe('key-1');
  });

  it('does not re-read the profile when the first attempt succeeded', async () => {
    ctx.transport.queue(savedOk());
    await ctx.controller.save(syntheticPreparedContent, 4);
    expect(getRequests(ctx.transport)).toHaveLength(0);
  });

  it('reports an unchanged save as a no-op rather than inventing a new revision', async () => {
    ctx.transport.queue(savedOk(4, false));
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.status).toMatchObject({ kind: 'SAVED', revision: 4, changed: false });
  });

  it('releases the idempotency key once a save settles', async () => {
    ctx.transport.queue(savedOk());
    await ctx.controller.save(syntheticPreparedContent, 4);
    expect(ctx.controller.pendingKey).toBeNull();
  });

  it('never attaches auth headers itself — that belongs to the shared client', async () => {
    ctx.transport.queue(savedOk());
    await ctx.controller.save(syntheticPreparedContent, 4);
    const headers = putRequests(ctx.transport)[0]?.headers ?? {};
    expect(Object.keys(headers)).toEqual(['Idempotency-Key']);
  });
});

describe('lost response (unknown outcome)', () => {
  it('replays the SAME idempotency key instead of starting a new attempt', async () => {
    ctx.transport.queue(networkFailure(), savedOk(5, true), profileOk());
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);

    expect(outcome.status.kind).toBe('SAVED');
    const keys = putRequests(ctx.transport).map((r) => r.headers?.['Idempotency-Key']);
    expect(keys).toEqual(['key-1', 'key-1']);
  });

  it('re-reads the current profile after a retry succeeded, in case it was a replay', async () => {
    ctx.transport.queue(networkFailure(), savedOk(5, true), profileOk());
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);

    expect(getRequests(ctx.transport).map((r) => r.path)).toEqual(['/api/resume']);
    expect(outcome.profile).toEqual(syntheticSavedProfile);
    expect(outcome.status).toMatchObject({ refreshedFromServer: true });
  });

  it('follows the 3/6/12 second schedule and then stops, rather than polling forever', async () => {
    ctx.transport.queue(networkFailure(), networkFailure(), networkFailure(), networkFailure());
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);

    expect(ctx.controller.lastWaits).toEqual([3, 6, 12]);
    expect(putRequests(ctx.transport)).toHaveLength(4);
    expect(outcome.status).toMatchObject({ kind: 'OUTCOME_UNKNOWN', reason: 'NO_RESPONSE' });
  });

  it('does not claim the resume was left unchanged when the outcome is unknown', async () => {
    ctx.transport.queue(networkFailure(), networkFailure(), networkFailure(), networkFailure());
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    const message = (outcome.status as { message: string }).message;
    expect(message).not.toMatch(/not saved|unchanged|failed/i);
    expect(message).toMatch(/could not confirm/i);
  });

  it('keeps the key after an unknown outcome so a manual retry is still one attempt', async () => {
    ctx.transport.queue(networkFailure(), networkFailure(), networkFailure(), networkFailure());
    await ctx.controller.save(syntheticPreparedContent, 4);
    expect(ctx.controller.pendingKey).toBe('key-1');

    ctx.transport.queue(savedOk(5, true), profileOk());
    await ctx.controller.save(syntheticPreparedContent, 4);
    const keys = putRequests(ctx.transport).map((r) => r.headers?.['Idempotency-Key']);
    expect(new Set(keys)).toEqual(new Set(['key-1']));
  });

  it('treats a 504 as unknown rather than as a definite failure', async () => {
    ctx.transport.queue(
      jsonResponse(504, errorEnvelope('PROCESSING_TIMEOUT', 'timed out', { retryable: true })),
      savedOk(5, true),
      profileOk(),
    );
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.status.kind).toBe('SAVED');
    expect(putRequests(ctx.transport).map((r) => r.headers?.['Idempotency-Key'])).toEqual([
      'key-1',
      'key-1',
    ]);
  });

  it('treats a 500 as unknown and resolves it by replay', async () => {
    ctx.transport.queue(
      jsonResponse(500, errorEnvelope('INTERNAL_ERROR', 'boom')),
      savedOk(5, true),
      profileOk(),
    );
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.status.kind).toBe('SAVED');
  });
});

describe('controlled overload', () => {
  it('reports 503 PROCESSING_BUSY as nothing saved, because no operation row was created', async () => {
    const busy = () =>
      jsonResponse(503, errorEnvelope('PROCESSING_BUSY', 'busy', { retryable: true }), {
        'Retry-After': '3',
      });
    ctx.transport.queue(busy(), busy(), busy(), busy());
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);

    expect(outcome.status).toMatchObject({
      kind: 'FAILED',
      code: 'PROCESSING_BUSY',
      retryable: true,
    });
    expect((outcome.status as { message: string }).message).toMatch(/nothing was saved/i);
  });

  it('honours a server Retry-After instead of the default schedule', async () => {
    const busy = () =>
      jsonResponse(503, errorEnvelope('PROCESSING_BUSY', 'busy', { retryable: true }), {
        'Retry-After': '7',
      });
    ctx.transport.queue(busy(), savedOk(5, true), profileOk());
    await ctx.controller.save(syntheticPreparedContent, 4);
    expect(ctx.controller.lastWaits).toEqual([7]);
  });

  it('recovers when the slot frees up, reusing the same key', async () => {
    ctx.transport.queue(
      jsonResponse(503, errorEnvelope('PROCESSING_BUSY', 'busy', { retryable: true })),
      savedOk(5, true),
      profileOk(),
    );
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.status.kind).toBe('SAVED');
    expect(putRequests(ctx.transport).map((r) => r.headers?.['Idempotency-Key'])).toEqual([
      'key-1',
      'key-1',
    ]);
  });

  it('reports a still-processing save as unconfirmed, not as failed', async () => {
    const inProgress = () =>
      jsonResponse(409, errorEnvelope('SAVE_IN_PROGRESS', 'in progress', { retryable: true }), {
        'Retry-After': '3',
      });
    ctx.transport.queue(inProgress(), inProgress(), inProgress(), inProgress());
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.status).toMatchObject({
      kind: 'OUTCOME_UNKNOWN',
      reason: 'STILL_PROCESSING',
    });
  });
});

describe('privacy re-check', () => {
  it('surfaces the cleaned replacement draft and saves nothing', async () => {
    ctx.transport.queue(
      jsonResponse(
        422,
        errorEnvelope('REVIEW_REQUIRED', 'privacy check changed your content', {
          details: { draft: syntheticCleanedContent },
        }),
      ),
    );
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);

    expect(outcome.status).toMatchObject({ kind: 'REVIEW_REQUIRED' });
    expect((outcome.status as { cleanedContent: unknown }).cleanedContent).toEqual(
      syntheticCleanedContent,
    );
    expect((outcome.status as { message: string }).message).toMatch(/nothing has been saved/i);
  });

  it('rotates the key so the reconfirmation is a new logical attempt', async () => {
    ctx.transport.queue(
      jsonResponse(
        422,
        errorEnvelope('REVIEW_REQUIRED', 'changed', {
          details: { draft: syntheticCleanedContent },
        }),
      ),
      savedOk(5, true),
    );
    await ctx.controller.save(syntheticPreparedContent, 4);
    expect(ctx.controller.pendingKey).toBeNull();

    await ctx.controller.save(syntheticCleanedContent, 4);
    const keys = putRequests(ctx.transport).map((r) => r.headers?.['Idempotency-Key']);
    expect(keys).toEqual(['key-1', 'key-2']);
  });

  it('fails safely when the cleaned draft cannot be read from the envelope', async () => {
    ctx.transport.queue(
      jsonResponse(422, errorEnvelope('REVIEW_REQUIRED', 'changed', { details: {} })),
    );
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.status).toMatchObject({ kind: 'FAILED', code: 'REVIEW_REQUIRED' });
  });
});

describe('stale revision conflicts', () => {
  it('re-reads the current profile and reports that nothing was overwritten', async () => {
    ctx.transport.queue(
      jsonResponse(409, errorEnvelope('REVISION_CONFLICT', 'stale', { details: {} })),
      profileOk(),
    );
    const outcome = await ctx.controller.save(syntheticPreparedContent, 2);

    expect(outcome.status).toMatchObject({
      kind: 'REVISION_CONFLICT',
      currentRevision: syntheticSavedProfile.revision,
    });
    expect((outcome.status as { message: string }).message).toMatch(/nothing was overwritten/i);
    expect(outcome.profile).toEqual(syntheticSavedProfile);
  });

  it('rotates the key, since a retry must carry a different expected_revision', async () => {
    ctx.transport.queue(
      jsonResponse(409, errorEnvelope('REVISION_CONFLICT', 'stale')),
      profileOk(),
      savedOk(5, true),
    );
    await ctx.controller.save(syntheticPreparedContent, 2);
    await ctx.controller.save(syntheticPreparedContent, 4);
    expect(putRequests(ctx.transport).map((r) => r.headers?.['Idempotency-Key'])).toEqual([
      'key-1',
      'key-2',
    ]);
  });

  it('falls back to the revision in the error envelope when the refresh fails', async () => {
    ctx.transport.queue(
      jsonResponse(409, errorEnvelope('REVISION_CONFLICT', 'stale', {
        details: { current_revision: 9 },
      })),
      networkFailure(),
    );
    const outcome = await ctx.controller.save(syntheticPreparedContent, 2);
    expect(outcome.status).toMatchObject({ currentRevision: 9 });
  });
});

describe('other definite outcomes', () => {
  it('keeps the draft and the key when the session expired', async () => {
    ctx.transport.queue(
      jsonResponse(401, errorEnvelope('SESSION_EXPIRED', 'session expired')),
    );
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.status.kind).toBe('AUTH_REQUIRED');
    expect((outcome.status as { message: string }).message).toMatch(/draft is still here/i);
    expect(ctx.controller.pendingKey).toBe('key-1');
  });

  it('does not retry a deterministic validation failure', async () => {
    ctx.transport.queue(
      jsonResponse(422, errorEnvelope('INVALID_CONTENT', 'too many skills')),
    );
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.status).toMatchObject({ kind: 'FAILED', retryable: false });
    expect(putRequests(ctx.transport)).toHaveLength(1);
    expect(ctx.controller.lastWaits).toEqual([]);
    // The server stored a terminal result against this key, so the next attempt needs a new one.
    expect(ctx.controller.pendingKey).toBeNull();
  });

  it('reports an idempotency conflict without overwriting anything', async () => {
    ctx.transport.queue(
      jsonResponse(409, errorEnvelope('IDEMPOTENCY_CONFLICT', 'mismatch')),
      profileOk(),
    );
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.status).toMatchObject({ kind: 'FAILED', code: 'IDEMPOTENCY_CONFLICT' });
    expect((outcome.status as { message: string }).message).toMatch(/nothing was overwritten/i);
    expect(outcome.profile).toEqual(syntheticSavedProfile);
  });
});

describe('resolveOperation', () => {
  it('reports a succeeded operation and refreshes the profile', async () => {
    ctx.transport.queue(
      jsonResponse(200, {
        operation_id: 'op-1',
        state: 'SUCCEEDED',
        result_revision: 5,
        failure_code: null,
      }),
      profileOk(),
    );
    const outcome = await ctx.controller.resolveOperation('op-1');
    expect(outcome.status).toMatchObject({ kind: 'SAVED', revision: 5 });
    expect(outcome.profile).toEqual(syntheticSavedProfile);
  });

  it('backs off while the operation is still processing, then stops', async () => {
    const processing = () =>
      jsonResponse(200, {
        operation_id: 'op-1',
        state: 'PROCESSING',
        result_revision: null,
        failure_code: null,
      });
    ctx.transport.queue(processing(), processing(), processing(), processing());
    const outcome = await ctx.controller.resolveOperation('op-1');
    expect(ctx.controller.lastWaits).toEqual([3, 6, 12]);
    expect(outcome.status).toMatchObject({ kind: 'OUTCOME_UNKNOWN', reason: 'STILL_PROCESSING' });
  });

  it('reads the current profile when the operation record has expired', async () => {
    ctx.transport.queue(
      jsonResponse(404, errorEnvelope('OPERATION_EXPIRED', 'expired')),
      profileOk(),
    );
    const outcome = await ctx.controller.resolveOperation('op-1');
    expect(outcome.status).toMatchObject({ kind: 'FAILED', code: 'OPERATION_EXPIRED' });
    expect(outcome.profile).toEqual(syntheticSavedProfile);
  });

  it('reports a failed operation as retryable with the draft intact', async () => {
    ctx.transport.queue(
      jsonResponse(200, {
        operation_id: 'op-1',
        state: 'FAILED',
        result_revision: null,
        failure_code: 'PROCESS_INTERRUPTED',
      }),
    );
    const outcome = await ctx.controller.resolveOperation('op-1');
    expect(outcome.status).toMatchObject({ kind: 'FAILED', code: 'PROCESS_INTERRUPTED' });
  });
});

describe('replay recovery across user actions', () => {
  it('refreshes current content on a manual retry after automatic retries are exhausted', async () => {
    ctx.transport.queue(networkFailure(), networkFailure(), networkFailure(), networkFailure());
    await ctx.controller.save(syntheticPreparedContent, 4);
    ctx.transport.queue(savedOk(5), profileOk());
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.profile).toEqual(syntheticSavedProfile);
    expect(getRequests(ctx.transport).map(r => r.path)).toEqual(['/api/resume']);
  });

  it('requires a refresh when a replay succeeds but the current profile cannot be read', async () => {
    ctx.transport.queue(networkFailure(), savedOk(5), networkFailure());
    const outcome = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(outcome.status.kind).toBe('SAVED_REFRESH_REQUIRED');
    expect(outcome.profile).toBeUndefined();
    expect(ctx.controller.pendingKey).toBe('key-1');
    ctx.transport.queue(savedOk(5), profileOk());
    const recovered = await ctx.controller.save(syntheticPreparedContent, 4);
    expect(recovered.profile).toEqual(syntheticSavedProfile);
    expect(putRequests(ctx.transport).map(r => r.headers?.['Idempotency-Key'])).toEqual(['key-1', 'key-1', 'key-1']);
  });

  it('does not report a resolved operation as current content when refresh fails', async () => {
    ctx.transport.queue(jsonResponse(200, { operation_id: 'op', state: 'SUCCEEDED', result_revision: 5, failure_code: null }), networkFailure());
    expect((await ctx.controller.resolveOperation('op')).status.kind).toBe('SAVED_REFRESH_REQUIRED');
  });
});
