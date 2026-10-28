import Hero from '../components/Hero.jsx';
import { Rail, Spinner, useFetch } from '../components/ui.jsx';
import { Link } from '../router.jsx';

export default function Home() {
  const [{ data, loading, error }] = useFetch('/home');
  if (loading) return <div className="page-center"><Spinner /></div>;
  if (error) return <div className="page-center"><p>Couldn’t load the catalog: {error.message}</p></div>;
  return (
    <>
      <Hero items={data.hero} />
      <div className="rails">
        <div className="stats-strip">
          <span><b>{data.stats.movies}</b> movies</span>
          <span><b>{data.stats.series}</b> series</span>
          <Link to="/browse">Browse everything →</Link>
        </div>
        {data.continue.length > 0 && <Rail title="Continue watching" items={data.continue} to="/history" />}
        {data.rails.map((r) => <Rail key={r.key} title={r.title} items={r.items}
          to={r.key.startsWith('genre-') ? `/browse?genre=${encodeURIComponent(r.title)}` : r.key === 'series' ? '/browse?kind=series' : r.key === 'top' ? '/browse?sort=rating' : r.key === 'new' ? '/browse?sort=newest' : r.key === 'latest' ? '/browse?sort=year_desc' : '/browse'} />)}
      </div>
    </>
  );
}
