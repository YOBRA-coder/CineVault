import { useCallback, useEffect, useRef, useState } from 'react';
import { Empty, Icon, Spinner, useFetch } from '../components/ui.jsx';
import DownloadModal from '../components/DownloadModal.jsx';
import { Link, navigate, useLocation } from '../router.jsx';
import { api, streamUrl } from '../api.js';
import { fmtSize, fmtTime } from '../util.js';

export default function Player({ slug }) {
  const { params } = useLocation();
  const [{ data: t, loading, error }] = useFetch(`/titles/${slug}`);
  const epId = Number(params.get('ep')) || null;
  const fileParam = Number(params.get('f')) || null;
  const startAt = Number(params.get('t')) || 0;

  const vref = useRef(null);
  const state = useRef({ pos: 0, dur: 0, lastSave: 0 });
  const seekTo = useRef(startAt);
  const [failed, setFailed] = useState(false);
  const [next, setNext] = useState(null); // countdown seconds
  const [dl, setDl] = useState(false);
  const [speed, setSpeed] = useState(1);

  const isSeries = t?.kind === 'series';
  const episode = isSeries ? (t.episodes.find((e) => e.id === epId) || t.episodes.find((e) => e.id === t.mine?.last?.episode_id) || t.episodes.find((e) => e.files.some((f) => f.playable)) || t.episodes[0]) : null;
  const files = (isSeries ? episode?.files : t?.files) || [];
  const playable = files.filter((f) => f.playable);
  const file = playable.find((f) => f.id === fileParam) || playable[0];
  const nextEp = isSeries && episode ? t.episodes.slice(t.episodes.indexOf(episode) + 1).find((e) => e.files.some((f) => f.playable)) : null;

  // resume from last position when opened without an explicit ?t=
  useEffect(() => {
    if (!t || startAt) return;
    const p = isSeries ? episode?.progress : t.mine?.last;
    if (p && !p.completed && p.position > 10) seekTo.current = p.position;
  }, [t?.id, episode?.id]); // eslint-disable-line

  useEffect(() => { if (t) document.title = `${t.name}${episode ? ` · S${episode.season}E${episode.number}` : ''} — CineVault`; }, [t?.id, episode?.id]); // eslint-disable-line
  useEffect(() => { setFailed(false); setNext(null); state.current = { pos: 0, dur: 0, lastSave: 0 }; }, [file?.id]);

  const save = useCallback((beacon = false) => {
    const s = state.current;
    if (!t || s.pos < 3) return;
    const body = { title_id: t.id, episode_id: episode?.id || 0, position: s.pos, duration: s.dur };
    s.lastSave = Date.now();
    return beacon ? api.beacon('/me/history', body) : api.post('/me/history', body).catch(() => {});
  }, [t, episode]);

  useEffect(() => {
    const onHide = () => save(true);
    window.addEventListener('pagehide', onHide);
    return () => { window.removeEventListener('pagehide', onHide); save(true); };
  }, [save]);

  useEffect(() => {
    const el = vref.current;
    const onKey = (e) => {
      if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName) || !el) return;
      const k = e.key.toLowerCase();
      if (k === ' ' || k === 'k') { e.preventDefault(); el.paused ? el.play() : el.pause(); }
      else if (k === 'arrowright' || k === 'l') el.currentTime += 10;
      else if (k === 'arrowleft' || k === 'j') el.currentTime -= 10;
      else if (k === 'arrowup') { e.preventDefault(); el.volume = Math.min(1, el.volume + 0.1); }
      else if (k === 'arrowdown') { e.preventDefault(); el.volume = Math.max(0, el.volume - 0.1); }
      else if (k === 'm') el.muted = !el.muted;
      else if (k === 'f') document.fullscreenElement ? document.exitFullscreen() : el.parentElement.requestFullscreen?.();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });

  useEffect(() => { if (vref.current) vref.current.playbackRate = speed; }, [speed, file?.id]);

  // lock-screen / notification / headset controls
  useEffect(() => {
    if (!('mediaSession' in navigator) || !t) return;
    const ms = navigator.mediaSession, el = () => vref.current;
    ms.metadata = new MediaMetadata({
      title: episode ? episode.name : t.name, artist: episode ? t.name : (t.directors[0] || ''), album: 'CineVault',
      artwork: t.poster ? [{ src: t.poster, sizes: '512x512' }] : [{ src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' }],
    });
    const set = (a, f) => { try { ms.setActionHandler(a, f); } catch { /* unsupported */ } };
    set('play', () => el()?.play()); set('pause', () => el()?.pause());
    set('seekbackward', () => { if (el()) el().currentTime -= 10; }); set('seekforward', () => { if (el()) el().currentTime += 10; });
    set('nexttrack', nextEp ? () => navigate(`/watch/${t.slug}?ep=${nextEp.id}`, { replace: true }) : null);
    return () => ['play', 'pause', 'seekbackward', 'seekforward', 'nexttrack'].forEach((a) => set(a, null));
  }, [t?.id, episode?.id, nextEp?.id]); // eslint-disable-line

  // auto-play next episode countdown
  useEffect(() => {
    if (next === null) return;
    if (next === 0) { navigate(`/watch/${t.slug}?ep=${nextEp.id}`, { replace: true }); return; }
    const id = setTimeout(() => setNext(next - 1), 1000);
    return () => clearTimeout(id);
  }, [next]); // eslint-disable-line

  if (loading) return <div className="page-center"><Spinner /></div>;
  if (error) return <div className="page"><Empty icon="info" title="Can’t open this title">{error.message}</Empty></div>;
  if (!file) {
    return (
      <div className="page"><Empty icon="film" title="No playable version yet">
        This title has no browser-playable file. {files.length > 0 ? <button className="link" onClick={() => setDl(true)}>Download it instead</button> : <>Try again later or <Link to={`/title/${t.slug}`}>go back</Link>.</>}
      </Empty>{dl && <DownloadModal title={t} files={files} onClose={() => setDl(false)} />}</div>
    );
  }

  const switchFile = (id) => {
    seekTo.current = state.current.pos;
    navigate(`/watch/${t.slug}?${episode ? `ep=${episode.id}&` : ''}f=${id}`, { replace: true });
  };

  return (
    <div className="player-page">
      <div className="player-top">
        <Link to={`/title/${t.slug}`} className="btn ghost sm"><Icon name="left" size={16} />Back</Link>
        <div className="player-title"><strong>{t.name}</strong>{episode && <span>S{episode.season} E{episode.number} · {episode.name}</span>}</div>
        <div className="player-tools">
          <label className="select compact" title="Quality">
            <select value={file.id} onChange={(e) => switchFile(Number(e.target.value))} aria-label="Quality">
              {playable.map((f) => <option key={f.id} value={f.id}>{f.quality} · {f.ext.toUpperCase()} · {fmtSize(f.size)}</option>)}
            </select>
          </label>
          <label className="select compact" title="Speed">
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Playback speed">
              {[0.75, 1, 1.25, 1.5, 2].map((s) => <option key={s} value={s}>{s}×</option>)}
            </select>
          </label>
          <button className="btn ghost sm" onClick={() => setDl(true)}><Icon name="download" size={16} />Download</button>
        </div>
      </div>

      <div className="stage">
        <video key={file.id} ref={vref} src={streamUrl(file.id)} controls autoPlay playsInline preload="metadata"
          onLoadedMetadata={(e) => { state.current.dur = e.currentTarget.duration; if (seekTo.current > 0 && seekTo.current < e.currentTarget.duration - 5) e.currentTarget.currentTime = seekTo.current; seekTo.current = 0; e.currentTarget.playbackRate = speed; }}
          onTimeUpdate={(e) => { const s = state.current; s.pos = e.currentTarget.currentTime; s.dur = e.currentTarget.duration || s.dur; if (Date.now() - s.lastSave > 10000) save(); }}
          onPause={() => save()}
          onEnded={() => { state.current.pos = state.current.dur; save(); if (nextEp) setNext(6); }}
          onError={() => setFailed(true)} />
        {failed && (
          <div className="stage-msg">
            <h3>Couldn’t stream this file</h3>
            <p>The archive may be busy, or this format isn’t supported by your browser.{playable.length > 1 ? ' Try another quality above.' : ''}</p>
            <div><button className="btn primary sm" onClick={() => setDl(true)}><Icon name="download" size={16} />Download instead</button>{t.archive_url && <a className="btn ghost sm" href={t.archive_url} target="_blank" rel="noreferrer">Open on archive.org</a>}</div>
          </div>
        )}
        {next !== null && nextEp && (
          <div className="up-next">
            <p>Up next in {next}s</p><strong>E{nextEp.number} · {nextEp.name}</strong>
            <div><button className="btn primary sm" onClick={() => setNext(0)}><Icon name="next" size={16} />Play now</button><button className="btn ghost sm" onClick={() => setNext(null)}>Cancel</button></div>
          </div>
        )}
      </div>

      <p className="shortcuts">Space play/pause · ←/→ ±10s · ↑/↓ volume · M mute · F fullscreen · your place is saved automatically</p>

      {isSeries && (
        <div className="player-eps">
          <h3>Episodes</h3>
          <div>
            {t.episodes.filter((e) => e.season === episode.season).map((e) => (
              <Link key={e.id} to={`/watch/${t.slug}?ep=${e.id}`} className={`pe ${e.id === episode.id ? 'on' : ''}`} aria-current={e.id === episode.id}>
                <b>{e.number}</b><span>{e.name}</span>{e.progress?.completed && <Icon name="check" size={14} />}
              </Link>
            ))}
          </div>
        </div>
      )}
      {dl && <DownloadModal title={t} files={files} heading={episode ? `S${episode.season}E${episode.number} · ${episode.name}` : t.name} onClose={() => setDl(false)} />}
    </div>
  );
}
