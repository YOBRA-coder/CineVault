import { useCallback, useEffect, useRef, useState } from 'react';
import { Icon, Modal, Poster, toast } from '../components/ui.jsx';
import { CID } from '../api.js';
import { ago } from '../util.js';

const tokenKey = 'cv_admin';
const getToken = () => { try { return sessionStorage.getItem(tokenKey) || ''; } catch { return ''; } };

async function adm(method, path, body) {
  const r = await fetch('/api/admin' + path, {
    method, headers: { 'Content-Type': 'application/json', 'X-Client-Id': CID, 'X-Admin-Token': getToken() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.error || r.statusText); e.status = r.status; throw e; }
  return data;
}

const STATUS = { ok: ['ok', 'Has files'], missing: ['missing', 'Not on archive'], error: ['error', 'Archive error'], pending: ['pending', 'Not checked'] };

export default function Admin() {
  const [ov, setOv] = useState(null);
  const [denied, setDenied] = useState(null); // message when the token is missing/wrong
  const [tokenInput, setTokenInput] = useState('');
  const wasRunning = useRef(false);

  const load = useCallback(async () => {
    try { setOv(await adm('GET', '/overview')); setDenied(null); }
    catch (e) { if (e.status === 403) setDenied(e.message); else toast(e.message, 'error'); }
  }, []);
  useEffect(() => { document.title = 'Admin — CineVault'; load(); }, [load]);

  // poll the background job while it runs
  const running = ov?.job?.running;
  useEffect(() => {
    if (!running) { if (wasRunning.current) { wasRunning.current = false; load(); } return; }
    wasRunning.current = true;
    const t = setInterval(async () => { try { const job = await adm('GET', '/status'); setOv((o) => ({ ...o, job })); } catch { /* ignore */ } }, 1200);
    return () => clearInterval(t);
  }, [running, load]);

  if (denied) {
    return (
      <div className="page narrow">
        <div className="panel gate">
          <Icon name="lock" size={34} />
          <h1>Admin</h1>
          <p className="muted">{denied}</p>
          <form onSubmit={(e) => { e.preventDefault(); try { sessionStorage.setItem(tokenKey, tokenInput.trim()); } catch { /* ignore */ } load(); }}>
            <input type="password" placeholder="Admin token" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} autoFocus />
            <button className="btn primary" type="submit">Unlock</button>
          </form>
          <p className="fine">The token is the <code>ADMIN_TOKEN</code> environment variable on your server (Render → Environment).</p>
        </div>
      </div>
    );
  }
  if (!ov) return <div className="page-center"><div className="spinner" /></div>;

  return (
    <div className="page admin">
      <div className="page-head row"><div><h1>Admin</h1><p className="muted">Manage the catalog, import from the Internet Archive and fix titles.</p></div>
        {getToken() && <button className="btn ghost sm" onClick={() => { sessionStorage.removeItem(tokenKey); location.reload(); }}>Lock</button>}</div>
      <Stats ov={ov} />
      {!ov.persistent && <div className="notice">Storage isn’t marked persistent. On Render’s free plan the database resets on every deploy/restart — attach a disk and set <code>CINEVAULT_DB=/var/data/cinevault.db</code>, or use <code>AUTO_IMPORT</code> to rebuild on boot.</div>}
      <div className="admin-grid">
        <Actions ov={ov} reload={load} />
        <JobLog job={ov.job} />
      </div>
      <TitleTable reload={load} />
    </div>
  );
}

function Stats({ ov }) {
  const s = ov.status || {};
  const cards = [['Titles', ov.titles], ['Movies', ov.movies], ['Series', ov.series], ['Episodes', ov.episodes], ['With files', s.ok || 0], ['Not on archive', s.missing || 0],
    ['Errors', s.error || 0], ['Unchecked', s.pending || 0], ['Downloads', ov.downloads], ['Viewers', ov.clients]];
  return (
    <div className="stat-row admin-stats">
      {cards.map(([k, v]) => <div key={k}><b>{v ?? 0}</b><span>{k}</span></div>)}
      <div className="wide"><span>Database</span><b className="sm">{ov.db_mb} MB</b><small>{ov.db_path}</small></div>
    </div>
  );
}

