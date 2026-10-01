import { useEffect, useId, useRef, useState, type RefObject } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ApiClient, ApiError } from '../../api/client';
import { filterOptions, type FilterKey, type JobDetail, type MatchItem, type MatchPage } from '../../api/contracts';
import { apiQuery, resetPage, validateQuery } from '../catalogue/query';
import { initials, label } from '../catalogue/jobPresentation';
import { safeExternalUrl } from '../catalogue/JobDetails';

const filterLabels: Record<FilterKey, string> = { job_type: 'Job type', employment_time: 'Employment', work_arrangement: 'Work arrangement' };

function stateMessage(error: ApiError): string {
  switch (error.code) {
    case 'RESUME_REQUIRED': return 'Save your resume before viewing recommendations.';
    case 'INSUFFICIENT_RESUME_INFORMATION': return 'Add a project or experience entry to get recommendations.';
    case 'MODEL_VERSION_UNAVAILABLE': return 'Recommendations are temporarily unavailable.';
    case 'AUTH_REQUIRED':
    case 'SESSION_EXPIRED': return 'Your session ended. Reconnect to load recommendations again.';
    default: return error.status >= 500 ? 'Recommendations are temporarily unavailable.' : 'Recommendations could not load. Please retry.';
  }
}

function knownFact(value: string, title: string) {
  return value === 'UNKNOWN' ? null : <span className="matches-fact" key={title}>{label(value)}</span>;
}

function MatchEvidence({ item }: { item: MatchItem }) {
  const idPrefix = useId();
  const [openRequirementId, setOpenRequirementId] = useState<string | null>(item.requirements[0]?.requirement_id ?? null);
  const [expandedPassageId, setExpandedPassageId] = useState<string | null>(null);
  useEffect(() => {
    setOpenRequirementId(item.requirements[0]?.requirement_id ?? null);
    setExpandedPassageId(null);
  }, [item.job.job_id, item.requirements]);
  return <section className="matches-evidence" aria-labelledby={idPrefix + '-heading'}>
    <h3 id={idPrefix + '-heading'}>Related resume evidence</h3>
    <p className="matches-evidence-note">Similar wording is not proof that a requirement is met.</p>
    {item.requirements.length ? <div className="matches-requirements">{item.requirements.map((requirement, index) => {
      const isOpen = openRequirementId === requirement.requirement_id;
      const expanded = expandedPassageId === requirement.requirement_id;
      const passage = requirement.closest_passage.text;
      const preview = passage.length > 240 ? passage.slice(0, 240).replace(/\s+\S*$/u, '') + '…' : passage;
      const panelId = idPrefix + '-passage-' + index;
      return <section className="matches-requirement" key={requirement.requirement_id}>
        <button type="button" className="matches-requirement-toggle" aria-expanded={isOpen} aria-controls={panelId}
          onClick={() => setOpenRequirementId(current => current === requirement.requirement_id ? null : requirement.requirement_id)}>
          <span>{requirement.requirement_text}</span><span className="matches-requirement-kind">{requirement.importance === 'REQUIRED' ? 'Required' : 'Preferred'}</span>
          <span className="matches-chevron" aria-hidden="true">{isOpen ? '⌃' : '⌄'}</span>
        </button>
        {isOpen && <div className="matches-requirement-content" id={panelId}>
          <blockquote className="matches-passage"><span className="matches-passage-label">Resume passage · {label(requirement.closest_passage.section)}</span>
            {expanded ? passage : preview}
          </blockquote>
          {passage.length > 240 && <button className="matches-text-button" type="button" aria-expanded={expanded}
            onClick={() => setExpandedPassageId(current => current === requirement.requirement_id ? null : requirement.requirement_id)}>{expanded ? 'Show less' : 'Read full passage'} <span aria-hidden="true">→</span></button>}
          {requirement.explicit_skill_evidence.length > 0 && <p className="matches-skill-evidence"><strong>Named skills evidenced</strong> · {requirement.explicit_skill_evidence.join(', ')}</p>}
          {requirement.named_skills_not_evidenced.length > 0 && <p className="matches-skill-missing"><strong>Not evidenced in this resume</strong> · {requirement.named_skills_not_evidenced.join(', ')}</p>}
        </div>}
      </section>;
    })}</div> : <p className="matches-evidence-note">No related resume passages were returned for this listing.</p>}
  </section>;
}

