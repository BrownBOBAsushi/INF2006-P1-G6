import { useEffect, useRef, type ReactNode } from 'react';

/** Keep the underlying workspace mounted, with focus confined to recovery controls. */
export function SessionRecovery({ children }: { children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, []);
  return <div className="reauth" role="dialog" aria-modal="true" aria-labelledby="sign-in-heading"
    ref={panel} tabIndex={-1} onKeyDown={event => {
      if (event.key !== 'Tab' || !panel.current) return;
      const controls = [...panel.current.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), iframe, [tabindex="0"]')]
        .filter(element => !element.closest('[inert], [hidden], [aria-hidden="true"]'));
      const first = controls[0], last = controls.at(-1);
      if (!first || !last) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    }}>{children}</div>;
}
