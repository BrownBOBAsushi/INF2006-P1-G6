import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClient, ApiError, StaleSessionError, type RecoveryReason } from '../../api/client';
import type { Me } from '../../api/contracts';
import { csrfToken, getAccount } from './authApi';

type Activity = 'idle' | 'checking' | 'signing-in' | 'signing-out';
export function useSession(client: ApiClient) {
  const [me, setMe] = useState<Me | null>(null);
  const account = useRef<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [recovery, setRecovery] = useState<RecoveryReason | null>(null);
  const [error, setError] = useState('');
  const [activity, setActivity] = useState<Activity>('idle');
  const activityRef = useRef<Activity>('idle');
  const [logoutPending, setLogoutPending] = useState(false);
  const logoutRef = useRef(false);
  const logoutNeedsCsrf = useRef(false);
  const logoutAccountId = useRef<string | null>(null);
  const [accountEpoch, setAccountEpoch] = useState(0);
  const [accessRevision, setAccessRevision] = useState(0);
  const operation = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const mounted = useRef(true);

  const begin = useCallback((next: Activity) => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const id = ++operation.current;
    activityRef.current = next; setActivity(next); setError('');
    return { signal: controller.signal, current: () => mounted.current && operation.current === id };
  }, []);
  const finish = useCallback(() => {
    activityRef.current = 'idle'; setActivity('idle'); setLoading(false);
    activeRequest.current = null;
  }, []);
  const install = useCallback((current: Me) => {
    if (account.current && account.current.user.user_id !== current.user.user_id) {
      // Revoke every old account adapter, including retries held by unmounted features.
      client.clearSession();
      setAccountEpoch(value => value + 1);
    }
    client.setCsrf(current.csrf_token);
    client.resumePrivateRequests();
    account.current = current; setMe(current); setRecovery(null);
    setAccessRevision(value => value + 1);
  }, [client]);

  const refresh = useCallback(async () => {
    if (logoutRef.current || activityRef.current === 'signing-in') throw new StaleSessionError();
    const attempt = begin('checking');
    try {
      const current = await getAccount(client, attempt.signal);
      if (!attempt.current()) throw new StaleSessionError();
      install(current);
    } catch (cause) {
      if (attempt.current() && !(cause instanceof ApiError && cause.status === 401)) {
        setError('Could not reconnect. Please sign in or retry.');
      }
      throw cause;
    } finally { if (attempt.current()) finish(); }
  }, [begin, client, finish, install]);

  useEffect(() => {
    mounted.current = true;
    const unsubscribe = client.onAuthenticationRequired(reason => {
      if (mounted.current && !logoutRef.current) setRecovery(reason);
    });
    void refresh().catch(() => { /* refresh owns the visible error */ });
    return () => {
      mounted.current = false; operation.current++;
      activeRequest.current?.abort(); unsubscribe();
    };
  }, [client, refresh]);

  async function signIn(credential: string) {
    // A synchronous ref prevents duplicate Google callbacks before React rerenders.
    if (logoutRef.current || activityRef.current === 'signing-in') return;
    const attempt = begin('signing-in');
    if (account.current) setRecovery(previous => previous ?? 'SESSION_EXPIRED');
    client.pausePrivateRequests();
    client.setCsrf(null);
    try {
      const bootstrap = await client.json<unknown>({ method: 'GET', path: '/api/auth/bootstrap', signal: attempt.signal });
      if (!attempt.current()) throw new StaleSessionError();
      client.setCsrf(csrfToken(bootstrap));
      const exchange = await client.json<unknown>({
        method: 'POST', path: '/api/auth/google', json: { credential }, signal: attempt.signal,
      });
      if (!attempt.current()) throw new StaleSessionError();
      client.setCsrf(csrfToken(exchange));
      const current = await getAccount(client, attempt.signal);
      if (!attempt.current()) throw new StaleSessionError();
      install(current);
    } catch {
      if (attempt.current()) {
        client.setCsrf(null);
        setError('Sign-in could not be completed. Please try again.');
      }
    } finally {
      credential = '';
      if (attempt.current()) finish();
    }
  }

  async function logout() {
    if (activityRef.current === 'signing-in' || activityRef.current === 'signing-out') return;
    if (!logoutRef.current) logoutAccountId.current = account.current?.user.user_id ?? null;
    logoutRef.current = true; setLogoutPending(true);
    const attempt = begin('signing-out');
    account.current = null; setMe(null); setAccountEpoch(value => value + 1);
    // Clear private work immediately, retaining CSRF only for the server logout attempt.
    client.clearPrivateState();
    try {
      try { window.google?.accounts.id.disableAutoSelect(); } catch { /* Google UI failure must not prevent server logout. */ }
      if (logoutNeedsCsrf.current) {
        // A CSRF failure clears the client's token and pauses all private work. A
        // retry may recover only the token through a safe read; it must not
        // reinstall the account or unpause feature requests during sign-out.
        const current = await getAccount(client, attempt.signal);
        if (!attempt.current()) return;
        if (logoutAccountId.current && current.user.user_id !== logoutAccountId.current) {
          // Another tab changed the account. Do not send a logout for it.
          client.clearSession(); setAccountEpoch(value => value + 1);
          logoutNeedsCsrf.current = false; logoutAccountId.current = null;
          logoutRef.current = false; setLogoutPending(false); setRecovery(null); return;
        }
        client.setCsrf(current.csrf_token);
        logoutNeedsCsrf.current = false;
      }
      await client.json({ method: 'POST', path: '/api/auth/logout', signal: attempt.signal });
      if (!attempt.current()) return;
      client.clearSession(); setAccountEpoch(value => value + 1);
      logoutNeedsCsrf.current = false; logoutAccountId.current = null;
      setRecovery(null);
      logoutRef.current = false; setLogoutPending(false);
    } catch (cause) {
      if (!attempt.current()) return;
      if (cause instanceof ApiError && (cause.status === 401 || cause.code === 'AUTH_REQUIRED' || cause.code === 'SESSION_EXPIRED')) {
        // The backend treats an expired session as already signed out. Keep the
        // local private state cleared while accepting that best-effort outcome.
        client.clearSession(); setAccountEpoch(value => value + 1);
        logoutNeedsCsrf.current = false; logoutAccountId.current = null;
        setRecovery(null); logoutRef.current = false; setLogoutPending(false); return;
      }
      if (cause instanceof ApiError && cause.code === 'CSRF_INVALID') logoutNeedsCsrf.current = true;
      setError('Local private content was cleared. Server sign-out is unconfirmed; retry sign-out.');
    } finally { if (attempt.current()) finish(); }
  }
  return { me, loading, recovery, error, activity, logoutPending, accountEpoch, accessRevision,
    refresh, signIn, logout, requireAuthentication: () => setRecovery('SESSION_EXPIRED') };
}
