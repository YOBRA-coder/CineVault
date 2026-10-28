import { useEffect, useState } from 'react';
import { Empty, Icon, Poster, Rating, Spinner, toast, useFetch } from '../components/ui.jsx';
import TrailerModal from '../components/TrailerModal.jsx';
import { api } from '../api.js';
import { Link, navigate, setParams, useLocation } from '../router.jsx';

export function DCard({ item }) {
  const [trailer, setTrailer] = useState(null);
  const href = item.library_slug ? `/title/${item.library_slug}` : `/discover/${item.kind}/${item.id}`;
  async function preview(e) {
    e.preventDefault(); e.stopPropagation();
    try {
      const d = await api.get(`/discover/${item.kind}/${item.id}`);
      d.trailer ? setTrailer(d.trailer) : toast('No trailer is listed for this title yet', 'error');
    } catch (err) { toast(err.message, 'error'); }
  }
  return (
    <>
      <Link to={href} className="card" title={item.name}>
        <div className="card-art">
          <Poster src={item.poster} name={item.name} />
          {item.library_slug ? <span className="badge free">Free in library</span> : item.kind === 'series' && <span className="badge">Series</span>}
          <div className="card-hover"><p>{item.overview || 'No description yet.'}</p></div>
          <button className="trailer-btn" onClick={preview} aria-label={`Watch trailer for ${item.name}`}><Icon name="play" fill size={14} />Trailer</button>
        </div>
        <div className="card-meta"><strong>{item.name}</strong><span><Rating value={item.rating} />{item.year || ''}</span></div>
      </Link>
      {trailer && <TrailerModal ytKey={trailer} title={item.name} onClose={() => setTrailer(null)} />}
    </>
  );
}

const thisYear = new Date().getFullYear();
const YEARS = [['', 'All time'], [String(thisYear), `This year (${thisYear})`], [String(thisYear - 1), `Last year (${thisYear - 1})`],
  ...Array.from({ length: thisYear - 1999 - 1 }, (_, i) => String(thisYear - 2 - i)).map((y) => [y, y])];

export default function Discover() {
  const { params } = useLocation();
  const q = params.get('q') || '';
  const [box, setBox] = useState(q);
  useEffect(() => setBox(q), [q]);
  useEffect(() => { document.title = q ? `Discover “${q}” — CineVault` : 'Discover — CineVault'; }, [q]);
  return (
    <div className="page">
      <div className="page-head">
        <h1>Discover</h1>
        <p className="muted">Every movie and series — latest, most watched, top ranked. Watch the trailer, see where to stream it legally, or play it free if it’s in our library.</p>
      </div>
      <form className="discover-search" onSubmit={(e) => { e.preventDefault(); navigate(`/discover${box.trim() ? `?q=${encodeURIComponent(box.trim())}` : ''}`); }}>
        <Icon name="search" size={18} />
        <input value={box} onChange={(e) => setBox(e.target.value)} placeholder="e.g. Game of Thrones, Inception, Squid Game…" aria-label="Search all titles" />
        <button className="btn primary sm">Search</button>
      </form>
      {q ? <SearchResults q={q} /> : <BrowseAll params={params} />}
      <p className="fine center-text">Titles marked <b>Free in library</b> are public domain and can be played and downloaded here. Everything else is commercially licensed — the trailer is a preview and we show where to watch it legally.</p>
    </div>
  );
}

function SearchResults({ q }) {
  const [{ data, loading, error }] = useFetch(`/discover?q=${encodeURIComponent(q)}`);
  if (loading) return <div className="page-center short"><Spinner /></div>;
  if (error) return <Empty icon="info" title="Couldn’t search">{error.message}</Empty>;
  if (!data.enabled) return <TmdbSetup />;
  return (
    <>
      <h2 className="section-title">Results for “{q}”</h2>
      {data.items.length === 0
        ? <Empty icon="search" title="No matches">Try another spelling. For free classics, <Link to={`/browse?q=${encodeURIComponent(q)}`}>search the library</Link>.</Empty>
        : <div className="grid">{data.items.map((i) => <DCard key={`${i.kind}-${i.id}`} item={i} />)}</div>}
    </>
  );
}

