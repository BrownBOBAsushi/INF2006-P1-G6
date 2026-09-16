import { useCallback, useEffect, useMemo, useState, type ComponentType } from 'react';
import { Link, Navigate, Route, Routes } from 'react-router';
import { ApiClient, ApiError } from './api/client';
import type { Me } from './api/contracts';
import { Catalogue } from './features/catalogue/Catalogue';
import { JobDetails } from './features/catalogue/JobDetails';
import { Onboarding } from './features/auth/Onboarding';
import { GoogleSignIn } from './features/auth/GoogleSignIn';
import { ResumeWorkspace, createResumeApi } from './features/resume';

export interface SignInProps { onCredential(credential: string): Promise<void> }
export function App({ client, mock = false, SignInControl = GoogleSignIn }: {
  client: ApiClient; mock?: boolean; SignInControl?: ComponentType<SignInProps>;
}) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [expired, setExpired] = useState(false);
  const [error, setError] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const [logoutPending, setLogoutPending] = useState(false);
  const [sessionEpoch, setSessionEpoch] = useState(0);
  const resumeApi = useMemo(() => createResumeApi(client), [client]);
  const refresh = useCallback(async () => {
    const current = await client.json<Me>({ method: 'GET', path: '/api/me' });
    client.setCsrf(current.csrf_token);
    setMe(previous => {
      if (previous && previous.user.user_id !== current.user.user_id) setSessionEpoch(value => value + 1);
      return current;
    });
    setExpired(false);
  }, [client]);
  useEffect(() => client.onAuthenticationRequired(() => setExpired(true)), [client]);
  useEffect(() => {
    void refresh().catch(cause => {
      if (!(cause instanceof ApiError && cause.status === 401)) setError('The service is unavailable. Retry connecting.');
    }).finally(() => setLoading(false));
  }, [refresh]);
  async function signIn(credential: string) {
    if (signingIn) return;
    setSigningIn(true); setError('');
    try {
      const bootstrap = await client.json<{ csrf_token: string }>({ method: 'GET', path: '/api/auth/bootstrap' });
      client.setCsrf(bootstrap.csrf_token);
      const result = await client.json<{ csrf_token: string }>({ method: 'POST', path: '/api/auth/google', json: { credential } });
      client.setCsrf(result.csrf_token);
      await refresh();
    } catch { setError('Sign-in could not be completed. Please try again.'); }
    finally { credential = ''; setSigningIn(false); }
  }
  async function logout() {
    setMe(null); setSessionEpoch(value => value + 1); setLogoutPending(true); setError('');
    window.google?.accounts.id.disableAutoSelect();
    try {
      await client.json({ method: 'POST', path: '/api/auth/logout' });
      client.clearSession(); setExpired(false); setLogoutPending(false);
    } catch { setError('Local private content was cleared. Server sign-out is unconfirmed; retry sign-out.'); }
  }
  const login = <section className="panel narrow" aria-label="Sign in">
    <h1>{expired && me ? 'Your session ended' : 'Find an internship that fits'}</h1>
    <p>{expired && me ? 'Your open draft stays in memory. Sign in again before saving. Do not refresh this page.' : 'Sign in to browse internships. You can skip uploading a resume.'}</p>
    {error && <p role="alert">{error}</p>}
    {signingIn ? <p role="status">Signing in…</p> : <SignInControl onCredential={signIn} />}
    <button onClick={() => { setError(''); void refresh().catch(() => setError('Could not reconnect. Please sign in or retry.')); }}>Retry connection</button>
  </section>;
  return <>
    <a className="skip-link" href="#content">Skip to content</a>
    <header><Link className="brand" to="/jobs">Internship Matcher</Link>{me && <nav aria-label="Main navigation">
      <Link to="/jobs">Browse jobs</Link><Link to="/resume">Your resume</Link><Link to="/matches">Recommendations</Link>
      <Link to="/onboarding">Your name</Link><button onClick={() => void logout()}>Sign out</button>
    </nav>}</header>
    {mock && <p className="mock-banner" role="status">Synthetic fixture preview — no real account or application.</p>}
    <main id="content">
      {loading ? <p role="status">Checking session…</p> : logoutPending ?
        <section className="panel"><h1>Signing out</h1>{error && <p role="alert">{error}</p>}<button onClick={() => void logout()}>Retry sign-out</button></section> :
        !me ? login : <>
          {expired && <div className="reauth">{login}</div>}
          <div key={sessionEpoch} inert={expired}>
            <Routes>
              <Route path="/login" element={<Navigate to={me.user.display_name ? '/jobs' : '/onboarding'} replace />} />
              <Route path="/onboarding" element={<Onboarding client={client} me={me} refresh={refresh} />} />
              <Route path="/jobs" element={me.user.display_name ? <Catalogue client={client} /> : <Navigate to="/onboarding" replace />} />
              <Route path="/jobs/:id" element={me.user.display_name ? <JobDetails client={client} /> : <Navigate to="/onboarding" replace />} />
              <Route path="/resume" element={me.user.display_name ? <ResumeWorkspace api={resumeApi} onAuthenticationRequired={() => setExpired(true)} /> : <Navigate to="/onboarding" replace />} />
              <Route path="/matches" element={<section className="panel"><h1>Recommendations</h1><p>This view is not available yet. You can browse all active jobs.</p><Link to="/jobs">Browse jobs</Link></section>} />
              <Route path="/" element={<Navigate to={me.user.display_name ? '/jobs' : '/onboarding'} replace />} />
              <Route path="*" element={<section><h1>Page not found</h1><Link to="/jobs">Browse jobs</Link></section>} />
            </Routes>
          </div>
        </>}
    </main><footer>Internship Matcher · Local MVP</footer>
  </>;
}
