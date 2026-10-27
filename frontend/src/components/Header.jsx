import { useEffect, useRef, useState } from 'react';
import { Icon, Poster } from './ui.jsx';
import { Link, navigate, useLocation } from '../router.jsx';
import { api } from '../api.js';
import { InstallButton } from './PwaBars.jsx';

const NAV = [
  ['/', 'Home'], ['/browse?kind=movie', 'Movies'], ['/browse?kind=series', 'Series'],
  ['/list', 'My List'], ['/history', 'History'], ['/downloads', 'Downloads'],
];

export default function Header() {
  const { path, params } = useLocation();
  const [q, setQ] = useState(params.get('q') || '');
  const [open, setOpen] = useState(false);
  const [sug, setSug] = useState({ titles: [], people: [] });
  const [recent, setRecent] = useState([]);
  const [scrolled, setScrolled] = useState(false);
  const [menu, setMenu] = useState(false);
  const box = useRef(null);
  const input = useRef(null);

  useEffect(() => setQ(params.get('q') || ''), [params.get('q')]); // eslint-disable-line
  useEffect(() => { setMenu(false); setOpen(false); }, [path]);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    const onKey = (e) => {
      if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); input.current?.focus(); }
    };
    const onClick = (e) => !box.current?.contains(e.target) && setOpen(false);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => { window.removeEventListener('scroll', onScroll); document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onClick); };
  }, []);

  useEffect(() => {
    if (q.trim().length < 2) { setSug({ titles: [], people: [] }); return; }
    const t = setTimeout(() => api.get(`/suggest?q=${encodeURIComponent(q.trim())}`).then(setSug).catch(() => {}), 160);
    return () => clearTimeout(t);
  }, [q]);

  function submit(e, term = q) {
    e?.preventDefault();
    if (!term.trim()) return;
    setOpen(false); input.current?.blur();
    navigate(`/browse?q=${encodeURIComponent(term.trim())}`);
  }
  const focus = () => { setOpen(true); api.get('/me/searches').then(setRecent).catch(() => {}); };
  const showSug = open && q.trim().length >= 2 && (sug.titles.length || sug.people.length);
  const showRecent = open && q.trim().length < 2 && recent.length > 0;

  return (
    <header className={`header ${scrolled ? 'solid' : ''}`}>
      <Link to="/" className="logo" aria-label="CineVault home"><span className="logo-mark"><Icon name="play" size={14} fill /></span><span>Cine<b>Vault</b></span></Link>
      <nav className={`nav ${menu ? 'open' : ''}`} aria-label="Main">
        {NAV.map(([to, label]) => {
          const active = to === '/' ? path === '/' : to.startsWith('/browse') ? (path === '/browse' && params.get('kind') === to.split('=')[1] && !params.get('q')) : path === to;
          return <Link key={to} to={to} className={active ? 'active' : ''}>{label}</Link>;
        })}
      </nav>
      <form className="search" ref={box} onSubmit={submit} role="search">
        <Icon name="search" size={18} />
        <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={focus}
          placeholder="Search titles, actors, genres…  ( / )" aria-label="Search" autoComplete="off" />
        {(showSug || showRecent) && (
          <div className="suggest">
            {showRecent && <>
              <div className="suggest-label">Recent searches <button type="button" onClick={() => { api.del('/me/searches'); setRecent([]); }}>Clear</button></div>
              {recent.map((r) => <button type="button" key={r} className="suggest-row" onClick={() => { setQ(r); submit(null, r); }}><Icon name="clock" size={16} />{r}</button>)}
            </>}
            {showSug && <>
              {sug.titles.map((t) => (
                <Link key={t.id} to={`/title/${t.slug}`} className="suggest-row" onClick={() => setOpen(false)}>
                  <span className="suggest-thumb"><Poster src={t.poster} name={t.name} /></span>
                  <span><strong>{t.name}</strong><small>{t.kind === 'series' ? 'Series' : 'Movie'} · {t.year}</small></span>
                </Link>
              ))}
              {sug.people.map((p) => (
                <button type="button" key={p.name} className="suggest-row" onClick={() => submit(null, p.name)}>
                  <Icon name="eye" size={16} /><span><strong>{p.name}</strong><small>{p.titles} title{p.titles > 1 ? 's' : ''}</small></span>
                </button>
              ))}
              <button type="button" className="suggest-row all" onClick={() => submit()}>See all results for “{q}”</button>
            </>}
          </div>
        )}
      </form>
      <InstallButton />
      <button className="burger" onClick={() => setMenu(!menu)} aria-label="Menu" aria-expanded={menu}><Icon name="list" /></button>
    </header>
  );
}
