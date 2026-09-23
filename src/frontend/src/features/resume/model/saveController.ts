import {
  ERROR_CODES,
  RETRY_BACKOFF_SECONDS,
  type ResumeContent,
  type ResumeProfileResponse,
} from '../api/contractTypes';
import { ApiError, isApiError, isUnknownOutcome } from '../api/errors';
import type { ResumeApiPort } from '../api/resumeApi';
import {
  attemptForPayload,
  createIdempotencyKey,
  type KeyFactory,
  type SaveAttempt,
} from './idempotency';
import { contentSignature } from './serialize';

/**
 * Drives PUT /api/resume through every outcome the contract defines.
 *
 * The hard part is not the happy path, it is being honest about what is known:
 *
 *   - a 503 PROCESSING_BUSY means nothing happened (no operation row was created),
 *   - a lost response means the outcome is genuinely unknown and must be resolved by
 *     replaying the same idempotency key, never by guessing,
 *   - a success that arrived after a retry may be a replay of an earlier commit, so
 *     the current profile is re-read rather than assuming the local draft is what the
 *     server holds.
 *
 * All waiting goes through an injected `sleep` so tests assert the real 3/6/12 second
 * schedule without waiting 21 seconds.
 */

export type UnknownReason = 'NO_RESPONSE' | 'STILL_PROCESSING';

export type SaveStatus =
  | { kind: 'IDLE' }
  | { kind: 'SAVING'; attempt: number }
  | {
      kind: 'WAITING_TO_RETRY';
      attempt: number;
      waitSeconds: number;
      reason: 'BUSY' | 'IN_PROGRESS' | 'NO_RESPONSE';
    }
  | { kind: 'SAVED'; revision: number; changed: boolean; refreshedFromServer: boolean; currentRevision?: number; profileDeleted?: boolean }
  | { kind: 'DELETED'; revision: number; message: string }
  | { kind: 'SAVED_REFRESH_REQUIRED'; message: string }
  | { kind: 'REVIEW_REQUIRED'; cleanedContent: ResumeContent; message: string }
  | { kind: 'REVISION_CONFLICT'; currentRevision: number | null; message: string }
  | { kind: 'AUTH_REQUIRED'; message: string }
  | { kind: 'OUTCOME_UNKNOWN'; reason: UnknownReason; message: string }
  | { kind: 'FAILED'; code: string; message: string; retryable: boolean };

export interface SaveOutcome {
  status: SaveStatus;
  /**
   * Present when the controller re-read GET /api/resume while resolving this outcome.
   * `null` means the server reports no profile. `undefined` means it was not read.
   */
  profile?: ResumeProfileResponse | null;
}

export interface SaveControllerOptions {
  api: ResumeApiPort;
  /** Injected for tests. Default waits real seconds. */
  sleep?: (seconds: number) => Promise<void>;
  keyFactory?: KeyFactory;
  onStatusChange?: (status: SaveStatus) => void;
}

const AUTH_CODES = new Set<string>([ERROR_CODES.AUTH_REQUIRED, ERROR_CODES.SESSION_EXPIRED]);

function defaultSleep(seconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

/** Pull the standardized cleaned replacement draft from a REVIEW_REQUIRED envelope. */
export function extractCleanedContent(details: Record<string, unknown>): ResumeContent | null {
  const candidate = details.cleaned_draft;
  if (typeof candidate === 'object' && candidate !== null && Array.isArray((candidate as Record<string, unknown>).skills)) {
    return candidate as ResumeContent;
  }
  return null;
}

function currentRevisionFromDetails(details: Record<string, unknown>): number | null {
  const value = details.current_revision;
  if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0) return value;
  return null;
}

export class ResumeSaveController {
  private readonly api: ResumeApiPort;
  private readonly sleep: (seconds: number) => Promise<void>;
  private readonly keyFactory: KeyFactory;
  private readonly onStatusChange: ((status: SaveStatus) => void) | undefined;

