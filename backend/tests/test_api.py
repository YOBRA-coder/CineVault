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
            if ident == "found_by_search":
                return self._json({"metadata": {"identifier": ident}, "files": [{"name": "m.mp4", "format": "h.264", "size": "10000", "height": "1080", "length": "7200"}]})
            return self._json({}, 200)  # archive.org answers {} for unknown ids
        if u.path == "/advancedsearch.php":
            q = parse_qs(u.query).get("q", [""])[0]
            if "Metropolis" in q:
                return self._json({"response": {"docs": [{"identifier": "found_by_search", "title": "Metropolis", "year": "1927", "downloads": 500000}]}})
            if "feature_films" in q:
                return self._json({"response": {"docs": [
                    {"identifier": "new_pd_film", "title": "A New Public Domain Film", "year": "1931", "creator": "Jane Doe",
                     "description": "<p>An imported <b>film</b>.</p>", "subject": ["Horror", "Silent"], "downloads": 12345, "avg_rating": "4.0", "num_reviews": 12}]}})
            return self._json({"response": {"docs": []}})
        if u.path.startswith("/download/"):
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
