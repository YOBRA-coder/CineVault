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

## Where the titles come from (and what isn't possible)

| Source | What you get | Play / download |
|---|---|---|
| **Internet Archive** (bundled + importer) | Public-domain & CC films and series. Admin → *Import* has collection presets (feature films, classic TV, silent, noir, sci-fi/horror, animation, open-source movies, Prelinger) and a **strict licence** toggle. Import keeps paging until it finds N *new* titles. `python app.py import 200 classic_tv --all` does the same from the CLI. | yes |
| **Blender open movies** (bundled) | Big Buck Bunny, Elephants Dream, Sintel, Tears of Steel (CC BY) from download.blender.org. | yes |
| **Any folder of video links** | Titles with a `source_url` (see `seed_data.DIRECT`) list the files in an open directory. | yes |
| **Collection links** | Paste an archive.org *collection* link in Admin → *Add by link*: it becomes a series, one episode per item. | yes |
| **Discover** (needs a free `TMDB_API_KEY`, v3 key or v4 token) | Search *every* movie and series (e.g. Game of Thrones): details, cast, trailer, and **where to watch legally** per country (JustWatch data via TMDB). | info only |

Recent or commercial titles such as Game of Thrones cannot be legally hosted or downloaded by this app, so Discover
shows where they stream, rent or sell instead. If a title also exists free in your library it is flagged *Free in library*.
Bundled archive.org identifiers are best guesses that *Sync* verifies and repairs, and bundled ratings are approximate until TMDB enrichment runs.
Existing databases are upgraded automatically: new bundled titles are added without touching or resurrecting anything you deleted.

## Admin panel
Open **/admin** (link in the footer). From there you can import films from archive.org (with a live log), re-check files,
enrich from TMDB, **add a title by pasting an archive.org link** (a series becomes one episode per video file),
and edit / feature / delete any title. Locally it just works; on a server it needs `ADMIN_TOKEN`.
Command-line equivalents: `python app.py import 300`, `python app.py add <link-or-id> [movie|series]`.

## Hosting on Render
1. Push this folder to a GitHub repo, then in Render: **New + → Blueprint** and select the repo (it reads `render.yaml`).
   *(Or New + → Web Service: build `pip install -r backend/requirements.txt`, start
   `gunicorn --chdir backend wsgi:app --workers 1 --threads 16 --timeout 300 --bind 0.0.0.0:$PORT`.)*
2. The website, API and admin all run from that one service – **nothing to start for the front end**, it is pre-built.
3. On first boot it imports `AUTO_IMPORT` films automatically. Open the Environment tab, copy the generated
   `ADMIN_TOKEN`, then visit `https://<your-app>.onrender.com/admin` to import more or manage titles.
4. Installing as a PWA on phones works as soon as you open the Render `https://` URL.

**Storage matters:** SQLite lives in a file. On a paid plan the blueprint mounts a disk at `/var/data`, so the catalog,
history, lists and ratings survive deploys. On the **free plan there is no disk** – remove the `disk:` block and the
`CINEVAULT_DB` line; the catalog is rebuilt on every start from `AUTO_IMPORT`, but viewers' history/lists reset on each
restart or deploy (free services also sleep when idle). For a free setup that keeps data, use a hosted database instead.

**Bandwidth:** the blueprint sets `PROXY_STREAM=0` so video plays straight from archive.org and doesn't use your
bandwidth; downloads still go through the server so they save with proper names (`PROXY_DOWNLOAD=0` redirects them too,
but browsers may then play the file instead of saving it).

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
40 API tests run against a strict fake archive server (search, filters, sync, range streaming, downloads, history, ratings, import, admin).

## Good to know
* **Client identity**: each browser gets an anonymous id (stored in `localStorage`) – history, list and ratings follow it.
  Add real accounts later by swapping `X-Client-Id` for a login token.
* **Bandwidth**: with `PROXY_STREAM=1` / `PROXY_DOWNLOAD=1` (the local default) media passes through your server. For public
  hosting set `PROXY_STREAM=0` so playback comes straight from archive.org.
* **Ratings**: bundled scores are approximate editorial values; TMDB enrichment replaces them with real ones.
* **Identifiers**: bundled archive.org item IDs are best-known guesses – `sync` verifies each and searches by
  title/year when one is wrong. Titles with no copy on the archive show "Check again" instead of dead buttons.
* **Not included yet**: subtitles, user accounts, and a Chromecast button.
* Metadata may come from TMDB when enabled: *this product uses the TMDB API but is not endorsed or certified by TMDB.*
