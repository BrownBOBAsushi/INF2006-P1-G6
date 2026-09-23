import { Brand } from './Brand';

export function Footer() {
  return <footer className="site-footer"><div className="footer-main"><div><Brand />
    <p>Imported listings with source links.</p></div>
    <p className="footer-note">Apply directly on the source website.<br />Your resume is never sent with an application link.</p>
  </div><div className="footer-credit">Internship Matcher · INF2006 student project</div></footer>;
}