function MatchDetails({ item, job, loading, error, retry, onBack, focusRef }: {
  item: MatchItem; job: JobDetail | null; loading: boolean; error: string; retry(): void;
  onBack(): void; focusRef: RefObject<HTMLHeadingElement | null>;
}) {
  const idPrefix = useId();
  const source = job ? safeExternalUrl(job.source_url) : undefined;
  const apply = job ? safeExternalUrl(job.apply_url) : undefined;
  return <article className="matches-detail panel" aria-labelledby={idPrefix + '-title'}>
    <button type="button" className="matches-back button-secondary" onClick={onBack}>← Back to results</button>
    <header className="matches-detail-heading">
      <span className="matches-company-mark" aria-hidden="true">{initials(item.job.company_name) || '·'}</span>
      <div className="matches-detail-company"><p>{item.job.company_name}</p><p>{item.job.location}</p></div>
      {source && <a className="matches-source-link" href={source} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Original listing <span aria-hidden="true">↗</span></a>}
      <h2 ref={focusRef} tabIndex={-1} id={idPrefix + '-title'}>{item.job.title}</h2>
      <div className="matches-facts" aria-label="Job details">{knownFact(item.job.job_type, 'Job type')}{knownFact(item.job.employment_time, 'Employment')}{knownFact(item.job.work_arrangement, 'Work arrangement')}</div>
    </header>
    {loading && <div className="matches-detail-state" aria-busy="true"><p role="status">Loading listing details…</p><div className="skeleton" aria-hidden="true" /></div>}
    {error && <div className="matches-detail-state" role="alert"><p>{error}</p>{error !== 'This listing is no longer available.' && <button className="button-secondary" type="button" onClick={retry}>Retry loading details</button>}</div>}
    <section className="matches-eligibility" aria-labelledby={idPrefix + '-eligibility'}>
        <h3 id={idPrefix + '-eligibility'}>Eligibility notes</h3>
        {item.eligibility_notes.length ? <ul>{item.eligibility_notes.map((note, index) => <li key={index}>{note.text}{note.source_quote && note.source_quote !== note.text && <blockquote>{note.source_quote}</blockquote>}</li>)}</ul>
          : <p>No source-provided eligibility notes are available. Review the employer’s requirements before applying.</p>}
    </section>
    <MatchEvidence item={item} />
    {job && <>
      <details className="matches-description"><summary>Full job description</summary><p className="preserve">{job.description || 'No job description was supplied with this listing.'}</p></details>
      <div className="matches-apply">
        {job.is_active && apply ? <a className="matches-apply-link" href={apply} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">View application <span aria-hidden="true">→</span></a>
          : <button type="button" disabled>Application unavailable</button>}
        <span>{job.is_active ? 'Opens the employer’s site' : 'This listing is closed'}</span>
      </div>
    </>}
  </article>;
}

