import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { filterOptions, type FilterKey } from '../../api/contracts';
import { FilterDropdown } from './FilterDropdown';

export const SEARCH_DOCK_PIN_KEY = 'internshipMatcher.searchDockPinned';
const filterTitles: Record<FilterKey, string> = { job_type: 'Job type', employment_time: 'Employment time', work_arrangement: 'Work arrangement' };
export function SearchDock({ search, setSearch, params, onSearch, onFilter, onClearGroup, onReset }: {
  search: string; setSearch(value: string): void; params: URLSearchParams; onSearch(value: string): void;
  onFilter(key: FilterKey, value: string, checked: boolean): void; onClearGroup(key: FilterKey): void; onReset(): void;
}) {
  const input = useRef<HTMLInputElement>(null), dock = useRef<HTMLElement>(null);
  const [pinFits, setPinFits] = useState(true);
  const [open, setOpen] = useState<FilterKey | null>(null);
  const [pinned, setPinned] = useState(() => {
    try { const value = window.localStorage.getItem(SEARCH_DOCK_PIN_KEY); if (value !== null) return value === 'true'; } catch { /* preference is optional */ }
    return typeof window.matchMedia !== 'function' || !window.matchMedia('(max-width: 720px)').matches;
  });
  useLayoutEffect(() => {
    const measure = () => {
      const height = dock.current?.getBoundingClientRect().height;
      if (!height) return;
      document.documentElement.style.setProperty('--search-dock-height', `${height}px`);
      const nav = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--nav-height')) || 80;
      setPinFits((window.visualViewport?.height ?? window.innerHeight) >= nav + height + 180);
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure);
    if (dock.current) observer?.observe(dock.current);
    window.addEventListener('resize', measure); window.visualViewport?.addEventListener('resize', measure);
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); window.visualViewport?.removeEventListener('resize', measure); document.documentElement.style.removeProperty('--search-dock-height'); };
  }, []);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.ctrlKey || event.altKey || event.metaKey || event.isComposing || input.current?.closest('[inert]')) return;
      if (event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]')) return;
      event.preventDefault(); input.current?.focus();
    };
    document.addEventListener('keydown', shortcut);
    return () => document.removeEventListener('keydown', shortcut);
  }, []);
  function togglePin() {
    const next = !pinned; setPinned(next);
    // Only a non-sensitive display preference. Never persist search, account, or resume data.
    try { window.localStorage.setItem(SEARCH_DOCK_PIN_KEY, String(next)); } catch { /* state still works when storage is blocked */ }
  }
  function submit(value: string) { setOpen(null); onSearch(value); }
  return <section ref={dock} className="search-dock" data-pinned={pinned && pinFits} aria-label="Search and filter internships">
    <div className="dock-toolbar"><span>Find your next opportunity</span>
      <button type="button" className="pin-toggle" disabled={!pinFits} title={pinFits ? undefined : 'Pinning needs more screen space. Search stays in the normal page flow.'} aria-pressed={pinned && pinFits} onClick={togglePin} aria-label={pinned && pinFits ? 'Unpin search dock' : 'Pin search dock'}>
        <span aria-hidden="true">{pinned && pinFits ? '◆' : '◇'}</span>{!pinFits ? 'Pin unavailable' : pinned ? 'Unpin search' : 'Pin search'}
      </button>
    </div>
    <form className="search-command-row" onSubmit={event => { event.preventDefault(); submit(search); }}>
      <div className="command-search"><span className="search-icon" aria-hidden="true">⌕</span><div>
        <label htmlFor="keywords">Keywords</label><input id="keywords" ref={input} value={search} maxLength={200} autoComplete="off" onChange={event => setSearch(event.target.value)} placeholder="Role, skill or company — e.g. Python" aria-describedby="search-semantics" />
      </div><kbd aria-hidden="true">/</kbd></div><button className="search-submit">Search jobs <span aria-hidden="true">→</span></button>
    </form>
    <div className="filter-row"><span className="refine-label">Refine</span>
      {(Object.keys(filterOptions) as FilterKey[]).map(key => <FilterDropdown key={key} title={filterTitles[key]} options={filterOptions[key]} selected={params.getAll(key)} open={open === key}
        onOpen={value => setOpen(value ? key : null)} onChange={(value, checked) => onFilter(key, value, checked)} onClear={() => onClearGroup(key)} />)}
      <button type="button" className="reset-filters" onClick={() => { setOpen(null); onReset(); }}>Reset filters</button>
    </div>
    <div className="suggestion-row"><span>Try</span>{['Python', 'React', 'Software', 'Data'].map(value => <button type="button" key={value} onClick={() => { setSearch(value); submit(value); input.current?.focus(); }}>{value}</button>)}</div>
    <p className="search-help" id="search-semantics">Every keyword must appear in the title, company or description. Punctuation is literal. Any selected value within a filter group; all selected groups together.</p>
  </section>;
}
