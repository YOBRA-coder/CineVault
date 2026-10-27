"""Seed the database from seed_data.py (idempotent) and small catalog helpers."""
import math
import re

import db
import seed_data

FEATURED = {
    "metropolis", "nosferatu", "night-of-the-living-dead", "charade",
    "flash-gordon-1936", "the-general", "superman-fleischer-1941",
}


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "title"


def unique_slug(conn, base):
    slug, n = base, 2
    while conn.execute("SELECT 1 FROM titles WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


def ia_thumb(identifier, base="https://archive.org"):
    return f"{base}/services/img/{identifier}" if identifier else None


def set_genres(conn, title_id, genres):
    conn.execute("DELETE FROM title_genres WHERE title_id = ?", (title_id,))
    for g in dict.fromkeys(genres):
        conn.execute("INSERT OR IGNORE INTO genres(name) VALUES (?)", (g,))
        gid = conn.execute("SELECT id FROM genres WHERE name = ?", (g,)).fetchone()["id"]
        conn.execute("INSERT OR IGNORE INTO title_genres VALUES (?, ?)", (title_id, gid))


def set_credit(conn, title_id, name, role="cast", character=None, ord_=0, photo=None):
    conn.execute("INSERT OR IGNORE INTO people(name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM people WHERE name = ?", (name,)).fetchone()
    if photo:
        conn.execute("UPDATE people SET photo_url = ? WHERE id = ?", (photo, row["id"]))
    conn.execute(
        "INSERT OR REPLACE INTO credits(title_id, person_id, role, character, ord) VALUES (?,?,?,?,?)",
        (title_id, row["id"], role, character, ord_),
    )


def popularity(rating, votes):
    return round((rating or 0) * math.log((votes or 0) + 1), 2)


def _upsert_title(conn, **f):
    row = conn.execute("SELECT id FROM titles WHERE slug = ?", (f["slug"],)).fetchone()
    if row:
        # keep user-affecting live fields (poster/sources/popularity); refresh editorial metadata
        conn.execute(
            """UPDATE titles SET name=?, year=?, description=?, runtime=?, director=?, rating=?, votes=?,
               featured=? WHERE id=?""",
            (f["name"], f["year"], f["description"], f["runtime"], f["director"], f["rating"], f["votes"],
             f["featured"], row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        """INSERT INTO titles(slug, kind, name, year, description, rating, votes, runtime, director,
             poster_url, backdrop_url, ia_identifier, ia_collection, popularity, featured, country, language)
           VALUES (:slug,:kind,:name,:year,:description,:rating,:votes,:runtime,:director,
             :poster_url,:backdrop_url,:ia_identifier,:ia_collection,:popularity,:featured,:country,:language)""",
        f,
    )
    return cur.lastrowid


def seed(conn):
    """Insert/refresh the bundled catalog. Safe to run repeatedly."""
    for (slug, name, year, genres, runtime, director, rating, votes, ia_id, cast, desc) in seed_data.MOVIES:
        tid = _upsert_title(
            conn, slug=slug, kind="movie", name=name, year=year, description=desc, rating=rating, votes=votes,
            runtime=runtime, director=director, poster_url=ia_thumb(ia_id), backdrop_url=ia_thumb(ia_id),
            ia_identifier=ia_id, ia_collection=None, popularity=popularity(rating, votes),
            featured=1 if slug in FEATURED else 0, country=None, language="English",
        )
        set_genres(conn, tid, genres)
        _set_cast(conn, tid, director, cast)

    for (slug, name, year, genres, ep_rt, creator, rating, votes, ia_id, ia_col, cast, desc, seasons) in seed_data.SERIES:
        tid = _upsert_title(
            conn, slug=slug, kind="series", name=name, year=year, description=desc, rating=rating, votes=votes,
            runtime=ep_rt, director=creator, poster_url=ia_thumb(ia_id), backdrop_url=ia_thumb(ia_id),
            ia_identifier=ia_id, ia_collection=ia_col, popularity=popularity(rating, votes),
            featured=1 if slug in FEATURED else 0, country=None, language="English",
        )
        set_genres(conn, tid, genres)
        _set_cast(conn, tid, creator, cast)
        for season, eps in seasons:
            for n, (ename, eyear, edesc) in enumerate(eps, start=1):
                conn.execute(
                    """INSERT INTO episodes(title_id, season, number, name, description, runtime, air_date)
                       VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(title_id, season, number) DO UPDATE SET
                         name=excluded.name, description=excluded.description, runtime=excluded.runtime,
                         air_date=excluded.air_date""",
                    (tid, season, n, ename, edesc, ep_rt, str(eyear)),
                )
    db.rebuild_fts(conn)


def _set_cast(conn, tid, director, cast):
    conn.execute("DELETE FROM credits WHERE title_id = ?", (tid,))
    if director:
        set_credit(conn, tid, director, "director", None, 0)
    for i, (actor, character) in enumerate(cast):
        set_credit(conn, tid, actor, "cast", character, i)


def ensure_seeded(conn):
    if conn.execute("SELECT COUNT(*) AS c FROM titles").fetchone()["c"] == 0:
        seed(conn)
        return True
    return False
