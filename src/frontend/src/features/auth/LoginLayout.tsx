import { useEffect, useRef, useState, type ReactNode } from 'react';

const HERO_ROLES = ['software engineer.', 'data scientist.', 'financial analyst.', 'product designer.'] as const;

/** Presentation only: authentication controls and session actions belong in App. */
export function LoginLayout({ children, open, onOpen, onClose }: {
  children: ReactNode; open: boolean; onOpen(): void; onClose(): void;
}) {
  const dialog = useRef<HTMLElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const [roleIndex, setRoleIndex] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(() => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReducedMotion(preference.matches);
    update(); preference.addEventListener?.('change', update);
    return () => preference.removeEventListener?.('change', update);
  }, []);
  useEffect(() => {
    if (reducedMotion) return;
    const timer = window.setInterval(() => setRoleIndex(index => (index + 1) % HERO_ROLES.length), 2600);
    return () => window.clearInterval(timer);
  }, [reducedMotion]);
  useEffect(() => {
    if (open) return;
    const target = previousFocus.current;
    previousFocus.current = null;
    if (target?.isConnected) target.focus({ preventScroll: true });
  }, [open]);
  useEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.focus();
    const firstControl = dialog.current?.querySelector<HTMLElement>('input:not(:disabled), .google-control button:not(:disabled), .google-control iframe');
    firstControl?.focus({ preventScroll: true });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); return; }
      if (event.key !== 'Tab' || !dialog.current) return;
      const controls = [...dialog.current.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), iframe, [tabindex="0"]')]
        .filter(element => !element.closest('[hidden], [aria-hidden="true"], [inert]'));
      const first = controls[0], last = controls.at(-1);
      if (!first || !last) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose]);

  return <div className="login-layout">
    <section className="login-visual" aria-label="Discover internships">
      <div className="login-backdrop-letter" aria-hidden="true">I</div>
      <div className="login-hero-grid">
        <div className="login-copy">
          <p className="eyebrow">A clearer starting point for student work</p>
          <h1>I want to be a<br /><span className="hero-role-slot" data-testid="hero-role" aria-hidden="true"><span key={roleIndex} className="hero-role">{HERO_ROLES[roleIndex]}</span></span><span className="sr-only">{HERO_ROLES[0]}</span></h1>
          <div className="login-hero-footer"><p>Search active internship listings with the role, requirements, and source details in view. Take the next step when the work makes sense for you.</p><button type="button" className="login-cta" onClick={onOpen}>Explore opportunities <span aria-hidden="true">→</span></button></div>
        </div>
        <aside className="login-preview" aria-label="How Internship Matcher helps">
          <div className="login-preview-top"><span>Internship Matcher</span><span className="login-preview-index">01 / 03</span></div>
          <p className="login-preview-title">Read the brief<br />before you commit.</p>
          <p className="login-preview-copy">Compare the source, requirements, and working arrangement before opening an application.</p>
          <div className="login-preview-meta"><span>Source linked</span><span>Context first</span></div>
        </aside>
      </div>
    </section>
    <section id="login-how" className="login-how">
      <div><p className="eyebrow">The useful part</p><h2>Less hunting.<br />Better reading.</h2></div>
      <div className="login-steps"><article><span>01</span><h3>Search with intent</h3><p>Start with a role, skill, or company and keep the search readable.</p></article><article><span>02</span><h3>Check the actual brief</h3><p>Requirements and source context sit beside the listing you are considering.</p></article><article><span>03</span><h3>Choose your next move</h3><p>Open the employer’s source website when you are ready to apply.</p></article></div>
    </section>
    <section id="login-principles" className="login-principles"><div><p className="eyebrow">Built for a closer look</p><p className="login-principle-title">No mystery scores.<br />No noisy promises.</p></div><div><p>Internship Matcher keeps your attention on the opportunity itself. A resume is optional, and the source listing stays part of the decision.</p><button type="button" className="login-inline-link" onClick={onOpen}>Browse with an account <span aria-hidden="true">↗</span></button></div></section>
    <div hidden={!open} className="login-dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section ref={dialog} className="login-dialog" role="dialog" aria-modal="true" aria-labelledby="sign-in-heading" tabIndex={-1}>
        <div className="login-dialog-top"><button type="button" className="dialog-close" onClick={onClose} aria-label="Close sign in">×</button></div>
        {children}
      </section>
    </div>
  </div>;
}
