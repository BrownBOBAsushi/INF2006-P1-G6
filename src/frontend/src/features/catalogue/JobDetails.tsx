import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router';
import { ApiClient, ApiError } from '../../api/client';
import type { JobDetail } from '../../api/contracts';
import { displayDate, initials, label } from './jobPresentation';

export function safeExternalUrl(value: string): string | undefined {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password && value.length <= 2048 ? url.href : undefined; }
  catch { return undefined; }
}

export function JobDetails({ client, accessRevision = 0, jobId, inline = false }: {
  client: ApiClient; accessRevision?: number; jobId?: string; inline?: boolean;
}) {
  const { id: routeId } = useParams();
  const location = useLocation();
  const id = jobId ?? routeId;
  const routeState = location.state as { from?: unknown } | null;
  const returnTo = typeof routeState?.from === 'string' && routeState.from.startsWith('/jobs') ? routeState.from : '/jobs';
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
  }, [client, id, retry, accessRevision]);

  if (error) return <section className="panel empty-state"><p className="eyebrow">Internship details</p><h2>{error}</h2><div className="actions"><Link to={returnTo}>Browse jobs</Link>{error !== 'Job not found.' && <button onClick={() => setRetry(value => value + 1)}>Retry loading details</button>}</div></section>;
  if (!job) return <section className="panel" aria-busy="true"><p role="status">Loading job details…</p><div className="skeleton" aria-hidden="true" /></section>;

  const apply = safeExternalUrl(job.apply_url), source = safeExternalUrl(job.source_url);
  const firstParagraph = job.description.split(/\n\s*\n/)[0] ?? '';
  const summary = firstParagraph.length > 240 ? firstParagraph.slice(0, 240).replace(/\s+\S*$/, '') + '…' : firstParagraph;
  const TitleHeading = inline ? 'h2' : 'h1';
  return <article className={`job-detail${inline ? ' job-detail-inline' : ''}`}>
    {!inline && <Link className="back-link" to={returnTo}><span aria-hidden="true">← </span>Browse jobs</Link>}
    <header className="panel detail-hero">
      <div className="detail-context"><div className="job-identity"><span className="company-badge" aria-hidden="true">{initials(job.company_name)}</span><div><p className="eyebrow">{job.company_name}</p><p className="company">{job.location} · {job.country_code}</p></div></div><span className={'status-pill' + (job.is_active ? '' : ' closed')}>{job.is_active ? 'Open' : 'Closed'}</span></div>
      <TitleHeading>{job.title}</TitleHeading>
      {summary && <p className="role-summary">{summary}</p>}
      <div className="detail-facts" aria-label="Job facts"><span><strong>{label(job.job_type)}</strong><small>Job type</small></span><span><strong>{label(job.employment_time)}</strong><small>Employment</small></span><span><strong>{label(job.work_arrangement)}</strong><small>Work arrangement</small></span><span><strong>{displayDate(job.posted_at)}</strong><small>Posted</small></span></div>
      <section className="apply-panel compact-apply" aria-label="Application">
        {job.is_active && apply ? <a className="apply-link" href={apply} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Apply on source website <span aria-hidden="true">↗</span></a> : <button disabled>Apply unavailable</button>}
        <p className="apply-note">Opens the source in a new tab. We do not send your resume.</p>
      </section>
      {!job.is_active && <p className="notice" role="status">This listing is closed. Its details remain available.</p>}
    </header>
    <div className="detail-layout">
      <div className="detail-body">
        <section className="panel detail-description" aria-labelledby="about-role-heading"><p className="eyebrow">The opportunity</p><h2 id="about-role-heading">About this internship</h2><p className="preserve">{job.description}</p></section>
        <section className="panel" aria-labelledby="requirements-heading"><p className="eyebrow">What the role asks for</p><h2 id="requirements-heading">Requirements</h2>
          {job.requirements.length ? <ul className="requirements-list">{job.requirements.map(requirement => <li key={requirement.requirement_id}>
            <span className={'requirement-level ' + requirement.importance.toLowerCase()}>{label(requirement.importance)}</span><p>{requirement.requirement_text}</p>
            {requirement.alternatives.length > 0 && <p className="alternatives">Alternatives (any one): {requirement.alternatives.join(' OR ')}</p>}
            {requirement.source_quote && <blockquote><span className="quote-label">From the source</span>{requirement.source_quote}</blockquote>}
          </li>)}</ul> : <p className="muted">No separate requirements were supplied with this listing. Check the source for full details.</p>}
        </section>
        {job.eligibility_notes.length > 0 && <section className="panel" aria-labelledby="eligibility-heading"><p className="eyebrow">Before applying</p><h2 id="eligibility-heading">Eligibility notes</h2><ul className="eligibility-list">{job.eligibility_notes.map((note, index) => <li key={index}><p>{note.text}</p>{note.source_quote && <blockquote><span className="quote-label">From the source</span>{note.source_quote}</blockquote>}</li>)}</ul></section>}
        <section className="panel source-panel" aria-labelledby="source-heading"><p className="eyebrow">Listing provenance</p><h2 id="source-heading">Source and freshness</h2>
          <p>{source ? <a href={source} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">{job.source} <span aria-hidden="true">↗</span><span className="sr-only"> (opens in a new tab)</span></a> : job.source}</p>
          <dl className="source-meta"><div><dt>Posted</dt><dd>{displayDate(job.posted_at)}</dd></div><div><dt>Last imported</dt><dd>{displayDate(job.last_imported_at)}</dd></div><div><dt>Last verified</dt><dd>{job.last_verified_at ? displayDate(job.last_verified_at) : 'Not verified'}</dd></div></dl>
          <p className="source-note">Import time does not mean live availability.</p><details><summary>Catalogue identifier</summary><p className="record-id">{job.job_id}</p></details>
        </section>
      </div>
    </div>
  </article>;
}
