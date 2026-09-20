import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import type { ApiClient } from '../../api/client';
import type { Me } from '../../api/contracts';

export function Onboarding({ client, me, refresh }: { client: ApiClient; me: Me; refresh(): Promise<void> }) {
  const [name, setName] = useState(me.user.display_name ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  async function confirm(destination: string) {
    const trimmed = name.trim();
    if (!trimmed || [...trimmed].length > 100 || /[\u0000-\u001f\u007f-\u009f]/u.test(trimmed)) {
      setError('Enter a display name of 1–100 characters without control characters.'); return;
    }
    setBusy(true); setError('');
    try {
      await client.json({ method: 'PATCH', path: '/api/me', json: { display_name: trimmed } });
      await refresh();
      navigate(destination);
    } catch { setError('Could not confirm your name. Please retry.'); }
    finally { setBusy(false); }
  }
  return <div className="onboard-wrap"><section className="panel onboard-card">
    <div className="onboard-top"><div><p className="eyebrow">Make yourself at home</p><h1>Welcome to Internship Matcher</h1>
      <p className="muted">Confirm your display name. It is excluded from matching.</p></div><span className="step">Your profile</span></div>
    <form onSubmit={event => { event.preventDefault(); void confirm('/jobs'); }}>
      <div className="onboard-field"><label htmlFor="display-name">Display name</label>
        <input id="display-name" value={name} maxLength={100} onChange={event => setName(event.target.value)} autoComplete="nickname" aria-describedby={error ? 'onboard-error' : undefined} />
      </div>
      <section className="optional-resume" aria-labelledby="optional-resume-title">
        <span className="upload-symbol" aria-hidden="true">↑</span><div><h2 id="optional-resume-title">A resume is optional</h2>
          <p>Browse every internship without uploading one. Add a text-based PDF or enter your details in your resume workspace.</p></div>
        <button className="button-secondary" disabled={busy} type="button" onClick={() => void confirm('/resume')}>Continue to resume</button>
      </section>
      {error && <p role="alert" id="onboard-error">{error}</p>}
      {busy && <p role="status">Confirming your name…</p>}
      <div className="actions onboard-actions"><button className="button-secondary" disabled={busy} type="button" onClick={() => void confirm('/jobs')}>Skip for now</button>
        <button disabled={busy} type="submit">Continue to jobs <span aria-hidden="true">→</span></button></div>
    </form>
    {me.user.display_name && <p><Link to="/jobs">Back to jobs</Link></p>}
  </section></div>;
}
