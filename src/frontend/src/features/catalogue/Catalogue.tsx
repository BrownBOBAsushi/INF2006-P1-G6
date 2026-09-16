import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ApiClient, ApiError } from '../../api/client';
import { filterOptions, type FilterKey, type JobPage } from '../../api/contracts';
import { apiQuery, resetPage, validateQuery } from './query';

export const label = (value: string) => value.toLowerCase().replaceAll('_', ' ');
export function Catalogue({ client }: { client: ApiClient }) {
  const [params, setParams] = useSearchParams();
  const signature = apiQuery(params).toString();
  const [search, setSearch] = useState(params.get('q') ?? '');
  const [page, setPage] = useState<JobPage | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => { setSearch(params.get('q') ?? ''); }, [params]);
  useEffect(() => {
    const query = new URLSearchParams(signature);
    const invalid = validateQuery(query);
    setPage(null); setError('');
    if (invalid) { setError(invalid); return; }
    const controller = new AbortController();
    let active = true;
    void client.json<JobPage>({ method: 'GET', path: '/api/jobs?' + signature, signal: controller.signal })
      .then(result => { if (active) setPage(result); })
      .catch(cause => {
        if (!active) return;
        if (cause instanceof ApiError && cause.code === 'RESULTS_CHANGED') {
          setNotice('The catalogue changed. Results restarted from the first page.');
          setParams(resetPage(query), { replace: true });
        } else setError('Jobs could not load. Please retry.');
      });
    return () => { active = false; controller.abort(); };
  }, [client, signature, retry, setParams]);
  function changeFilter(key: FilterKey, value: string, checked: boolean) {
    const next = resetPage(params);
    const selected = next.getAll(key).filter(item => item !== value);
    if (checked) selected.push(value);
    next.delete(key); selected.forEach(item => next.append(key, item));
    setParams(next); setNotice('');
  }
  function go(offset: number) {
    if (!page) return;
    const next = new URLSearchParams(params);
    next.set('offset', String(offset)); next.set('catalogue_revision', String(page.catalogue_revision));
    setParams(next);
  }
  return <section>
    <p className="eyebrow">Find your next step</p><h1>Browse internships</h1>
    <p>Explore opportunities. A resume is optional.</p>
    <form className="search" onSubmit={event => {
      event.preventDefault();
      const next = resetPage(params); search.trim() ? next.set('q', search.trim()) : next.delete('q');
      setParams(next); setNotice('');
    }}>
      <label htmlFor="keywords">Keywords</label><input id="keywords" value={search} maxLength={200} onChange={event => setSearch(event.target.value)} placeholder="Python software" />
      <button>Search jobs</button>
      <small>Every term must appear in the title, company or description. Punctuation is literal.</small>
    </form>
    <div className="catalogue-layout"><aside className="panel" aria-label="Job filters">
      {(Object.keys(filterOptions) as FilterKey[]).map(key => <fieldset key={key}>
        <legend>{label(key)}</legend>{filterOptions[key].map(value => <label className="check" key={value}>
          <input type="checkbox" checked={params.getAll(key).includes(value)} onChange={event => changeFilter(key, value, event.target.checked)} />{label(value)}
        </label>)}
      </fieldset>)}
      <p className="muted">Any selected value within a group; all selected groups together.</p>
      <button onClick={() => { setParams({}); setNotice(''); }}>Clear search and filters</button>
    </aside><div>
      {notice && <p role="status">{notice}</p>}
      {error ? <div role="alert"><p>{error}</p><button onClick={() => setRetry(value => value + 1)}>Retry loading jobs</button></div> :
        !page ? <p role="status">Loading jobs…</p> : <>
          <p role="status">{page.total} active opportunities</p>
          {!page.items.length && <div className="panel"><h2>No jobs found</h2><p>Try fewer keywords or change your filters.</p></div>}
          <ul className="job-list">{page.items.map(job => <li className="panel" key={job.job_id}>
            <p className="muted">{job.company_name}</p><h2><Link to={'/jobs/' + job.job_id}>{job.title}</Link></h2>
            <p>{job.location} · {label(job.employment_time)} · {label(job.work_arrangement)}</p>
            <p className="muted">Posted: {job.posted_at?.slice(0, 10) ?? 'Unknown'} · Last imported: {job.last_imported_at.slice(0, 10)}</p>
          </li>)}</ul>
          <nav className="actions" aria-label="Pagination"><button disabled={page.offset === 0} onClick={() => go(Math.max(0, page.offset - page.limit))}>Previous</button>
          <span>Page {Math.floor(page.offset / page.limit) + 1}</span>
          <button disabled={page.offset + page.limit >= page.total || page.offset + page.limit > 10000} onClick={() => go(page.offset + page.limit)}>Next</button></nav>
        </>}
    </div></div>
  </section>;
}