export function Matches({ client, accessRevision = 0 }: { client: ApiClient; accessRevision?: number }) {
  const [params, setParams] = useSearchParams();
  const signature = params.toString();
  const [search, setSearch] = useState(params.get('q') ?? '');
  const [page, setPage] = useState<MatchPage | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
  const [detailRetry, setDetailRetry] = useState(0);
  const [selectedId, setSelectedId] = useState('');
  const [jobState, setJobState] = useState<{ id: string; revision: number; job: JobDetail } | null>(null);
  const [detailErrorState, setDetailErrorState] = useState<{ id: string; revision: number; message: string } | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [mobile, setMobile] = useState(() => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 720px)').matches);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [listScrollY, setListScrollY] = useState(0);
  const resultRefs = useRef(new Map<string, HTMLButtonElement>());
  const detailHeadingRef = useRef<HTMLHeadingElement>(null);
  const selectedItem = page?.items.find(item => item.job.job_id === selectedId) ?? null;
  const job = jobState?.id === selectedId && jobState.revision === accessRevision ? jobState.job : null;
  const detailError = detailErrorState?.id === selectedId && detailErrorState.revision === accessRevision ? detailErrorState.message : '';

  useEffect(() => setSearch(params.get('q') ?? ''), [params]);
  useEffect(() => {
    const media = window.matchMedia?.('(max-width: 720px)');
    if (!media) return;
    const update = () => {
      setMobile(media.matches);
      if (media.matches) setMobileDetailOpen(false);
    };
    update(); media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, []);
  useEffect(() => {
    const query = apiQuery(params);
    const profileRevision = params.get('profile_revision');
    if (profileRevision !== null) query.set('profile_revision', profileRevision);
    const invalid = validateQuery(query) ?? (profileRevision !== null &&
      (!/^\d+$/u.test(profileRevision) || !Number.isSafeInteger(Number(profileRevision))) ? 'Invalid resume revision.' : null);
    setPage(null); setSelectedId(''); setJobState(null); setDetailErrorState(null); setError('');
    if (invalid) { setError(invalid); return; }
    const controller = new AbortController();
    let active = true;
    void client.json<MatchPage>({ method: 'GET', path: '/api/matches?' + query.toString(), signal: controller.signal })
      .then(result => { if (active) setPage(result); })
      .catch(cause => {
        if (!active) return;
        if (cause instanceof ApiError && cause.code === 'RESULTS_CHANGED') {
          setNotice('Recommendations restarted because the catalogue or resume changed.');
          setParams(resetPage(query), { replace: true });
        } else setError(cause instanceof ApiError ? stateMessage(cause) : 'Recommendations could not load. Please retry.');
      });
    return () => { active = false; controller.abort(); };
  }, [client, signature, retry, setParams, accessRevision]);

  useEffect(() => {
    if (!page) { setSelectedId(''); setMobileDetailOpen(false); return; }
    setSelectedId(page.items[0]?.job.job_id ?? '');
    setMobileDetailOpen(false);
  }, [page]);
  useEffect(() => {
    setJobState(null); setDetailErrorState(null);
    if (!selectedItem) return;
    const controller = new AbortController();
    let active = true;
    void client.json<JobDetail>({ method: 'GET', path: '/api/jobs/' + encodeURIComponent(selectedItem.job.job_id), signal: controller.signal })
      .then(result => {
        if (!active) return;
        if (result.job_id !== selectedItem.job.job_id) setDetailErrorState({ id: selectedItem.job.job_id, revision: accessRevision, message: 'This listing could not be loaded.' });
        else setJobState({ id: selectedItem.job.job_id, revision: accessRevision, job: result });
      })
      .catch(cause => {
        if (!active) return;
        const message = cause instanceof ApiError && cause.status === 404 ? 'This listing is no longer available.' : 'This listing could not be loaded.';
        setDetailErrorState({ id: selectedItem.job.job_id, revision: accessRevision, message });
      });
    return () => { active = false; controller.abort(); };
  }, [client, selectedItem?.job.job_id, detailRetry, accessRevision]);

  function changeFilter(key: FilterKey, value: string, checked: boolean) {
    const next = resetPage(params); const selected = next.getAll(key).filter(item => item !== value);
    if (checked) selected.push(value);
    next.delete(key); selected.forEach(item => next.append(key, item)); setParams(next); setNotice('');
  }
  function removeFilter(key: FilterKey, value: string) {
    const next = resetPage(params); const selected = next.getAll(key).filter(item => item !== value);
    next.delete(key); selected.forEach(item => next.append(key, item)); setParams(next); setNotice('');
  }
  function searchMatches(value: string) { const next = resetPage(params); value.trim() ? next.set('q', value.trim()) : next.delete('q'); setParams(next); setNotice(''); }
  function clearFilters() {
    const next = resetPage(params);
    (Object.keys(filterOptions) as FilterKey[]).forEach(key => next.delete(key));
    setParams(next); setNotice('');
  }
  function go(offset: number) {
    if (!page) return;
    const next = new URLSearchParams(params);
    next.set('offset', String(offset)); next.set('limit', String(page.limit));
    next.set('catalogue_revision', String(page.catalogue_revision)); next.set('profile_revision', String(page.profile_revision)); setParams(next);
  }
  function choose(item: MatchItem) {
    if (mobile && !mobileDetailOpen) setListScrollY(window.scrollY);
    setSelectedId(item.job.job_id); setDetailErrorState(null); setMobileDetailOpen(mobile);
    if (mobile) requestAnimationFrame(() => detailHeadingRef.current?.focus());
  }
  function backToResults() {
    setMobileDetailOpen(false);
    if (mobile) requestAnimationFrame(() => {
      window.scrollTo({ top: listScrollY, behavior: 'auto' });
      if (selectedId) resultRefs.current.get(selectedId)?.focus();
    });
  }
  const filters = (Object.keys(filterOptions) as FilterKey[]).flatMap(key => params.getAll(key).map(value => ({ key, value })));
  const detailReady = Boolean(job && job.job_id === selectedId);

  return <section className="matches-shell" aria-labelledby="matches-heading">
    <header className="matches-hero">
      <h1 id="matches-heading">Find your next internship</h1>
      <p>Jobs are ranked by how closely their requirements match the meaning of your projects and experience.</p>
      <details className="matches-ranking-help"><summary>How ranking works</summary><p>Recommendations compare job requirements with passages from your saved resume. Named skills are checked separately. Similarity is not proof that you meet a requirement or are eligible.</p></details>
    </header>
    <div className="matches-search-row">
      <form className="matches-search" role="search" onSubmit={event => { event.preventDefault(); searchMatches(search); }}>
        <label className="sr-only" htmlFor="matches-search-input">Search jobs</label>
        <span aria-hidden="true">⌕</span><input id="matches-search-input" type="search" role="searchbox" aria-label="Search jobs" value={search} maxLength={200} autoComplete="off" onChange={event => setSearch(event.target.value)} placeholder="Search role, skill or company" />
        <button type="submit">Search</button>
      </form>
      <button className="matches-filter-trigger button-secondary" type="button" aria-expanded={filtersOpen} aria-controls="matches-filter-options" onClick={() => setFiltersOpen(open => !open)}>☷ <span>Filters</span>{filters.length > 0 && <span className="matches-filter-count">{filters.length}</span>}</button>
    </div>
    {filtersOpen && <div className="matches-filter-options" id="matches-filter-options">{(Object.keys(filterOptions) as FilterKey[]).map(key =>
      <fieldset key={key}><legend>{filterLabels[key]}</legend>{filterOptions[key].map(value => <label key={value}>
        <input type="checkbox" checked={params.getAll(key).includes(value)} onChange={event => changeFilter(key, value, event.target.checked)} />{label(value)}
      </label>)}</fieldset>)}<button className="button-quiet" type="button" onClick={clearFilters}>Clear all filters</button></div>}
    {filters.length > 0 && <div className="matches-active-filters" aria-label="Active filters">{filters.map(({ key, value }) => <button type="button" key={`${key}-${value}`} aria-label={`${label(value)}, remove filter`} onClick={() => removeFilter(key, value)}>{label(value)} <span aria-hidden="true">×</span></button>)}</div>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {error ? <div className="panel matches-state" role="alert"><h2>Recommendations are not ready</h2><p>{error}</p><div className="actions"><button onClick={() => setRetry(value => value + 1)}>Retry recommendations</button>{/resume before|project or experience/i.test(error) && <Link className="button-secondary" to="/resume">Review resume</Link>}</div></div>
      : !page ? <div className="panel matches-state" aria-busy="true"><p role="status">Loading recommendations…</p></div>
        : <>
          <p className="matches-total" role="status">{page.total} {page.total === 1 ? 'job' : 'jobs'} ranked by resume similarity</p>
          {!page.items.length ? <div className="panel empty-state"><h2>No matching opportunities found</h2><p>Try another search or change your filters.</p></div> : <div className={`matches-results${mobileDetailOpen ? ' mobile-detail-open' : ''}`}>
            <div className="matches-list-column" hidden={mobile && mobileDetailOpen}>
              <ul className="matches-list" aria-label="Jobs ranked by resume similarity">{page.items.map(item => <li key={item.job.job_id}>
                <button ref={element => { if (element) resultRefs.current.set(item.job.job_id, element); else resultRefs.current.delete(item.job.job_id); }}
                  className={`matches-result${selectedId === item.job.job_id ? ' selected' : ''}`} type="button" aria-current={selectedId === item.job.job_id ? 'true' : undefined} onClick={() => choose(item)}>
                  <span className="matches-company-mark" aria-hidden="true">{initials(item.job.company_name) || '·'}</span><span className="matches-result-copy"><strong>{item.job.title}</strong><span>{item.job.company_name} <span aria-hidden="true">·</span> {item.job.location}</span><span className="matches-facts">{knownFact(item.job.job_type, 'Job type')}{knownFact(item.job.work_arrangement, 'Work arrangement')}</span></span><span className="matches-result-arrow" aria-hidden="true">›</span>
                </button>
              </li>)}</ul>
              <nav className="matches-pagination" aria-label="Recommendation pagination"><button className="button-secondary" disabled={page.offset === 0} onClick={() => go(Math.max(0, page.offset - page.limit))}>← <span>Previous</span></button><span>Page {Math.floor(page.offset / page.limit) + 1}</span><button className="button-secondary" disabled={page.offset + page.limit >= page.total} onClick={() => go(page.offset + page.limit)}><span>Next</span> →</button></nav>
            </div>
            <div className="matches-detail-column" hidden={mobile && !mobileDetailOpen}>
              {selectedItem ? <MatchDetails item={selectedItem} job={detailReady ? job : null} loading={!detailReady && !detailError} error={detailError}
                retry={() => setDetailRetry(value => value + 1)} onBack={backToResults} focusRef={detailHeadingRef} />
                : <div className="matches-detail-empty panel"><p>Select a job to review its resume evidence.</p></div>}
            </div>
          </div>}
        </>}
  </section>;
}
