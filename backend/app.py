"""CineVault - public-domain movies & series: search, preview, play, download, history.

Run:      python app.py                 (serves API + built React app on http://localhost:5000)
Sync:     python app.py sync            (verify archive.org items, fetch playable files)
Import:   python app.py import 200      (add up to 200 more public-domain films from archive.org)
Add one:  python app.py add <archive.org link or id> [movie|series]
Admin UI: http://localhost:5000/admin   (set ADMIN_TOKEN to use it on a server)
Enrich:   python app.py tmdb            (optional posters/cast from TMDB when TMDB_API_KEY is set)
"""
import difflib
import hmac
import mimetypes
import os
import re
import sys
import threading
import time
from collections import deque
from urllib.parse import quote

import requests
from flask import Flask, Response, abort, g, jsonify, redirect, request, send_from_directory, stream_with_context

import archive
import catalog
import db
import tmdb

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.environ.get("CINEVAULT_DIST", os.path.join(HERE, "..", "frontend", "dist"))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
PROXY_MEDIA = os.environ.get("PROXY_MEDIA", "1") != "0"                       # master switch
PROXY_STREAM = os.environ.get("PROXY_STREAM", "1" if PROXY_MEDIA else "0") != "0"      # false = redirect playback to archive.org
PROXY_DOWNLOAD = os.environ.get("PROXY_DOWNLOAD", "1" if PROXY_MEDIA else "0") != "0"  # false = redirect downloads (browser may play instead of save)
CID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
SORTS = {
    "popular": "t.popularity DESC",
    "rating": "t.rating DESC, t.votes DESC",
    "newest": "t.added_at DESC, t.id DESC",
    "year_desc": "t.year DESC",
    "year_asc": "t.year ASC",
    "az": "t.name COLLATE NOCASE ASC",
}


