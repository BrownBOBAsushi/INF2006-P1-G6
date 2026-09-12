/**
 * Idempotency-Key lifecycle for PUT /api/resume.
 *
 * The server's key scope is (user + PUT resume) and its stored payload_hash covers
 * expected_revision, content and embedding_version. Two rules follow, and both matter:
 *
 *   1. A network-level retry of the SAME payload must reuse the SAME key, otherwise a
 *      save that already committed would be applied a second time.
 *      (IMPLEMENTATION_GUIDE: "Do not rotate idempotency key on a network retry.")
 *
 *   2. A changed payload must use a NEW key, otherwise the server answers
 *      409 IDEMPOTENCY_CONFLICT. Note that expected_revision is part of the payload
 *      hash, so retrying after a REVISION_CONFLICT — which necessarily changes
 *      expected_revision — is a new logical attempt and must rotate the key.
 *
 * Modelling the key as a function of payload identity makes both rules fall out of one
 * check instead of being remembered at each call site.
 */

export interface SaveAttempt {
  key: string;
  expectedRevision: number;
  /** Local content signature; see serialize.contentSignature. */
  signature: string;
}

export type KeyFactory = () => string;

export function createIdempotencyKey(): string {
  const globalCrypto = globalThis.crypto as Crypto | undefined;
  if (globalCrypto && typeof globalCrypto.randomUUID === 'function') {
    return globalCrypto.randomUUID();
  }
  // Fallback for environments without randomUUID. The contract requires a UUID shape.
  const bytes = new Uint8Array(16);
  if (globalCrypto && typeof globalCrypto.getRandomValues === 'function') {
    globalCrypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = ((bytes[6] as number) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] as number) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** True when `attempt` addresses exactly this payload and its key may be reused. */
export function attemptMatchesPayload(
  attempt: SaveAttempt | null,
  expectedRevision: number,
  signature: string,
): attempt is SaveAttempt {
  return (
    attempt !== null &&
    attempt.expectedRevision === expectedRevision &&
    attempt.signature === signature
  );
}

/**
 * Returns the attempt to use for this payload: the existing one when the payload is
 * unchanged (safe replay), otherwise a fresh key.
 */
export function attemptForPayload(
  current: SaveAttempt | null,
  expectedRevision: number,
  signature: string,
  keyFactory: KeyFactory = createIdempotencyKey,
): SaveAttempt {
  if (attemptMatchesPayload(current, expectedRevision, signature)) return current;
  return { key: keyFactory(), expectedRevision, signature };
}
