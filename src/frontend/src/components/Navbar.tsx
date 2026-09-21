import { useLayoutEffect, useRef } from 'react';
import { Link, NavLink } from 'react-router';
import type { Me } from '../api/contracts';
import { Brand } from './Brand';

export function Navbar({ me, inert, signingIn, onLogout, theme, onToggleTheme, onOpenSignIn }: {
  me: Me | null; inert: boolean; signingIn: boolean; onLogout(): void;
  theme?: 'dark' | 'light'; onToggleTheme?(): void; onOpenSignIn?(): void;
}) {
  const header = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const measure = () => {
      const height = header.current?.getBoundingClientRect().height;
      if (height) document.documentElement.style.setProperty('--nav-height', `${height}px`);
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure);
    if (header.current) observer?.observe(header.current);
    window.addEventListener('resize', measure);
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); document.documentElement.style.removeProperty('--nav-height'); };
  }, []);
  const name = me?.user.display_name ?? 'Your profile';
  const initials = name.trim().split(/\s+/).slice(0, 2).map(part => [...part][0]).join('').toUpperCase();
  const isLight = theme === 'light';
  return <header ref={header} className="navbar" inert={inert}>
    <Link className="brand" to="/jobs"><Brand /></Link>
    {me ? <nav className="nav-tabs" aria-label="Main navigation">
      <NavLink to="/jobs">Jobs</NavLink><NavLink to="/resume">Resume</NavLink><NavLink to="/matches">Matches</NavLink>
    </nav> : <nav className="landing-nav" aria-label="Landing page navigation">
      <a href="#login-how">How it works</a><a href="#login-principles">Why it’s different</a><button type="button" onClick={onOpenSignIn}>Browse roles <span aria-hidden="true">↗</span></button>
    </nav>}
    <div className="nav-user"><button type="button" className="theme-toggle" onClick={onToggleTheme} aria-label={isLight ? 'Switch to dark theme' : 'Switch to light theme'} aria-pressed={isLight}><span aria-hidden="true">{isLight ? '◐' : '☼'}</span><span className="theme-toggle-label">{isLight ? 'Light' : 'Dark'}</span></button>{me && <><Link className="profile-chip" to="/onboarding" aria-label={`Your name: ${name}`}>
      <span className="avatar" aria-hidden="true">{initials}</span><span className="profile-copy"><strong>{name}</strong><small>Your profile</small></span>
    </Link><button className="button-quiet" disabled={signingIn} onClick={onLogout}>Logout</button></>}</div>
  </header>;
}
