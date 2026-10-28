"""API tests. archive.org is replaced by a tiny in-process fake so tests run offline."""
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

try:
    import pytest
except ImportError:  # allow `python tests/run.py` without pytest
    class pytest:  # noqa: N801
        @staticmethod
        def fixture(*a, **k):
            return (lambda f: f) if not a or not callable(a[0]) else a[0]

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

VIDEO = b"0123456789" * 1000  # 10 KB fake video
LAST_TMDB = {}                # what the fake TMDB saw last (auth style assertions)


class FakeIA(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200); self.send_header("Content-Length", "5000"); self.end_headers()

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        if u.path.startswith("/metadata/"):
            ident = u.path.split("/")[-1]
            if ident == "night_of_the_living_dead":
                files = [
                    {"name": "notld.mp4", "format": "h.264", "size": "9000", "height": "480", "length": "5760", "source": "derivative"},
                    {"name": "notld.ogv", "format": "Ogg Video", "size": "7000", "height": "360", "length": "5760"},
                    {"name": "notld.mpeg", "format": "MPEG2", "size": "20000", "length": "5760"},
                    {"name": "notld_trailer.mp4", "format": "h.264", "size": "100", "length": "60"},
                    {"name": "notld.jpg", "format": "JPEG", "size": "1"},
                ]
                return self._json({"metadata": {"identifier": ident}, "files": files})
            if ident == "Flash_Gordon_1936":
                files = [{"name": f"flash_ch{n:02d}.mp4", "format": "h.264", "size": "5000", "height": "720", "length": "1200"} for n in range(1, 14)]
                return self._json({"metadata": {"identifier": ident}, "files": files})
            if ident == "brand_new_item":
                return self._json({"metadata": {"identifier": ident, "title": "Brand New Item", "year": "1949", "creator": "A. Director",
                                   "description": "Added by hand.", "subject": "comedy; silent"},
                                   "files": [{"name": "item.mp4", "format": "h.264", "size": "9000", "height": "480", "length": "3000"}]})
            if ident == "coll_series":
                return self._json({"metadata": {"identifier": ident, "title": "Old Radio Serial", "year": "1948", "mediatype": "collection"}, "files": []})
            if ident in ("ep_a", "ep_b"):
                return self._json({"metadata": {"identifier": ident}, "files": [{"name": f"{ident}.mp4", "format": "h.264", "size": "700", "height": "480", "length": "900"}]})
            if ident == "series_item":
                return self._json({"metadata": {"identifier": ident, "title": "Tiny Serial", "year": "1950"},
                                   "files": [{"name": f"ep{n}.mp4", "format": "h.264", "size": "900", "height": "360", "length": "600"} for n in (1, 2, 3)]})
            if ident == "found_by_search":
                return self._json({"metadata": {"identifier": ident}, "files": [{"name": "m.mp4", "format": "h.264", "size": "10000", "height": "1080", "length": "7200"}]})
            return self._json({}, 200)  # archive.org answers {} for unknown ids
        if u.path == "/advancedsearch.php":
            qs = parse_qs(u.query)
            q = qs.get("q", [""])[0]
            docs = []
            if "Metropolis" in q:
                docs = [{"identifier": "found_by_search", "title": "Metropolis", "year": "1927", "downloads": 500000}]
            elif "feature_films" in q:
                docs = [{"identifier": "new_pd_film", "title": "A New Public Domain Film", "year": "1931", "creator": "Jane Doe",
                         "description": "<p>An imported <b>film</b>.</p>", "subject": ["Horror", "Silent"], "downloads": 12345, "avg_rating": "4.0", "num_reviews": 12},
                        {"title": "record without identifier"}]
            # like the real archive.org: only the fields requested through the bracketed `fl[]` come back
            if "collection:bulk_films" in q:       # 120 films with awkward real-world runtimes
                runtimes = ["1 hr 30 min", "1:35:00 min", "95 min", "5700", "01:35:00", "about an hour", None]
                allq = [{"identifier": f"bulk_{i:03d}", "title": f"Bulk Film {i}", "year": str(1930 + i % 40), "downloads": 1000 - i,
                         "runtime": runtimes[i % len(runtimes)], "subject": "comedy", "creator": ["Dir %d" % (i % 9)]} for i in range(120)]
                rows, page = int(qs.get("rows", ["50"])[0]), int(qs.get("page", ["1"])[0])
                docs = allq[(page - 1) * rows: page * rows]
            if "collection:coll_series" in q:
                docs = [{"identifier": "ep_b", "title": "Episode 10"}, {"identifier": "ep_a", "title": "Episode 2"}]
            if "collection:classic_tv" in q and "licenseurl" not in q:     # untagged collection: strict search finds nothing
                docs = [{"identifier": "ep_a", "title": "Lone Episode"}, {"identifier": "series_item", "title": "Tiny Serial", "year": "1950"}]
            wanted = qs.get("fl[]", [])
            return self._json({"response": {"docs": [{k: v for k, v in d.items() if k in wanted} for d in docs]}})
        if u.path.startswith("/tmdb/3/"):
            LAST_TMDB.update(path=u.path, qs=parse_qs(u.query), auth=self.headers.get("Authorization"))
            p = u.path[len("/tmdb/3"):]
            if p == "/search/multi":
                q = parse_qs(u.query).get("query", [""])[0].lower()
                res = []
                if "thrones" in q:
                    res.append({"id": 1399, "media_type": "tv", "name": "Game of Thrones", "first_air_date": "2011-04-17", "poster_path": "/got.jpg", "overview": "Nine noble families fight for control.", "vote_average": 8.4, "vote_count": 25000})
                if "metropolis" in q:
                    res.append({"id": 19, "media_type": "movie", "title": "Metropolis", "release_date": "1927-01-10", "poster_path": "/m.jpg", "overview": "x", "vote_average": 8.2, "vote_count": 2000})
                res.append({"id": 5, "media_type": "person", "name": "Someone"})
                return self._json({"results": res, "total_pages": 1, "total_results": len(res)})
            if p == "/trending/all/week":
                return self._json({"results": [{"id": 1399, "media_type": "tv", "name": "Game of Thrones", "first_air_date": "2011-04-17", "vote_average": 8.4}]})
            if p == "/tv/1399":
                return self._json({"id": 1399, "name": "Game of Thrones", "first_air_date": "2011-04-17", "overview": "Nine noble families fight for control.",
                                   "tagline": "Winter Is Coming", "poster_path": "/got.jpg", "backdrop_path": "/gotb.jpg", "vote_average": 8.4, "vote_count": 25000,
                                   "genres": [{"name": "Drama"}, {"name": "Fantasy"}], "number_of_seasons": 8, "number_of_episodes": 73, "episode_run_time": [60], "status": "Ended",
                                   "created_by": [{"name": "David Benioff"}, {"name": "D. B. Weiss"}],
                                   "credits": {"cast": [{"name": "Emilia Clarke", "character": "Daenerys Targaryen", "profile_path": "/e.jpg"}], "crew": []},
                                   "videos": {"results": [{"site": "YouTube", "type": "Clip", "key": "CLIPKEY"}, {"site": "YouTube", "type": "Trailer", "official": True, "key": "TRAILERKEY"}, {"site": "Vimeo", "type": "Trailer", "key": "NO"}]},
                                   "watch/providers": {"results": {"US": {"link": "https://www.themoviedb.org/tv/1399/watch?locale=US",
                                                                           "flatrate": [{"provider_name": "Max", "logo_path": "/max.png"}],
                                                                           "rent": [{"provider_name": "Apple TV", "logo_path": "/atv.png"}], "buy": [{"provider_name": "Amazon Video", "logo_path": "/amz.png"}]},
                                                                  "KE": {"link": "https://www.themoviedb.org/tv/1399/watch?locale=KE", "flatrate": [{"provider_name": "Showmax", "logo_path": "/sm.png"}]}}}})
            self.send_response(404); self.end_headers(); return
        if u.path == "/folder/":
            links = ["big_buck_bunny_720p.mp4", "big_buck_bunny_1080p.mov", "big_buck_bunny_trailer.mp4", "movie-stereo.mp4", "notes.txt", "bundle.zip", "old.mkv"]
            html = "<html><body><h1>Index</h1>" + "".join(f'<a href="{n}">{n}</a><br>' for n in links) + '<a href="?C=N;O=D">Name</a></body></html>'
            body = html.encode(); self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        if u.path.startswith("/download/") or (u.path.startswith("/folder/") and u.path != "/folder/"):
            data, status = VIDEO, 200
            rng = self.headers.get("Range")
            hdr = {"Content-Type": "video/mp4", "Accept-Ranges": "bytes"}
            if rng:
                a, b = rng.replace("bytes=", "").split("-")
                a, b = int(a), int(b) if b else len(VIDEO) - 1
                data, status = VIDEO[a:b + 1], 206
                hdr["Content-Range"] = f"bytes {a}-{b}/{len(VIDEO)}"
            self.send_response(status)
            for k, v in hdr.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()


