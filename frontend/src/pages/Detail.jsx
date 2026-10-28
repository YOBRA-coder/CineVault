import { useEffect, useMemo, useState } from 'react';
import { Empty, Icon, ListButton, Poster, Rail, Rating, Spinner, Stars, toast, useFetch } from '../components/ui.jsx';
import TrailerModal from '../components/TrailerModal.jsx';
import { youtubeId } from '../adminApi.js';
import DownloadModal from '../components/DownloadModal.jsx';
import PreviewModal from '../components/PreviewModal.jsx';
import { Link } from '../router.jsx';
import { api } from '../api.js';
import { fmtRuntime, fmtTime } from '../util.js';

export default function Detail({ slug }) {
  const [{ data: t, loading, error }, setT] = useFetch(`/titles/${slug}`);
  const [{ data: similar }] = useFetch(`/titles/${slug}/similar`);
  const [tab, setTab] = useState('episodes');
  const [season, setSeason] = useState(1);
  const [{ data: health }] = useFetch('/health');
  const [trailerKey, setTrailerKey] = useState(null);
  const [embed, setEmbed] = useState(null);
  const [modal, setModal] = useState(null); // {type:'download'|'preview', files, heading}

  useEffect(() => { if (t) { document.title = `${t.name} (${t.year}) — CineVault`; setSeason(t.mine?.last?.episode_id ? (t.episodes.find((e) => e.id === t.mine.last.episode_id)?.season || 1) : (t.seasons[0] || 1)); setTab(t.kind === 'series' ? 'episodes' : 'cast'); } }, [t?.id]); // eslint-disable-line

  const eps = useMemo(() => (t?.episodes || []).filter((e) => e.season === season), [t, season]);
  if (loading) return <div className="page-center"><Spinner /></div>;
  if (error) return <div className="page"><Empty icon="info" title="Title not found">{error.message} — <Link to="/browse">browse the catalog</Link>.</Empty></div>;

  const isSeries = t.kind === 'series';
  const allFiles = isSeries ? t.episodes.flatMap((e) => e.files) : t.files;
  const playable = allFiles.filter((f) => f.playable);
  const last = t.mine?.last;
  const resuming = last && !last.completed && last.position > 10;
  const resumeEp = resuming && last.episode_id ? t.episodes.find((e) => e.id === last.episode_id) : null;
  const firstEp = t.episodes.find((e) => e.files.some((f) => f.playable));
  const playHref = resuming
    ? `/watch/${t.slug}?${last.episode_id ? `ep=${last.episode_id}&` : ''}t=${Math.floor(last.position)}`
    : `/watch/${t.slug}${isSeries && firstEp ? `?ep=${firstEp.id}` : ''}`;
  const playLabel = resuming ? `Resume ${resumeEp ? `S${resumeEp.season}E${resumeEp.number} · ` : ''}${fmtTime(last.position)}` : isSeries && firstEp ? `Play S${firstEp.season} E${firstEp.number}` : 'Play';
  const previewFile = (isSeries ? firstEp?.files : t.files)?.find((f) => f.playable);
  const bestFiles = isSeries ? [] : t.files;

  async function rate(stars) {
    try { await api.post(`/titles/${t.slug}/rate`, { stars }); setT({ ...t, mine: { ...t.mine, rating: stars } }); toast(stars ? `You rated it ${stars}★` : 'Rating removed'); }
    catch (e) { toast(e.message, 'error'); }
  }
  async function trailer() {
    try {
      const r = await api.get(`/titles/${t.slug}/trailer`);
      r.key ? setTrailerKey(r.key) : toast(r.enabled ? 'No trailer is listed for this title' : 'Trailers need a TMDB key', 'error');
    } catch (e) { toast(e.message, 'error'); }
  }
  async function recheck() {
    toast('Checking the archive…');
    const r = await api.post(`/titles/${t.slug}/refresh`).catch(() => ({ status: 'error' }));
    toast(r.status === 'ok' ? 'Files found!' : r.status === 'missing' ? 'Still not available on the archive' : 'Archive unreachable — try later', r.status === 'ok' ? 'info' : 'error');
    api.get(`/titles/${t.slug}`).then(setT);
  }

  return (
    <div className="detail">
      <div className="detail-bg">{t.backdrop && <img src={t.backdrop} alt="" onError={(e) => (e.currentTarget.style.display = 'none')} />}<div /></div>
      <div className="detail-main">
        <div className="detail-poster"><Poster src={t.poster} name={t.name} /></div>
        <div className="detail-info">
          <p className="eyebrow">{isSeries ? 'Series' : 'Movie'}{t.directors[0] ? ` · ${isSeries ? 'Created by' : 'Directed by'} ${t.directors.join(', ')}` : ''}</p>
          <h1>{t.name}</h1>
          {t.tagline && <p className="tagline">{t.tagline}</p>}
          <p className="meta-row">
            <Rating value={t.rating} />
            <span>{t.year}</span>
            {t.runtime && <span>{fmtRuntime(t.runtime)}{isSeries ? ' / ep' : ''}</span>}
            {isSeries && <span>{t.episodes.length} episodes</span>}
            <span className="license">{t.license}</span>
          </p>
          <p className="chips">{t.genres.map((g) => <Link key={g} className="chip" to={`/browse?genre=${encodeURIComponent(g)}`}>{g}</Link>)}</p>
          <p className="desc">{t.description}</p>

          <div className="actions">
            {playable.length > 0
              ? <Link to={playHref} className="btn primary lg"><Icon name="play" fill size={20} />{playLabel}</Link>
              : t.links.length > 0
                ? <a href={t.links[0].url} target="_blank" rel="noreferrer" className="btn primary lg"><Icon name="play" fill size={20} />Watch on {t.links[0].label}</a>
                : <button className="btn primary lg" disabled><Icon name="play" fill size={20} />Unavailable</button>}
            {health?.tmdb && <button className="btn ghost lg" onClick={trailer}><Icon name="play" size={20} />Trailer</button>}
            {previewFile && <button className="btn ghost lg" onClick={() => setModal({ type: 'preview' })}><Icon name="eye" size={20} />Preview</button>}
            <button className="btn ghost lg" onClick={() => setModal({ type: 'download', files: bestFiles, heading: t.name, season: isSeries ? 0 : undefined, bulk: isSeries })} disabled={!allFiles.length}><Icon name="download" size={20} />Download</button>
            <ListButton item={t} label size="lg" />
          </div>

          {t.links.length > 0 && (
            <div className="legal-links">
              <span>{allFiles.length ? 'Also watch legally on' : 'Watch legally on'}</span>
              {t.links.map((l) => (
                <span className="legal-link" key={l.id}>
                  <a href={l.url} target="_blank" rel="noreferrer" className="btn ghost sm">{l.label} <Icon name="ext" size={13} /></a>
                  {youtubeId(l.url) && <button className="icon-btn" aria-label={`Play ${l.label} here`} title="Play here" onClick={() => setEmbed({ id: youtubeId(l.url), label: l.label })}><Icon name="play" size={14} fill /></button>}
                </span>
              ))}
            </div>
          )}

          {!allFiles.length && !t.links.length && (
            <div className="notice">
              {t.sources_status === 'error' ? 'The archive couldn’t be reached just now.' : 'We couldn’t find a downloadable copy of this title on the archive yet.'}{' '}
              <button className="link" onClick={recheck}>Check again</button>
              {t.archive_url && <> · <a href={t.archive_url} target="_blank" rel="noreferrer">Open on Internet Archive <Icon name="ext" size={13} /></a></>}
            </div>
          )}

          <div className="your-rating"><span>Your rating</span><Stars value={t.mine?.rating} onChange={rate} /></div>
        </div>
      </div>

      <div className="detail-tabs">
        <div className="tabs" role="tablist">
          {isSeries && <button role="tab" aria-selected={tab === 'episodes'} className={tab === 'episodes' ? 'on' : ''} onClick={() => setTab('episodes')}>Episodes</button>}
          <button role="tab" aria-selected={tab === 'cast'} className={tab === 'cast' ? 'on' : ''} onClick={() => setTab('cast')}>Cast & crew</button>
          <button role="tab" aria-selected={tab === 'about'} className={tab === 'about' ? 'on' : ''} onClick={() => setTab('about')}>About</button>
        </div>

        {tab === 'episodes' && isSeries && (
          <div className="episodes">
            <div className="ep-head">
              {t.seasons.length > 1
                ? <label className="select">Season<select value={season} onChange={(e) => setSeason(Number(e.target.value))}>{t.seasons.map((s) => <option key={s} value={s}>Season {s}</option>)}</select></label>
                : <h3>Season {t.seasons[0] || 1}</h3>}
              <button className="btn ghost sm" disabled={!allFiles.length} onClick={() => setModal({ type: 'download', files: [], heading: `${t.name} — Season ${season}`, season, bulk: true })}><Icon name="download" size={16} />Download season</button>
            </div>
            {eps.map((e) => {
              const can = e.files.some((f) => f.playable);
              const pct = e.progress?.duration ? Math.min(100, (e.progress.position / e.progress.duration) * 100) : 0;
              return (
                <div key={e.id} className={`ep ${e.progress?.completed ? 'done' : ''}`}>
                  <span className="ep-num">{e.number}</span>
                  <div className="ep-body">
                    <h4>{e.name}{e.air_date && <small>{e.air_date}</small>}</h4>
                    <p>{e.description}</p>
                    {pct > 0 && <div className="progress inline"><i style={{ width: `${pct}%` }} /></div>}
                  </div>
                  <span className="ep-time">{fmtRuntime(e.runtime)}</span>
                  <span className="ep-actions">
                    {can && <Link to={`/watch/${t.slug}?ep=${e.id}${e.progress && !e.progress.completed && e.progress.position > 10 ? `&t=${Math.floor(e.progress.position)}` : ''}`} className="icon-btn solid" aria-label={`Play ${e.name}`}><Icon name="play" size={16} fill /></Link>}
                    <button className="icon-btn" aria-label={`Download ${e.name}`} disabled={!e.files.length} onClick={() => setModal({ type: 'download', files: e.files, heading: `S${e.season}E${e.number} · ${e.name}` })}><Icon name="download" size={16} /></button>
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {tab === 'cast' && (
          <div className="cast">
            {t.directors.length > 0 && <p className="crew"><span>{isSeries ? 'Creator' : 'Director'}</span>{t.directors.join(', ')}</p>}
            <div className="cast-grid">
              {t.cast.map((c) => (
                <Link key={c.name} to={`/browse?q=${encodeURIComponent(c.name)}`} className="cast-card">
                  <span className="avatar">{c.photo ? <img src={c.photo} alt="" loading="lazy" /> : c.name.split(' ').map((w) => w[0]).slice(0, 2).join('')}</span>
                  <strong>{c.name}</strong><small>{c.character}</small>
                </Link>
              ))}
            </div>
          </div>
        )}

        {tab === 'about' && (
          <dl className="about">
            <div><dt>Released</dt><dd>{t.year}</dd></div>
            <div><dt>Type</dt><dd>{isSeries ? `Series · ${t.episodes.length} episodes` : 'Feature film'}</dd></div>
            {t.runtime && <div><dt>Runtime</dt><dd>{fmtRuntime(t.runtime)}{isSeries ? ' per episode' : ''}</dd></div>}
            <div><dt>Language</dt><dd>{t.language}</dd></div>
            <div><dt>Genres</dt><dd>{t.genres.join(', ')}</dd></div>
            <div><dt>Score</dt><dd>{t.rating ? `${t.rating.toFixed(1)} / 10 (${t.votes.toLocaleString()} votes)` : 'Not rated yet'}</dd></div>
            <div><dt>Licence</dt><dd>{t.license}</dd></div>
            {t.archive_url && <div><dt>Source</dt><dd><a href={t.archive_url} target="_blank" rel="noreferrer">Internet Archive <Icon name="ext" size={13} /></a></dd></div>}
          </dl>
        )}
      </div>

      {similar?.length > 0 && <div className="rails"><Rail title="More like this" items={similar} /></div>}

      {trailerKey && <TrailerModal ytKey={trailerKey} title={t.name} onClose={() => setTrailerKey(null)} />}
      {embed && <TrailerModal ytKey={embed.id} title={`${t.name} on ${embed.label}`} onClose={() => setEmbed(null)} />}
      {modal?.type === 'download' && <DownloadModal title={t} files={modal.files} heading={modal.heading} season={modal.season} bulk={modal.bulk} onClose={() => setModal(null)} />}
      {modal?.type === 'preview' && previewFile && <PreviewModal title={t} file={previewFile} start={t.preview_start} onClose={() => setModal(null)} />}
    </div>
  );
}
