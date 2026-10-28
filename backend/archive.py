"""Internet Archive client: verify/resolve items, list playable files, import more titles.

Everything that talks to archive.org lives here so it can be swapped out in tests.
Set IA_BASE to point at a mirror or a fake server.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

import catalog
import db
import direct

IA_BASE = os.environ.get("IA_BASE", "https://archive.org").rstrip("/")
TIMEOUT = (10, 70)   # archive.org search can be slow; fail only after a long wait
RETRY_STATUS = (429, 500, 502, 503, 504)
HEADERS = {"User-Agent": "CineVault/1.0 (public-domain media browser)"}
VIDEO_EXT = {"mp4", "m4v", "webm", "ogv", "mkv", "avi", "mpeg", "mpg", "mov"}
PLAYABLE_EXT = {"mp4", "m4v", "webm", "ogv"}
SKIP_WORDS = ("trailer", "sample", "preview", "teaser", "_thumb")
RETRY_AFTER = timedelta(hours=1)   # when archive.org was unreachable
RECHECK_AFTER = timedelta(days=7)  # when sources were fine


def _get(path, **params):
    """GET json from archive.org, retrying timeouts / 5xx / rate limits with backoff."""
    last = None
    for attempt in range(3):
        try:
            r = requests.get(f"{IA_BASE}{path}", params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code in RETRY_STATUS:
                raise requests.HTTPError(f"HTTP {r.status_code} from archive.org", response=r)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code not in RETRY_STATUS:
                raise
            last = e
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    raise last


def media_url(identifier, name):
    from urllib.parse import quote
    return f"{IA_BASE}/download/{identifier}/{quote(name)}"


def file_url(f):
    """Download URL for a media_files row (direct sources store their own full URL)."""
    return f["url"] if "url" in f.keys() and f["url"] else media_url(f["ia_identifier"], f["name"])


def details_url(identifier):
    return f"{IA_BASE}/details/{identifier}"


# ---------------------------------------------------------------- lookups
def get_metadata(identifier):
    """Item metadata or None when the item does not exist."""
    if not identifier:
        return None
    try:
        data = _get(f"/metadata/{identifier}")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise
    return data if data.get("files") is not None and data.get("metadata") else None


def search_items(query, rows=10, sort="downloads desc", fields=None, page=1):
    fields = fields or ["identifier", "title", "year", "downloads"]
    # archive.org only honours the bracketed names `fl[]` / `sort[]`; plain `fl` returns docs without fields
    data = _get("/advancedsearch.php", **{"q": query, "fl[]": fields, "sort[]": [sort], "rows": rows, "page": page, "output": "json"})
    return [d for d in data.get("response", {}).get("docs", []) if d.get("identifier")]


def find_identifier(name, year, kind="movie"):
    """Best archive.org match for a title when our stored identifier is wrong."""
    safe = name.replace('"', " ")
    q = f'title:("{safe}") AND mediatype:movies'
    docs = search_items(q, rows=15)
    best, best_score = None, -1
    for d in docs:
        if not d.get("identifier"):
            continue
        score = 0
        dyear = str(d.get("year") or "")
        if year and dyear == str(year):
            score += 5
        title = (d.get("title") or "").lower()
        if title == name.lower():
            score += 4
        elif name.lower() in title:
            score += 2
        score += min(int(d.get("downloads") or 0) / 100000, 3)
        if score > best_score:
            best, best_score = d, score
    return best.get("identifier") if best and best_score >= 2 else None


# ---------------------------------------------------------------- file parsing
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _duration(v):
    """Seconds from archive.org's many formats: 5700, '01:35:00', '1:35:00 min', '1 hr 30 min', '95 min'. None if unknown."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if ":" in s and nums and len(nums) <= 3:
        out = 0.0
        for p in nums:
            out = out * 60 + float(p)
        return out
    h = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", s)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|min|mins|minute|minutes)\b", s)
    if h or m:
        return (float(h.group(1)) * 3600 if h else 0) + (float(m.group(1)) * 60 if m else 0)
    return None


def runtime_minutes(raw):
    sec = _duration(_first(raw))
    if not sec:
        return None
    return int(round(sec / 60)) if sec > 600 else int(sec) if sec >= 1 else None


def quality_label(height, fmt, name):
    if height:
        h = int(height)
        for lim, lab in ((1000, "1080p"), (680, "720p"), (440, "480p"), (300, "360p")):
            if h >= lim:
                return lab
        return f"{h}p"
    m = re.search(r"(2160|1080|720|480|360)p", name)
    if m:
        return f"{m.group(1)}p"
    return (fmt or name.rsplit(".", 1)[-1]).upper()


