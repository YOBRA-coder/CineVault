import { useEffect, useState } from 'react';
import { Empty, Grid, Icon, Spinner, useFetch } from '../components/ui.jsx';
import { api } from '../api.js';
import { Link, navigate, setParams, useLocation } from '../router.jsx';

const SORTS = [['popular', 'Popular'], ['rating', 'Top rated'], ['newest', 'Recently added'], ['year_desc', 'Year: newest'], ['year_asc', 'Year: oldest'], ['az', 'A–Z']];
const ERAS = [['', 'Any year'], ['1900-1929', 'Silent era (–1929)'], ['1930-1949', '1930s–40s'], ['1950-1969', '1950s–60s'], ['1970-2030', '1970 +']];

export default function Browse() {
  const { params } = useLocation();
  const q = params.get('q') || '';
  const kind = params.get('kind') || '';
  const genres = (params.get('genre') || '').split(',').filter(Boolean);
  const sort = params.get('sort') || (q ? 'relevance' : 'popular');
  const era = params.get('era') || '';
  const minRating = params.get('min') || '';
  const dl = params.get('dl') || '';
  const page = Number(params.get('page') || 1);

  const [{ data: genreList }] = useFetch(`/genres${kind ? `?kind=${kind}` : ''}`, []);
  const [showFilters, setShowFilters] = useState(false);
  const [{ data: health }] = useFetch('/health');

  const qs = new URLSearchParams({ page, per_page: 24 });
  if (q) qs.set('q', q);
  if (kind) qs.set('kind', kind);
  if (genres.length) qs.set('genre', genres.join(','));
  if (sort && !(sort === 'relevance' && !q)) qs.set('sort', sort);
  if (era) { const [a, b] = era.split('-'); qs.set('year_from', a); qs.set('year_to', b); }
  if (minRating) qs.set('min_rating', minRating);
  if (dl) qs.set('downloadable', '1');
  const [{ data, loading, error }] = useFetch(`/titles?${qs}`);
  const set = (o) => setParams(o, params);
  const toggleGenre = (g) => set({ genre: (genres.includes(g) ? genres.filter((x) => x !== g) : [...genres, g]).join(',') });
  const active = genres.length + (era ? 1 : 0) + (minRating ? 1 : 0) + (dl ? 1 : 0);
  const gotoPage = (p) => { const n = new URLSearchParams(params); n.set('page', p); navigate(`/browse?${n}`); window.scrollTo(0, 0); };

  useEffect(() => { document.title = q ? `“${q}” — CineVault` : 'Browse — CineVault'; }, [q]);

  return (
    <div className="page">
      <div className="page-head">
        <h1>{q ? <>Results for <em>“{q}”</em></> : kind === 'series' ? 'Series' : kind === 'movie' ? 'Movies' : 'Browse everything'}</h1>
        {data && <p className="muted">{data.total} title{data.total === 1 ? '' : 's'}</p>}
      </div>

      <div className="toolbar">
        <div className="seg" role="tablist" aria-label="Type">
          {[['', 'All'], ['movie', 'Movies'], ['series', 'Series']].map(([v, l]) => (
            <button key={v} role="tab" aria-selected={kind === v} className={kind === v ? 'on' : ''} onClick={() => set({ kind: v, genre: '' })}>{l}</button>
          ))}
        </div>
        <label className="select">Sort
          <select value={sort} onChange={(e) => set({ sort: e.target.value })}>
            {q && <option value="relevance">Best match</option>}
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <button className={`btn ghost sm ${active ? 'has' : ''}`} onClick={() => setShowFilters(!showFilters)} aria-expanded={showFilters}>
          <Icon name="filter" size={16} />Filters{active ? ` (${active})` : ''}
        </button>
      </div>

      <div className="chips" aria-label="Genres">
        {(genreList || []).map((g) => (
          <button key={g.name} className={`chip-btn ${genres.includes(g.name) ? 'on' : ''}`} onClick={() => toggleGenre(g.name)} aria-pressed={genres.includes(g.name)}>
            {g.name}<small>{g.count}</small>
          </button>
        ))}
      </div>

      {showFilters && (
        <div className="filters">
          <label className="select">Era
            <select value={era} onChange={(e) => set({ era: e.target.value })}>{ERAS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          </label>
          <label className="select">Rating
            <select value={minRating} onChange={(e) => set({ min: e.target.value })}>
              <option value="">Any</option><option value="6">6.0 +</option><option value="7">7.0 +</option><option value="8">8.0 +</option>
            </select>
          </label>
          <label className="check"><input type="checkbox" checked={!!dl} onChange={(e) => set({ dl: e.target.checked ? '1' : '' })} />Downloadable only</label>
          {active > 0 && <button className="btn ghost sm" onClick={() => set({ genre: '', era: '', min: '', dl: '' })}>Clear filters</button>}
        </div>
      )}

      {q && health?.tmdb && data && !loading && (
        <div className="notice discover-cta">Not the one you wanted? <Link to={`/discover?q=${encodeURIComponent(q)}`}>Search every movie & series for “{q}”</Link> — details, trailers and where to watch.</div>
      )}
      {data?.fuzzy && data.items.length > 0 && <div className="notice">No exact matches for “{q}” — showing the closest titles.</div>}
      {loading && <div className="page-center short"><Spinner /></div>}
      {error && <Empty icon="info" title="Something went wrong">{error.message}</Empty>}
      {data && !loading && data.items.length === 0 && (
        <Empty icon="search" title="Nothing found">
          Try a shorter title, an actor’s name, or a genre like <Link to="/browse?genre=Horror">Horror</Link> or <Link to="/browse?genre=Comedy">Comedy</Link>.
        </Empty>
      )}
      {data && !loading && data.items.length > 0 && <Grid items={data.items} />}

      {data && data.pages > 1 && (
        <nav className="pager" aria-label="Pagination">
          <button className="btn ghost sm" disabled={page <= 1} onClick={() => gotoPage(page - 1)}><Icon name="left" size={16} />Prev</button>
          <span>Page {page} of {data.pages}</span>
          <button className="btn ghost sm" disabled={page >= data.pages} onClick={() => gotoPage(page + 1)}>Next<Icon name="right" size={16} /></button>
        </nav>
      )}
    </div>
  );
}