def create_app():
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False
    db.init_db()
    with db.session() as conn:
        catalog.ensure_seeded(conn)

    # ------------------------------------------------------------ plumbing
    @app.before_request
    def open_db():
        g.db = db.connect()
        cid = request.headers.get("X-Client-Id") or request.args.get("cid")
        g.cid = cid if cid and CID_RE.match(cid) else None
        if g.cid:
            g.db.execute("INSERT OR IGNORE INTO clients(id) VALUES (?)", (g.cid,))

    @app.teardown_request
    def close_db(exc):
        conn = g.pop("db", None)
        if conn:
            if exc is None:
                conn.commit()
            conn.close()

    def need_client():
        if not g.cid:
            abort(400, "Missing or invalid X-Client-Id")
        return g.cid

    def need_admin():
        if ADMIN_TOKEN:
            sent = request.headers.get("X-Admin-Token", "")
            if not hmac.compare_digest(sent.encode(), ADMIN_TOKEN.encode()):
                abort(403, "Admin token required")
        elif request.remote_addr not in ("127.0.0.1", "::1"):
            abort(403, "Admin is disabled: set the ADMIN_TOKEN environment variable to enable it remotely")

    @app.after_request
    def pwa_headers(resp):
        p = request.path
        if p == "/sw.js":
            resp.headers["Cache-Control"] = "no-cache"          # browsers must always re-check the worker
            resp.headers["Service-Worker-Allowed"] = "/"
            resp.headers["Content-Type"] = "text/javascript; charset=utf-8"
        elif p == "/manifest.webmanifest":
            resp.headers["Content-Type"] = "application/manifest+json"
            resp.headers["Cache-Control"] = "no-cache"
        elif not p.startswith("/api/") and ("." not in p.rsplit("/", 1)[-1]):
            resp.headers["Cache-Control"] = "no-cache"          # SPA shell: always revalidate
        elif p.startswith("/icons/"):
            resp.headers["Cache-Control"] = "public, max-age=604800"
        return resp

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    def json_error(e):
        if request.path.startswith("/api/"):
            return jsonify(error=getattr(e, "description", str(e))), e.code
        return e

    # ------------------------------------------------------------ serializers
    def genres_for(ids):
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        out = {i: [] for i in ids}
        for r in g.db.execute(
            f"""SELECT tg.title_id, ge.name FROM title_genres tg JOIN genres ge ON ge.id = tg.genre_id
                WHERE tg.title_id IN ({marks}) ORDER BY ge.name""", ids):
            out[r["title_id"]].append(r["name"])
        return out

    def card_rows(rows):
        ids = [r["id"] for r in rows]
        gmap = genres_for(ids)
        mine, progress = set(), {}
        if g.cid and ids:
            marks = ",".join("?" * len(ids))
            mine = {r["title_id"] for r in g.db.execute(
                f"SELECT title_id FROM watchlist WHERE client_id=? AND title_id IN ({marks})", (g.cid, *ids))}
        out = []
        for r in rows:
            out.append({
                "id": r["id"], "slug": r["slug"], "kind": r["kind"], "name": r["name"], "year": r["year"],
                "rating": round(r["rating"] or 0, 1), "votes": r["votes"], "runtime": r["runtime"],
                "poster": r["poster_url"], "backdrop": r["backdrop_url"], "genres": gmap.get(r["id"], []),
                "description": r["description"], "tagline": r["tagline"], "in_list": r["id"] in mine,
                "has_files": r["sources_status"] == "ok", "license": r["license"],
            })
        return out

    def file_json(f):
        return {
            "id": f["id"], "name": f["name"], "format": f["format"], "size": f["size"], "quality": f["quality"],
            "height": f["height"], "duration": f["duration"], "playable": bool(f["playable"]),
            "ext": f["name"].rsplit(".", 1)[-1].lower(), "episode_id": f["episode_id"],
        }

    # ------------------------------------------------------------ catalog queries
    def build_filters(args):
        where, params = ["1=1"], []
        if args.get("kind") in ("movie", "series"):
            where.append("t.kind = ?")
            params.append(args["kind"])
        for gname in [x for x in args.get("genre", "").split(",") if x]:
            where.append("EXISTS (SELECT 1 FROM title_genres tg JOIN genres ge ON ge.id=tg.genre_id "
                         "WHERE tg.title_id=t.id AND ge.name=?)")
            params.append(gname)
        if args.get("year_from", type=int):
            where.append("t.year >= ?")
            params.append(args.get("year_from", type=int))
        if args.get("year_to", type=int):
            where.append("t.year <= ?")
            params.append(args.get("year_to", type=int))
        if args.get("min_rating", type=float):
            where.append("t.rating >= ?")
            params.append(args.get("min_rating", type=float))
        if args.get("downloadable") == "1":
            where.append("t.sources_status != 'missing'")
        return " AND ".join(where), params

    def fuzzy_ids(q, limit=8):
        """Typo tolerance: closest title/cast names by edit similarity."""
        names = {}
        for r in g.db.execute("SELECT id, name FROM titles"):
            names.setdefault(r["name"].lower(), []).append(r["id"])
        for r in g.db.execute("SELECT c.title_id AS id, p.name FROM credits c JOIN people p ON p.id=c.person_id"):
            names.setdefault(r["name"].lower(), []).append(r["id"])
        ql = q.lower()
        scored = []
        for n in names:
            cands = [n, n[:len(ql)]] + n.split() + [w[:len(ql)] for w in n.split()]
            best = max(difflib.SequenceMatcher(None, ql, c).ratio() for c in cands)
            if best >= 0.72:
                scored.append((best, n))
        ids = []
        for _, n in sorted(scored, reverse=True):
            for i in names[n]:
                if i not in ids:
                    ids.append(i)
        return ids[:limit]

    @app.get("/api/titles")
    def list_titles():
        a = request.args
        page = max(a.get("page", 1, type=int), 1)
        per = min(max(a.get("per_page", 24, type=int), 1), 60)
        where, params = build_filters(a)
        q = (a.get("q") or "").strip()
        sort = a.get("sort") or ("relevance" if q else "popular")
        fuzzy = False
        if q:
            fq = db.fts_query(q)
            ids = []
            if fq:
                ids = [r["rowid"] for r in g.db.execute(
                    "SELECT rowid FROM title_fts WHERE title_fts MATCH ? ORDER BY bm25(title_fts, 10, 2, 4, 3, 1) LIMIT 500", (fq,))]
            if not ids:
                ids, fuzzy = fuzzy_ids(q, 30), True
            if g.cid and page == 1:
                g.db.execute("DELETE FROM searches WHERE client_id=? AND lower(q)=lower(?)", (g.cid, q))
                g.db.execute("INSERT INTO searches(client_id, q) VALUES (?,?)", (g.cid, q))
            if not ids:
                return jsonify(items=[], total=0, page=page, pages=0, fuzzy=False, q=q)
            marks = ",".join("?" * len(ids))
            where += f" AND t.id IN ({marks})"
            params += ids
            rank = {i: n for n, i in enumerate(ids)}
        total = g.db.execute(f"SELECT COUNT(*) AS c FROM titles t WHERE {where}", params).fetchone()["c"]
        if q and sort == "relevance":
            rows = g.db.execute(f"SELECT t.* FROM titles t WHERE {where}", params).fetchall()
            rows.sort(key=lambda r: rank.get(r["id"], 1e9))
            rows = rows[(page - 1) * per: page * per]
        else:
            order = SORTS.get(sort, SORTS["popular"])
            rows = g.db.execute(
                f"SELECT t.* FROM titles t WHERE {where} ORDER BY {order}, t.id LIMIT ? OFFSET ?",
                (*params, per, (page - 1) * per)).fetchall()
        return jsonify(items=card_rows(rows), total=total, page=page, pages=-(-total // per), fuzzy=fuzzy, q=q)

    @app.get("/api/suggest")
    def suggest():
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify(titles=[], people=[])
        like = f"%{q}%"
        rows = g.db.execute(
            """SELECT * FROM titles WHERE name LIKE ? ORDER BY (name LIKE ?) DESC, popularity DESC LIMIT 6""",
            (like, f"{q}%")).fetchall()
        if not rows:
            fq = db.fts_query(q)
            ids = [r["rowid"] for r in g.db.execute(
                "SELECT rowid FROM title_fts WHERE title_fts MATCH ? ORDER BY bm25(title_fts) LIMIT 6", (fq,))] if fq else []
            ids = ids or fuzzy_ids(q, 6)
            if ids:
                rows = g.db.execute(f"SELECT * FROM titles WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        people = [dict(r) for r in g.db.execute(
            "SELECT p.name, COUNT(*) AS titles FROM people p JOIN credits c ON c.person_id=p.id "
            "WHERE p.name LIKE ? GROUP BY p.id ORDER BY titles DESC LIMIT 4", (like,))]
        return jsonify(titles=[{k: c[k] for k in ("id", "slug", "kind", "name", "year", "poster", "rating")} for c in card_rows(rows)],
                       people=people)

    @app.get("/api/genres")
    def genres():
        kind = request.args.get("kind")
        kind_sql = "AND t.kind = ?" if kind in ("movie", "series") else ""
        args = (kind,) if kind_sql else ()
        rows = g.db.execute(
            f"""SELECT ge.name, COUNT(*) AS count FROM genres ge JOIN title_genres tg ON tg.genre_id=ge.id
                JOIN titles t ON t.id=tg.title_id WHERE 1=1 {kind_sql} GROUP BY ge.id ORDER BY count DESC, ge.name""", args)
        return jsonify([dict(r) for r in rows])

    @app.get("/api/home")
    def home():
        def rail(key, title, sql, params=()):
            rows = g.db.execute(sql, params).fetchall()
            return {"key": key, "title": title, "items": card_rows(rows)} if rows else None

        hero = g.db.execute("SELECT * FROM titles WHERE featured=1 ORDER BY popularity DESC LIMIT 6").fetchall()
        rails = [
            rail("trending", "Trending now", "SELECT * FROM titles ORDER BY popularity DESC LIMIT 16"),
            rail("series", "Series & serials", "SELECT * FROM titles WHERE kind='series' ORDER BY popularity DESC LIMIT 16"),
            rail("top", "Top rated", "SELECT * FROM titles WHERE votes>=1000 ORDER BY rating DESC LIMIT 16"),
            rail("new", "Recently added", "SELECT * FROM titles ORDER BY added_at DESC, id DESC LIMIT 16"),
        ]
        for gr in g.db.execute(
            """SELECT ge.name FROM genres ge JOIN title_genres tg ON tg.genre_id=ge.id
               GROUP BY ge.id HAVING COUNT(*)>=3 ORDER BY COUNT(*) DESC LIMIT 5"""):
            rails.append(rail(f"genre-{gr['name']}", gr["name"],
                              """SELECT t.* FROM titles t JOIN title_genres tg ON tg.title_id=t.id
                                 JOIN genres ge ON ge.id=tg.genre_id WHERE ge.name=? ORDER BY t.rating DESC LIMIT 16""", (gr["name"],)))
        out = {"hero": card_rows(hero), "rails": [r for r in rails if r],
               "stats": dict(g.db.execute("SELECT SUM(kind='movie') AS movies, SUM(kind='series') AS series FROM titles").fetchone())}
        out["continue"] = continue_watching() if g.cid else []
        return jsonify(out)

    # ------------------------------------------------------------ title detail
    def find_title(ref):
        row = g.db.execute("SELECT * FROM titles WHERE id=?", (int(ref),)).fetchone() if str(ref).isdigit() else \
            g.db.execute("SELECT * FROM titles WHERE slug=?", (ref,)).fetchone()
        if not row:
            abort(404, "Title not found")
        return row

    @app.get("/api/titles/<ref>")
    def title_detail(ref):
        t = find_title(ref)
        archive_error = None
        try:
            archive.ensure_sources(g.db, t["id"])
        except Exception as e:  # never break the page because archive.org is down
            archive_error = str(e)
        t = find_title(t["id"])
        card = card_rows([t])[0]
        cast = [dict(r) for r in g.db.execute(
            """SELECT p.name, p.photo_url AS photo, c.character FROM credits c JOIN people p ON p.id=c.person_id
               WHERE c.title_id=? AND c.role='cast' ORDER BY c.ord""", (t["id"],))]
        directors = [r["name"] for r in g.db.execute(
            "SELECT p.name FROM credits c JOIN people p ON p.id=c.person_id WHERE c.title_id=? AND c.role='director'", (t["id"],))]
        files = [file_json(f) for f in g.db.execute(
            "SELECT * FROM media_files WHERE title_id=? AND episode_id IS NULL ORDER BY playable DESC, COALESCE(height,0) DESC, size DESC", (t["id"],))]
        episodes = []
        if t["kind"] == "series":
            by_ep = {}
            for f in g.db.execute("SELECT * FROM media_files WHERE title_id=? AND episode_id IS NOT NULL "
                                  "ORDER BY playable DESC, COALESCE(height,0) DESC, size DESC", (t["id"],)):
                by_ep.setdefault(f["episode_id"], []).append(file_json(f))
            prog = {}
            if g.cid:
                prog = {r["episode_id"]: dict(r) for r in g.db.execute(
                    "SELECT episode_id, position, duration, completed FROM history WHERE client_id=? AND title_id=?", (g.cid, t["id"]))}
            for e in g.db.execute("SELECT * FROM episodes WHERE title_id=? ORDER BY season, number", (t["id"],)):
                episodes.append({"id": e["id"], "season": e["season"], "number": e["number"], "name": e["name"],
                                 "description": e["description"], "runtime": e["runtime"], "air_date": e["air_date"],
                                 "files": by_ep.get(e["id"], []), "progress": prog.get(e["id"])})
        mine = {}
        if g.cid:
            r = g.db.execute("SELECT value FROM user_ratings WHERE client_id=? AND title_id=?", (g.cid, t["id"])).fetchone()
            mine["rating"] = r["value"] // 2 if r else None
            last = g.db.execute("SELECT * FROM history WHERE client_id=? AND title_id=? ORDER BY updated_at DESC LIMIT 1", (g.cid, t["id"])).fetchone()
            mine["last"] = dict(last) if last else None
        card.update(
            cast=cast, directors=directors, files=files, episodes=episodes, mine=mine, language=t["language"],
            country=t["country"], sources_status=t["sources_status"],
            archive_url=archive.details_url(t["ia_identifier"]) if t["ia_identifier"] else None,
            archive_error=archive_error,
            seasons=sorted({e["season"] for e in episodes}),
            preview_start=int(min(max((t["runtime"] or 20) * 60 * 0.12, 20), 300)),
        )
        return jsonify(card)

    @app.get("/api/titles/<ref>/similar")
    def similar(ref):
        t = find_title(ref)
        rows = g.db.execute(
            """SELECT t2.*, COUNT(*) AS shared FROM title_genres a JOIN title_genres b ON a.genre_id=b.genre_id AND b.title_id!=a.title_id
               JOIN titles t2 ON t2.id=b.title_id WHERE a.title_id=? GROUP BY t2.id
               ORDER BY shared DESC, (t2.kind=?) DESC, t2.rating DESC LIMIT 12""", (t["id"], t["kind"])).fetchall()
        return jsonify(card_rows(rows))

    @app.post("/api/titles/<ref>/refresh")
    def refresh_sources(ref):
        t = find_title(ref)
        g.db.execute("UPDATE titles SET sources_status='pending', sources_checked_at=NULL WHERE id=?", (t["id"],))
        g.db.commit()
        try:
            status = archive.sync_title(g.db, find_title(t["id"]))
        except Exception as e:
            status = "error"
        return jsonify(status=status)

    # ------------------------------------------------------------ rating
    @app.post("/api/titles/<ref>/rate")
    def rate(ref):
        cid, t = need_client(), find_title(ref)
        stars = (request.get_json(silent=True) or {}).get("stars")
        if stars is None:
            g.db.execute("DELETE FROM user_ratings WHERE client_id=? AND title_id=?", (cid, t["id"]))
        else:
            if not isinstance(stars, int) or not 1 <= stars <= 5:
                abort(400, "stars must be 1-5")
            g.db.execute("INSERT OR REPLACE INTO user_ratings VALUES (?,?,?)", (cid, t["id"], stars * 2))
        # blended score: seed rating weighted by its votes + every client rating
        agg = g.db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(value),0) AS s FROM user_ratings WHERE title_id=?", (t["id"],)).fetchone()
        base_votes, base = t["votes"] - 0, t["rating"]
        return jsonify(user_stars=stars, community={"ratings_from_viewers": agg["n"], "viewer_average": round(agg["s"] / agg["n"], 1) if agg["n"] else None,
                                                    "score": round(base, 1)})

    # ------------------------------------------------------------ media: stream & download
    def get_file(file_id):
        f = g.db.execute(
            """SELECT f.*, t.name AS title_name, t.year AS title_year, t.kind AS kind, e.season, e.number, e.name AS ep_name
               FROM media_files f JOIN titles t ON t.id=f.title_id LEFT JOIN episodes e ON e.id=f.episode_id WHERE f.id=?""",
            (file_id,)).fetchone()
        if not f:
            abort(404, "File not found")
        return f

    def pretty_filename(f):
        ext = f["name"].rsplit(".", 1)[-1]
        base = f"{f['title_name']} ({f['title_year']})" if f["title_year"] else f["title_name"]
        if f["kind"] == "series" and f["number"]:
            base += f" - S{f['season']:02d}E{f['number']:02d} {f['ep_name']}"
        return re.sub(r'[\\/:*?"<>|]+', "", f"{base} [{f['quality']}].{ext}")

    def upstream(f, attachment):
        url = archive.media_url(f["ia_identifier"], f["name"])
        if not (PROXY_DOWNLOAD if attachment else PROXY_STREAM):
            return redirect(url, 302)
        headers = dict(archive.HEADERS)
        if request.headers.get("Range"):
            headers["Range"] = request.headers["Range"]
        try:
            up = requests.get(url, headers=headers, stream=True, timeout=(8, 30))
        except requests.RequestException:
            abort(404, "Archive is unreachable right now - try again shortly")
        if up.status_code >= 400:
            up.close()
            abort(404, "This file is no longer available on the archive")
        mime = mimetypes.guess_type(f["name"])[0] or "video/mp4"
        resp_headers = {"Content-Type": mime, "Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
        for h in ("Content-Length", "Content-Range"):
            if up.headers.get(h):
                resp_headers[h] = up.headers[h]
        if attachment:
            resp_headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(pretty_filename(f))}"

        def gen():
            try:
                for chunk in up.iter_content(64 * 1024):
                    yield chunk
            finally:
                up.close()
        return Response(stream_with_context(gen()), status=up.status_code, headers=resp_headers)

    @app.get("/api/stream/<int:file_id>")
    def stream(file_id):
        f = get_file(file_id)
        if not f["playable"]:
            abort(400, "This format can't play in a browser - download it instead")
        return upstream(f, attachment=False)

    @app.get("/api/download/<int:file_id>")
    def download(file_id):
        f = get_file(file_id)
        # count once per request that starts at byte 0 (browsers resume with Range)
        rng = request.headers.get("Range", "")
        if g.cid and (not rng or rng.startswith("bytes=0-")):
            g.db.execute("INSERT INTO downloads(client_id,title_id,episode_id,file_id,filename,size) VALUES (?,?,?,?,?,?)",
                         (g.cid, f["title_id"], f["episode_id"], f["id"], pretty_filename(f), f["size"]))
            g.db.execute("UPDATE titles SET popularity=popularity+10 WHERE id=?", (f["title_id"],))
            g.db.commit()
        return upstream(f, attachment=True)

    def episode_links(t, season):
        sql = ("SELECT f.*, t.name AS title_name, t.year AS title_year, t.kind AS kind, e.season, e.number, e.name AS ep_name "
               "FROM media_files f JOIN titles t ON t.id=f.title_id LEFT JOIN episodes e ON e.id=f.episode_id WHERE f.title_id=?")
        params = [t["id"]]
        if season:
            sql += " AND e.season=?"
            params.append(season)
        sql += " ORDER BY e.season, e.number, f.playable DESC, COALESCE(f.height,0) DESC"
        seen, out = set(), []
        for f in g.db.execute(sql, params):
            key = f["episode_id"] or 0
            if key in seen:
                continue  # best quality only
            seen.add(key)
            out.append(f)
        return out

    @app.get("/api/titles/<ref>/links.txt")
    def links_txt(ref):
        t = find_title(ref)
        lines = [archive.media_url(f["ia_identifier"], f["name"]) for f in episode_links(t, request.args.get("season", type=int))]
        return Response("\n".join(lines) + "\n", mimetype="text/plain",
                        headers={"Content-Disposition": f'attachment; filename="{re.sub(r"[^A-Za-z0-9]+", "_", t["name"])}_links.txt"'})

    @app.get("/api/titles/<ref>/playlist.m3u")
    def playlist(ref):
        t = find_title(ref)
        lines = ["#EXTM3U"]
        for f in episode_links(t, request.args.get("season", type=int)):
            label = pretty_filename(f).rsplit(".", 1)[0]
            lines += [f"#EXTINF:{int(f['duration'] or -1)},{label}", archive.media_url(f["ia_identifier"], f["name"])]
        return Response("\n".join(lines) + "\n", mimetype="audio/x-mpegurl",
                        headers={"Content-Disposition": f'attachment; filename="{re.sub(r"[^A-Za-z0-9]+", "_", t["name"])}.m3u"'})

    # ------------------------------------------------------------ per-client: history, list, downloads, searches
    def continue_watching():
        rows = g.db.execute(
            """SELECT t.*, h.episode_id AS h_ep, h.position, h.duration AS h_dur, h.updated_at AS h_at
               FROM history h JOIN titles t ON t.id=h.title_id
               WHERE h.client_id=? AND h.completed=0 AND h.position>10
                 AND h.updated_at=(SELECT MAX(updated_at) FROM history WHERE client_id=h.client_id AND title_id=h.title_id)
               ORDER BY h.updated_at DESC LIMIT 12""", (g.cid,)).fetchall()
        cards = card_rows(rows)
        for c, r in zip(cards, rows):
            c["resume"] = {"episode_id": r["h_ep"] or None, "position": r["position"], "duration": r["h_dur"]}
        return cards

    @app.get("/api/me/history")
    def get_history():
        cid = need_client()
        rows = g.db.execute(
            """SELECT h.id AS hid, h.episode_id, h.position, h.duration AS h_dur, h.completed, h.updated_at AS watched_at,
                      e.season, e.number, e.name AS ep_name, t.*
               FROM history h JOIN titles t ON t.id=h.title_id LEFT JOIN episodes e ON e.id=h.episode_id
               WHERE h.client_id=? ORDER BY h.updated_at DESC LIMIT 200""", (cid,)).fetchall()
        cards = card_rows(rows)
        for c, r in zip(cards, rows):
            c["history"] = {"id": r["hid"], "episode_id": r["episode_id"] or None, "position": r["position"], "duration": r["h_dur"],
                            "completed": bool(r["completed"]), "watched_at": r["watched_at"],
                            "episode": f"S{r['season']:02d}E{r['number']:02d} · {r['ep_name']}" if r["season"] else None}
        return jsonify(cards)

    @app.post("/api/me/history")
    def save_history():
        cid, body = need_client(), request.get_json(silent=True) or {}
        t = find_title(body.get("title_id", 0))
        ep = int(body.get("episode_id") or 0)
        pos, dur = float(body.get("position") or 0), float(body.get("duration") or 0)
        done = 1 if dur and pos / dur > 0.93 else 0
        existed = g.db.execute("SELECT 1 FROM history WHERE client_id=? AND title_id=? AND episode_id=?", (cid, t["id"], ep)).fetchone()
        g.db.execute(
            """INSERT INTO history(client_id,title_id,episode_id,position,duration,completed,updated_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(client_id,title_id,episode_id) DO UPDATE SET position=excluded.position,
                 duration=excluded.duration, completed=excluded.completed, updated_at=CURRENT_TIMESTAMP""",
            (cid, t["id"], ep, pos, dur, done))
        if not existed:
            g.db.execute("UPDATE titles SET popularity=popularity+5 WHERE id=?", (t["id"],))
        return jsonify(ok=True, completed=bool(done))

    @app.delete("/api/me/history")
    def clear_history():
        g.db.execute("DELETE FROM history WHERE client_id=?", (need_client(),))
        return jsonify(ok=True)

    @app.delete("/api/me/history/<int:hid>")
    def delete_history(hid):
        g.db.execute("DELETE FROM history WHERE id=? AND client_id=?", (hid, need_client()))
        return jsonify(ok=True)

    @app.get("/api/me/watchlist")
    def get_watchlist():
        cid = need_client()
        rows = g.db.execute("SELECT t.* FROM watchlist w JOIN titles t ON t.id=w.title_id WHERE w.client_id=? ORDER BY w.added_at DESC", (cid,)).fetchall()
        return jsonify(card_rows(rows))

    @app.put("/api/me/watchlist/<int:title_id>")
    def add_watchlist(title_id):
        find_title(title_id)
        g.db.execute("INSERT OR IGNORE INTO watchlist(client_id,title_id) VALUES (?,?)", (need_client(), title_id))
        return jsonify(in_list=True)

    @app.delete("/api/me/watchlist/<int:title_id>")
    def remove_watchlist(title_id):
        g.db.execute("DELETE FROM watchlist WHERE client_id=? AND title_id=?", (need_client(), title_id))
        return jsonify(in_list=False)

    @app.get("/api/me/downloads")
    def my_downloads():
        cid = need_client()
        rows = g.db.execute(
            """SELECT d.id, d.filename, d.size, d.created_at, d.file_id, d.title_id, t.name, t.slug, t.poster_url AS poster, t.kind
               FROM downloads d JOIN titles t ON t.id=d.title_id WHERE d.client_id=? ORDER BY d.id DESC LIMIT 200""", (cid,))
        return jsonify([dict(r) for r in rows])

    @app.delete("/api/me/downloads")
    def clear_downloads():
        g.db.execute("DELETE FROM downloads WHERE client_id=?", (need_client(),))
        return jsonify(ok=True)

    @app.get("/api/me/searches")
    def my_searches():
        cid = need_client()
        return jsonify([r["q"] for r in g.db.execute("SELECT q FROM searches WHERE client_id=? ORDER BY id DESC LIMIT 8", (cid,))])

    @app.delete("/api/me/searches")
    def clear_searches():
        g.db.execute("DELETE FROM searches WHERE client_id=?", (need_client(),))
        return jsonify(ok=True)

    @app.get("/api/me/stats")
    def my_stats():
        cid = need_client()
        row = g.db.execute(
            """SELECT (SELECT COUNT(DISTINCT title_id) FROM history WHERE client_id=:c) AS watched,
                      (SELECT COALESCE(SUM(position),0) FROM history WHERE client_id=:c) AS seconds,
                      (SELECT COUNT(*) FROM downloads WHERE client_id=:c) AS downloads,
                      (SELECT COUNT(*) FROM watchlist WHERE client_id=:c) AS list""", {"c": cid}).fetchone()
        return jsonify(dict(row))

    # ------------------------------------------------------------ admin
    jobs = {"name": None, "started": None, "finished": None, "result": None, "error": None, "log": deque(maxlen=400)}
    jobs_lock = threading.Lock()

    def run_job(name, fn):
        """Run fn(conn, log) in a background thread; one job at a time, live log for the admin UI."""
        with jobs_lock:
            if jobs["name"]:
                abort(400, f"A job is already running: {jobs['name']}")
            jobs.update(name=name, started=time.time(), finished=None, result=None, error=None)
            jobs["log"].clear()

        def log(msg=""):
            jobs["log"].append(str(msg))

        def work():
            try:
                log(f"Started {name}…")
                with db.session() as conn:
                    jobs["result"] = fn(conn, log)
                log("Finished.")
            except Exception as e:
                jobs["error"] = f"{type(e).__name__}: {e}"
                log(f"FAILED - {jobs['error']}")
                if isinstance(e, requests.RequestException):
                    log("Could not reach archive.org from this server (check internet / firewall / IA_BASE).")
            finally:
                jobs["finished"] = time.time()
                jobs["name"] = None
        threading.Thread(target=work, daemon=True).start()

    def job_json():
        return {"running": jobs["name"], "started": jobs["started"], "finished": jobs["finished"],
                "result": jobs["result"], "error": jobs["error"], "log": list(jobs["log"])}

    @app.get("/api/admin/status")
    def admin_status():
        need_admin()
        return jsonify(job_json())

    @app.get("/api/admin/overview")
    def admin_overview():
        need_admin()
        q = lambda sql: g.db.execute(sql).fetchone()[0]  # noqa: E731
        path = db.DB_PATH
        return jsonify(
            titles=q("SELECT COUNT(*) FROM titles"), movies=q("SELECT COUNT(*) FROM titles WHERE kind='movie'"),
            series=q("SELECT COUNT(*) FROM titles WHERE kind='series'"), episodes=q("SELECT COUNT(*) FROM episodes"),
            files=q("SELECT COUNT(*) FROM media_files"),
            status={r["sources_status"]: r["n"] for r in g.db.execute("SELECT sources_status, COUNT(*) AS n FROM titles GROUP BY 1")},
            downloads=q("SELECT COUNT(*) FROM downloads"), plays=q("SELECT COUNT(*) FROM history"), clients=q("SELECT COUNT(*) FROM clients"),
            tmdb=tmdb.enabled(), proxy_stream=PROXY_STREAM, proxy_download=PROXY_DOWNLOAD, archive_base=archive.IA_BASE,
            db_path=path, db_mb=round(os.path.getsize(path) / 1e6, 2) if os.path.exists(path) else 0,
            persistent=path.startswith("/var/data") or os.environ.get("PERSISTENT_STORAGE") == "1", job=job_json())

    @app.post("/api/admin/import")
    def admin_import():
        need_admin()
        body = request.get_json(silent=True) or {}
        n = max(1, min(int(body.get("limit") or request.args.get("limit", 100)), 500))
        query = (body.get("query") or "").strip() or None

        def job(conn, log):
            added = archive.import_catalog(conn, n, query=query, progress=log)
            log(f"Imported {added} new titles. Checking files on archive.org…")
            res = archive.sync_all(conn, progress=log, only_stale=True)
            return {"imported": added, "sync": res}
        run_job("import", job)
        return jsonify(started=True)

    @app.post("/api/admin/sync")
    def admin_sync():
        need_admin()
        stale = (request.get_json(silent=True) or {}).get("only_stale", False)
        run_job("sync", lambda c, log: archive.sync_all(c, progress=log, only_stale=stale))
        return jsonify(started=True)

    @app.post("/api/admin/tmdb")
    def admin_tmdb():
        need_admin()
        if not tmdb.enabled():
            abort(400, "Set TMDB_API_KEY first")
        run_job("tmdb", lambda c, log: {"enriched": tmdb.enrich_all(c, progress=log)})
        return jsonify(started=True)

    @app.post("/api/admin/reindex")
    def admin_reindex():
        need_admin()
        db.rebuild_fts(g.db)
        return jsonify(ok=True)

    @app.get("/api/admin/titles")
    def admin_titles():
        need_admin()
        a = request.args
        where, params = ["1=1"], []
        if a.get("q"):
            where.append("(t.name LIKE ? OR t.ia_identifier LIKE ?)")
            params += [f"%{a['q']}%"] * 2
        if a.get("status"):
            where.append("t.sources_status = ?")
            params.append(a["status"])
        if a.get("kind") in ("movie", "series"):
            where.append("t.kind = ?")
            params.append(a["kind"])
        page, per = max(a.get("page", 1, type=int), 1), 25
        w = " AND ".join(where)
        total = g.db.execute(f"SELECT COUNT(*) FROM titles t WHERE {w}", params).fetchone()[0]
        rows = g.db.execute(
            f"""SELECT t.id, t.slug, t.kind, t.name, t.year, t.description, t.rating, t.ia_identifier, t.poster_url, t.sources_status,
                       t.featured, t.license, (SELECT COUNT(*) FROM media_files f WHERE f.title_id=t.id) AS files
                FROM titles t WHERE {w} ORDER BY t.id DESC LIMIT ? OFFSET ?""", (*params, per, (page - 1) * per)).fetchall()
        return jsonify(items=[dict(r) for r in rows], total=total, page=page, pages=-(-total // per))

    @app.post("/api/admin/titles")
    def admin_add_title():
        need_admin()
        body = request.get_json(silent=True) or {}
        kind = body.get("kind") if body.get("kind") in ("movie", "series") else "movie"
        try:
            tid = archive.add_from_identifier(g.db, body.get("identifier"), kind, progress=lambda *_: None)
        except ValueError as e:
            abort(400, str(e))
        except requests.RequestException:
            abort(400, "Couldn't reach archive.org from this server")
        t = g.db.execute("SELECT id, slug, name, sources_status FROM titles WHERE id=?", (tid,)).fetchone()
        return jsonify(dict(t))

    @app.patch("/api/admin/titles/<int:tid>")
    def admin_edit_title(tid):
        need_admin()
        t = find_title(tid)
        body = request.get_json(silent=True) or {}
        fields = {k: body[k] for k in ("name", "year", "description", "rating", "poster_url", "backdrop_url", "ia_identifier", "featured", "tagline", "director") if k in body}
        if "ia_identifier" in fields:
            ident = archive.parse_identifier(fields["ia_identifier"]) if fields["ia_identifier"] else None
            if fields["ia_identifier"] and not ident:
                abort(400, "Invalid archive.org identifier")
            fields["ia_identifier"] = ident
        if "name" in fields and not str(fields["name"]).strip():
            abort(400, "Name can't be empty")
        if "featured" in fields:
            fields["featured"] = 1 if fields["featured"] else 0
        if fields:
            g.db.execute(f"UPDATE titles SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), tid))
            if fields.get("ia_identifier") != t["ia_identifier"] and "ia_identifier" in fields:
                g.db.execute("DELETE FROM media_files WHERE title_id=?", (tid,))
                g.db.execute("UPDATE titles SET sources_status='pending', sources_checked_at=NULL WHERE id=?", (tid,))
            db.rebuild_fts(g.db, tid)
        return jsonify(ok=True)

    @app.delete("/api/admin/titles/<int:tid>")
    def admin_delete_title(tid):
        need_admin()
        find_title(tid)
        g.db.execute("DELETE FROM title_fts WHERE rowid=?", (tid,))
        g.db.execute("DELETE FROM titles WHERE id=?", (tid,))
        return jsonify(ok=True)

    @app.post("/api/admin/titles/<int:tid>/sync")
    def admin_sync_one(tid):
        need_admin()
        t = find_title(tid)
        try:
            status = archive.sync_title(g.db, t)
        except Exception as e:
            status = "error"
        g.db.commit()
        return jsonify(status=status)

    @app.get("/api/health")
    def health():
        c = g.db.execute("SELECT COUNT(*) AS n, SUM(sources_status='ok') AS ok FROM titles").fetchone()
        return jsonify(status="ok", titles=c["n"], with_sources=c["ok"] or 0, job=jobs["name"], tmdb=tmdb.enabled(),
                       proxy_stream=PROXY_STREAM, proxy_download=PROXY_DOWNLOAD)

    # ------------------------------------------------------------ SPA
    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path):
        if path.startswith("api/"):
            abort(404)
        full = os.path.join(DIST, path)
        if path and os.path.isfile(full):
            return send_from_directory(DIST, path)
        if os.path.isfile(os.path.join(DIST, "index.html")):
            return send_from_directory(DIST, "index.html")
        return ("Frontend not built yet. Run `npm install && npm run build` in /frontend "
                "(or use the prebuilt frontend/dist).", 200)

    return app


def start_background():
    """Optional first-boot work, used by `python app.py` and by gunicorn (wsgi.py):
    AUTO_IMPORT=N  import N public-domain films once (when none were imported yet)
    AUTO_SYNC=1    verify stale titles against archive.org
    """
    def bg():
        try:
            with db.session() as conn:
                n = int(os.environ.get("AUTO_IMPORT", "0") or 0)
                if n and conn.execute("SELECT COUNT(*) FROM titles WHERE license LIKE '%CC%'").fetchone()[0] == 0:
                    archive.import_catalog(conn, n, progress=lambda *_: None)
                if os.environ.get("AUTO_SYNC", "1") == "1":
                    archive.sync_all(conn, progress=lambda *_: None, only_stale=True)
        except Exception as e:
            print(f"[background] {type(e).__name__}: {e}", file=sys.stderr)
    threading.Thread(target=bg, daemon=True).start()


def cli():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        app = create_app()
        start_background()
        port = int(os.environ.get("PORT", 5000))
        print(f"CineVault running on http://localhost:{port}   (admin panel: /admin)")
        app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, threaded=True, debug=False)
        return
    db.init_db()
    with db.session() as conn:
        catalog.ensure_seeded(conn)
        try:
            if cmd == "sync":
                print(archive.sync_all(conn))
            elif cmd == "import":
                n = int(sys.argv[2]) if len(sys.argv) > 2 else 100
                print(f"Imported {archive.import_catalog(conn, n)} titles")
                print(archive.sync_all(conn, only_stale=True))
            elif cmd == "add":
                kind = sys.argv[3] if len(sys.argv) > 3 else "movie"
                archive.add_from_identifier(conn, sys.argv[2], kind)
            elif cmd == "tmdb":
                print(f"Enriched {tmdb.enrich_all(conn)} titles")
            elif cmd == "reseed":
                catalog.seed(conn)
                print("Catalog refreshed")
            else:
                print(__doc__)
        except requests.RequestException as e:
            sys.exit(f"Could not reach archive.org: {e}")
        except (ValueError, IndexError) as e:
            sys.exit(f"Error: {e}")


if __name__ == "__main__":
    cli()