def _natkey(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def video_groups(meta):
    """Group an item's video files by stem -> {stem: [file dicts]} (one stem per episode/movie)."""
    groups = {}
    for f in meta.get("files", []):
        name = f.get("name", "")
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in VIDEO_EXT or any(w in name.lower() for w in SKIP_WORDS):
            continue
        height = _num(f.get("height"))
        fmt = f.get("format")
        entry = {
            "name": name, "format": fmt, "size": int(_num(f.get("size")) or 0), "height": int(height) if height else None,
            "duration": _duration(f.get("length")), "ext": ext,
            "quality": quality_label(height, fmt, name), "playable": 1 if ext in PLAYABLE_EXT else 0,
        }
        stem = name.rsplit(".", 1)[0]
        stem = re.sub(r"[._ -](ia|512kb|hd|sd|\d{3,4}p)$", "", stem, flags=re.I)
        groups.setdefault(stem, []).append(entry)
    return dict(sorted(groups.items(), key=lambda kv: _natkey(kv[0])))


# ---------------------------------------------------------------- sync
def _now():
    return datetime.now(timezone.utc)


def _stamp(conn, title_id, status):
    conn.execute(
        "UPDATE titles SET sources_status=?, sources_checked_at=? WHERE id=?",
        (status, _now().strftime("%Y-%m-%d %H:%M:%S"), title_id),
    )


def _store_files(conn, title_id, episode_id, identifier, files):
    for f in files:
        conn.execute(
            """INSERT INTO media_files(title_id, episode_id, ia_identifier, name, format, size, height, duration, quality, playable)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ia_identifier, name) DO UPDATE SET title_id=excluded.title_id, episode_id=excluded.episode_id,
                 format=excluded.format, size=excluded.size, height=excluded.height, duration=excluded.duration,
                 quality=excluded.quality, playable=excluded.playable""",
            (title_id, episode_id, identifier, f["name"], f["format"], f["size"], f["height"], f["duration"],
             f["quality"], f["playable"]),
        )


def sync_title(conn, title):
    """Verify the archive.org item, fix the identifier if needed and store its video files.

    Returns the resulting sources_status ('ok' | 'missing' | 'error').
    """
    tid = title["id"]
    ident = title["ia_identifier"]
    try:
        if title["source_url"]:                       # direct-download folder (e.g. Blender open movies)
            status = direct.sync_title(conn, title)
            _stamp(conn, tid, status)
            return status
        if title["ia_collection"]:                    # series whose episodes are the items of an archive.org collection
            status = _sync_collection(conn, title)
            _stamp(conn, tid, status)
            return status
        meta = get_metadata(ident)
        if meta is None:
            ident = find_identifier(title["name"], title["year"], title["kind"])
            meta = get_metadata(ident) if ident else None
        if meta is None:
            _stamp(conn, tid, "missing")
            return "missing"

        groups = video_groups(meta)
        if not groups:
            conn.execute("UPDATE titles SET ia_identifier=? WHERE id=?", (ident, tid))
            _stamp(conn, tid, "missing")
            return "missing"

        conn.execute(
            "UPDATE titles SET ia_identifier=?, poster_url=COALESCE(NULLIF(poster_url,''),?) WHERE id=?",
            (ident, catalog.ia_thumb(ident, IA_BASE), tid),
        )
        if title["poster_url"] and "/services/img/" in title["poster_url"]:
            conn.execute("UPDATE titles SET poster_url=?, backdrop_url=? WHERE id=?",
                         (catalog.ia_thumb(ident, IA_BASE),) * 2 + (tid,))
        if title["kind"] == "movie":
            _sync_movie(conn, tid, ident, groups)
        else:
            _sync_series(conn, tid, ident, groups)
        _stamp(conn, tid, "ok")
        return "ok"
    except (requests.RequestException, ValueError):
        _stamp(conn, tid, "error")
        return "error"


def _sync_movie(conn, tid, ident, groups):
    # the main feature is the stem with the longest duration / biggest file
    def weight(files):
        return max((f["duration"] or 0, f["size"]) for f in files)
    main_stem = max(groups, key=lambda s: weight(groups[s]))
    conn.execute("DELETE FROM media_files WHERE title_id=? AND episode_id IS NULL AND ia_identifier=?", (tid, ident))
    _store_files(conn, tid, None, ident, groups[main_stem])


def _sync_series(conn, tid, ident, groups):
    episodes = conn.execute(
        "SELECT id FROM episodes WHERE title_id=? ORDER BY season, number", (tid,)
    ).fetchall()
    conn.execute("DELETE FROM media_files WHERE title_id=?", (tid,))
    for ep, (stem, files) in zip(episodes, groups.items()):
        conn.execute("UPDATE episodes SET ia_identifier=? WHERE id=?", (ident, ep["id"]))
        _store_files(conn, tid, ep["id"], ident, files)


def _sync_collection(conn, title):
    """Each episode has its own archive.org item; fetch every item's files."""
    eps = conn.execute("SELECT id, ia_identifier FROM episodes WHERE title_id=? ORDER BY season, number", (title["id"],)).fetchall()
    conn.execute("DELETE FROM media_files WHERE title_id=?", (title["id"],))
    got = 0
    for ep in eps:
        try:
            meta = get_metadata(ep["ia_identifier"])
        except requests.RequestException:
            continue
        groups = video_groups(meta) if meta else {}
        if not groups:
            continue
        main = max(groups, key=lambda s: max((f["duration"] or 0, f["size"]) for f in groups[s]))
        _store_files(conn, title["id"], ep["id"], ep["ia_identifier"], groups[main])
        got += 1
    return "ok" if got else ("error" if eps else "missing")


def needs_check(title):
    status, checked = title["sources_status"], title["sources_checked_at"]
    if status == "pending" or not checked:
        return True
    age = _now() - datetime.strptime(checked, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if status == "error":
        return age > RETRY_AFTER
    return age > RECHECK_AFTER


def ensure_sources(conn, title_id):
    """Lazy per-title sync used when a client opens a title page."""
    title = conn.execute("SELECT * FROM titles WHERE id=?", (title_id,)).fetchone()
    if title and (title["ia_identifier"] is not None or title["source_url"]) and needs_check(title):
        sync_title(conn, title)
        conn.commit()


def sync_all(conn, progress=print, only_stale=False):
    out = {"ok": 0, "missing": 0, "error": 0}
    for title in conn.execute("SELECT * FROM titles ORDER BY popularity DESC").fetchall():
        if only_stale and not needs_check(title):
            continue
        try:
            status = sync_title(conn, title)
        except Exception as e:  # one bad item must never stop the run
            conn.rollback()
            _stamp(conn, title["id"], "error")
            status = "error"
            progress(f"      ! {title['name']}: {type(e).__name__}: {e}")
        conn.commit()
        out[status] += 1
        progress(f"  [{status:7}] {title['name']}")
    return out


# ---------------------------------------------------------------- import more titles
GENRE_KEYWORDS = {
    "Horror": ["horror", "zombie", "monster", "vampire", "ghost", "haunted"],
    "Sci-Fi": ["science fiction", "sci-fi", "scifi", "space", "alien", "robot"],
    "Comedy": ["comedy", "slapstick", "humor", "humour", "farce"],
    "Film-Noir": ["noir"],
    "Crime": ["crime", "gangster", "detective", "mystery"],
    "Western": ["western", "cowboy"],
    "Romance": ["romance", "love story"],
    "Adventure": ["adventure", "jungle", "treasure"],
    "Animation": ["animation", "animated", "cartoon"],
    "Documentary": ["documentary"],
    "War": ["war", "wwii", "world war"],
    "Musical": ["musical", "music"],
    "Silent": ["silent"],
    "Family": ["family", "children", "kids"],
    "Thriller": ["thriller", "suspense"],
    "Drama": ["drama"],
    "History": ["history", "historical"],
    "Fantasy": ["fantasy", "fairy tale"],
    "Action": ["action"],
}

# curated archive.org collections (the key is what the admin UI / CLI call a preset)
PRESETS = {
    "feature_films": ("Feature films", "feature_films"),
    "classic_tv": ("Classic TV", "classic_tv"),
    "silent_films": ("Silent films", "silent_films"),
    "film_noir": ("Film noir", "film_noir"),
    "scifi_horror": ("Sci-fi & horror", "SciFi_Horror"),
    "animation": ("Animation & cartoons", "animationandcartoons"),
    "opensource_movies": ("Community films (Creative Commons)", "opensource_movies"),
    "prelinger": ("Prelinger vintage films", "prelinger"),
    "classic_tv_series": ("Classic TV (as series)", "classic_tv"),
    "cartoon_series": ("Cartoons (as series)", "animationandcartoons"),
    "sci_fi_tv_series": ("Sci-fi serials (as series)", "SciFi_Horror"),
}
SERIES_PRESETS = {"classic_tv_series", "cartoon_series", "sci_fi_tv_series"}
LICENSE_CLAUSE = "(licenseurl:(http*creativecommons.org/publicdomain*) OR licenseurl:(http*creativecommons.org/licenses/*))"
IMPORT_FIELDS = ["identifier", "title", "year", "creator", "description", "subject", "downloads", "avg_rating", "num_reviews", "runtime"]
PAGE_ROWS = 50
MAX_PAGES = 40  # scan at most 2000 results per import run


def build_query(preset="feature_films", strict=True, query=None):
    """Search string for an import. `query` (custom) wins; `strict` keeps only items archive.org marks as
    public domain / Creative Commons (small but safest); off = whole collection."""
    if query:
        return query
    coll = PRESETS.get(preset, ("", preset))[1]
    q = f"collection:{coll} AND mediatype:movies"
    return f"{q} AND {LICENSE_CLAUSE}" if strict else q


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def map_genres(subjects):
    text = " ".join(subjects if isinstance(subjects, list) else [subjects or ""]).lower()
    found = [g for g, kws in GENRE_KEYWORDS.items() if any(k in text for k in kws)]
    return found[:4] or ["Drama"]


def _clean_html(s):
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    return re.sub(r"\s+", " ", s).strip()


def _import_series_doc(conn, d):
    """Series mode: keep an item only if it holds several episodes (video files); one episode per file."""
    ident = d.get("identifier")
    if not ident or conn.execute("SELECT 1 FROM titles WHERE ia_identifier=?", (ident,)).fetchone():
        return None
    meta = get_metadata(ident)
    if not meta or len(video_groups(meta)) < 2:
        return None
    # add_from_identifier commits and syncs; it is fine inside the savepoint (nothing else is pending)
    try:
        add_from_identifier(conn, ident, "series", progress=lambda *_: None)
    except ValueError:
        return None
    return _clean_html(_first(d.get("title"))) or ident


def _import_doc(conn, d):
    """Insert one search result as a movie. Returns the name added, or None if it was a duplicate."""
    ident = d.get("identifier")
    if not ident or conn.execute("SELECT 1 FROM titles WHERE ia_identifier=?", (ident,)).fetchone():
        return None
    name = _clean_html(_first(d.get("title"))) or ident
    try:
        year = int(str(_first(d.get("year")) or "")[:4])
    except ValueError:
        year = None
    rating5 = _num(_first(d.get("avg_rating")))
    rating = round(rating5 * 2, 1) if rating5 else 0
    votes = int(_num(_first(d.get("num_reviews"))) or 0)
    downloads = int(_num(_first(d.get("downloads"))) or 0)
    creator = _clean_html(_first(d.get("creator"))) or None
    cur = conn.execute(
        """INSERT INTO titles(slug, kind, name, year, description, rating, votes, runtime, director,
             poster_url, backdrop_url, ia_identifier, popularity, license)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (catalog.unique_slug(conn, catalog.slugify(f"{name}-{year}" if year else name)), "movie", name, year,
         _clean_html(_first(d.get("description")))[:900] or "No description available.",
         rating, votes, runtime_minutes(d.get("runtime")), creator,
         catalog.ia_thumb(ident, IA_BASE), catalog.ia_thumb(ident, IA_BASE), ident,
         catalog.popularity(rating or 5, downloads / 50), "Public Domain / CC"))
    tid = cur.lastrowid
    catalog.set_genres(conn, tid, map_genres(d.get("subject")))
    if creator:
        catalog.set_credit(conn, tid, creator[:120], "director")
    db.rebuild_fts(conn, tid)
    return f"{name} ({year or '?'})"


def import_catalog(conn, limit=100, query=None, progress=print, preset="feature_films", strict=True, kind=None):
    """Add up to `limit` NEW films. Pages through the results (skipping ones already in the catalog), so
    running it again keeps adding more instead of re-reading the same top results. One bad record is
    logged and skipped - it never aborts the run."""
    kind = kind or ("series" if preset in SERIES_PRESETS else "movie")
    q = build_query(preset, strict, query)
    progress(f"Searching archive.org: {q}")
    if strict and not query and not search_items(q, rows=1, fields=["identifier"]):
        # most items in these collections carry no licence tag, so the strict filter matches nothing
        strict = False
        q = build_query(preset, False, query)
        progress("No items in this collection are tagged public domain / CC, so importing the whole collection instead "
                 "(almost always old public-domain material - review what you publish).")
        progress(f"Searching archive.org: {q}")
    added = skipped = seen = 0
    for page in range(1, MAX_PAGES + 1):
        docs = search_items(q, rows=PAGE_ROWS, fields=IMPORT_FIELDS, page=page)
        if not docs:
            break
        seen += len(docs)
        for d in docs:
            if added >= limit:
                break
            try:
                if kind == "series":          # add_from_identifier commits per item, so no savepoint here
                    name = _import_series_doc(conn, d)
                else:
                    conn.execute("SAVEPOINT imp")
                    try:
                        name = _import_doc(conn, d)
                        conn.execute("RELEASE imp")
                    except Exception:
                        conn.execute("ROLLBACK TO imp")
                        conn.execute("RELEASE imp")
                        raise
            except Exception as e:  # noqa: BLE001 - keep going, report it
                skipped += 1
                progress(f"  ! skipped {d.get('identifier')}: {type(e).__name__}: {e}")
                continue
            if name:
                added += 1
                progress(f"  + {name}")
        conn.commit()
        if added >= limit or len(docs) < PAGE_ROWS:
            break
    if seen == 0:
        progress("archive.org returned no results for that search." + (
            " Try turning off 'only items marked public domain / CC' or pick another collection." if strict else ""))
    elif added == 0:
        progress(f"Scanned {seen} results - all were already in your catalog. Try another collection or turn off the licence filter.")
    if skipped:
        progress(f"{skipped} records were skipped because of bad data.")
    return added


# ---------------------------------------------------------------- add one title by hand (admin)
def parse_identifier(ref):
    """Accepts an archive.org URL (details/download/embed) or a bare identifier."""
    ref = (ref or "").strip()
    m = re.search(r"archive\.org/(?:details|download|embed|metadata)/([^/?#\s]+)", ref)
    ident = m.group(1) if m else ref
    return ident if re.fullmatch(r"[A-Za-z0-9._-]+", ident or "") else None


def add_from_identifier(conn, ref, kind="movie", progress=print):
    """Create a catalog title from one archive.org item (series: one episode per video file)."""
    ident = parse_identifier(ref)
    if not ident:
        raise ValueError("That doesn't look like an archive.org link or identifier")
    if conn.execute("SELECT 1 FROM titles WHERE ia_identifier=?", (ident,)).fetchone():
        raise ValueError("This item is already in the catalog")
    meta = get_metadata(ident)
    if not meta:
        raise ValueError("archive.org has no item with that identifier")
    md = meta["metadata"]
    is_collection = _first(md.get("mediatype")) == "collection"
    groups = {} if is_collection else video_groups(meta)
    collection_items = []
    if is_collection:
        kind = "series"
        collection_items = search_items(f"collection:{ident} AND mediatype:movies", rows=300, sort="titleSorter asc",
                                         fields=["identifier", "title"])
        if not collection_items:
            raise ValueError("That collection has no videos")
    elif not groups:
        raise ValueError("The item has no video files")
    name = _clean_html(_first(md.get("title"))) or ident
    try:
        year = int(str(_first(md.get("year")) or _first(md.get("date")) or "")[:4])
    except ValueError:
        year = None
    desc = _clean_html(_first(md.get("description")))[:900] or "No description available."
    cur = conn.execute(
        """INSERT INTO titles(slug, kind, name, year, description, rating, votes, runtime, director,
             poster_url, backdrop_url, ia_identifier, popularity, license)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (catalog.unique_slug(conn, catalog.slugify(f"{name}-{year}" if year else name)), kind, name, year, desc, 0, 0, None,
         _first(md.get("creator")), catalog.ia_thumb(ident, IA_BASE), catalog.ia_thumb(ident, IA_BASE), ident, 5, "Public Domain / CC"))
    tid = cur.lastrowid
    if is_collection:
        conn.execute("UPDATE titles SET ia_collection=? WHERE id=?", (ident, tid))
    catalog.set_genres(conn, tid, map_genres(md.get("subject")))
    if _first(md.get("creator")):
        catalog.set_credit(conn, tid, _first(md.get("creator")), "director")
    if is_collection:
        for n, item in enumerate(sorted(collection_items, key=lambda d: _natkey(_first(d.get("title")) or d["identifier"])), start=1):
            conn.execute("INSERT INTO episodes(title_id, season, number, name, ia_identifier) VALUES (?,?,?,?,?)",
                         (tid, 1, n, _clean_html(_first(item.get("title"))) or item["identifier"], item["identifier"]))
    elif kind == "series":
        for n, stem in enumerate(groups, start=1):
            conn.execute("INSERT INTO episodes(title_id, season, number, name) VALUES (?,?,?,?)",
                         (tid, 1, n, re.sub(r"[_]+", " ", stem).strip()))
    db.rebuild_fts(conn, tid)
    conn.commit()
    sync_title(conn, conn.execute("SELECT * FROM titles WHERE id=?", (tid,)).fetchone())
    conn.commit()
    progress(f"  + {name} ({year or '?'}) as {kind}")
    return tid
