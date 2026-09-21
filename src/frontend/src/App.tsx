import { useCallback, useEffect, useMemo, useState, type ComponentType } from 'react';
import { Link, Navigate, Route, Routes } from 'react-router';
import { ApiClient } from './api/client';
import { Navbar } from './components/Navbar';
import { Footer } from './components/Footer';
import { LoginLayout } from './features/auth/LoginLayout';
import { Catalogue } from './features/catalogue/Catalogue';
import { JobDetails } from './features/catalogue/JobDetails';
import { Onboarding } from './features/auth/Onboarding';
import { GoogleSignIn } from './features/auth/GoogleSignIn';
import { SessionRecovery } from './features/auth/SessionRecovery';
import { AuthPreview } from './features/auth/AuthPreview';
import { useSession } from './features/auth/useSession';
import { ResumeWorkspace, createResumeApi } from './features/resume';

export interface SignInProps { onCredential(credential: string): Promise<void> }
export const THEME_STORAGE_KEY = 'internshipMatcher.theme';

type Theme = 'dark' | 'light';

function initialTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

export function App({ client, mock = false, SignInControl = GoogleSignIn }: {
  client: ApiClient; mock?: boolean; SignInControl?: ComponentType<SignInProps>;
}) {
  const session = useSession(client);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [loginOpen, setLoginOpen] = useState(false);
  const openLogin = useCallback(() => setLoginOpen(true), []);
  const closeLogin = useCallback(() => setLoginOpen(false), []);
  const { me, recovery, error, activity, accessRevision } = session;
  useEffect(() => {
    if (me || session.logoutPending) setLoginOpen(false);
  }, [me, session.logoutPending]);
  const resumeApi = useMemo(() => createResumeApi(client.scopedTransport()), [client, session.accountEpoch]);
  const busy = activity !== 'idle';
  function toggleTheme() {
    setTheme(current => {
      const next = current === 'dark' ? 'light' : 'dark';
      try { window.localStorage.setItem(THEME_STORAGE_KEY, next); } catch { /* theme still works when storage is blocked */ }
      return next;
    });
  }
  const recoveryLogin = <section className="panel narrow recovery-card signin" aria-label="Sign in">
    <p className="eyebrow">Welcome to Internship Matcher</p><h2 id="sign-in-heading">{recovery && me ?
      recovery === 'CSRF_INVALID' ? 'Refresh your session' : 'Your session ended'
      : 'Find an internship that fits'}</h2>
    <p>{recovery && me ? 'Your open draft stays in memory. Reconnect or sign in before saving. Do not refresh this page.' : 'Sign in to browse internships. You can skip uploading a resume.'}</p>
    {error && <p role="alert">{error}</p>}
    <div className="google-control" inert={busy} aria-hidden={busy || undefined}><SignInControl onCredential={session.signIn} /></div>
    {busy && <p role="status">{activity === 'signing-in' ? 'Signing in…' : 'Checking session…'}</p>}
    <button className="button-secondary" disabled={busy} onClick={() => { void session.refresh().catch(() => {}); }}>Retry connection</button>
    {me && recovery && <button disabled={activity === 'signing-in'} onClick={() => void session.logout()}>Sign out instead</button>}
  </section>;
  const login = recovery && me ? recoveryLogin : <AuthPreview
    googleControl={<SignInControl onCredential={session.signIn} />}
    busy={busy}
    activity={activity}
    error={error}
    open={loginOpen}
    onRetry={() => { void session.refresh().catch(() => {}); }}
  />;
  return <div className={`app-shell theme-${theme}`}>
    <a className="skip-link" href="#content">Skip to content</a>
    <Navbar me={me} inert={Boolean(me && recovery)} signingIn={activity === 'signing-in'} onLogout={() => void session.logout()} theme={theme} onToggleTheme={toggleTheme} onOpenSignIn={openLogin} />
    {mock && <p className="mock-banner" role="status">Synthetic fixture preview — no real account or application.</p>}
    <main id="content" className={!me && !session.loading && !session.logoutPending ? 'login-content' : undefined}>
      {session.loading ? <p role="status">Checking session…</p> : session.logoutPending ?
        <section className="panel"><h2>Signing out</h2>{error && <p role="alert">{error}</p>}
          <button disabled={activity === 'signing-out'} onClick={() => void session.logout()}>Retry sign-out</button></section> :
        !me ? <LoginLayout open={loginOpen} onOpen={openLogin} onClose={closeLogin}>{login}</LoginLayout> : <>
          {recovery && <SessionRecovery>{login}</SessionRecovery>}
          <div key={session.accountEpoch} inert={Boolean(recovery)}>
            <Routes>
              <Route path="/login" element={<Navigate to={me.user.display_name ? '/jobs' : '/onboarding'} replace />} />
              <Route path="/onboarding" element={<Onboarding client={client} me={me} refresh={session.refresh} />} />
              <Route path="/jobs" element={me.user.display_name ? <Catalogue client={client} accessRevision={accessRevision} /> : <Navigate to="/onboarding" replace />} />
              <Route path="/jobs/:id" element={me.user.display_name ? <JobDetails client={client} accessRevision={accessRevision} /> : <Navigate to="/onboarding" replace />} />
              <Route path="/resume" element={me.user.display_name ? <div className="resume-shell"><div className="workspace-intro"><p className="eyebrow">Your experience, in your words</p><p>Resume details are optional. Review what you share before saving.</p></div><div className="panel resume-slot"><ResumeWorkspace api={resumeApi} onAuthenticationRequired={session.requireAuthentication} /></div></div> : <Navigate to="/onboarding" replace />} />
              <Route path="/matches" element={me.user.display_name ? <section className="matches-shell" aria-labelledby="matches-heading"><div className="matches-hero"><p className="eyebrow">Personalised discovery</p><h1 id="matches-heading">Recommendations</h1><p>A place to explore how your experience connects with internship opportunities.</p></div><div className="panel matches-state"><span className="availability-label">Not available yet</span><h2>Keep exploring the catalogue</h2><p>This view is not available yet. You can browse all active jobs.</p><div className="actions"><Link className="button" to="/jobs">Browse jobs <span aria-hidden="true">→</span></Link><Link className="button button-secondary" to="/resume">Review your resume</Link></div></div></section> : <Navigate to="/onboarding" replace />} />
              <Route path="/" element={<Navigate to={me.user.display_name ? '/jobs' : '/onboarding'} replace />} />
              <Route path="*" element={<section><h1>Page not found</h1><Link to="/jobs">Browse jobs</Link></section>} />
            </Routes>
          </div>
        </>}
    </main><Footer />
  </div>;
}
