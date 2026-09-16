import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { ApiClient, ApiError } from '../../api/client';
import type { JobDetail } from '../../api/contracts';
import { label } from './Catalogue';

export function safeExternalUrl(value: string): string | undefined {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password && value.length <= 2048 ? url.href : undefined; }
  catch { return undefined; }
}
export function JobDetails({ client }: { client: ApiClient }) {
  const { id } = useParams();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    setJob(null); setError('');
    if (!id || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) { setError('Job not found.'); return; }
    const controller = new AbortController();
    let active = true;
    void client.json<JobDetail>({ method: 'GET', path: '/api/jobs/' + id, signal: controller.signal })
      .then(result => { if (active) setJob(result); })
      .catch(cause => { if (active) setError(cause instanceof ApiError && cause.status === 404 ? 'Job not found.' : 'Job details could not load. Please retry.'); });
    return () => { active = false; controller.abort(); };
  }, [client, id, retry]);
  if (error) return <section><h1>{error}</h1><Link to="/jobs">Browse jobs</Link>{error !== 'Job not found.' && <button onClick={() => setRetry(value => value + 1)}>Retry loading details</button>}</section>;
  if (!job) return <p role="status">Loading job details…</p>;
  const apply = safeExternalUrl(job.apply_url), source = safeExternalUrl(job.source_url);
  return <article className="panel">
    <Link to="/jobs">Browse jobs</Link><p className="eyebrow">{job.company_name}</p><h1>{job.title}</h1>
    <p>{job.location} · {label(job.job_type)} · {label(job.employment_time)} · {label(job.work_arrangement)}</p>
    {!job.is_active && <p role="status">This listing is closed. Its details remain available.</p>}
    <div className="actions">{job.is_active && apply ? <a className="button" href={apply} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Apply on source website</a> : <button disabled>Apply unavailable</button>}</div>
    <p>Apply opens the source in a new tab. We do not send your resume. Confirm availability on the source website.</p>
    <h2>About this internship</h2><p className="preserve">{job.description}</p>
    <h2>Requirements</h2><ul>{job.requirements.map(requirement => <li key={requirement.requirement_id}>
      <strong>{label(requirement.importance)}: </strong>{requirement.requirement_text}
      {requirement.alternatives.length > 0 && <p>Alternatives (any one): {requirement.alternatives.join(' OR ')}</p>}
      <blockquote>{requirement.source_quote}</blockquote>
    </li>)}</ul>
    {job.eligibility_notes.length > 0 && <><h2>Eligibility notes</h2><ul>{job.eligibility_notes.map((note, index) => <li key={index}>{note.text}</li>)}</ul></>}
    <h2>Source and freshness</h2><p>{source ? <a href={source} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">{job.source}</a> : job.source}</p>
    <p>Posted: {job.posted_at?.slice(0, 10) ?? 'Unknown'} · Last imported: {job.last_imported_at.slice(0, 10)}</p>
    <p>Last verified: {job.last_verified_at?.slice(0, 10) ?? 'Not verified'}. Import time does not mean live availability.</p>
  </article>;
}