@pytest.fixture(scope="session")
def fake_ia():
    srv = HTTPServer(("127.0.0.1", 0), FakeIA)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture()
def client(fake_ia, monkeypatch, tmp_path):
    monkeypatch.setenv("CINEVAULT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("IA_BASE", fake_ia)
    for m in ("db", "archive", "catalog", "tmdb", "app"):
        sys.modules.pop(m, None)
    import app as appmod
    app = appmod.create_app()
    app.testing = True
    c = app.test_client()
    c.environ_base["HTTP_X_CLIENT_ID"] = "test-client-0001"
    c.appmod = appmod
    return c


def test_seed_and_home(client):
    r = client.get("/api/home").get_json()
    assert r["stats"]["movies"] >= 30 and r["stats"]["series"] >= 3
    assert r["hero"] and r["rails"][0]["items"]
    assert any(rail["key"].startswith("genre-") for rail in r["rails"])


def test_filters_and_sort(client):
    s = client.get("/api/titles?kind=series").get_json()
    assert s["total"] == 3 and all(i["kind"] == "series" for i in s["items"])
    h = client.get("/api/titles?kind=movie&genre=Horror&sort=rating").get_json()
    ratings = [i["rating"] for i in h["items"]]
    assert ratings == sorted(ratings, reverse=True) and h["total"] > 5
    both = client.get("/api/titles?genre=Horror,Silent").get_json()
    assert 0 < both["total"] < h["total"] + 5
    assert all({"Horror", "Silent"} <= set(i["genres"]) for i in both["items"])
    y = client.get("/api/titles?year_from=1960&year_to=1964").get_json()
    assert y["items"] and all(1960 <= i["year"] <= 1964 for i in y["items"])
    assert all(i["rating"] >= 8 for i in client.get("/api/titles?min_rating=8").get_json()["items"])


def test_search_by_title_cast_prefix_and_typo(client):
    assert client.get("/api/titles?q=nosferatu").get_json()["items"][0]["name"] == "Nosferatu"
    cast = client.get("/api/titles?q=Audrey Hepburn").get_json()
    assert [i["name"] for i in cast["items"]] == ["Charade"]
    assert client.get("/api/titles?q=metrop").get_json()["items"][0]["name"] == "Metropolis"
    typo = client.get("/api/titles?q=nosfaratu").get_json()
    assert typo["fuzzy"] and typo["items"][0]["name"] == "Nosferatu"
    assert client.get('/api/titles?q="; DROP TABLE titles;--').status_code == 200
    assert client.get("/api/titles?q=zzzzqqq").get_json()["total"] == 0
    sg = client.get("/api/suggest?q=plan").get_json()
    assert sg["titles"][0]["name"].startswith("Plan 9")
    assert client.get("/api/me/searches").get_json()[0] == "zzzzqqq"


def test_detail_movie_syncs_files(client):
    d = client.get("/api/titles/night-of-the-living-dead").get_json()
    assert d["directors"] == ["George A. Romero"] and d["cast"][0]["character"] == "Ben"
    assert d["sources_status"] == "ok"
    names = [f["name"] for f in d["files"]]
    assert "notld_trailer.mp4" not in names and "notld.jpg" not in names
    assert d["files"][0]["playable"] and d["files"][0]["quality"] == "480p"
    assert not [f for f in d["files"] if f["ext"] == "mpeg"][0]["playable"]


def test_wrong_identifier_is_resolved_by_search(client):
    d = client.get("/api/titles/metropolis").get_json()
    assert d["sources_status"] == "ok" and d["files"][0]["quality"] == "1080p"
    assert "found_by_search" in d["archive_url"]


def test_missing_item_marked_missing(client):
    d = client.get("/api/titles/the-general").get_json()
    assert d["sources_status"] == "missing" and d["files"] == [] and d["archive_url"]


def test_series_episodes_get_files(client):
    d = client.get("/api/titles/flash-gordon-1936").get_json()
    assert len(d["episodes"]) == 13 and d["seasons"] == [1]
    assert all(len(e["files"]) == 1 for e in d["episodes"])
    assert d["episodes"][0]["name"] == "The Planet of Peril"
    sup = client.get("/api/titles/superman-fleischer-1941").get_json()
    assert sup["seasons"] == [1, 2] and len(sup["episodes"]) == 17


def test_stream_download_range_and_log(client):
    d = client.get("/api/titles/night-of-the-living-dead").get_json()
    fid = d["files"][0]["id"]
    r = client.get(f"/api/stream/{fid}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.data) == 100 and r.headers["Content-Range"].startswith("bytes 0-99/")
    bad = [f for f in d["files"] if not f["playable"]][0]
    assert client.get(f"/api/stream/{bad['id']}").status_code == 400
    dl = client.get(f"/api/download/{fid}")
    assert dl.status_code == 200 and dl.data == VIDEO
    from urllib.parse import unquote
    assert "Night of the Living Dead (1968) [480p].mp4" in unquote(dl.headers["Content-Disposition"])
    client.get(f"/api/download/{fid}", headers={"Range": "bytes=500-"})  # resume: must not be logged again
    log = client.get("/api/me/downloads").get_json()
    assert len(log) == 1 and log[0]["name"] == "Night of the Living Dead"
    assert client.get("/api/stream/999999").status_code == 404


def test_links_and_playlist(client):
    client.get("/api/titles/flash-gordon-1936")
    links = client.get("/api/titles/flash-gordon-1936/links.txt").data.decode().split()
    assert len(links) == 13 and links[0].endswith("flash_ch01.mp4")
    m3u = client.get("/api/titles/flash-gordon-1936/playlist.m3u").data.decode()
    assert m3u.startswith("#EXTM3U") and "S01E01 The Planet of Peril" in m3u


def test_history_continue_watching_and_progress(client):
    tid = client.get("/api/titles/nosferatu").get_json()["id"]
    assert client.post("/api/me/history", json={"title_id": tid, "position": 600, "duration": 5600}).status_code == 200
    cw = client.get("/api/home").get_json()["continue"]
    assert cw[0]["name"] == "Nosferatu" and cw[0]["resume"]["position"] == 600
    client.post("/api/me/history", json={"title_id": tid, "position": 5500, "duration": 5600})
    assert client.get("/api/home").get_json()["continue"] == []  # finished -> drops off
    h = client.get("/api/me/history").get_json()
    assert h[0]["history"]["completed"] is True
    client.delete(f"/api/me/history/{h[0]['history']['id']}")
    assert client.get("/api/me/history").get_json() == []


def test_series_episode_history(client):
    d = client.get("/api/titles/flash-gordon-1936").get_json()
    ep = d["episodes"][2]["id"]
    client.post("/api/me/history", json={"title_id": d["id"], "episode_id": ep, "position": 300, "duration": 1200})
    h = client.get("/api/me/history").get_json()[0]
    assert h["history"]["episode"].startswith("S01E03")
    d2 = client.get("/api/titles/flash-gordon-1936").get_json()
    assert d2["episodes"][2]["progress"]["position"] == 300 and d2["mine"]["last"]["episode_id"] == ep


def test_watchlist_and_rating_are_per_client(client):
    tid = client.get("/api/titles/charade").get_json()["id"]
    assert client.put(f"/api/me/watchlist/{tid}").get_json()["in_list"]
    assert client.get("/api/me/watchlist").get_json()[0]["name"] == "Charade"
    assert client.get("/api/titles?q=charade").get_json()["items"][0]["in_list"] is True
    client.environ_base["HTTP_X_CLIENT_ID"] = "other-client-0002"
    assert client.get("/api/me/watchlist").get_json() == []
    client.environ_base["HTTP_X_CLIENT_ID"] = "test-client-0001"
    assert client.post("/api/titles/charade/rate", json={"stars": 4}).status_code == 200
    assert client.get("/api/titles/charade").get_json()["mine"]["rating"] == 4
    assert client.post("/api/titles/charade/rate", json={"stars": 9}).status_code == 400
    client.delete(f"/api/me/watchlist/{tid}")
    assert client.get("/api/me/watchlist").get_json() == []


def test_client_id_required_and_validated(client):
    client.environ_base.pop("HTTP_X_CLIENT_ID")
    assert client.get("/api/me/history").status_code == 400
    assert client.get("/api/titles").status_code == 200


def test_import_adds_new_titles(client):
    import archive, db
    with db.session() as conn:
        before = conn.execute("SELECT COUNT(*) c FROM titles").fetchone()["c"]
        assert archive.import_catalog(conn, 10, progress=lambda *_: None) == 1
        assert archive.import_catalog(conn, 10, progress=lambda *_: None) == 0  # idempotent
        t = conn.execute("SELECT * FROM titles WHERE ia_identifier='new_pd_film'").fetchone()
        assert t["rating"] == 8.0 and t["description"] == "An imported film ."
    r = client.get("/api/titles?q=new public domain").get_json()
    assert r["items"][0]["name"] == "A New Public Domain Film" and "Horror" in r["items"][0]["genres"]


def test_spa_and_health(client):
    assert client.get("/api/health").get_json()["status"] == "ok"
    assert client.get("/api/nope").status_code == 404
    assert client.get("/some/route").status_code == 200


# ------------------------------------------------------------------ admin
def _wait_job(client, timeout=10):
    import time
    end = time.time() + timeout
    while time.time() < end:
        st = client.get("/api/admin/status").get_json()
        if not st["running"]:
            return st
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_search_uses_bracketed_fields_regression(client):
    import archive
    docs = archive.search_items("title:(\"x\") AND feature_films", rows=5)
    assert docs and all(d["identifier"] for d in docs)         # docs without identifier are dropped
    assert archive.find_identifier("Metropolis", 1927) == "found_by_search"


def test_admin_import_job_with_log(client):
    before = client.get("/api/admin/overview").get_json()["titles"]
    assert client.post("/api/admin/import", json={"limit": 10}).get_json()["started"]
    st = _wait_job(client)
    assert st["error"] is None and st["result"]["imported"] == 1
    assert any("Imported 1 new titles" in line for line in st["log"])
    assert client.get("/api/admin/overview").get_json()["titles"] == before + 1


def test_admin_sync_job_and_overview(client):
    client.post("/api/admin/sync", json={})
    st = _wait_job(client)
    assert st["result"]["ok"] >= 2 and st["result"]["missing"] >= 1
    ov = client.get("/api/admin/overview").get_json()
    assert ov["status"]["ok"] >= 2 and ov["files"] > 0 and ov["series"] == 3
    assert client.post("/api/admin/tmdb").status_code == 400   # no TMDB key configured


def test_admin_add_edit_delete_title(client):
    r = client.post("/api/admin/titles", json={"identifier": "https://archive.org/details/brand_new_item?x=1"})
    assert r.status_code == 200 and r.get_json()["sources_status"] == "ok"
    tid = r.get_json()["id"]
    assert client.post("/api/admin/titles", json={"identifier": "brand_new_item"}).status_code == 400      # duplicate
    assert client.post("/api/admin/titles", json={"identifier": "does_not_exist"}).status_code == 400
    assert client.post("/api/admin/titles", json={"identifier": "bad id!!"}).status_code == 400
    d = client.get("/api/titles/brand-new-item-1949").get_json()
    assert d["files"] and "Comedy" in d["genres"] and "Silent" in d["genres"]
    s = client.post("/api/admin/titles", json={"identifier": "series_item", "kind": "series"}).get_json()
    sd = client.get(f"/api/titles/{s['slug']}").get_json()
    assert len(sd["episodes"]) == 3 and all(e["files"] for e in sd["episodes"])
    assert client.patch(f"/api/admin/titles/{tid}", json={"name": "Renamed Gem", "featured": True, "description": "New text"}).status_code == 200
    assert client.get("/api/titles?q=renamed gem").get_json()["items"][0]["name"] == "Renamed Gem"   # search index refreshed
    assert client.patch(f"/api/admin/titles/{tid}", json={"name": " "}).status_code == 400
    assert client.patch(f"/api/admin/titles/{tid}", json={"ia_identifier": "found_by_search"}).status_code == 200
    row = [i for i in client.get("/api/admin/titles?q=Renamed").get_json()["items"]][0]
    assert row["sources_status"] == "pending" and row["files"] == 0 and row["featured"] == 1
    assert client.post(f"/api/admin/titles/{tid}/sync").get_json()["status"] == "ok"
    assert client.delete(f"/api/admin/titles/{tid}").status_code == 200
    assert client.get(f"/api/titles/{tid}").status_code == 404
    assert client.get("/api/titles?q=renamed gem").get_json()["total"] == 0


def test_admin_list_filters(client):
    client.post("/api/admin/sync", json={}); _wait_job(client)
    missing = client.get("/api/admin/titles?status=missing").get_json()
    assert missing["total"] >= 1 and all(i["sources_status"] == "missing" for i in missing["items"])
    assert client.get("/api/admin/titles?kind=series").get_json()["total"] == 3


def test_admin_requires_token_when_configured(client):
    client.appmod.ADMIN_TOKEN = "s3cret"
    assert client.get("/api/admin/overview").status_code == 403
    assert client.get("/api/admin/overview", headers={"X-Admin-Token": "nope"}).status_code == 403
    assert client.get("/api/admin/overview", headers={"X-Admin-Token": "s3cret"}).status_code == 200
    assert client.post("/api/admin/import", json={}).status_code == 403
    assert client.get("/api/titles").status_code == 200        # public API unaffected


def test_admin_blocked_remotely_without_token(client):
    r = client.get("/api/admin/overview", environ_overrides={"REMOTE_ADDR": "203.0.113.9"})
    assert r.status_code == 403 and "ADMIN_TOKEN" in r.get_json()["error"]


def test_redirect_mode_for_stream_only(client):
    client.appmod.PROXY_STREAM = False
    fid = client.get("/api/titles/night-of-the-living-dead").get_json()["files"][0]["id"]
    r = client.get(f"/api/stream/{fid}")
    assert r.status_code == 302 and "/download/night_of_the_living_dead/" in r.headers["Location"]
    assert client.get(f"/api/download/{fid}").status_code == 200       # downloads still proxied (named + saved, not played)


# ------------------------------------------------------------------ import hardening, direct sources, collections
def test_runtime_parsing_handles_real_world_formats():
    import archive
    cases = [("1 hr 30 min", 90), ("1:35:00 min", 95), ("95 min", 95), ("5700", 95), ("01:35:00", 95), ("about an hour", None),
             (None, None), ("88:00", 88), (5400, 90), ("2 hours", 120), ("0", None)]
    for raw, want in cases:
        assert archive.runtime_minutes(raw) == want, (raw, archive.runtime_minutes(raw), want)
    assert archive.runtime_minutes(["1:30:00"]) == 90


def test_import_pages_through_results_and_survives_bad_data(client):
    import archive, db
    with db.session() as conn:
        logs = []
        a = archive.import_catalog(conn, 60, query="collection:bulk_films AND mediatype:movies", progress=logs.append)
        assert a == 60                                             # spans two pages of 50; odd runtimes did not crash it
        b = archive.import_catalog(conn, 60, query="collection:bulk_films AND mediatype:movies", progress=logs.append)
        assert b == 60                                             # second run continues where the first stopped
        c = archive.import_catalog(conn, 60, query="collection:bulk_films AND mediatype:movies", progress=logs.append)
        assert c == 0 and any("already in your catalog" in l for l in logs)
        assert conn.execute("SELECT COUNT(*) FROM titles WHERE ia_identifier LIKE 'bulk_%'").fetchone()[0] == 120
        assert conn.execute("SELECT runtime FROM titles WHERE ia_identifier='bulk_000'").fetchone()[0] == 90


def test_build_query_presets_and_strict_toggle():
    import archive
    assert "collection:classic_tv" in archive.build_query("classic_tv", strict=False)
    assert "licenseurl" not in archive.build_query("classic_tv", strict=False)
    assert "licenseurl" in archive.build_query("classic_tv", strict=True)
    assert archive.build_query(query="custom AND thing") == "custom AND thing"
    assert "SciFi_Horror" in archive.build_query("scifi_horror")


def test_admin_import_accepts_preset_and_strict(client):
    client.post("/api/admin/import", json={"limit": 5, "preset": "film_noir", "strict": False})
    st = _wait_job(client)
    assert st["error"] is None and any("collection:film_noir" in l and "licenseurl" not in l for l in st["log"])
    assert {p["key"] for p in client.get("/api/admin/presets").get_json()} >= {"feature_films", "classic_tv", "scifi_horror"}


def test_direct_source_folder_is_discovered(client, fake_ia=None):
    import db
    base = client.appmod.archive.IA_BASE
    with db.session() as conn:
        conn.execute("UPDATE titles SET source_url=? WHERE slug='big-buck-bunny'", (base + "/folder/",))
    d = client.get("/api/titles/big-buck-bunny").get_json()
    assert d["sources_status"] == "ok" and d["license"].startswith("CC BY")
    names = sorted(f["name"] for f in d["files"])
    assert names == ["big_buck_bunny_1080p.mov", "big_buck_bunny_720p.mp4", "old.mkv"]   # trailer / stereo / zip / txt are ignored
    best = d["files"][0]
    assert best["playable"] and {f["quality"] for f in d["files"] if f["playable"]} == {"720p", "1080p"}
    assert [f["playable"] for f in d["files"] if f["name"] == "old.mkv"] == [False]       # mkv: download only
    r = client.get(f"/api/download/{best['id']}")
    assert r.status_code == 200 and "Big%20Buck%20Bunny" in r.headers["Content-Disposition"]
    assert client.get(f"/api/stream/{best['id']}", headers={"Range": "bytes=0-9"}).status_code == 206


def test_direct_folder_down_is_error_not_crash(client):
    import db
    with db.session() as conn:
        conn.execute("UPDATE titles SET source_url='http://127.0.0.1:1/nope/' WHERE slug='sintel'")
    assert client.get("/api/titles/sintel").get_json()["sources_status"] == "error"


def test_blender_titles_are_seeded(client):
    for slug in ("big-buck-bunny", "sintel", "tears-of-steel", "elephants-dream"):
        d = client.get(f"/api/titles/{slug}").get_json()
        assert d["license"].startswith("CC BY") and "Short" in d["genres"]


def test_collection_becomes_series_with_episode_files(client):
    r = client.post("/api/admin/titles", json={"identifier": "https://archive.org/details/coll_series"}).get_json()
    d = client.get(f"/api/titles/{r['slug']}").get_json()
    assert d["kind"] == "series" and [e["name"] for e in d["episodes"]] == ["Episode 2", "Episode 10"]   # natural sort
    assert all(e["files"] for e in d["episodes"]) and d["sources_status"] == "ok"


def test_deleted_seed_title_stays_deleted_after_restart_and_new_seed_titles_arrive(client):
    import db, catalog
    tid = client.get("/api/titles/the-kid").get_json()["id"]
    client.delete(f"/api/admin/titles/{tid}")
    with db.session() as conn:
        conn.execute("DELETE FROM titles WHERE slug='sintel'")        # simulate a DB from before Sintel was bundled
        catalog.ensure_seeded(conn)                                    # what happens on every startup
    assert client.get("/api/titles/the-kid").status_code == 404        # not resurrected
    assert client.get("/api/titles/sintel").status_code == 200         # new bundled title added


def test_old_database_is_migrated(tmp_path):
    import sqlite3, importlib, sys, os
    path = str(tmp_path / "old.db")
    os.environ["CINEVAULT_DB"] = path
    sys.modules.pop("db", None)
    import db
    # an "old" database = today's schema minus the two columns added in this release
    old_schema = "\n".join(l for l in db.SCHEMA.splitlines() if "source_url TEXT" not in l and "    url TEXT," not in l and "deleted_slugs" not in l)
    c = sqlite3.connect(path)
    c.executescript(old_schema)
    c.execute("INSERT INTO titles(slug, kind, name) VALUES ('keep-me','movie','Keep Me')")
    c.commit()
    assert "source_url" not in {r[1] for r in c.execute("PRAGMA table_info(titles)")}
    c.close()
    db.init_db(path)
    with db.session(path) as conn:
        assert "source_url" in {r["name"] for r in conn.execute("PRAGMA table_info(titles)")}
        assert "url" in {r["name"] for r in conn.execute("PRAGMA table_info(media_files)")}
        assert conn.execute("SELECT name FROM titles WHERE slug='keep-me'").fetchone()[0] == "Keep Me"      # data survives


# ------------------------------------------------------------------ discover (TMDB)
def _tmdb_client(client, fake_ia, monkeypatch, key="a" * 32):
    monkeypatch.setenv("TMDB_API_KEY", key)
    monkeypatch.setenv("TMDB_BASE", fake_ia + "/tmdb/3")
    client.appmod.tmdb._cache.clear()
    return client


def test_discover_disabled_without_key(client):
    r = client.get("/api/discover?q=thrones").get_json()
    assert r["enabled"] is False and r["items"] == []
    assert client.get("/api/discover/series/1399").status_code == 404


def test_discover_search_trending_and_library_link(client, fake_ia, monkeypatch):
    _tmdb_client(client, fake_ia, monkeypatch)
    r = client.get("/api/discover?q=game of thrones").get_json()
    assert r["enabled"] and [i["name"] for i in r["items"]] == ["Game of Thrones"]          # people results are dropped
    got = r["items"][0]
    assert got["kind"] == "series" and got["year"] == 2011 and got["library_slug"] is None and got["poster"].endswith("/w342/got.jpg")
    m = client.get("/api/discover?q=metropolis").get_json()["items"][0]
    assert m["kind"] == "movie" and m["library_slug"] == "metropolis"                           # already free in the library
    t = client.get("/api/discover").get_json()
    assert t["trending"] and t["items"][0]["name"] == "Game of Thrones"


def test_discover_detail_trailer_cast_and_where_to_watch(client, fake_ia, monkeypatch):
    _tmdb_client(client, fake_ia, monkeypatch)
    d = client.get("/api/discover/series/1399?region=us").get_json()
    assert d["name"] == "Game of Thrones" and d["seasons"] == 8 and d["episodes"] == 73 and d["runtime"] == 60
    assert d["trailer"] == "TRAILERKEY"                                      # official YouTube trailer beats clips and Vimeo
    assert d["people"] == ["David Benioff", "D. B. Weiss"] and d["cast"][0]["character"] == "Daenerys Targaryen"
    w = d["watch"]
    assert w["region"] == "US" and [p["name"] for p in w["stream"]] == ["Max"] and w["rent"][0]["name"] == "Apple TV" and w["buy"][0]["name"] == "Amazon Video"
    assert w["link"].startswith("https://www.themoviedb.org/") and set(w["regions"]) == {"US", "KE"}
    ke = client.get("/api/discover/series/1399?region=KE").get_json()["watch"]
    assert [p["name"] for p in ke["stream"]] == ["Showmax"] and ke["rent"] == []
    assert client.get("/api/discover/series/999999").status_code == 404
    assert client.get("/api/discover/book/1").status_code == 404


def test_tmdb_key_styles(client, fake_ia, monkeypatch):
    _tmdb_client(client, fake_ia, monkeypatch, key="k" * 32)               # v3 API key -> query parameter
    client.get("/api/discover?q=thrones")
    assert LAST_TMDB["qs"].get("api_key") == ["k" * 32] and LAST_TMDB["auth"] is None
    token = "eyJ" + "x" * 150
    _tmdb_client(client, fake_ia, monkeypatch, key=token)                  # v4 read-access token -> bearer header
    client.get("/api/discover?q=metropolis")
    assert LAST_TMDB["auth"] == f"Bearer {token}" and "api_key" not in LAST_TMDB["qs"]


def test_tmdb_errors_are_friendly(client, fake_ia, monkeypatch):
    _tmdb_client(client, fake_ia, monkeypatch)
    monkeypatch.setenv("TMDB_BASE", "http://127.0.0.1:1/unreachable")      # nothing listening
    client.appmod.tmdb._cache.clear()
    r = client.get("/api/discover?q=thrones")
    assert r.status_code == 502 and "TMDB" in r.get_json()["error"]


def test_strict_import_falls_back_when_collection_has_no_licence_tags(client):
    import archive, db
    with db.session() as conn:
        logs = []
        n = archive.import_catalog(conn, 5, preset="classic_tv", strict=True, progress=logs.append)
        assert n == 2 and any("importing the whole collection" in l for l in logs)


def test_series_mode_imports_multi_file_items_as_series(client):
    import archive, db
    with db.session() as conn:
        logs = []
        n = archive.import_catalog(conn, 5, preset="classic_tv_series", strict=False, progress=logs.append)
        assert n == 1                                              # ep_a has one file, so it is not a series
        t = conn.execute("SELECT * FROM titles WHERE ia_identifier='series_item'").fetchone()
        assert t["kind"] == "series"
        assert conn.execute("SELECT COUNT(*) FROM episodes WHERE title_id=?", (t["id"],)).fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM titles WHERE ia_identifier='ep_a'").fetchone()[0] == 0
