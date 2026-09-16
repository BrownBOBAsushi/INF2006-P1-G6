import { ApiClient } from '../../api/client';
import type { Me } from '../../api/contracts';

// Validate only the auth shapes this shell consumes. No backend schema is invented.
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid account response.');
  return value as Record<string, unknown>;
}
export function csrfToken(value: unknown): string {
  const token = object(value).csrf_token;
  if (typeof token !== 'string' || !token.trim() || /[\r\n]/.test(token)) throw new Error('Invalid account response.');
  return token;
}
export function accountResponse(value: unknown): Me {
  const body = object(value), user = object(body.user);
  if (typeof user.user_id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(user.user_id) ||
    !(user.display_name === null || (typeof user.display_name === 'string' && user.display_name.trim().length > 0 && [...user.display_name].length <= 100)) ||
    !Number.isSafeInteger(body.resume_revision) || Number(body.resume_revision) < 0 ||
    typeof body.has_resume !== 'boolean' || typeof body.has_matchable_resume !== 'boolean' ||
    (body.has_matchable_resume && !body.has_resume)) throw new Error('Invalid account response.');
  return {
    user: { user_id: user.user_id, display_name: user.display_name },
    resume_revision: body.resume_revision as number, has_resume: body.has_resume,
    has_matchable_resume: body.has_matchable_resume, csrf_token: csrfToken(body),
  };
}
export async function getAccount(client: ApiClient, signal?: AbortSignal) {
  return accountResponse(await client.json<unknown>({ method: 'GET', path: '/api/me', signal }));
}
