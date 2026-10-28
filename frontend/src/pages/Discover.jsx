import { useEffect, useState } from 'react';
import { Empty, Icon, Poster, Rating, Spinner, useFetch } from '../components/ui.jsx';
import { Link, navigate, useLocation } from '../router.jsx';

export function DCard({ item }) {
  const href = item.library_slug ? `/title/${item.library_slug}` : `/discover/${item.kind}/${item.id}`;
  return (
    <Link to={href} className="card" title={item.name}>
      <div className="card-art">
        <Poster src={item.poster} name={item.name} />
        {item.library_slug ? <span className="badge free">Free in library</span> : item.kind === 'series' && <span className="badge">Series</span>}
        <div className="card-hover"><p>{item.overview || 'No description yet.'}</p></div>
      </div>
      <div className="card-meta"><strong>{item.name}</strong><span><Rating value={item.rating} />{item.year || ''}</span></div>
    </Link>
  );
}

export default function Discover() {
  const { params } = useLocation();
  const q = params.get('q') || '';
  const [box, setBox] = useState(q);
  const [{ data, loading, error }] = useFetch(`/discover${q ? `?q=${encodeURIComponent(q)}` : ''}`);
  useEffect(() => setBox(q), [q]);
  useEffect(() => { document.title = q ? `Discover “${q}” — CineVault` : 'Discover — CineVault'; }, [q]);

  return (
    <div className="page">
      <div className="page-head">
        <h1>Discover</h1>
        <p className="muted">Look up any movie or series — details, cast, trailer, and where to watch it legally.</p>
      </div>
      <form className="discover-search" onSubmit={(e) => { e.preventDefault(); navigate(`/discover${box.trim() ? `?q=${encodeURIComponent(box.trim())}` : ''}`); }}>
        <Icon name="search" size={18} />
        <input value={box} onChange={(e) => setBox(e.target.value)} placeholder="e.g. Game of Thrones, Inception, Squid Game…" aria-label="Search all titles" autoFocus />
        <button className="btn primary sm">Search</button>
      </form>

      {loading && <div className="page-center short"><Spinner /></div>}
      {error && <Empty icon="info" title="Couldn’t search">{error.message}</Empty>}
      {data && !data.enabled && <TmdbSetup />}
      {data?.enabled && (
        <>
          <h2 className="section-title">{q ? `Results for “${q}”` : 'Trending this week'}</h2>
          {data.items.length === 0
            ? <Empty icon="search" title="No matches">Try another spelling. For free classics, <Link to={`/browse?q=${encodeURIComponent(q)}`}>search the library</Link>.</Empty>
            : <div className="grid">{data.items.map((i) => <DCard key={`${i.kind}-${i.id}`} item={i} />)}</div>}
          <p className="fine center-text">Titles marked <b>Free in library</b> are public domain and can be played and downloaded here. Everything else is commercially licensed — we show where to watch it legally.</p>
        </>
      )}
    </div>
  );
}

function TmdbSetup() {
  return (
    <div className="panel setup">
      <h3>Turn on Discover (free, 2 minutes)</h3>
      <ol>
        <li>Create a free account at <a href="https://www.themoviedb.org/signup" target="_blank" rel="noreferrer">themoviedb.org</a>, then open <b>Settings → API</b> and copy your <b>API Key</b> (or the <b>Read Access Token</b>).</li>
        <li>Set it as the <code>TMDB_API_KEY</code> environment variable — on Render: <b>Environment → Add</b>; locally: <code>export TMDB_API_KEY=…</code> before <code>python app.py</code>.</li>
        <li>Restart the app. Discover will then search every movie and series, with trailers and “where to watch”.</li>
      </ol>
      <p className="fine">The same key also lets the admin panel fetch real posters, cast and ratings for your library.</p>
    </div>
  );
}
