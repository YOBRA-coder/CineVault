import Header from './components/Header.jsx';
import { Toasts, Icon } from './components/ui.jsx';
import Home from './pages/Home.jsx';
import Browse from './pages/Browse.jsx';
import Detail from './pages/Detail.jsx';
import Player from './pages/Player.jsx';
import { Downloads, History, MyList } from './pages/Library.jsx';
import Admin from './pages/Admin.jsx';
import Discover from './pages/Discover.jsx';
import DiscoverDetail from './pages/DiscoverDetail.jsx';
import { Link, useLocation } from './router.jsx';
import { OfflineBar, UpdateBar } from './components/PwaBars.jsx';

function NotFound() {
  return <div className="page-center"><div className="empty"><Icon name="film" size={40} /><h3>Scene missing</h3><p>That page doesn’t exist. <Link to="/">Back to the lobby</Link></p></div></div>;
}

export default function App() {
  const { path } = useLocation();
  const seg = path.split('/').filter(Boolean);
  let page;
  if (path === '/') page = <Home />;
  else if (seg[0] === 'browse') page = <Browse />;
  else if (seg[0] === 'title' && seg[1]) page = <Detail key={seg[1]} slug={seg[1]} />;
  else if (seg[0] === 'watch' && seg[1]) page = <Player key={seg[1]} slug={seg[1]} />;
  else if (seg[0] === 'list') page = <MyList />;
  else if (seg[0] === 'history') page = <History />;
  else if (seg[0] === 'downloads') page = <Downloads />;
  else if (seg[0] === 'admin') page = <Admin />;
  else if (seg[0] === 'discover' && seg[1] && seg[2]) page = <DiscoverDetail key={`${seg[1]}-${seg[2]}`} kind={seg[1]} id={seg[2]} />;
  else if (seg[0] === 'discover') page = <Discover />;
  else page = <NotFound />;
  const watching = seg[0] === 'watch';
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      {!watching && <Header />}
      <main id="main" className={watching ? 'watching' : ''}>{page}</main>
      {!watching && (
        <footer className="footer">
          <p><b>CineVault</b> · Public-domain & openly licensed films and series, hosted by the <a href="https://archive.org" target="_blank" rel="noreferrer">Internet Archive</a>.</p>
          <p><Link to="/admin">Admin</Link></p>
          <p>Metadata may be enriched by <a href="https://www.themoviedb.org" target="_blank" rel="noreferrer">TMDB</a> when enabled; this product is not endorsed or certified by TMDB.</p>
        </footer>
      )}
      <OfflineBar />
      <UpdateBar />
      <Toasts />
    </>
  );
}