const SORTS = (kind) => [['trending', 'Trending this week'], ['latest', 'Latest releases'], ['popular', 'Most watched'], ['top', 'Top ranked'], ['now', kind === 'series' ? 'On air now' : 'In cinemas now']];

function BrowseAll({ params }) {
  const kind = params.get('kind') === 'series' ? 'series' : 'movie';
  const sort = params.get('sort') || 'trending';
  const year = params.get('year') || '';
  const genre = params.get('genre') || '';
  const set = (o) => setParams(o, params);
  const [{ data: genres }] = useFetch(`/discover/genres?kind=${kind}`, [kind]);
  const [state, setState] = useState({ items: [], page: 0, pages: 1, loading: true, error: null, enabled: true });
  const key = `${kind}|${sort}|${year}|${genre}`;

  async function load(page, reset) {
    setState((s) => ({ ...s, loading: true, error: null, ...(reset ? { items: [], page: 0 } : {}) }));
    try {
      const qs = new URLSearchParams({ kind, sort, page });
      if (year && sort !== 'trending' && sort !== 'now') qs.set('year', year);
      if (genre && sort !== 'trending' && sort !== 'now') qs.set('genre', genre);
      const d = await api.get(`/discover/browse?${qs}`);
      setState((s) => {
        const seen = new Set(reset ? [] : s.items.map((i) => i.id));
        return { items: [...(reset ? [] : s.items), ...d.items.filter((i) => !seen.has(i.id))], page: d.page, pages: d.pages, loading: false, error: null, enabled: d.enabled !== false };
      });
    } catch (e) { setState((s) => ({ ...s, loading: false, error: e.message })); }
  }
  useEffect(() => { load(1, true); }, [key]); // eslint-disable-line

  if (!state.enabled) return <TmdbSetup />;
  const filtered = sort === 'trending' || sort === 'now';
  return (
    <>
      <div className="discover-filters">
        <div className="seg" role="tablist" aria-label="Type">
          {[['movie', 'Movies'], ['series', 'Series']].map(([v, l]) => <button key={v} className={kind === v ? 'on' : ''} onClick={() => set({ kind: v === 'movie' ? '' : v, genre: '' })}>{l}</button>)}
        </div>
        <div className="chips-row" role="tablist" aria-label="Sort">
          {SORTS(kind).map(([v, l]) => <button key={v} className={`chip ${sort === v ? 'on' : ''}`} onClick={() => set({ sort: v === 'trending' ? '' : v })}>{l}</button>)}
        </div>
        <label className="select">Year<select value={year} disabled={filtered} onChange={(e) => set({ year: e.target.value })}>{YEARS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label className="select">Genre<select value={genre} disabled={filtered} onChange={(e) => set({ genre: e.target.value })}><option value="">All genres</option>{(genres || []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
      </div>
      {state.error && <Empty icon="info" title="Couldn’t load this list">{state.error}</Empty>}
      {!state.error && state.items.length === 0 && !state.loading && <Empty icon="search" title="Nothing here">Try a different year or genre.</Empty>}
      <div className="grid">{state.items.map((i) => <DCard key={`${i.kind}-${i.id}`} item={i} />)}</div>
      {state.loading && <div className="page-center short"><Spinner /></div>}
      {!state.loading && state.page < state.pages && state.items.length > 0 && (
        <div className="center-text"><button className="btn ghost" onClick={() => load(state.page + 1, false)}>Load more</button></div>
      )}
    </>
  );
}

function TmdbSetup() {
  return (
    <div className="panel setup">
      <h3>Turn on Discover (free, 2 minutes)</h3>
      <ol>
        <li>Create a free account at <a href="https://www.themoviedb.org/signup" target="_blank" rel="noreferrer">themoviedb.org</a>, then open <b>Settings → API</b> and copy your <b>API Key</b> (or the <b>Read Access Token</b>).</li>
        <li>Set it as the <code>TMDB_API_KEY</code> environment variable — on Render: <b>Environment → Add</b>; locally: <code>export TMDB_API_KEY=…</code> before <code>python app.py</code>.</li>
        <li>Restart the app. Discover will then list the latest, most watched and top ranked movies and series, with trailers and “where to watch”.</li>
      </ol>
      <p className="fine">The same key also gives every library title a trailer preview, and lets the admin panel fetch real posters, cast and ratings.</p>
    </div>
  );
}
