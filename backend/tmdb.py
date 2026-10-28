"""Optional enrichment from TMDB (posters, backdrops, full cast, ratings).

Enable by setting TMDB_API_KEY (free at themoviedb.org). Without a key this module does nothing and the
app uses the bundled metadata + Internet Archive thumbnails.
This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
import os
import time

import requests

import catalog
import db

API = "https://api.themoviedb.org/3"           # override with TMDB_BASE (tests / proxies)
IMG = "https://image.tmdb.org/t/p"
KEY = lambda: (os.environ.get("TMDB_API_KEY") or "").strip()  # noqa: E731
_cache = {}                                    # (path, params) -> (time, json); TMDB data barely changes
TTL = 3600


def enabled():
    return bool(KEY())


def _get(path, **params):
    """Works with either a v3 API key (32 chars) or a v4 'Read Access Token' (long JWT)."""
    key, headers = KEY(), {}
    if len(key) > 40:
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    cache_key = (path, tuple(sorted((k, str(v)) for k, v in params.items() if k != "api_key")))
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    r = requests.get(f"{os.environ.get('TMDB_BASE', API).rstrip('/')}{path}", params=params, headers=headers, timeout=(8, 20))
    r.raise_for_status()
    data = r.json()
    if len(_cache) > 500:
        _cache.clear()
    _cache[cache_key] = (time.time(), data)
    return data


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


# ---------------------------------------------------------------- discover: any movie / series, trailer, where to watch
def _img(path, size="w342"):
    return f"{IMG}/{size}{path}" if path else None


def _card(r):
    kind = "series" if r.get("media_type", "tv" if "name" in r else "movie") == "tv" else "movie"
    name = r.get("title") or r.get("name") or ""
    date = r.get("release_date") or r.get("first_air_date") or ""
    return {"id": r["id"], "kind": kind, "name": name, "year": int(date[:4]) if date[:4].isdigit() else None,
            "poster": _img(r.get("poster_path")), "overview": r.get("overview") or "",
            "rating": round(r.get("vote_average") or 0, 1), "votes": r.get("vote_count") or 0}


def search_any(q, page=1):
    d = _get("/search/multi", query=q, page=page, include_adult="false")
    items = [_card(r) for r in d.get("results", []) if r.get("media_type") in ("movie", "tv")]
    return {"items": items, "pages": d.get("total_pages", 1), "total": d.get("total_results", len(items))}


def trending():
    d = _get("/trending/all/week")
    return {"items": [_card(r) for r in d.get("results", []) if r.get("media_type") in ("movie", "tv")][:24]}


def _providers(block, region):
    """Legal places to watch in one country. `link` is TMDB's JustWatch-powered page."""
    results = (block or {}).get("results") or {}
    here = results.get(region) or {}
    pick = lambda k: [{"name": p["provider_name"], "logo": _img(p.get("logo_path"), "w92")} for p in here.get(k, [])]  # noqa: E731
    return {"region": region, "link": here.get("link"), "stream": pick("flatrate"), "free": pick("free") + pick("ads"),
            "rent": pick("rent"), "buy": pick("buy"), "regions": sorted(results.keys())}


def details(kind, tmdb_id, region="US"):
    path = f"/{'movie' if kind == 'movie' else 'tv'}/{int(tmdb_id)}"
    d = _get(path, append_to_response="credits,videos,watch/providers")
    card = _card({**d, "media_type": "movie" if kind == "movie" else "tv"})
    vids = [v for v in (d.get("videos") or {}).get("results", []) if v.get("site") == "YouTube"]
    vids.sort(key=lambda v: (v.get("type") != "Trailer", not v.get("official"), v.get("type") != "Teaser"))
    crew = (d.get("credits") or {}).get("crew") or []
    people = [c["name"] for c in crew if c.get("job") == "Director"] if kind == "movie" else [c["name"] for c in d.get("created_by", [])]
    card.update(
        tagline=d.get("tagline") or "", backdrop=_img(d.get("backdrop_path"), "w1280"), genres=[g["name"] for g in d.get("genres", [])],
        runtime=d.get("runtime") or (d.get("episode_run_time") or [None])[0], status=d.get("status"),
        seasons=d.get("number_of_seasons"), episodes=d.get("number_of_episodes"), people=people[:4],
        cast=[{"name": c["name"], "character": c.get("character"), "photo": _img(c.get("profile_path"), "w185")}
              for c in ((d.get("credits") or {}).get("cast") or [])[:14]],
        trailer=vids[0]["key"] if vids else None, watch=_providers(d.get("watch/providers"), region.upper()),
    )
    return card
