import { Link } from 'react-router';
import type { JobSummary } from '../../api/contracts';
import { displayDate, initials, label } from './jobPresentation';

export function JobCard({ job }: { job: JobSummary }) {
  return <li className="job-card"><div className="job-top"><div className="job-identity">
    <span className="company-badge" aria-hidden="true">{initials(job.company_name)}</span><div>
      <h2><Link to={'/jobs/' + job.job_id}>{job.title}</Link></h2><p className="company">{job.company_name} · {job.location}</p>
    </div></div><span className={`status-pill ${job.is_active ? '' : 'closed'}`}>{job.is_active ? 'Open' : 'Closed'}</span></div>
    <div className="pills"><span className="pill">{label(job.job_type)}</span><span className="pill">{label(job.employment_time)}</span><span className="pill">{label(job.work_arrangement)}</span><span className="pill source-pill">Imported listing</span></div>
    <div className="job-bottom"><p className="job-date">Posted: {displayDate(job.posted_at)} · Last imported: {displayDate(job.last_imported_at)}</p>
      <Link className="view-link" to={'/jobs/' + job.job_id} aria-label={`View details: ${job.title}`}>View details <span aria-hidden="true">→</span></Link></div>
  </li>;
}
