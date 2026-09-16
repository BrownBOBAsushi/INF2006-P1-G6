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
  return <section className="panel narrow">
    <p className="eyebrow">Make yourself at home</p><h1>Welcome to Internship Matcher</h1>
    <p>Confirm your display name. It is excluded from matching.</p>
    <form onSubmit={event => { event.preventDefault(); void confirm('/jobs'); }}>
      <label htmlFor="display-name">Display name</label>
      <input id="display-name" value={name} maxLength={100} onChange={event => setName(event.target.value)} autoComplete="nickname" />
      <h2>A resume is optional</h2><p>Browse every internship without uploading one. Add it later to prepare for personalised recommendations.</p>
      {error && <p role="alert">{error}</p>}
      <div className="actions"><button disabled={busy} type="submit">Skip resume and browse jobs</button>
      <button disabled={busy} type="button" onClick={() => void confirm('/resume')}>Continue to resume</button></div>
    </form>
    {me.user.display_name && <p><Link to="/jobs">Back to jobs</Link></p>}
  </section>;
}
