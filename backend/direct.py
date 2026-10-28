"""Direct-download sources: a web folder (Apache/nginx style index) of video files, e.g. download.blender.org.

Files are discovered at sync time by reading the folder listing, so nothing is hard-coded and a moved file
simply shows up as missing instead of a dead link.
"""
import re
from urllib.parse import unquote, urljoin

import requests

HEADERS = {"User-Agent": "CineVault/1.0 (+media browser)"}
EXT_PLAYABLE = {"mp4", "m4v", "webm", "ogv", "mov"}
EXT_ALL = EXT_PLAYABLE | {"mkv", "avi"}
SKIP = re.compile(r"trailer|sample|preview|teaser|stereo|3d|dcp|\.zip|\.tar|\.gz|\.7z", re.I)
HREF = re.compile(r'href="([^"?#]+?\.(?:%s))"' % "|".join(sorted(EXT_ALL)), re.I)


def quality_of(name, height=None):
    m = re.search(r"(2160|1440|1080|720|576|480|360|320x180)p?", name)
    if m:
        t = m.group(1)
        return "360p" if t == "320x180" else f"{t}p"
    if re.search(r"4k|uhd", name, re.I):
        return "2160p"
    if re.search(r"hd", name, re.I):
        return "720p"
    return name.rsplit(".", 1)[-1].upper()


def list_files(folder_url):
    """[(name, absolute_url)] for every video linked from the folder index."""
    r = requests.get(folder_url, headers=HEADERS, timeout=(10, 40))
    r.raise_for_status()
    out, seen = [], set()
    for href in HREF.findall(r.text):
        url = urljoin(folder_url if folder_url.endswith("/") else folder_url + "/", href)
        name = unquote(url.rsplit("/", 1)[-1])
        if url in seen or SKIP.search(name):
            continue
        seen.add(url)
        out.append((name, url))
    return out


def head_size(url):
    try:
        r = requests.head(url, headers=HEADERS, timeout=(8, 12), allow_redirects=True)
        return int(r.headers.get("Content-Length") or 0)
    except (requests.RequestException, ValueError):
        return 0


def sync_title(conn, title):
    """Store the folder's video files for a direct-source title. Returns 'ok' | 'missing' | 'error'."""
    tid, folder = title["id"], title["source_url"]
    try:
        files = list_files(folder)
    except requests.RequestException:
        return "error"
    if not files:
        return "missing"
    conn.execute("DELETE FROM media_files WHERE title_id=? AND episode_id IS NULL", (tid,))
    ident = f"direct:{title['slug']}"
    for name, url in files:
        ext = name.rsplit(".", 1)[-1].lower()
        conn.execute(
            """INSERT INTO media_files(title_id, episode_id, ia_identifier, url, name, format, size, height, duration, quality, playable)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ia_identifier, name) DO UPDATE SET url=excluded.url, size=excluded.size, quality=excluded.quality, playable=excluded.playable""",
            (tid, None, ident, url, name, ext.upper(), head_size(url), None, None, quality_of(name), 1 if ext in EXT_PLAYABLE else 0))
    return "ok"
