import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ApiClient, ApiError } from '../../api/client';
import type { FilterKey, MatchItem, MatchPage } from '../../api/contracts';
import { apiQuery, resetPage, validateQuery } from '../catalogue/query';
import { JobCard } from '../catalogue/JobCard';
import { SearchDock } from '../catalogue/SearchDock';

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

function Evidence({ item }: { item: MatchItem }) {
  return <div className="match-explanations">
    {item.requirements.map(requirement => <section className="match-requirement" key={requirement.requirement_id}>
      <p className="match-requirement-label">{requirement.importance === 'REQUIRED' ? 'Required' : 'Preferred'} requirement</p>
      <p className="match-requirement-text">{requirement.requirement_text}</p>
      <p className="match-passage"><strong>Closest resume passage</strong><br />{requirement.closest_passage.text}</p>
      {requirement.explicit_skill_evidence.length > 0 && <p className="match-evidence"><strong>Named skills evidenced</strong>: {requirement.explicit_skill_evidence.join(', ')}</p>}
      {requirement.named_skills_not_evidenced.length > 0 && <p className="match-missing"><strong>Named skills not evidenced</strong>: {requirement.named_skills_not_evidenced.join(', ')}</p>}
    </section>)}
    {item.eligibility_notes.length > 0 && <section className="match-eligibility"><p className="match-requirement-label">Eligibility notes</p><ul>{item.eligibility_notes.map((note, index) => <li key={index}>{note.text}</li>)}</ul></section>}
  </div>;
}

function MatchCard({ item }: { item: MatchItem }) {
  return <JobCard job={item.job}><Evidence item={item} /></JobCard>;
}

export function Matches({ client, accessRevision = 0 }: { client: ApiClient; accessRevision?: number }) {
  const [params, setParams] = useSearchParams();
  const signature = params.toString();
  const [search, setSearch] = useState(params.get('q') ?? '');
  const [page, setPage] = useState<MatchPage | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => setSearch(params.get('q') ?? ''), [params]);
  useEffect(() => {
    const query = apiQuery(params);
    const profileRevision = params.get('profile_revision');
    if (profileRevision !== null) query.set('profile_revision', profileRevision);
    const invalid = validateQuery(query) ?? (profileRevision !== null &&
      (!/^\d+$/u.test(profileRevision) || !Number.isSafeInteger(Number(profileRevision)))
      ? 'Invalid resume revision.' : null);
    setPage(null); setError('');
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

  function changeFilter(key: FilterKey, value: string, checked: boolean) {
    const next = resetPage(params); const selected = next.getAll(key).filter(item => item !== value);
    if (checked) selected.push(value);
    next.delete(key); selected.forEach(item => next.append(key, item)); setParams(next); setNotice('');
  }
  function clearGroup(key: FilterKey) { const next = resetPage(params); next.delete(key); setParams(next); setNotice(''); }
  function searchMatches(value: string) { const next = resetPage(params); value.trim() ? next.set('q', value.trim()) : next.delete('q'); setParams(next); setNotice(''); }
  function go(offset: number) {
    if (!page) return;
    const next = new URLSearchParams(params);
    next.set('offset', String(offset)); next.set('limit', String(page.limit));
    next.set('catalogue_revision', String(page.catalogue_revision)); next.set('profile_revision', String(page.profile_revision)); setParams(next);
  }
  return <section className="matches-shell" aria-labelledby="matches-heading">
    <div className="matches-hero"><p className="eyebrow">Based on your saved resume</p><h1 id="matches-heading">Recommendations</h1><p>Read the requirements alongside the closest passages from your resume. The listing source stays in view.</p></div>
    <SearchDock search={search} setSearch={setSearch} params={params} onSearch={searchMatches} onFilter={changeFilter} onClearGroup={clearGroup} onReset={() => { setParams({}); setNotice(''); }} />
    {notice && <p className="notice" role="status">{notice}</p>}
    {error ? <div className="panel matches-state" role="alert"><h2>Recommendations are not ready</h2><p>{error}</p><div className="actions"><button onClick={() => setRetry(value => value + 1)}>Retry recommendations</button>{/resume before|project or experience/i.test(error) && <Link className="button-secondary" to="/resume">Review resume</Link>}</div></div> : !page ? <div className="panel matches-state" aria-busy="true"><p role="status">Loading recommendations…</p></div> : <>
      <p className="jobs-meta" role="status">{page.total} recommendation{page.total === 1 ? '' : 's'}</p>
      {!page.items.length ? <div className="panel empty-state"><p className="eyebrow">No recommendations yet</p><h2>No matching opportunities found</h2><p>Try a different search or filter.</p></div> : <ul className="job-list matches-list">{page.items.map(item => <MatchCard item={item} key={item.job.job_id} />)}</ul>}
      <nav className="actions pagination" aria-label="Recommendation pagination"><button className="button-secondary" disabled={page.offset === 0} onClick={() => go(Math.max(0, page.offset - page.limit))}>Previous</button><span>Page {Math.floor(page.offset / page.limit) + 1}</span><button className="button-secondary" disabled={page.offset + page.limit >= page.total} onClick={() => go(page.offset + page.limit)}>Next</button></nav>
    </>}
  </section>;
}
