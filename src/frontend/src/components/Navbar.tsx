import { useLayoutEffect, useRef } from 'react';
import { Link, NavLink } from 'react-router';
import type { Me } from '../api/contracts';
import { Brand } from './Brand';

export function Navbar({ me, inert, signingIn, onLogout }: {
  me: Me | null; inert: boolean; signingIn: boolean; onLogout(): void;
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
  return <header ref={header} className="navbar" inert={inert}>
    <Link className="brand" to="/jobs"><Brand /></Link>
    {me && <>
      <nav className="nav-tabs" aria-label="Main navigation">
        <NavLink to="/jobs">Jobs</NavLink><NavLink to="/resume">Resume</NavLink><NavLink to="/matches">Matches</NavLink>
      </nav>
      <div className="nav-user"><Link className="profile-chip" to="/onboarding" aria-label={`Your name: ${name}`}>
        <span className="avatar" aria-hidden="true">{initials}</span><span className="profile-copy"><strong>{name}</strong><small>Your profile</small></span>
      </Link><button className="button-quiet" disabled={signingIn} onClick={onLogout}>Logout</button></div>
    </>}
  </header>;
}
