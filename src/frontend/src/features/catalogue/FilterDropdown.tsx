import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { label } from './jobPresentation';

/** A disclosure containing native checkboxes, preserving multi-select filter semantics. */
export function FilterDropdown({ title, options, selected, open, onOpen, onChange, onClear }: {
  title: string; options: readonly string[]; selected: string[]; open: boolean;
  onOpen(open: boolean): void; onChange(value: string, checked: boolean): void; onClear(): void;
}) {
  const id = useId(), root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const firstOption = useRef<HTMLInputElement>(null), focusOnOpen = useRef(false);
  const [placement, setPlacement] = useState<{ above: boolean; maxHeight: number }>();
  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const rect = root.current?.getBoundingClientRect();
      if (!rect?.height) return;
      const nav = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--nav-height')) || 80;
      const viewport = window.visualViewport;
      const bottom = (viewport?.height ?? window.innerHeight) + (viewport?.offsetTop ?? 0);
      const below = bottom - rect.bottom - 16, above = rect.top - Math.max(nav, viewport?.offsetTop ?? 0) - 16;
      const openAbove = below < 240 && above > below;
      setPlacement({ above: openAbove, maxHeight: Math.max(100, Math.min(340, openAbove ? above : below)) });
    };
    measure(); window.addEventListener('resize', measure); window.addEventListener('scroll', measure, true);
    window.visualViewport?.addEventListener('resize', measure);
    return () => { window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true); window.visualViewport?.removeEventListener('resize', measure); };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    if (focusOnOpen.current) { firstOption.current?.focus(); focusOnOpen.current = false; }
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) onOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [open, onOpen]);
  const summary = selected.length ? selected.map(label).join(', ') : 'All';
  return <div ref={root} className="dropdown-filter" onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onOpen(false);
  }} onKeyDown={event => {
    if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); onOpen(false); trigger.current?.focus(); }
  }}>
    <button type="button" ref={trigger} className="dropdown-trigger" aria-expanded={open} aria-controls={id} onClick={() => onOpen(!open)}
      onKeyDown={event => { if (event.key === 'ArrowDown') { event.preventDefault(); if (open) firstOption.current?.focus(); else { focusOnOpen.current = true; onOpen(true); } } }}>
      <span className="drop-label">{title}</span><span className="drop-value">{summary}</span><span className="drop-caret" aria-hidden="true">⌄</span>
    </button>
    <div id={id} className="dropdown-menu" hidden={!open} data-above={placement?.above} style={placement ? { maxHeight: placement.maxHeight } : undefined}>
      <button type="button" className="dropdown-all" onClick={() => { onClear(); onOpen(false); trigger.current?.focus(); }}>All {title.toLowerCase()}</button>
      <fieldset><legend className="sr-only">{title}</legend>{options.map((value, index) => <label className="filter-option" data-selected={selected.includes(value)} key={value}>
        <input ref={index === 0 ? firstOption : undefined} type="checkbox" checked={selected.includes(value)} onChange={event => onChange(value, event.target.checked)} />
        <span>{label(value)}</span><span className="filter-tick" aria-hidden="true">{selected.includes(value) ? '✓' : ''}</span>
      </label>)}</fieldset><p className="filter-help">Select any that apply. Press Esc to close.</p>
    </div>
  </div>;
}