  /** The in-flight logical attempt. Retained across network retries, cleared on terminal states. */
  private attempt: SaveAttempt | null = null;
  /** Waits performed, in seconds, for the current save() call. Exposed for tests/evidence. */
  private waits: number[] = [];

  constructor(options: SaveControllerOptions) {
    this.api = options.api;
    this.sleep = options.sleep ?? defaultSleep;
    this.keyFactory = options.keyFactory ?? createIdempotencyKey;
    this.onStatusChange = options.onStatusChange;
  }

  /** Idempotency key currently held, or null when the next save starts a new attempt. */
  get pendingKey(): string | null {
    return this.attempt?.key ?? null;
  }

  /** Backoff waits performed during the most recent save(), in seconds. */
  get lastWaits(): readonly number[] {
    return this.waits;
  }

  /**
   * Discards the held idempotency key so the next save is a new logical attempt.
   * Call this after the student edits the draft following a conflict.
   */
  startNewAttempt(): void {
    this.attempt = null;
  }

  private emit(status: SaveStatus): SaveStatus {
    this.onStatusChange?.(status);
    return status;
  }

  private async refreshProfile(): Promise<ResumeProfileResponse | null | undefined> {
    try {
      return await this.api.getProfile();
    } catch {
      // A failed refresh must not turn a known save outcome into an error.
      return undefined;
    }
  }

