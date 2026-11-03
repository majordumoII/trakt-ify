"""SQLite persistence for ingested Trakt data.

Kept deliberately dumb: no ORM, no migrations. The schema is re-runnable.
`related_fetch` makes ingestion resumable, which matters because a full pass is
~1900 requests and spends ~11 minutes rate-limited.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import Movie, RatedMovie, WatchedMovie, WatchlistMovie

SCHEMA = """
CREATE TABLE IF NOT EXISTS movies (
    trakt_id INTEGER PRIMARY KEY,
    title    TEXT NOT NULL,
    year     INTEGER,
    slug     TEXT,
    imdb     TEXT,
    tmdb     INTEGER
);

CREATE TABLE IF NOT EXISTS watched (
    trakt_id         INTEGER PRIMARY KEY REFERENCES movies(trakt_id),
    plays            INTEGER NOT NULL DEFAULT 0,
    last_watched_at  TEXT
);

CREATE TABLE IF NOT EXISTS related (
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    PRIMARY KEY (source_id, target_id)
);

CREATE INDEX IF NOT EXISTS idx_related_source ON related(source_id);
CREATE INDEX IF NOT EXISTS idx_related_target ON related(target_id);

CREATE TABLE IF NOT EXISTS related_fetch (
    source_id  INTEGER PRIMARY KEY,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_ratings (
    trakt_id INTEGER PRIMARY KEY,
    rating   INTEGER NOT NULL,
    rated_at TEXT
);

CREATE TABLE IF NOT EXISTS watchlist (
    trakt_id  INTEGER PRIMARY KEY,
    listed_at TEXT
);

-- Model-written cluster descriptions. Louvain re-runs can renumber clusters,
-- so labels are matched back to clusters by member overlap, not by index.
CREATE TABLE IF NOT EXISTS cluster_labels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    members    TEXT NOT NULL,
    label      TEXT NOT NULL,
    summary    TEXT NOT NULL,
    themes     TEXT NOT NULL,
    model      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Metadata columns from `?extended=full`, added in place to older databases.
_META_COLUMNS = {
    "genres": "TEXT",
    "rating": "REAL",
    "votes": "INTEGER",
    "overview": "TEXT",
    "tagline": "TEXT",
    "runtime": "INTEGER",
    "certification": "TEXT",
    "language": "TEXT",
    "released": "TEXT",
    "poster": "TEXT",
    "meta_fetched_at": "TEXT",
}

_UPSERT_MOVIE = """
INSERT INTO movies (trakt_id, title, year, slug, imdb, tmdb)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(trakt_id) DO UPDATE SET
    title = excluded.title,
    year  = excluded.year,
    slug  = excluded.slug,
    imdb  = excluded.imdb,
    tmdb  = excluded.tmdb
"""

_UPSERT_WATCHED = """
INSERT INTO watched (trakt_id, plays, last_watched_at)
VALUES (?, ?, ?)
ON CONFLICT(trakt_id) DO UPDATE SET
    plays           = excluded.plays,
    last_watched_at = excluded.last_watched_at
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._con = sqlite3.connect(path, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=NORMAL")

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def init_schema(self) -> None:
        self._con.executescript(SCHEMA)
        existing = {row["name"] for row in self._con.execute("PRAGMA table_info(movies)")}
        for column, kind in _META_COLUMNS.items():
            if column not in existing:
                self._con.execute(f"ALTER TABLE movies ADD COLUMN {column} {kind}")

    # -- writes ------------------------------------------------------------

    def upsert_movies(self, movies: Iterable[Movie]) -> int:
        rows = [
            (m.ids.trakt, m.title, m.year, m.ids.slug, m.ids.imdb, m.ids.tmdb)
            for m in movies
        ]
        if rows:
            self._con.executemany(_UPSERT_MOVIE, rows)
        return len(rows)

    def upsert_movie_meta(self, movies: Iterable[Movie]) -> int:
        """Store extended metadata. Base upserts never touch these columns."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                m.ids.trakt, m.title, m.year, m.ids.slug, m.ids.imdb, m.ids.tmdb,
                json.dumps(m.genres or []), m.rating, m.votes, m.overview, m.tagline,
                m.runtime, m.certification, m.language, m.released, m.poster, now,
            )
            for m in movies
            if m.is_extended
        ]
        if rows:
            self._con.executemany(
                "INSERT INTO movies (trakt_id, title, year, slug, imdb, tmdb, genres, rating, "
                "votes, overview, tagline, runtime, certification, language, released, poster, "
                "meta_fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(trakt_id) DO UPDATE SET title=excluded.title, year=excluded.year, "
                "genres=excluded.genres, rating=excluded.rating, votes=excluded.votes, "
                "overview=excluded.overview, tagline=excluded.tagline, runtime=excluded.runtime, "
                "certification=excluded.certification, language=excluded.language, "
                "released=excluded.released, poster=excluded.poster, "
                "meta_fetched_at=excluded.meta_fetched_at",
                rows,
            )
        return len(rows)

    def replace_ratings(self, entries: Iterable[RatedMovie]) -> int:
        rows = [
            (e.movie.ids.trakt, e.rating, e.rated_at.isoformat() if e.rated_at else None)
            for e in entries
        ]
        with self._con:
            self._con.execute("DELETE FROM user_ratings")
            self._con.executemany("INSERT OR REPLACE INTO user_ratings VALUES (?,?,?)", rows)
        return len(rows)

    def replace_watchlist(self, entries: Iterable[WatchlistMovie]) -> int:
        rows = [
            (e.movie.ids.trakt, e.listed_at.isoformat() if e.listed_at else None)
            for e in entries
        ]
        with self._con:
            self._con.execute("DELETE FROM watchlist")
            self._con.executemany("INSERT OR REPLACE INTO watchlist VALUES (?,?)", rows)
        return len(rows)

    def add_cluster_label(
        self, members: Iterable[int], label: str, summary: str, themes: list[str], model: str
    ) -> None:
        self._con.execute(
            "INSERT INTO cluster_labels (members, label, summary, themes, model, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                json.dumps(sorted(members)), label, summary, json.dumps(themes), model,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def upsert_watched(self, entries: Iterable[WatchedMovie]) -> int:
        rows = [
            (
                e.movie.ids.trakt,
                e.plays,
                e.last_watched_at.isoformat() if e.last_watched_at else None,
            )
            for e in entries
        ]
        if rows:
            self._con.executemany(_UPSERT_WATCHED, rows)
        return len(rows)

    def replace_related(self, source_id: int, target_ids: Iterable[int]) -> int:
        rows = [(source_id, int(t)) for t in target_ids if int(t) != source_id]
        with self._con:
            self._con.execute("DELETE FROM related WHERE source_id = ?", (source_id,))
            if rows:
                self._con.executemany(
                    "INSERT OR IGNORE INTO related (source_id, target_id) VALUES (?, ?)",
                    rows,
                )
            self._con.execute(
                "INSERT INTO related_fetch (source_id, fetched_at) VALUES (?, ?) "
                "ON CONFLICT(source_id) DO UPDATE SET fetched_at = excluded.fetched_at",
                (source_id, datetime.now(timezone.utc).isoformat()),
            )
        return len(rows)

    def set_meta(self, key: str, value: str) -> None:
        self._con.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # -- reads -------------------------------------------------------------

    def watched_ids(self) -> list[int]:
        cursor = self._con.execute("SELECT trakt_id FROM watched ORDER BY trakt_id")
        return [row["trakt_id"] for row in cursor]

    def pending_related_ids(self, *, refresh: bool = False) -> list[int]:
        if refresh:
            return self.watched_ids()
        cursor = self._con.execute(
            "SELECT w.trakt_id FROM watched w "
            "LEFT JOIN related_fetch f ON f.source_id = w.trakt_id "
            "WHERE f.source_id IS NULL ORDER BY w.trakt_id"
        )
        return [row["trakt_id"] for row in cursor]

    def related_for_watched(self) -> dict[int, set[int]]:
        """Related-sets keyed by watched source. The graph's raw material."""
        cursor = self._con.execute(
            "SELECT r.source_id, r.target_id FROM related r "
            "JOIN watched w ON w.trakt_id = r.source_id"
        )
        result: dict[int, set[int]] = {}
        for row in cursor:
            result.setdefault(row["source_id"], set()).add(row["target_id"])
        return result

    def watched_nodes(self) -> dict[int, sqlite3.Row]:
        cursor = self._con.execute(
            "SELECT m.trakt_id, m.title, m.year, m.slug, m.imdb, m.tmdb, m.genres, "
            "       w.plays, w.last_watched_at, r.rating AS user_rating "
            "FROM movies m JOIN watched w ON w.trakt_id = m.trakt_id "
            "LEFT JOIN user_ratings r ON r.trakt_id = m.trakt_id"
        )
        return {row["trakt_id"]: row for row in cursor}

    def all_related(self) -> dict[int, set[int]]:
        """Every stored related-set, keyed by source (watched or not)."""
        result: dict[int, set[int]] = {}
        for row in self._con.execute("SELECT source_id, target_id FROM related"):
            result.setdefault(row["source_id"], set()).add(row["target_id"])
        return result

    def movie_rows(self, ids: Iterable[int]) -> dict[int, sqlite3.Row]:
        ids = list(ids)
        out: dict[int, sqlite3.Row] = {}
        for start in range(0, len(ids), 900):
            chunk = ids[start : start + 900]
            marks = ",".join("?" * len(chunk))
            for row in self._con.execute(
                f"SELECT * FROM movies WHERE trakt_id IN ({marks})", chunk
            ):
                out[row["trakt_id"]] = row
        return out

    def missing_meta(self, ids: Iterable[int]) -> list[int]:
        rows = self.movie_rows(ids)
        return [i for i in ids if i not in rows or rows[i]["meta_fetched_at"] is None]

    def user_ratings(self) -> dict[int, int]:
        return {
            row["trakt_id"]: row["rating"]
            for row in self._con.execute("SELECT trakt_id, rating FROM user_ratings")
        }

    def watchlist_ids(self) -> set[int]:
        return {row["trakt_id"] for row in self._con.execute("SELECT trakt_id FROM watchlist")}

    def cluster_labels(self) -> list[dict]:
        return [
            {
                "members": set(json.loads(row["members"])),
                "label": row["label"],
                "summary": row["summary"],
                "themes": json.loads(row["themes"]),
                "model": row["model"],
            }
            for row in self._con.execute("SELECT * FROM cluster_labels ORDER BY id DESC")
        ]

    def get_meta(self, key: str) -> str | None:
        row = self._con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for label, sql in (
            ("movies", "SELECT COUNT(*) FROM movies"),
            ("watched", "SELECT COUNT(*) FROM watched"),
            ("related_fetched", "SELECT COUNT(*) FROM related_fetch"),
            ("related_edges", "SELECT COUNT(*) FROM related"),
        ):
            out[label] = self._con.execute(sql).fetchone()[0]
        return out
