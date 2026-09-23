import { Link } from 'react-router';
import type { ReactNode } from 'react';
import type { JobSummary } from '../../api/contracts';
import { displayDate, label } from './jobPresentation';

export function JobCard({ job, selected = false, selectHref, returnTo, children }: {
  job: JobSummary; selected?: boolean; selectHref?: string; returnTo?: string; children?: ReactNode;
}) {
  const titleId = `job-title-${job.job_id}`;
  const factsId = `job-facts-${job.job_id}`;
  return <li className={`job-card${selected ? ' selected' : ''}`}>
    <Link className="job-card-link" to={selectHref ?? `/jobs/${job.job_id}`} state={returnTo ? { from: returnTo } : undefined} aria-labelledby={titleId} aria-describedby={factsId} aria-current={selected ? 'true' : undefined}>
      <div className="job-top"><div className="job-identity">
        <div>
          <h2 id={titleId}>{job.title}</h2><p className="company">{job.company_name} · {job.location}</p>
        </div></div><span className={`status-pill ${job.is_active ? '' : 'closed'}`}>{job.is_active ? 'Open' : 'Closed'}</span></div>
      <div className="pills"><span className="pill">{label(job.job_type)}</span><span className="pill">{label(job.employment_time)}</span><span className="pill">{label(job.work_arrangement)}</span></div>
      <span id={factsId} className="sr-only">{job.company_name}, {job.location}. {label(job.job_type)}, {label(job.employment_time)}, {label(job.work_arrangement)}. {job.is_active ? 'Open listing.' : 'Closed listing.'}</span>
    </Link>
    <div className="job-bottom"><p className="job-date">Posted: {displayDate(job.posted_at)} · Last imported: {displayDate(job.last_imported_at)}</p>
      <Link className="view-link" to={`/jobs/${job.job_id}`} state={returnTo ? { from: returnTo } : undefined} aria-label={`View details: ${job.title}`}>View details <span aria-hidden="true">→</span></Link></div>{children}
  </li>;
}
