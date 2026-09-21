import { useEffect, useState, type ReactNode } from 'react';

/** Presentation only: authentication controls and session actions belong to App. */
export function LoginLayout({ children }: { children: ReactNode }) {
  const [word, setWord] = useState('clarity.');
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      clearInterval(timer); setWord('clarity.');
      if (preference.matches) return;
      let index = 0;
      const words = ['confidence.', 'context.', 'clarity.'];
      timer = setInterval(() => {
        setWord(words[index++]!);
        if (index === words.length) clearInterval(timer);
      }, 3000);
    };
    start(); preference.addEventListener('change', start);
    return () => { clearInterval(timer); preference.removeEventListener('change', start); };
  }, []);
  return <div className="login-layout">
    <section className="login-visual" aria-label="Discover internships">
      <div className="login-mesh" aria-hidden="true" />
      <div className="login-copy"><p className="eyebrow">Your next chapter starts here</p>
        <h2>Find internships with <span className="sr-only">clarity.</span><span className="rotating-word" aria-hidden="true">{word}</span></h2>
        <p>Explore imported listings, get to know the role, and take the next step on the employer’s website.</p>
        <div className="login-tagline">Your resume is optional. Your next step is yours.</div>
      </div>
    </section>
    <div className="login-form">{children}</div>
  </div>;
}