  async save(content: ResumeContent, expectedRevision: number): Promise<SaveOutcome> {
    const signature = contentSignature(content);
    const previousAttempt = this.attempt;
    this.attempt = attemptForPayload(this.attempt, expectedRevision, signature, this.keyFactory);
    const reusingKey = previousAttempt === this.attempt;
    const key = this.attempt.key;
    this.waits = [];

    let networkAttempt = 0;
    let backoffIndex = 0;

    const waitThenContinue = async (
      reason: 'BUSY' | 'IN_PROGRESS' | 'NO_RESPONSE',
      serverRetryAfter: number | null,
    ): Promise<boolean> => {
      if (backoffIndex >= RETRY_BACKOFF_SECONDS.length) return false;
      const waitSeconds = serverRetryAfter ?? (RETRY_BACKOFF_SECONDS[backoffIndex] as number);
      backoffIndex += 1;
      this.emit({ kind: 'WAITING_TO_RETRY', attempt: networkAttempt, waitSeconds, reason });
      this.waits.push(waitSeconds);
      await this.sleep(waitSeconds);
      return true;
    };

    for (;;) {
      networkAttempt += 1;
      this.emit({ kind: 'SAVING', attempt: networkAttempt });

      try {
        const result = await this.api.save(
          { expected_revision: expectedRevision, content },
          key,
        );

        // A success on a later network attempt may be a replay of a commit whose
        // response was lost. The contract requires reading the current profile rather
        // than trusting the replayed response to describe current server content.
        const possiblyReplayed = reusingKey || networkAttempt > 1;
        const profile = possiblyReplayed ? await this.refreshProfile() : undefined;

        if (possiblyReplayed && profile === undefined) {
          return { status: this.emit({
            kind: 'SAVED_REFRESH_REQUIRED',
            message: 'Your earlier save completed, but the current resume could not be loaded. Your draft is still here. Retry to check the current version.',
          }) };
        }
        this.attempt = null;
        return {
          status: this.emit({
            kind: 'SAVED',
            revision: result.result_revision,
            changed: result.changed,
            refreshedFromServer: possiblyReplayed && profile !== undefined,
            currentRevision: profile?.revision,
            profileDeleted: profile === null,
          }),
          ...(profile !== undefined ? { profile } : {}),
        };
      } catch (caught) {
        if (isUnknownOutcome(caught)) {
          // Outcome genuinely unknown. Replaying the same key is safe: the server
          // either returns the stored terminal result or performs the save once.
          if (await waitThenContinue('NO_RESPONSE', null)) continue;
          return {
            status: this.emit({
              kind: 'OUTCOME_UNKNOWN',
              reason: 'NO_RESPONSE',
              message:
                'We could not confirm whether your resume was saved. Your draft is still here. Retry to check safely — retrying cannot save it twice.',
            }),
          };
        }

        if (!isApiError(caught)) throw caught;
        const error: ApiError = caught;

        switch (error.code) {
          case ERROR_CODES.SAVE_IN_PROGRESS: {
            if (await waitThenContinue('IN_PROGRESS', error.retryAfterSeconds)) continue;
            return {
              status: this.emit({
                kind: 'OUTCOME_UNKNOWN',
                reason: 'STILL_PROCESSING',
                message:
                  'This save is still being processed. Your draft is still here. Retry to check the result.',
              }),
            };
          }

          case ERROR_CODES.PROCESSING_BUSY: {
            if (await waitThenContinue('BUSY', error.retryAfterSeconds)) continue;
            // Busy is a controlled rejection: no operation row was created, so we know
            // nothing was saved. The key is retained so a manual retry stays one attempt.
            return {
              status: this.emit({
                kind: 'FAILED',
                code: error.code,
                message:
                  'Resume processing is busy. Nothing was saved and your draft is unchanged. Try again shortly.',
                retryable: true,
              }),
            };
          }

          case ERROR_CODES.REVIEW_REQUIRED: {
            const cleaned = extractCleanedContent(error.details);
            // A new confirmation is a new logical attempt.
            this.attempt = null;
            if (cleaned === null) {
              return {
                status: this.emit({
                  kind: 'FAILED',
                  code: error.code,
                  message:
                    'The privacy check changed your resume, but the corrected version could not be read. Re-upload or edit your details and try again.',
                  retryable: false,
                }),
              };
            }
            return {
              status: this.emit({
                kind: 'REVIEW_REQUIRED',
                cleanedContent: cleaned,
                message:
                  'The privacy check removed personal details from what you submitted. Review the corrected version below, then confirm again. Nothing has been saved yet.',
              }),
            };
          }

          case ERROR_CODES.REVISION_CONFLICT: {
            // expected_revision is part of the server payload hash, so any retry after
            // this is necessarily a different payload and needs a fresh key.
            this.attempt = null;
            const profile = await this.refreshProfile();
            const revisionFromDetails = currentRevisionFromDetails(error.details);
            return {
              status: this.emit({
                kind: 'REVISION_CONFLICT',
                currentRevision:
                  profile !== undefined && profile !== null ? profile.revision : revisionFromDetails,
                message:
                  'Your resume was changed somewhere else after this page loaded. Nothing was overwritten. Review the current version before saving again.',
              }),
              ...(profile !== undefined ? { profile } : {}),
            };
          }

          case ERROR_CODES.IDEMPOTENCY_CONFLICT: {
            this.attempt = null;
            const profile = await this.refreshProfile();
            return {
              status: this.emit({
                kind: 'FAILED',
                code: error.code,
                message:
                  'This save could not be matched to your earlier attempt. Nothing was overwritten. Check the current version and confirm again.',
                retryable: false,
              }),
              ...(profile !== undefined ? { profile } : {}),
            };
          }

          case ERROR_CODES.OPERATION_EXPIRED: {
            this.attempt = null;
            const profile = await this.refreshProfile();
            return {
              status: this.emit({
                kind: 'FAILED',
                code: error.code,
                message:
                  'This save attempt is too old to check. Your current saved resume is shown below; confirm again if you still want to change it.',
                retryable: false,
              }),
              ...(profile !== undefined ? { profile } : {}),
            };
          }

          default: {
            if (AUTH_CODES.has(error.code)) {
              // Keep both the draft and the key: after re-authenticating this is still
              // the same logical attempt, and no operation row was created.
              return {
                status: this.emit({
                  kind: 'AUTH_REQUIRED',
                  message:
                    'Your session ended before this was saved. Your draft is still here. Sign in again, then confirm.',
                }),
              };
            }
            if (error.code === ERROR_CODES.CSRF_INVALID) {
              return {
                status: this.emit({
                  kind: 'FAILED',
                  code: error.code,
                  message:
                    'This request could not be verified. Your draft is still here. Reload the page and confirm again.',
                  retryable: false,
                }),
              };
            }
            // Deterministic validation and other definite failures: the server stored a
            // terminal result against this key, so a further attempt needs a new key.
            this.attempt = null;
            return {
              status: this.emit({
                kind: 'FAILED',
                code: error.code,
                message: error.message,
                retryable: error.retryable,
              }),
            };
          }
        }
      }
    }
  }

