# CineVault

A premium movie & series library you can **search, preview, stream, download and track** – built on the
Internet Archive's public-domain and openly licensed catalog. It upgrades the original *MoviesDownload* Flask app
into a full React + Flask + SQLite product.

> **Why not Goojara / MovieBox / Telegram-style sources?** Those sites distribute pirated copies, vanish without
> notice, and expose you and your users to legal and malware risk. CineVault stays on legal sources, so the
> downloads are real, permanent and safe to host publicly.

## Run it

```bash
./run.sh            # macOS / Linux           (Windows: run.bat)
# open http://localhost:5000
```
Needs Python 3.9+ only – the React front end is already built in `frontend/dist`.
On first launch it creates `backend/data/cinevault.db`, loads **35 films + 3 series (42 episodes)** and, in the
background, checks archive.org to attach real download/stream files.

### Grow the catalog
```bash
cd backend
python app.py sync        # verify every item on archive.org, fix wrong IDs, fetch files & qualities
python app.py import 300  # add up to 300 more licence-marked films from archive.org (genres auto-mapped)
python app.py tmdb        # optional: needs TMDB_API_KEY – real posters, backdrops, full cast, ratings
```

## What's inside

| Area | Features |
|---|---|
| **Browse** | Hero carousel, rails (trending, top rated, new, per-genre, series), *Continue watching* |
| **Sort / filter** | Movies vs Series, multi-genre, era, min rating, downloadable-only, sort by popular / rating / newest / year / A–Z, pagination, URL-shareable filters |
| **Search** | SQLite FTS5 across title, cast, director, genre & description · prefix matching · **typo tolerance** ("nosfaratu") · live suggestions with posters + actor names · recent searches · press `/` to focus |
| **Details** | Description, genres, year, runtime, rating, licence, cast with characters, director/creator, similar titles, season picker + every episode with its own description and progress |
| **Preview** | 30-second muted clip from partway into the film |
| **Play** | Browser player with quality switch, speed, keyboard shortcuts, **resume where you stopped**, auto-play next episode |
| **Download** | Every quality/format with size, proper file names (`Title (Year) - S01E03 Name [720p].mp4`), resumable, copy-link for IDM/aria2, whole-season **link list (.txt)** and **playlist (.m3u)** |
| **Personal** | History with progress, My List, 1–5★ ratings, download log, watch stats – per device, no sign-up |
| **PWA** | Installable on Android, iOS, Windows, macOS & ChromeOS (**Install app** button, home-screen icon, standalone window, app shortcuts) · offline app shell + previously opened pages · offline banner · one-tap **update prompt** · lock-screen / headset media controls while playing |
| **UX** | Responsive, keyboard accessible, reduced-motion aware, graceful fallbacks when art or the archive is unavailable |

## Installing as an app (PWA)
* **Android / desktop Chrome & Edge**: press **Install app** in the header (or the browser's install icon).
* **iPhone / iPad**: Share → *Add to Home Screen* (the button shows these steps).
* Browsers only allow installing from **HTTPS** (or `localhost`). To use it on phones, host it behind HTTPS
  (Caddy / nginx / Cloudflare Tunnel, or any host) – the manifest and service worker need no changes.
* Offline: the shell and any catalog page you've already opened work without a connection; videos are never cached
  (they're large, and streaming needs Range requests), so playback and downloads need to be online.
* Releases: `npm run build` stamps a new service-worker version; installed apps then show *"A new version is ready – Update now"*.

## Layout
```
backend/   app.py (API + CLI) · db.py (schema, FTS) · archive.py (Internet Archive sync/import)
           catalog.py + seed_data.py (bundled catalog) · tmdb.py (optional) · tests/
frontend/  src/ (React) · public/ (manifest, sw.js, icons) · build.mjs (esbuild) · dist/ (pre-built, served by Flask)
```
Rebuild the front end after editing `src/`: `cd frontend && npm install && npm run build`
(`npm run watch` while developing).

## Tests
```bash
cd backend && python tests/run.py      # or: pytest tests
```
15 API tests run against a fake archive server (search, filters, sync, range streaming, downloads, history, ratings, import).

## Good to know
* **Client identity**: each browser gets an anonymous id (stored in `localStorage`) – history, list and ratings follow it.
  Add real accounts later by swapping `X-Client-Id` for a login token.
* **Bandwidth**: with `PROXY_MEDIA=1` every stream/download passes through your server. For public hosting set
  `PROXY_MEDIA=0`, or serve with `waitress` behind a CDN.
* **Ratings**: bundled scores are approximate editorial values; TMDB enrichment replaces them with real ones.
* **Identifiers**: bundled archive.org item IDs are best-known guesses – `sync` verifies each and searches by
  title/year when one is wrong. Titles with no copy on the archive show "Check again" instead of dead buttons.
* **Not included yet**: subtitles, user accounts, and a Chromecast button.
* Metadata may come from TMDB when enabled: *this product uses the TMDB API but is not endorsed or certified by TMDB.*
# CineVault