function Actions({ ov, reload }) {
  const [limit, setLimit] = useState(100);
  const [query, setQuery] = useState('');
  const [stale, setStale] = useState(true);
  const [ident, setIdent] = useState('');
  const [kind, setKind] = useState('movie');
  const [busy, setBusy] = useState(false);
  const running = !!ov.job.running;
  const start = async (path, body, msg) => { try { await adm('POST', path, body); toast(msg); reload(); } catch (e) { toast(e.message, 'error'); } };

  async function add(e) {
    e.preventDefault(); setBusy(true);
    try { const t = await adm('POST', '/titles', { identifier: ident, kind }); toast(`Added “${t.name}”`); setIdent(''); reload(); window.dispatchEvent(new Event('cv-admin-refresh')); }
    catch (err) { toast(err.message, 'error'); } finally { setBusy(false); }
  }
  return (
    <div className="panel">
      <h3>Import & sync</h3>
      <div className="act">
        <div><strong>Import films</strong><small>Adds the most-downloaded licence-marked films from archive.org, then fetches their files.</small></div>
        <div className="act-controls">
          <input type="number" min="1" max="500" value={limit} onChange={(e) => setLimit(e.target.value)} aria-label="How many" />
          <button className="btn primary sm" disabled={running} onClick={() => start('/import', { limit: Number(limit), query }, 'Import started')}><Icon name="download" size={16} />Import</button>
        </div>
        <details><summary>Custom archive.org search (optional)</summary>
          <input className="full" value={query} onChange={(e) => setQuery(e.target.value)} placeholder='e.g. collection:feature_films AND mediatype:movies AND subject:"film noir"' />
        </details>
      </div>
      <div className="act">
        <div><strong>Check files on archive.org</strong><small>Verifies each title, fixes wrong IDs, refreshes qualities.</small></div>
        <div className="act-controls">
          <label className="check"><input type="checkbox" checked={stale} onChange={(e) => setStale(e.target.checked)} />Only stale</label>
          <button className="btn ghost sm" disabled={running} onClick={() => start('/sync', { only_stale: stale }, 'Sync started')}><Icon name="refresh" size={16} />Sync</button>
        </div>
      </div>
      <div className="act">
        <div><strong>Posters, cast & ratings (TMDB)</strong><small>{ov.tmdb ? 'Enriches every title from TMDB.' : 'Set TMDB_API_KEY on the server to enable.'}</small></div>
        <div className="act-controls"><button className="btn ghost sm" disabled={running || !ov.tmdb} onClick={() => start('/tmdb', {}, 'Enrichment started')}>Enrich</button>
          <button className="btn ghost sm" onClick={async () => { await adm('POST', '/reindex'); toast('Search index rebuilt'); }}>Rebuild search</button></div>
      </div>
      <form className="act" onSubmit={add}>
        <div><strong>Add a title by link</strong><small>Paste an archive.org link or identifier. A series becomes one episode per video file.</small></div>
        <div className="act-controls wrap">
          <input className="grow" value={ident} onChange={(e) => setIdent(e.target.value)} placeholder="https://archive.org/details/…" aria-label="archive.org link or id" required />
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Type"><option value="movie">Movie</option><option value="series">Series</option></select>
          <button className="btn primary sm" disabled={busy}>{busy ? 'Adding…' : 'Add'}</button>
        </div>
      </form>
    </div>
  );
}

function JobLog({ job }) {
  const box = useRef(null);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [job.log.length]);
  const state = job.running ? `Running: ${job.running}` : job.error ? 'Failed' : job.finished ? 'Done' : 'Idle';
  return (
    <div className="panel">
      <h3>Activity <span className={`pill ${job.running ? 'pending' : job.error ? 'error' : 'ok'}`}>{state}</span></h3>
      <pre className="log" ref={box} aria-live="polite">{job.log.length ? job.log.join('\n') : 'Nothing has run yet. Start an import or sync on the left.'}</pre>
      {job.result && !job.running && <p className="fine">Result: {JSON.stringify(job.result)}</p>}
    </div>
  );
}

