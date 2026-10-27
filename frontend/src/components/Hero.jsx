import { useEffect, useState } from 'react';
import { Icon, Rating, ListButton, Poster } from './ui.jsx';
import { Link } from '../router.jsx';
import { fmtRuntime, hueOf } from '../util.js';

export default function Hero({ items }) {
  const [i, setI] = useState(0);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (paused || items.length < 2) return;
    const t = setInterval(() => setI((x) => (x + 1) % items.length), 8000);
    return () => clearInterval(t);
  }, [paused, items.length]);
  if (!items.length) return null;
  return (
    <section className="hero" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} aria-roledescription="carousel">
      {items.map((t, n) => (
        <article key={t.id} className={`hero-slide ${n === i ? 'on' : ''}`} aria-hidden={n !== i} style={{ '--h': hueOf(t.name) }}>
          {t.backdrop && <img className="hero-bg" src={t.backdrop} alt="" onError={(e) => (e.currentTarget.style.display = 'none')} />}
          <div className="hero-shade" />
          <Link to={`/title/${t.slug}`} className="hero-poster" tabIndex={-1} aria-hidden="true"><Poster src={t.poster} name={t.name} /></Link>
          <div className="hero-body">
            <p className="eyebrow">{t.kind === 'series' ? 'Series' : 'Feature film'} · {t.year}</p>
            <h1>{t.name}</h1>
            <p className="hero-meta"><Rating value={t.rating} /> {fmtRuntime(t.runtime)}{t.kind === 'series' ? ' per episode' : ''} {t.genres.slice(0, 3).map((g) => <span key={g} className="chip">{g}</span>)}</p>
            <p className="hero-desc">{t.description}</p>
            <div className="hero-actions">
              <Link to={`/watch/${t.slug}`} className="btn primary" tabIndex={n === i ? 0 : -1}><Icon name="play" fill size={18} />Play</Link>
              <Link to={`/title/${t.slug}`} className="btn ghost" tabIndex={n === i ? 0 : -1}><Icon name="info" size={18} />Details</Link>
              <ListButton item={t} label />
            </div>
          </div>
        </article>
      ))}
      <div className="hero-dots">
        {items.map((t, n) => <button key={t.id} className={n === i ? 'on' : ''} onClick={() => setI(n)} aria-label={`Show ${t.name}`} />)}
      </div>
    </section>
  );
}
