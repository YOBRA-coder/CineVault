import { useState } from 'react';
import { Empty, Grid, Icon, Poster, Spinner, toast, useFetch } from '../components/ui.jsx';
import { Link } from '../router.jsx';
import { api, downloadUrl } from '../api.js';
import { ago, fmtSize, fmtTime } from '../util.js';

export function MyList() {
  const [{ data, loading }, setData] = useFetch('/me/watchlist');
  if (loading) return <div className="page-center"><Spinner /></div>;
  return (
    <div className="page">
      <div className="page-head"><h1>My List</h1><p className="muted">{data.length} saved</p></div>
      {data.length === 0
        ? <Empty icon="list" title="Your list is empty">Tap the <b>+</b> on any title to save it for later. <Link to="/browse">Find something to watch</Link>.</Empty>
        : <Grid items={data} onListChange={(on) => !on && api.get('/me/watchlist').then(setData)} />}
    </div>
  );
}

export function History() {
  const [{ data, loading }, setData] = useFetch('/me/history');
  const [{ data: stats }] = useFetch('/me/stats');
  if (loading) return <div className="page-center"><Spinner /></div>;
  const remove = async (id) => { await api.del(`/me/history/${id}`); setData(data.filter((h) => h.history.id !== id)); };
  const clear = async () => { if (!confirm('Clear your entire watch history?')) return; await api.del('/me/history'); setData([]); toast('History cleared'); };
  return (
    <div className="page">
      <div className="page-head row"><div><h1>Watch history</h1><p className="muted">Pick up where you left off.</p></div>
        {data.length > 0 && <button className="btn ghost sm" onClick={clear}><Icon name="trash" size={16} />Clear all</button>}</div>
      {stats && data.length > 0 && (
        <div className="stat-row">
          <div><b>{stats.watched}</b><span>titles watched</span></div>
          <div><b>{(stats.seconds / 3600).toFixed(1)}h</b><span>watched</span></div>
          <div><b>{stats.downloads}</b><span>downloads</span></div>
        </div>
      )}
      {data.length === 0 ? <Empty icon="clock" title="Nothing watched yet">Everything you play shows up here, with your place saved. <Link to="/">Start watching</Link>.</Empty> : (
        <ul className="rows">
          {data.map((h) => {
            const pct = h.history.duration ? Math.min(100, (h.history.position / h.history.duration) * 100) : 0;
            const href = `/watch/${h.slug}?${h.history.episode_id ? `ep=${h.history.episode_id}&` : ''}${!h.history.completed ? `t=${Math.floor(h.history.position)}` : ''}`;
            return (
              <li key={h.history.id} className="row-item">
                <Link to={href} className="row-thumb"><Poster src={h.poster} name={h.name} />{pct > 0 && <div className="progress"><i style={{ width: `${pct}%` }} /></div>}</Link>
                <div className="row-body">
                  <Link to={`/title/${h.slug}`}><strong>{h.name}</strong></Link>
                  {h.history.episode && <span>{h.history.episode}</span>}
                  <small>{h.history.completed ? 'Finished' : `Stopped at ${fmtTime(h.history.position)}`} · {ago(h.history.watched_at)}</small>
                </div>
                <Link to={href} className="btn ghost sm">{h.history.completed ? 'Watch again' : 'Resume'}</Link>
                <button className="icon-btn" onClick={() => remove(h.history.id)} aria-label={`Remove ${h.name} from history`}><Icon name="trash" size={16} /></button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function Downloads() {
  const [{ data, loading }, setData] = useFetch('/me/downloads');
  if (loading) return <div className="page-center"><Spinner /></div>;
  const clear = async () => { await api.del('/me/downloads'); setData([]); };
  return (
    <div className="page">
      <div className="page-head row"><div><h1>Downloads</h1><p className="muted">Everything you’ve downloaded — grab it again any time.</p></div>
        {data.length > 0 && <button className="btn ghost sm" onClick={clear}><Icon name="trash" size={16} />Clear log</button>}</div>
      {data.length === 0 ? <Empty icon="download" title="No downloads yet">Open any title and press <b>Download</b> to save it to your device. <Link to="/browse">Browse titles</Link>.</Empty> : (
        <ul className="rows">
          {data.map((d) => (
            <li key={d.id} className="row-item">
              <Link to={`/title/${d.slug}`} className="row-thumb sm"><Poster src={d.poster} name={d.name} /></Link>
              <div className="row-body"><strong>{d.filename}</strong><small>{fmtSize(d.size)} · {ago(d.created_at)}</small></div>
              {d.file_id
                ? <a className="btn primary sm" href={downloadUrl(d.file_id)} download><Icon name="download" size={16} />Download again</a>
                : <span className="muted">No longer available</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
