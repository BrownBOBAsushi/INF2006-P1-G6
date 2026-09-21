import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router';
import { ApiClient, ApiError } from '../../api/client';
import { type FilterKey, type JobPage } from '../../api/contracts';
import { apiQuery, resetPage, validateQuery } from './query';

import { SearchDock } from './SearchDock';
import { JobCard } from './JobCard';
import { JobDetails } from './JobDetails';
export { label } from './jobPresentation';
export function Catalogue({ client, accessRevision = 0 }: { client: ApiClient; accessRevision?: number }) {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const signature = apiQuery(params).toString();
  const [search, setSearch] = useState(params.get('q') ?? '');
  const [page, setPage] = useState<JobPage | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
  const [desktopSplit, setDesktopSplit] = useState(() => typeof window === 'undefined' || typeof window.matchMedia !== 'function' || window.matchMedia('(min-width: 1001px)').matches);
  const selectedId = desktopSplit ? params.get('selected') : null;
  const previewId = selectedId ?? (desktopSplit ? page?.items[0]?.job_id ?? null : null);
  const selectedPane = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia('(min-width: 1001px)');
    const update = () => setDesktopSplit(media.matches);
    update(); media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, []);
  useEffect(() => { setSearch(params.get('q') ?? ''); }, [params]);
  useEffect(() => { if (selectedPane.current) selectedPane.current.scrollTop = 0; }, [previewId]);
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
    next.delete('selected');
    const selected = next.getAll(key).filter(item => item !== value);
    if (checked) selected.push(value);
    next.delete(key); selected.forEach(item => next.append(key, item));
    setParams(next); setNotice('');
  }
  function go(offset: number) {
    if (!page) return;
    const next = new URLSearchParams(params);
    next.delete('selected');
    next.set('offset', String(offset)); next.set('catalogue_revision', String(page.catalogue_revision));
    setParams(next);
  }
  function searchJobs(value: string) {
    const next = resetPage(params); value.trim() ? next.set('q', value.trim()) : next.delete('q');
    next.delete('selected');
    setParams(next); setNotice('');
  }
  function clearGroup(key: FilterKey) {
    const next = resetPage(params); next.delete(key); next.delete('selected'); setParams(next); setNotice('');
  }
  const returnTo = `${location.pathname}${location.search}`;
  function selectionHref(jobId: string) {
    const next = new URLSearchParams(params); next.set('selected', jobId);
    return `/jobs?${next.toString()}`;
  }
  return <section>
    <div className="page-head"><h1>Browse internships</h1>
      <p className="page-intro">Search active listings by role, skill, or company.</p></div>
    <SearchDock search={search} setSearch={setSearch} params={params} onSearch={searchJobs} onFilter={changeFilter} onClearGroup={clearGroup} onReset={() => { setParams({}); setNotice(''); }} />
    <div className="jobs-layout"><div className="jobs-results">
      {notice && <p className="notice" role="status">{notice}</p>}
      {error ? <div className="panel" role="alert"><h2>We couldn’t load the catalogue</h2><p>{error}</p><button onClick={() => setRetry(value => value + 1)}>Retry loading jobs</button></div> :
        !page ? <div className="panel loading-panel" aria-busy="true"><p role="status">Loading jobs…</p><div className="skeleton" aria-hidden="true" /></div> : <>
          <p className="jobs-meta" role="status">{page.total} active opportunities</p>
          {!page.items.length && <div className="panel empty-state"><p className="eyebrow">Keep exploring</p><h2>No jobs found</h2><p>Try fewer keywords or change your filters.</p><button className="button-secondary" onClick={() => { setParams({}); setNotice(''); }}>Clear search and filters</button></div>}
          <ul className="job-list">{page.items.map(job => <JobCard job={job} key={job.job_id} selected={previewId === job.job_id}
            selectHref={desktopSplit ? selectionHref(job.job_id) : `/jobs/${job.job_id}`} returnTo={returnTo} />)}</ul>
          <nav className="actions pagination" aria-label="Pagination"><button className="button-secondary" disabled={page.offset === 0} onClick={() => go(Math.max(0, page.offset - page.limit))}>Previous</button>
            <span>Page {Math.floor(page.offset / page.limit) + 1}</span><button className="button-secondary" disabled={page.offset + page.limit >= page.total || page.offset + page.limit > 10000} onClick={() => go(page.offset + page.limit)}>Next</button></nav>
        </>}
    </div>{desktopSplit && <div ref={selectedPane} className="selected-job-pane" role="complementary" aria-label="Selected job">
      {previewId ? <JobDetails client={client} accessRevision={accessRevision} jobId={previewId} inline /> : <div className="selected-job-empty"><p className="eyebrow">Selected job</p><h2>Choose a listing to preview</h2><p>Job details will stay beside the results while you compare opportunities.</p><Link to="/resume">Resume workspace <span aria-hidden="true">→</span></Link></div>}
    </div>}</div>
  </section>;
}
