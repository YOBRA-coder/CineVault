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

IA_BASE = os.environ.get("IA_BASE", "https://archive.org").rstrip("/")
TIMEOUT = (8, 25)
HEADERS = {"User-Agent": "CineVault/1.0 (public-domain media browser)"}
VIDEO_EXT = {"mp4", "m4v", "webm", "ogv", "mkv", "avi", "mpeg", "mpg", "mov"}
PLAYABLE_EXT = {"mp4", "m4v", "webm", "ogv"}
SKIP_WORDS = ("trailer", "sample", "preview", "teaser", "_thumb")
RETRY_AFTER = timedelta(hours=1)   # when archive.org was unreachable
RECHECK_AFTER = timedelta(days=7)  # when sources were fine


def _get(path, **params):
    r = requests.get(f"{IA_BASE}{path}", params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def media_url(identifier, name):
    from urllib.parse import quote
    return f"{IA_BASE}/download/{identifier}/{quote(name)}"


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


def search_items(query, rows=10, sort="downloads desc", fields=None):
    fields = fields or ["identifier", "title", "year", "downloads"]
    data = _get("/advancedsearch.php", **{"q": query, "fl[]": fields, "sort[]": [sort], "rows": rows, "page": 1, "output": "json"})
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
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        out = 0
        for p in parts:
            out = out * 60 + p
        return out
    return _num(s)


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
    except requests.RequestException:
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
    if title and title["ia_identifier"] is not None and needs_check(title):
        sync_title(conn, title)
        conn.commit()


def sync_all(conn, progress=print, only_stale=False):
    out = {"ok": 0, "missing": 0, "error": 0}
    for title in conn.execute("SELECT * FROM titles ORDER BY popularity DESC").fetchall():
        if only_stale and not needs_check(title):
            continue
        status = sync_title(conn, title)
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

IMPORT_QUERY = (
    "collection:feature_films AND mediatype:movies AND "
    "(licenseurl:(http*creativecommons.org/publicdomain*) OR licenseurl:(http*creativecommons.org/licenses/*))"
)


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def map_genres(subjects):
    text = " ".join(subjects if isinstance(subjects, list) else [subjects or ""]).lower()
    found = [g for g, kws in GENRE_KEYWORDS.items() if any(k in text for k in kws)]
    return found[:4] or ["Drama"]


def _clean_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def import_catalog(conn, limit=100, query=None, progress=print):
    """Pull the most-downloaded licence-marked films from archive.org into the catalog."""
    fields = ["identifier", "title", "year", "creator", "description", "subject", "downloads", "avg_rating", "num_reviews", "runtime"]
    docs = search_items(query or IMPORT_QUERY, rows=min(limit, 500), fields=fields)
    added = 0
    for d in docs:
        ident = d.get("identifier")
        if not ident or conn.execute("SELECT 1 FROM titles WHERE ia_identifier=?", (ident,)).fetchone():
            continue
        name = _clean_html(_first(d.get("title"))) or ident
        try:
            year = int(str(_first(d.get("year")) or "")[:4])
        except ValueError:
            year = None
        base_slug = catalog.slugify(f"{name}-{year}" if year else name)
        rating5 = _num(_first(d.get("avg_rating")))
        reviews = int(_num(_first(d.get("num_reviews"))) or 0)
        rating = round(rating5 * 2, 1) if rating5 else 0
        votes = reviews
        runtime = None
        rt = _first(d.get("runtime"))
        if rt:
            sec = _duration(rt)
            runtime = int(round(sec / 60)) if sec and sec > 600 else (int(sec) if sec else None)
        cur = conn.execute(
            """INSERT INTO titles(slug, kind, name, year, description, rating, votes, runtime, director,
                 poster_url, backdrop_url, ia_identifier, popularity, license)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (catalog.unique_slug(conn, base_slug), "movie", name, year,
             _clean_html(_first(d.get("description")))[:900] or "No description available.",
             rating, votes, runtime, _first(d.get("creator")),
             catalog.ia_thumb(ident, IA_BASE), catalog.ia_thumb(ident, IA_BASE), ident,
             catalog.popularity(rating or 5, int(_num(_first(d.get("downloads"))) or 0) / 50), "Public Domain / CC"),
        )
        tid = cur.lastrowid
        catalog.set_genres(conn, tid, map_genres(d.get("subject")))
        creators = _first(d.get("creator"))
        if creators:
            catalog.set_credit(conn, tid, creators, "director")
        db.rebuild_fts(conn, tid)
        added += 1
        progress(f"  + {name} ({year or '?'})")
    conn.commit()
    return added
