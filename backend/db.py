"""SQLite schema, connection helpers and the full-text search index."""
import os
import re
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("CINEVAULT_DB", os.path.join(os.path.dirname(__file__), "data", "cinevault.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS titles (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('movie','series')),
    name TEXT NOT NULL,
    year INTEGER,
    tagline TEXT,
    description TEXT,
    rating REAL DEFAULT 0,
    votes INTEGER DEFAULT 0,
    runtime INTEGER,
    language TEXT DEFAULT 'English',
    country TEXT,
    director TEXT,
    poster_url TEXT,
    backdrop_url TEXT,
    ia_identifier TEXT,
    ia_collection TEXT,
    source_url TEXT,                          -- direct-download folder (non-archive.org sources)
    license TEXT DEFAULT 'Public Domain',
    sources_status TEXT DEFAULT 'pending',   -- pending | ok | missing | error
    sources_checked_at TEXT,
    popularity REAL DEFAULT 0,
    featured INTEGER DEFAULT 0,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_titles_kind ON titles(kind);
CREATE INDEX IF NOT EXISTS idx_titles_year ON titles(year);

CREATE TABLE IF NOT EXISTS genres (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS title_genres (
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
    PRIMARY KEY (title_id, genre_id)
);

CREATE TABLE IF NOT EXISTS people (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, photo_url TEXT);
CREATE TABLE IF NOT EXISTS credits (
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'cast',        -- cast | director
    character TEXT,
    ord INTEGER DEFAULT 0,
    PRIMARY KEY (title_id, person_id, role)
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    season INTEGER NOT NULL DEFAULT 1,
    number INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    runtime INTEGER,
    air_date TEXT,
    ia_identifier TEXT,
    UNIQUE (title_id, season, number)
);

CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    episode_id INTEGER REFERENCES episodes(id) ON DELETE CASCADE,
    ia_identifier TEXT NOT NULL,
    url TEXT,                                 -- full URL for direct sources; NULL = archive.org item file
    name TEXT NOT NULL,
    format TEXT,
    size INTEGER,
    height INTEGER,
    duration REAL,
    quality TEXT,
    playable INTEGER DEFAULT 1,
    UNIQUE (ia_identifier, name)
);
CREATE INDEX IF NOT EXISTS idx_files_title ON media_files(title_id);
CREATE INDEX IF NOT EXISTS idx_files_episode ON media_files(episode_id);

CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    client_id TEXT NOT NULL,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    episode_id INTEGER NOT NULL DEFAULT 0,
    position REAL DEFAULT 0,
    duration REAL DEFAULT 0,
    completed INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (client_id, title_id, episode_id)
);
CREATE INDEX IF NOT EXISTS idx_history_client ON history(client_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS watchlist (
    client_id TEXT NOT NULL,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (client_id, title_id)
);

CREATE TABLE IF NOT EXISTS user_ratings (
    client_id TEXT NOT NULL,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    value INTEGER NOT NULL CHECK (value BETWEEN 1 AND 10),
    PRIMARY KEY (client_id, title_id)
);

CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY,
    client_id TEXT NOT NULL,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    episode_id INTEGER,
    file_id INTEGER REFERENCES media_files(id) ON DELETE SET NULL,
    filename TEXT,
    size INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_downloads_client ON downloads(client_id, created_at DESC);

CREATE TABLE IF NOT EXISTS watch_links (          -- extra legal places to watch/stream a title (added by the admin)
    id INTEGER PRIMARY KEY,
    title_id INTEGER NOT NULL REFERENCES titles(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_watch_links_title ON watch_links(title_id);

CREATE TABLE IF NOT EXISTS deleted_slugs (slug TEXT PRIMARY KEY);   -- admin-deleted seed titles stay deleted

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY,
    client_id TEXT NOT NULL,
    q TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_searches_client ON searches(client_id, id DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS title_fts USING fts5(
    name, genres, cast, director, description, tokenize = 'unicode61 remove_diacritics 2'
);
"""


def connect(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session(path=None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


MIGRATIONS = [  # (table, column, DDL) - upgrade databases created by earlier versions
    ("titles", "source_url", "ALTER TABLE titles ADD COLUMN source_url TEXT"),
    ("media_files", "url", "ALTER TABLE media_files ADD COLUMN url TEXT"),
]


def init_db(path=None):
    with session(path) as conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(ddl)


def rebuild_fts(conn, title_id=None):
    """(Re)build search rows. Pass title_id to refresh one title."""
    where = "WHERE t.id = ?" if title_id else ""
    args = (title_id,) if title_id else ()
    if title_id:
        conn.execute("DELETE FROM title_fts WHERE rowid = ?", (title_id,))
    else:
        conn.execute("DELETE FROM title_fts")
    conn.execute(
        f"""INSERT INTO title_fts(rowid, name, genres, cast, director, description)
            SELECT t.id, t.name,
              COALESCE((SELECT group_concat(g.name, ' ') FROM title_genres tg JOIN genres g ON g.id = tg.genre_id WHERE tg.title_id = t.id), ''),
              COALESCE((SELECT group_concat(p.name, ' ') FROM credits c JOIN people p ON p.id = c.person_id WHERE c.title_id = t.id AND c.role = 'cast'), ''),
              COALESCE(t.director, ''),
              COALESCE(t.description, '')
            FROM titles t {where}""",
        args,
    )


_tok = re.compile(r"[\w']+", re.UNICODE)


def fts_query(q):
    """Turn user text into a safe FTS5 query: every word must match, last word is a prefix."""
    words = [w.replace("'", "") for w in _tok.findall(q or "")]
    words = [w for w in words if w]
    if not words:
        return None
    parts = [f'"{w}"' for w in words[:-1]] + [f'"{words[-1]}"*']
    return " ".join(parts)
