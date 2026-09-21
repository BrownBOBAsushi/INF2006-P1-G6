import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ApiClient, ApiError } from '../../api/client';
import { type FilterKey, type JobPage } from '../../api/contracts';
import { apiQuery, resetPage, validateQuery } from './query';

import { SearchDock } from './SearchDock';
import { JobCard } from './JobCard';
export { label } from './jobPresentation';
export function Catalogue({ client, accessRevision = 0 }: { client: ApiClient; accessRevision?: number }) {
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
  }, [client, signature, retry, setParams, accessRevision]);
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
  function searchJobs(value: string) {
    const next = resetPage(params); value.trim() ? next.set('q', value.trim()) : next.delete('q');
    setParams(next); setNotice('');
  }
  function clearGroup(key: FilterKey) {
    const next = resetPage(params); next.delete(key); setParams(next); setNotice('');
  }
  return <section>
    <div className="page-head"><div><span className="catalogue-status">Imported catalogue</span>
      <p className="eyebrow">Find your next step</p><h1>Browse internships</h1>
      <p className="page-intro">Find work that fits how you want to grow. Explore opportunities with or without a resume.</p></div></div>
    <SearchDock search={search} setSearch={setSearch} params={params} onSearch={searchJobs} onFilter={changeFilter} onClearGroup={clearGroup} onReset={() => { setParams({}); setNotice(''); }} />
    <div className="jobs-layout"><div>
      {notice && <p className="notice" role="status">{notice}</p>}
      {error ? <div className="panel" role="alert"><h2>We couldn’t load the catalogue</h2><p>{error}</p><button onClick={() => setRetry(value => value + 1)}>Retry loading jobs</button></div> :
        !page ? <div className="panel loading-panel" aria-busy="true"><p role="status">Loading jobs…</p><div className="skeleton" aria-hidden="true" /></div> : <>
          <p className="jobs-meta" role="status">{page.total} active opportunities</p>
          {!page.items.length && <div className="panel empty-state"><p className="eyebrow">Keep exploring</p><h2>No jobs found</h2><p>Try fewer keywords or change your filters.</p><button className="button-secondary" onClick={() => { setParams({}); setNotice(''); }}>Clear search and filters</button></div>}
          <ul className="job-list">{page.items.map(job => <JobCard job={job} key={job.job_id} />)}</ul>
          <nav className="actions pagination" aria-label="Pagination"><button className="button-secondary" disabled={page.offset === 0} onClick={() => go(Math.max(0, page.offset - page.limit))}>Previous</button>
            <span>Page {Math.floor(page.offset / page.limit) + 1}</span><button className="button-secondary" disabled={page.offset + page.limit >= page.total || page.offset + page.limit > 10000} onClick={() => go(page.offset + page.limit)}>Next</button></nav>
        </>}
    </div><aside className="catalogue-aside"><p className="eyebrow">A little clarity</p><h2>Your next step starts with a closer look.</h2>
      <p>Compare the role, requirements and eligibility notes before you apply. Import dates tell you when a listing entered the catalogue.</p>
      <hr /><h3>A resume is optional</h3><p>You can browse every active opportunity now and add your details when you’re ready.</p>
      <Link to="/resume">Open resume workspace <span aria-hidden="true">→</span></Link>
    </aside></div>
  </section>;
}
