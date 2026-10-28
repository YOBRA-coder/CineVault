"""CineVault - public-domain movies & series: search, preview, play, download, history.

Run:      python app.py                 (serves API + built React app on http://localhost:5000)
Sync:     python app.py sync            (verify archive.org items, fetch playable files)
Import:   python app.py import 200      (add up to 200 more public-domain films from archive.org)
Enrich:   python app.py tmdb            (optional posters/cast from TMDB when TMDB_API_KEY is set)
"""
import difflib
import mimetypes
import os
import re
import sys
import threading
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
PROXY_MEDIA = os.environ.get("PROXY_MEDIA", "1") != "0"
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
        if ADMIN_TOKEN and request.headers.get("X-Admin-Token") != ADMIN_TOKEN:
            abort(403, "Admin token required")
        if not ADMIN_TOKEN and request.remote_addr not in ("127.0.0.1", "::1"):
            abort(403, "Admin actions are local-only unless ADMIN_TOKEN is set")

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
        if not PROXY_MEDIA:
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
    jobs = {"running": None}

    def run_job(name, fn):
        if jobs["running"]:
            abort(400, f"A job is already running: {jobs['running']}")
        jobs["running"] = name

        def work():
            try:
                with db.session() as conn:
                    fn(conn)
            finally:
                jobs["running"] = None
        threading.Thread(target=work, daemon=True).start()

    @app.post("/api/admin/sync")
    def admin_sync():
        need_admin()
        run_job("sync", lambda c: archive.sync_all(c, progress=lambda *_: None))
        return jsonify(started=True)

    @app.post("/api/admin/import")
    def admin_import():
        need_admin()
        n = request.args.get("limit", 100, type=int)
        run_job("import", lambda c: (archive.import_catalog(c, n, progress=lambda *_: None), archive.sync_all(c, progress=lambda *_: None, only_stale=True)))
        return jsonify(started=True)

    @app.get("/api/health")
    def health():
        c = g.db.execute("SELECT COUNT(*) AS n, SUM(sources_status='ok') AS ok FROM titles").fetchone()
        return jsonify(status="ok", titles=c["n"], with_sources=c["ok"] or 0, job=jobs["running"], tmdb=tmdb.enabled(), proxy_media=PROXY_MEDIA)

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


def cli():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        app = create_app()
        if os.environ.get("AUTO_SYNC", "1") == "1":
            def bg():
                try:
                    with db.session() as conn:
                        archive.sync_all(conn, progress=lambda *_: None, only_stale=True)
                except Exception:
                    pass
            threading.Thread(target=bg, daemon=True).start()
        port = int(os.environ.get("PORT", 10000))
        print(f"CineVault running on http://localhost:{port}")
        app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, threaded=True, debug=False)
        return
    db.init_db()
    with db.session() as conn:
        catalog.ensure_seeded(conn)
        if cmd == "sync":
            print(archive.sync_all(conn))
        elif cmd == "import":
            n = int(sys.argv[2]) if len(sys.argv) > 2 else 100
            print(f"Imported {archive.import_catalog(conn, n)} titles")
            print(archive.sync_all(conn, only_stale=True))
        elif cmd == "tmdb":
            print(f"Enriched {tmdb.enrich_all(conn)} titles")
        elif cmd == "reseed":
            catalog.seed(conn)
            print("Catalog refreshed")
        else:
            print(__doc__)


if __name__ == "__main__":
    cli()