  /**
   * Resolve a save whose operation_id is known, using the capped backoff schedule.
   * Used when the app holds an operation_id and needs its terminal state without
   * re-sending the body.
   */
  async resolveOperation(operationId: string): Promise<SaveOutcome> {
    let backoffIndex = 0;
    this.waits = [];

    for (;;) {
      try {
        const status = await this.api.getOperation(operationId);
        if (status.state === 'SUCCEEDED') {
          this.attempt = null;
          const profile = await this.refreshProfile();
          if (profile === undefined) {
            return { status: this.emit({
              kind: 'SAVED_REFRESH_REQUIRED',
              message: 'Your earlier save completed, but the current resume could not be loaded. Check again before making another save.',
            }) };
          }
          return {
            status: this.emit({
              kind: 'SAVED',
              revision: status.result_revision ?? 0,
              changed: true,
              refreshedFromServer: profile !== undefined,
              currentRevision: profile?.revision,
              profileDeleted: profile === null,
            }),
            ...(profile !== undefined ? { profile } : {}),
          };
        }
        if (status.state === 'FAILED') {
          this.attempt = null;
          return {
            status: this.emit({
              kind: 'FAILED',
              code: status.failure_code ?? 'INTERNAL_ERROR',
              message: 'That save did not complete. Your draft is still here; confirm again to retry.',
              retryable: true,
            }),
          };
        }
        // PROCESSING
        if (backoffIndex >= RETRY_BACKOFF_SECONDS.length) {
          return {
            status: this.emit({
              kind: 'OUTCOME_UNKNOWN',
              reason: 'STILL_PROCESSING',
              message:
                'This save is still being processed. Your draft is still here. Check again in a moment.',
            }),
          };
        }
        const waitSeconds = RETRY_BACKOFF_SECONDS[backoffIndex] as number;
        backoffIndex += 1;
        this.emit({
          kind: 'WAITING_TO_RETRY',
          attempt: backoffIndex,
          waitSeconds,
          reason: 'IN_PROGRESS',
        });
        this.waits.push(waitSeconds);
        await this.sleep(waitSeconds);
      } catch (caught) {
        if (isApiError(caught) && caught.code === ERROR_CODES.OPERATION_EXPIRED) {
          this.attempt = null;
          const profile = await this.refreshProfile();
          return {
            status: this.emit({
              kind: 'FAILED',
              code: ERROR_CODES.OPERATION_EXPIRED,
              message:
                'This save attempt is too old to check. The current saved resume is shown below.',
              retryable: false,
            }),
            ...(profile !== undefined ? { profile } : {}),
          };
        }
        if (isApiError(caught) && AUTH_CODES.has(caught.code)) {
          return {
            status: this.emit({
              kind: 'AUTH_REQUIRED',
              message: 'Your session ended. Sign in again to check this save.',
            }),
          };
        }
        return {
          status: this.emit({
            kind: 'OUTCOME_UNKNOWN',
            reason: 'NO_RESPONSE',
            message: 'The save status could not be read. Your draft is still here.',
          }),
        };
      }
    }
  }
}
