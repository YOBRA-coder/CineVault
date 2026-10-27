import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Link } from '../router.jsx';
import { api } from '../api.js';
import { hueOf } from '../util.js';

const P = {
  play: 'M8 5v14l11-7z',
  plus: 'M12 5v14M5 12h14',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  download: 'M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 19h14',
  search: 'M11 4a7 7 0 100 14 7 7 0 000-14zm9 16l-4-4',
  star: 'M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.9 6.8 19.7l1-5.9L3.5 9.7l5.9-.8z',
  info: 'M12 8h.01M11 12h1v5h1M12 3a9 9 0 100 18 9 9 0 000-18z',
  close: 'M6 6l12 12M18 6L6 18',
  left: 'M15 5l-7 7 7 7',
  right: 'M9 5l7 7-7 7',
  clock: 'M12 7v5l3 2M12 3a9 9 0 100 18 9 9 0 000-18z',
  trash: 'M5 7h14M10 7V4h4v3m-8 0l1 13h10l1-13',
  link: 'M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1',
  eye: 'M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12zM12 9.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5z',
  ext: 'M14 4h6v6M20 4l-9 9M18 14v5H5V6h5',
  next: 'M6 5v14l9-7zM18 5v14',
  list: 'M4 6h16M4 12h16M4 18h10',
  volume: 'M4 9v6h4l5 4V5L8 9zM16.5 8.5a5 5 0 010 7',
  mute: 'M4 9v6h4l5 4V5L8 9zM17 9l4 6M21 9l-4 6',
  film: 'M4 5h16v14H4zM8 5v14M16 5v14M4 9h4M4 15h4M16 9h4M16 15h4',
  filter: 'M4 5h16l-6 8v6l-4-2v-4z',
};

export function Icon({ name, size = 20, fill = false, className = '' }) {
  return (
    <svg className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill={fill ? 'currentColor' : 'none'}
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={P[name]} />
    </svg>
  );
}

/* ---------- toasts ---------- */
let toasts = [];
const subs = new Set();
const emit = () => subs.forEach((f) => f());
export function toast(message, kind = 'info') {
  const t = { id: Math.random(), message, kind };
  toasts = [...toasts, t];
  emit();
  setTimeout(() => { toasts = toasts.filter((x) => x !== t); emit(); }, 3600);
}
export function Toasts() {
  const list = useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => toasts);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {list.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.message}</div>)}
    </div>
  );
}

/* ---------- imagery ---------- */
export function Poster({ src, name }) {
  const [bad, setBad] = useState(false);
  useEffect(() => setBad(false), [src]);
  if (!src || bad) {
    return (
      <div className="poster-fallback" style={{ '--h': hueOf(name) }}>
        <Icon name="film" size={28} />
        <span>{name}</span>
      </div>
    );
  }
  return <img src={src} alt={`${name} poster`} loading="lazy" onError={() => setBad(true)} />;
}

export function Stars({ value, onChange, size = 22 }) {
  const [hover, setHover] = useState(0);
  const shown = hover || value || 0;
  return (
    <div className="stars" role="radiogroup" aria-label="Your rating" onMouseLeave={() => setHover(0)}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" role="radio" aria-checked={value === n} aria-label={`${n} star${n > 1 ? 's' : ''}`}
          className={n <= shown ? 'on' : ''} onMouseEnter={() => setHover(n)}
          onClick={() => onChange(value === n ? null : n)}>
          <Icon name="star" size={size} fill={n <= shown} />
        </button>
      ))}
    </div>
  );
}

export const Rating = ({ value }) => (value ? <span className="rating"><Icon name="star" size={13} fill />{value.toFixed(1)}</span> : null);

/* ---------- list button shared by cards & detail ---------- */
export function ListButton({ item, onChange, label = false, size = '' }) {
  const [on, setOn] = useState(item.in_list);
  useEffect(() => setOn(item.in_list), [item.in_list, item.id]);
  async function toggle(e) {
    e.preventDefault(); e.stopPropagation();
    const next = !on;
    setOn(next);
    try {
      await (next ? api.put(`/me/watchlist/${item.id}`) : api.del(`/me/watchlist/${item.id}`));
      toast(next ? `Added “${item.name}” to My List` : 'Removed from My List');
      onChange?.(next);
    } catch (err) { setOn(!next); toast(err.message, 'error'); }
  }
  return (
    <button className={label ? `btn ghost ${size}` : 'icon-btn'} onClick={toggle} aria-pressed={on} title={on ? 'Remove from My List' : 'Add to My List'}>
      <Icon name={on ? 'check' : 'plus'} size={label ? 18 : 16} />{label && (on ? 'In My List' : 'My List')}
    </button>
  );
}

/* ---------- cards ---------- */
export function Card({ item, onListChange }) {
  const pct = item.resume && item.resume.duration ? Math.min(100, (item.resume.position / item.resume.duration) * 100) : 0;
  const href = item.resume ? `/watch/${item.slug}?${item.resume.episode_id ? `ep=${item.resume.episode_id}&` : ''}t=${Math.floor(item.resume.position)}` : `/title/${item.slug}`;
  return (
    <Link to={href} className="card" title={item.name}>
      <div className="card-art">
        <Poster src={item.poster} name={item.name} />
        {item.kind === 'series' && <span className="badge">Series</span>}
        <span className="card-actions"><ListButton item={item} onChange={onListChange} /></span>
        <div className="card-hover">
          <span className="play-chip"><Icon name="play" size={18} fill /></span>
          <p>{item.description}</p>
        </div>
        {pct > 0 && <div className="progress"><i style={{ width: `${pct}%` }} /></div>}
      </div>
      <div className="card-meta">
        <strong>{item.name}</strong>
        <span><Rating value={item.rating} />{item.year}{item.genres[0] ? ` · ${item.genres[0]}` : ''}</span>
      </div>
    </Link>
  );
}

export function Grid({ items, onListChange }) {
  return <div className="grid">{items.map((i) => <Card key={i.id} item={i} onListChange={onListChange} />)}</div>;
}

export function Rail({ title, items, to }) {
  const ref = useRef(null);
  const scroll = (dir) => ref.current?.scrollBy({ left: dir * ref.current.clientWidth * 0.85, behavior: 'smooth' });
  if (!items.length) return null;
  return (
    <section className="rail">
      <div className="rail-head">
        <h2>{title}</h2>
        {to && <Link to={to} className="see-all">See all <Icon name="right" size={14} /></Link>}
      </div>
      <div className="rail-wrap">
        <button className="rail-arrow left" onClick={() => scroll(-1)} aria-label="Scroll left"><Icon name="left" /></button>
        <div className="rail-track" ref={ref}>{items.map((i) => <Card key={i.id} item={i} />)}</div>
        <button className="rail-arrow right" onClick={() => scroll(1)} aria-label="Scroll right"><Icon name="right" /></button>
      </div>
    </section>
  );
}

/* ---------- misc ---------- */
export function Modal({ onClose, children, wide = false, label }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = ''; };
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={label}>
        <button className="modal-x" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
        {children}
      </div>
    </div>
  );
}

export const Spinner = () => <div className="spinner" role="progressbar" aria-label="Loading" />;

export function Empty({ icon = 'film', title, children }) {
  return (
    <div className="empty">
      <Icon name={icon} size={40} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

export function useFetch(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    api.get(path).then((data) => live && setState({ data, error: null, loading: false }))
      .catch((error) => live && setState({ data: null, error, loading: false }));
    return () => { live = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  return [state, (data) => setState((s) => ({ ...s, data }))];
}
