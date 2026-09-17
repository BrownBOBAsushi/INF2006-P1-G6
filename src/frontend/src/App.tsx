import { useMemo, type ComponentType } from 'react';
import { Link, Navigate, Route, Routes } from 'react-router';
import { ApiClient } from './api/client';
import { Catalogue } from './features/catalogue/Catalogue';
import { JobDetails } from './features/catalogue/JobDetails';
import { Onboarding } from './features/auth/Onboarding';
import { GoogleSignIn } from './features/auth/GoogleSignIn';
import { SessionRecovery } from './features/auth/SessionRecovery';
import { useSession } from './features/auth/useSession';
import { ResumeWorkspace, createResumeApi } from './features/resume';

export interface SignInProps { onCredential(credential: string): Promise<void> }
export function App({ client, mock = false, SignInControl = GoogleSignIn }: {
  client: ApiClient; mock?: boolean; SignInControl?: ComponentType<SignInProps>;
}) {
  const session = useSession(client);
  const { me, recovery, error, activity, accessRevision } = session;
  const resumeApi = useMemo(() => createResumeApi(client.scopedTransport()), [client, session.accountEpoch]);
  const busy = activity !== 'idle';
  const login = <section className="panel narrow" aria-label="Sign in">
    <h1 id="sign-in-heading">{recovery && me ?
      recovery === 'CSRF_INVALID' ? 'Refresh your session' : 'Your session ended'
      : 'Find an internship that fits'}</h1>
    <p>{recovery && me ? 'Your open draft stays in memory. Reconnect or sign in before saving. Do not refresh this page.' : 'Sign in to browse internships. You can skip uploading a resume.'}</p>
    {error && <p role="alert">{error}</p>}
    <div inert={busy} aria-hidden={busy || undefined}><SignInControl onCredential={session.signIn} /></div>
    {busy && <p role="status">{activity === 'signing-in' ? 'Signing in…' : 'Checking session…'}</p>}
    <button disabled={busy} onClick={() => { void session.refresh().catch(() => {}); }}>Retry connection</button>
    {me && recovery && <button disabled={activity === 'signing-in'} onClick={() => void session.logout()}>Sign out instead</button>}
  </section>;
  return <>
    <a className="skip-link" href="#content">Skip to content</a>
    <header inert={Boolean(me && recovery)}><Link className="brand" to="/jobs">Internship Matcher</Link>{me && <nav aria-label="Main navigation">
      <Link to="/jobs">Browse jobs</Link><Link to="/resume">Your resume</Link><Link to="/matches">Recommendations</Link>
      <Link to="/onboarding">Your name</Link><button disabled={activity === 'signing-in'} onClick={() => void session.logout()}>Sign out</button>
    </nav>}</header>
    {mock && <p className="mock-banner" role="status">Synthetic fixture preview — no real account or application.</p>}
    <main id="content">
      {session.loading ? <p role="status">Checking session…</p> : session.logoutPending ?
        <section className="panel"><h1>Signing out</h1>{error && <p role="alert">{error}</p>}
          <button disabled={activity === 'signing-out'} onClick={() => void session.logout()}>Retry sign-out</button></section> :
        !me ? login : <>
          {recovery && <SessionRecovery>{login}</SessionRecovery>}
          <div key={session.accountEpoch} inert={Boolean(recovery)}>
            <Routes>
              <Route path="/login" element={<Navigate to={me.user.display_name ? '/jobs' : '/onboarding'} replace />} />
              <Route path="/onboarding" element={<Onboarding client={client} me={me} refresh={session.refresh} />} />
              <Route path="/jobs" element={me.user.display_name ? <Catalogue client={client} accessRevision={accessRevision} /> : <Navigate to="/onboarding" replace />} />
              <Route path="/jobs/:id" element={me.user.display_name ? <JobDetails client={client} accessRevision={accessRevision} /> : <Navigate to="/onboarding" replace />} />
              <Route path="/resume" element={me.user.display_name ? <ResumeWorkspace api={resumeApi} onAuthenticationRequired={session.requireAuthentication} /> : <Navigate to="/onboarding" replace />} />
              <Route path="/matches" element={<section className="panel"><h1>Recommendations</h1><p>This view is not available yet. You can browse all active jobs.</p><Link to="/jobs">Browse jobs</Link></section>} />
              <Route path="/" element={<Navigate to={me.user.display_name ? '/jobs' : '/onboarding'} replace />} />
              <Route path="*" element={<section><h1>Page not found</h1><Link to="/jobs">Browse jobs</Link></section>} />
            </Routes>
          </div>
        </>}
    </main><footer>Internship Matcher · Local MVP</footer>
  </>;
}
