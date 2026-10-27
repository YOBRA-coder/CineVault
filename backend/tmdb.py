"""Optional enrichment from TMDB (posters, backdrops, full cast, ratings).

Enable by setting TMDB_API_KEY (free at themoviedb.org). Without a key this module does nothing and the
app uses the bundled metadata + Internet Archive thumbnails.
This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
import os

import requests

import catalog
import db

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"
KEY = lambda: os.environ.get("TMDB_API_KEY")  # noqa: E731


def enabled():
    return bool(KEY())


def _get(path, **params):
    params["api_key"] = KEY()
    r = requests.get(f"{API}{path}", params=params, timeout=(8, 20))
    r.raise_for_status()
    return r.json()


def enrich_title(conn, title):
    kind = "movie" if title["kind"] == "movie" else "tv"
    year_param = "year" if kind == "movie" else "first_air_date_year"
    found = _get(f"/search/{kind}", query=title["name"].split(" (")[0], **{year_param: title["year"] or ""})
    results = found.get("results") or []
    if not results:
        return False
    d = _get(f"/{kind}/{results[0]['id']}", append_to_response="credits")
    updates = {}
    if d.get("poster_path"):
        updates["poster_url"] = f"{IMG}/w500{d['poster_path']}"
    if d.get("backdrop_path"):
        updates["backdrop_url"] = f"{IMG}/w1280{d['backdrop_path']}"
    if d.get("overview") and len(d["overview"]) > 60:
        updates["description"] = d["overview"]
    if d.get("tagline"):
        updates["tagline"] = d["tagline"]
    if d.get("vote_count", 0) >= 20:
        updates["rating"] = round(d["vote_average"], 1)
        updates["votes"] = d["vote_count"]
    if updates:
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE titles SET {sets} WHERE id=?", (*updates.values(), title["id"]))
    cast = (d.get("credits") or {}).get("cast") or []
    if cast:
        conn.execute("DELETE FROM credits WHERE title_id=? AND role='cast'", (title["id"],))
        for i, c in enumerate(cast[:12]):
            photo = f"{IMG}/w185{c['profile_path']}" if c.get("profile_path") else None
            catalog.set_credit(conn, title["id"], c["name"], "cast", c.get("character"), i, photo)
    db.rebuild_fts(conn, title["id"])
    return True


def enrich_all(conn, progress=print):
    if not enabled():
        progress("TMDB_API_KEY not set - skipping enrichment")
        return 0
    n = 0
    for t in conn.execute("SELECT * FROM titles").fetchall():
        try:
            if enrich_title(conn, t):
                n += 1
                progress(f"  [tmdb] {t['name']}")
            conn.commit()
        except requests.RequestException as e:
            progress(f"  [tmdb error] {t['name']}: {e}")
    return n
