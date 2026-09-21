import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';

type AuthMode = 'signin' | 'create' | 'forgot';

export function AuthPreview({
  googleControl,
  busy,
  activity,
  error,
  onRetry,
  open = true,
}: {
  googleControl: ReactNode;
  busy: boolean;
  activity: string;
  error: string | null;
  onRetry(): void;
  open?: boolean;
}) {
  const [mode, setMode] = useState<AuthMode>('signin');
  const [showPassword, setShowPassword] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [resetComplete, setResetComplete] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const hasOpened = useRef(false);

  useEffect(() => {
    if (!open) {
      setMode('signin');
      setShowPassword(false);
      setNotice(null);
      setResetComplete(false);
      form.current?.reset();
    }
  }, [open]);
  useEffect(() => {
    if (!open) { hasOpened.current = false; return; }
    if (hasOpened.current) heading.current?.focus({ preventScroll: true });
    hasOpened.current = true;
  }, [mode, resetComplete, open]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === 'forgot') {
      setResetComplete(true);
      return;
    }
    setNotice(mode === 'create'
      ? 'Preview only — no email was sent and no account was created.'
      : 'Preview only — credentials were not sent.');
  }

  const title = mode === 'signin' ? 'Welcome back' : mode === 'create' ? 'Create your account' : 'Find your account';
  const subtitle = mode === 'signin'
    ? 'Keep your search readable and your next step clear.'
    : mode === 'create'
      ? 'Keep your account details in one place.'
      : 'Enter your email to continue the preview flow.';

  return <section className="auth-preview" aria-label="Email and password authentication preview">
    <h2 id="sign-in-heading" tabIndex={-1} ref={heading}>{title}</h2>
    <p className="auth-subtitle">{subtitle}</p>
    <p className="auth-preview-notice" role="note">UI preview: email/password authentication is not connected.</p>
    {error && <p role="alert">{error}</p>}
    {resetComplete ? <div className="auth-reset-complete" role="status"><h3>Reset preview complete</h3><p>No email was sent.</p><button type="button" className="auth-text-link" onClick={() => { setResetComplete(false); setMode('signin'); }}>Back to sign in</button></div> : <form ref={form} onSubmit={submit}>
      {mode === 'create' && <label htmlFor="auth-name">Name<input id="auth-name" name="name" autoComplete="name" required /></label>}
      <label htmlFor="auth-email">Email address<input id="auth-email" name="email" type="email" autoComplete="email" required /></label>
      {mode !== 'forgot' && <><label htmlFor="auth-password">Password</label><span className="auth-password-field"><input id="auth-password" name="password" type={showPassword ? 'text' : 'password'} autoComplete={mode === 'create' ? 'new-password' : 'current-password'} required minLength={8} /><button type="button" className="auth-show-password" aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)}>{showPassword ? 'Hide' : 'Show'}</button></span></>}
      {mode === 'signin' && <button type="button" className="auth-text-link auth-forgot-link" onClick={() => { setMode('forgot'); setNotice(null); }}>Forgot email or password?</button>}
      <div className="auth-form-actions">
        <button type="submit" disabled={busy}>{mode === 'signin' ? 'Sign in' : mode === 'create' ? 'Create account' : 'Send reset link'}</button>
      </div>
    </form>}
    {notice && <p className="auth-preview-result" role="status">{notice}</p>}
    <div className="auth-divider" aria-hidden="true"><span>or continue with</span></div>
    <div className="google-control" inert={busy} aria-hidden={busy || undefined}>{googleControl}</div>
    {busy && <p role="status">{activity === 'signing-in' ? 'Signing in…' : 'Checking session…'}</p>}
    {error && <button className="button-secondary auth-retry" disabled={busy} onClick={onRetry}>Retry connection</button>}
    <p className="auth-switch">{mode === 'signin' ? <>New here? <button type="button" className="auth-text-link" onClick={() => { setMode('create'); setNotice(null); }}>Create one</button></> : <button type="button" className="auth-text-link" onClick={() => { setMode('signin'); setNotice(null); }}>Back to sign in</button>}</p>
  </section>;
}