function TitleTable({ reload }) {
  const [f, setF] = useState({ q: '', status: '', kind: '', page: 1 });
  const [data, setData] = useState(null);
  const [edit, setEdit] = useState(null);
  const fetchList = useCallback(async () => {
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
    try { setData(await adm('GET', `/titles?${qs}`)); } catch (e) { toast(e.message, 'error'); }
  }, [f]);
  useEffect(() => { const t = setTimeout(fetchList, f.q ? 250 : 0); return () => clearTimeout(t); }, [fetchList, f.q]);
  useEffect(() => { window.addEventListener('cv-admin-refresh', fetchList); return () => window.removeEventListener('cv-admin-refresh', fetchList); }, [fetchList]);
  const set = (o) => setF((x) => ({ ...x, page: 1, ...o }));
  const act = async (fn, msg) => { try { await fn(); if (msg) toast(msg); fetchList(); reload(); } catch (e) { toast(e.message, 'error'); } };

  return (
    <section className="panel">
      <div className="table-head">
        <h3>Titles {data && <small className="muted">{data.total}</small>}</h3>
        <input className="grow" placeholder="Search name or archive id…" value={f.q} onChange={(e) => set({ q: e.target.value })} />
        <select value={f.status} onChange={(e) => set({ status: e.target.value })} aria-label="Status"><option value="">Any status</option>{Object.entries(STATUS).map(([k, [, l]]) => <option key={k} value={k}>{l}</option>)}</select>
        <select value={f.kind} onChange={(e) => set({ kind: e.target.value })} aria-label="Type"><option value="">All types</option><option value="movie">Movies</option><option value="series">Series</option></select>
      </div>
      <div className="table-wrap">
        <table className="tbl">
          <thead><tr><th></th><th>Title</th><th>Archive ID</th><th>Status</th><th>Files</th><th></th></tr></thead>
          <tbody>
            {data?.items.map((t) => (
              <tr key={t.id}>
                <td className="thumb"><Poster src={t.poster_url} name={t.name} /></td>
                <td><a href={`/title/${t.slug}`} target="_blank" rel="noreferrer"><strong>{t.name}</strong></a><small>{t.kind === 'series' ? 'Series' : 'Movie'} · {t.year || '—'}{t.featured ? ' · ★ featured' : ''}</small></td>
                <td><code>{t.ia_identifier || '—'}</code></td>
                <td><span className={`pill ${STATUS[t.sources_status]?.[0]}`}>{STATUS[t.sources_status]?.[1] || t.sources_status}</span></td>
                <td>{t.files}</td>
                <td className="row-actions">
                  <button className="icon-btn" title="Re-check files" onClick={() => act(async () => { const r = await adm('POST', `/titles/${t.id}/sync`); toast(r.status === 'ok' ? 'Files found' : r.status === 'missing' ? 'Not on the archive' : 'Archive unreachable', r.status === 'ok' ? 'info' : 'error'); })}><Icon name="refresh" size={15} /></button>
                  <button className="icon-btn" title="Edit" onClick={() => setEdit(t)}><Icon name="edit" size={15} /></button>
                  <button className="icon-btn" title="Delete" onClick={() => confirm(`Delete “${t.name}”? This removes it from the catalog.`) && act(() => adm('DELETE', `/titles/${t.id}`), 'Deleted')}><Icon name="trash" size={15} /></button>
                </td>
              </tr>
            ))}
            {data && data.items.length === 0 && <tr><td colSpan="6" className="muted center">No titles match.</td></tr>}
          </tbody>
        </table>
      </div>
      {data && data.pages > 1 && (
        <nav className="pager">
          <button className="btn ghost sm" disabled={f.page <= 1} onClick={() => setF({ ...f, page: f.page - 1 })}>Prev</button>
          <span>Page {data.page} of {data.pages}</span>
          <button className="btn ghost sm" disabled={f.page >= data.pages} onClick={() => setF({ ...f, page: f.page + 1 })}>Next</button>
        </nav>
      )}
      {edit && <EditModal t={edit} onClose={() => setEdit(null)} onSave={(body) => act(async () => { await adm('PATCH', `/titles/${edit.id}`, body); setEdit(null); }, 'Saved')} />}
    </section>
  );
}

function EditModal({ t, onClose, onSave }) {
  const [v, setV] = useState({ name: t.name, year: t.year || '', ia_identifier: t.ia_identifier || '', description: t.description || '', poster_url: t.poster_url || '', rating: t.rating || 0, featured: !!t.featured });
  const up = (k) => (e) => setV({ ...v, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  return (
    <Modal onClose={onClose} label="Edit title">
      <form className="dl edit" onSubmit={(e) => { e.preventDefault(); onSave({ ...v, year: v.year ? Number(v.year) : null, rating: Number(v.rating) || 0 }); }}>
        <h3>Edit title</h3>
        <label>Name<input value={v.name} onChange={up('name')} required /></label>
        <div className="two"><label>Year<input type="number" value={v.year} onChange={up('year')} /></label>
          <label>Rating (0–10)<input type="number" step="0.1" min="0" max="10" value={v.rating} onChange={up('rating')} /></label></div>
        <label>archive.org identifier<input value={v.ia_identifier} onChange={up('ia_identifier')} placeholder="e.g. night_of_the_living_dead" /><small>Changing this re-checks the files.</small></label>
        <label>Poster URL<input value={v.poster_url} onChange={up('poster_url')} placeholder="https://…" /></label>
        <label>Description<textarea rows="4" value={v.description} onChange={up('description')} /></label>
        <label className="check"><input type="checkbox" checked={v.featured} onChange={up('featured')} />Feature on the home page hero</label>
        <div className="modal-actions"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary">Save</button></div>
      </form>
    </Modal>
  );
}
