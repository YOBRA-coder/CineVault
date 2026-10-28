import { useEffect, useState } from 'react';
import { Empty, Icon, Modal, Poster, Rating, Spinner, useFetch } from '../components/ui.jsx';
import { Link } from '../router.jsx';
import { fmtRuntime } from '../util.js';

const REGIONS = [['US', 'United States'], ['GB', 'United Kingdom'], ['KE', 'Kenya'], ['NG', 'Nigeria'], ['ZA', 'South Africa'], ['UG', 'Uganda'], ['TZ', 'Tanzania'],
  ['GH', 'Ghana'], ['IN', 'India'], ['CA', 'Canada'], ['AU', 'Australia'], ['DE', 'Germany'], ['FR', 'France'], ['BR', 'Brazil']];

function initialRegion() {
  try { const s = localStorage.getItem('cv_region'); if (s) return s; } catch { /* ignore */ }
  const m = (navigator.language || '').split('-')[1];
  return m && REGIONS.some(([c]) => c === m.toUpperCase()) ? m.toUpperCase() : 'US';
}

export default function DiscoverDetail({ kind, id }) {
  const [region, setRegion] = useState(initialRegion);
  const [{ data: t, loading, error }] = useFetch(`/discover/${kind}/${id}?region=${region}`);
  const [trailer, setTrailer] = useState(false);
  useEffect(() => { try { localStorage.setItem('cv_region', region); } catch { /* ignore */ } }, [region]);
  useEffect(() => { if (t) document.title = `${t.name}${t.year ? ` (${t.year})` : ''} — CineVault`; }, [t?.id]); // eslint-disable-line

  if (loading && !t) return <div className="page-center"><Spinner /></div>;
  if (error) return <div className="page"><Empty icon="info" title="Couldn’t load this title">{error.message} — <Link to="/discover">back to Discover</Link></Empty></div>;
  const w = t.watch;
  const groups = [['Stream', w.stream], ['Free with ads', w.free], ['Rent', w.rent], ['Buy', w.buy]].filter(([, l]) => l.length);

  return (
    <div className="detail">
      <div className="detail-bg">{t.backdrop && <img src={t.backdrop} alt="" onError={(e) => (e.currentTarget.style.display = 'none')} />}<div /></div>
      <div className="detail-main">
        <div className="detail-poster"><Poster src={t.poster} name={t.name} /></div>
        <div className="detail-info">
          <p className="eyebrow">{t.kind === 'series' ? 'Series' : 'Movie'}{t.people.length ? ` · ${t.kind === 'series' ? 'Created by' : 'Directed by'} ${t.people.join(', ')}` : ''}</p>
          <h1>{t.name}</h1>
          {t.tagline && <p className="tagline">{t.tagline}</p>}
          <p className="meta-row">
            <Rating value={t.rating} />{t.year && <span>{t.year}</span>}
            {t.runtime && <span>{fmtRuntime(t.runtime)}{t.kind === 'series' ? ' / ep' : ''}</span>}
            {t.seasons && <span>{t.seasons} season{t.seasons > 1 ? 's' : ''} · {t.episodes} episodes</span>}
            {t.status && t.kind === 'series' && <span className="license">{t.status}</span>}
          </p>
          <p className="chips">{t.genres.map((g) => <span key={g} className="chip">{g}</span>)}</p>
          <p className="desc">{t.overview || 'No description available.'}</p>
          <div className="actions">
            {t.library_slug && <Link to={`/title/${t.library_slug}`} className="btn primary lg"><Icon name="play" fill size={20} />Watch free in CineVault</Link>}
            {t.trailer && <button className={`btn lg ${t.library_slug ? 'ghost' : 'primary'}`} onClick={() => setTrailer(true)}><Icon name="play" fill size={20} />Watch trailer</button>}
          </div>
        </div>
      </div>

      <div className="detail-tabs">
        <section className="panel watch">
          <div className="watch-head">
            <h3>Where to watch</h3>
            <label className="select">Country
              <select value={region} onChange={(e) => setRegion(e.target.value)}>
                {!REGIONS.some(([c]) => c === region) && <option value={region}>{region}</option>}
                {REGIONS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
              </select>
            </label>
          </div>
          {groups.length === 0 ? (
            <p className="muted">No legal streaming, rental or purchase options are listed for {region} yet.{w.regions.length > 0 && <> It is available in: {w.regions.slice(0, 12).join(', ')}{w.regions.length > 12 ? '…' : ''}.</>}</p>
          ) : groups.map(([label, list]) => (
            <div className="prov-row" key={label}>
              <span className="prov-label">{label}</span>
              <div className="prov-list">{list.map((p) => <span key={p.name} className="prov" title={p.name}>{p.logo ? <img src={p.logo} alt="" loading="lazy" /> : null}<b>{p.name}</b></span>)}</div>
            </div>
          ))}
          {w.link && <a className="btn ghost sm" href={w.link} target="_blank" rel="noreferrer">Full list & links <Icon name="ext" size={14} /></a>}
          {!t.library_slug && <p className="fine">This title is commercially licensed, so CineVault can’t stream or offer it for download. Use one of the legal options above — or your local library’s digital service.</p>}
          <p className="fine">Streaming availability data by JustWatch, via TMDB. This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
        </section>

        {t.cast.length > 0 && (
          <>
            <div className="tabs"><button className="on">Cast</button></div>
            <div className="cast-grid">
              {t.cast.map((c) => (
                <div key={c.name} className="cast-card">
                  <span className="avatar">{c.photo ? <img src={c.photo} alt="" loading="lazy" /> : c.name.split(' ').map((x) => x[0]).slice(0, 2).join('')}</span>
                  <strong>{c.name}</strong><small>{c.character}</small>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {trailer && (
        <Modal onClose={() => setTrailer(false)} wide label={`${t.name} trailer`}>
          <div className="trailer"><iframe src={`https://www.youtube-nocookie.com/embed/${t.trailer}?autoplay=1&rel=0`} title={`${t.name} trailer`} allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowFullScreen /></div>
        </Modal>
      )}
    </div>
  );
}
