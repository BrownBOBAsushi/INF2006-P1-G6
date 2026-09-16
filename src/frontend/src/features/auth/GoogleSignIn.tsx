import { useEffect, useRef, useState } from 'react';
interface GoogleIdentity {
  initialize(options: { client_id: string; callback(response: { credential: string }): void }): void;
  renderButton(element: HTMLElement, options: { theme: string; size: string }): void;
  disableAutoSelect(): void;
}
declare global { interface Window { google?: { accounts: { id: GoogleIdentity } } } }
let loading: Promise<GoogleIdentity> | undefined;
function loadGoogle() {
  if (window.google) return Promise.resolve(window.google.accounts.id);
  if (!loading) loading = new Promise<GoogleIdentity>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    const timer = setTimeout(() => { script.remove(); loading = undefined; reject(new Error('Google unavailable')); }, 15000);
    script.onload = () => {
      clearTimeout(timer);
      if (window.google) resolve(window.google.accounts.id);
      else { loading = undefined; reject(new Error('Google unavailable')); }
    };
    script.onerror = () => { clearTimeout(timer); script.remove(); loading = undefined; reject(new Error('Google unavailable')); };
    document.head.append(script);
  });
  return loading;
}
export function GoogleSignIn({ onCredential }: { onCredential(credential: string): Promise<void> }) {
  const container = useRef<HTMLDivElement>(null);
  const callback = useRef(onCredential);
  callback.current = onCredential;
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;
  useEffect(() => {
    if (!clientId) return;
    let active = true;
    setError(false);
    void loadGoogle().then(identity => {
      if (!active || !container.current) return;
      identity.initialize({ client_id: clientId, callback: response => {
        if (active) void callback.current(response.credential);
      } });
      identity.renderButton(container.current, { theme: 'outline', size: 'large' });
    }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [clientId, attempt]);
  if (!clientId) return <p role="status">Google sign-in is not configured for this local environment.</p>;
  return <><div ref={container} />{error && <p role="alert">Google sign-in could not load. <button onClick={() => setAttempt(value => value + 1)}>Retry Google sign-in</button></p>}</>;
}
