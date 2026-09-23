import type { ReactNode } from 'react';

export function GoogleOnlySignIn({ googleControl, busy, activity, error, onRetry }: {
  googleControl: ReactNode; busy: boolean; activity: string; error: string | null; onRetry(): void;
}) {
  return <section className="google-signin-panel" aria-label="Google sign in">
    <h2 id="sign-in-heading">Find an internship that fits</h2>
    <p>Sign in with Google to browse internships. You can skip uploading a resume.</p>
    {error && <p role="alert">{error}</p>}
    <div className="google-control" inert={busy} aria-hidden={busy || undefined}>{googleControl}</div>
    {busy && <p role="status">{activity === 'signing-in' ? 'Signing in…' : 'Checking session…'}</p>}
    {error && <button className="button-secondary" disabled={busy} onClick={onRetry}>Retry connection</button>}
    <p className="google-only-note">Sign in with Google to continue.</p>
  </section>;
}
