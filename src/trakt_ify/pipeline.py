"""Ingestion orchestration: watched history -> related-sets -> SQLite."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .client import TraktClient
from .config import Settings
from .store import Store


@dataclass
class IngestStats:
    watched: int = 0
    fetched: int = 0
    related_rows: int = 0
    skipped: int = 0
    failed: list[int] | None = None


class Progress:
    """Single-line progress reporter that degrades to plain lines."""

    def __init__(self, total: int, *, enabled: bool = True) -> None:
        self.total = total
        self.enabled = enabled
        self.done = 0

    def tick(self, extra: str = "") -> None:
        self.done += 1
        if not self.enabled or self.total == 0:
            return
        pct = self.done / self.total
        width = 28
        filled = int(width * pct)
        bar = "#" * filled + "-" * (width - filled)
        print(f"\r  [{bar}] {self.done}/{self.total} {extra:<24}", end="", flush=True)

    def finish(self) -> None:
        if self.enabled:
            print()


async def ingest(
    settings: Settings,
    *,
    store: Store,
    refresh: bool = False,
    workers: int = 8,
    quiet: bool = False,
) -> IngestStats:
    """Pull watched history and related-sets into SQLite.

    Resumable: titles already in `related_fetch` are skipped unless `refresh`.
    """
    stats = IngestStats(failed=[])

    async with TraktClient(settings.client_id, concurrency=workers) as client:
        if not quiet:
            print(f"Fetching watched history for {settings.username} ...")

        watched_batch: list = []
        async for entry in client.watched_movies(settings.username):
            watched_batch.append(entry)
            # Flush in chunks so a long ingest checkpoints as it goes.
            if len(watched_batch) >= 200:
                store.upsert_movies(e.movie for e in watched_batch)
                store.upsert_watched(watched_batch)
                watched_batch = []

        if watched_batch:
            store.upsert_movies(e.movie for e in watched_batch)
            store.upsert_watched(watched_batch)

        stats.watched = len(store.watched_ids())
        if not quiet:
            print(f"  {stats.watched} watched titles stored.")

        pending = store.pending_related_ids(refresh=refresh)
        stats.skipped = stats.watched - len(pending)

        if not pending:
            if not quiet:
                print("  Related-sets already complete; nothing to fetch.")
            return stats

        if not quiet:
            minutes = len(pending) / 900 * 5
            print(
                f"Fetching related-sets for {len(pending)} titles "
                f"(~{minutes:.0f} min at Trakt's rate limit) ..."
            )

        progress = Progress(len(pending), enabled=not quiet)
        lock = asyncio.Lock()

        async def fetch_one(trakt_id: int, retry: int = 0) -> None:
            try:
                movies = await client.related_movies(trakt_id)
            except Exception as exc:  # keep going; report at the end
                if retry < 3:
                    await asyncio.sleep(2.0 * (retry + 1))
                    await fetch_one(trakt_id, retry + 1)
                    return
                async with lock:
                    stats.failed.append(trakt_id)
                    progress.tick(f"FAILED {trakt_id}: {type(exc).__name__}")
                return

            target_ids = [m.ids.trakt for m in movies]
            async with lock:
                store.upsert_movies(movies)
                rows = store.replace_related(trakt_id, target_ids)
                stats.fetched += 1
                stats.related_rows += rows
                progress.tick(f"edges+{rows}")

        # A bounded worker pool; the client's own limiter handles pacing.
        queue: asyncio.Queue[int] = asyncio.Queue()
        for trakt_id in pending:
            queue.put_nowait(trakt_id)

        async def worker() -> None:
            while True:
                try:
                    trakt_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await fetch_one(trakt_id)
                finally:
                    queue.task_done()

        await asyncio.gather(*(worker() for _ in range(workers)))
        progress.finish()

    store.set_meta("last_ingest", str(stats.watched))
    return stats


@dataclass
class EnrichStats:
    watched_meta: int = 0
    ratings: int = 0
    watchlist: int = 0
    candidates_fetched: int = 0
    candidates_failed: int = 0


async def enrich(
    settings: Settings,
    *,
    store: Store,
    per_cluster: int = 40,
    workers: int = 8,
    quiet: bool = False,
) -> EnrichStats:
    """Fetch what turns the graph into insight: genres and ratings for watched
    films, your own ratings and watchlist, and metadata for the strongest
    recommendation candidates in each cluster (so they can be quality-checked
    and shown with a poster and synopsis)."""
    from .assemble import assemble
    from .insights import build_profiles

    stats = EnrichStats()
    async with TraktClient(settings.client_id, concurrency=workers) as client:
        if not quiet:
            print("Fetching genres and ratings for watched films ...")
        batch = []
        async for entry in client.watched_movies(settings.username, extended=True):
            batch.append(entry.movie)
        stats.watched_meta = store.upsert_movie_meta(batch)

        stats.ratings = store.replace_ratings(await client.ratings(settings.username))
        watchlist = await client.watchlist(settings.username)
        stats.watchlist = store.replace_watchlist(watchlist)
        store.upsert_movies(e.movie for e in watchlist)
        if not quiet:
            print(f"  {stats.watched_meta} films, {stats.ratings} ratings, "
                  f"{stats.watchlist} on watchlist.")

        # Rank candidates with the default graph, then fetch the top of each
        # cluster's list. Over-fetch, since some will fail the quality bar.
        payload = assemble(store, settings.username)
        watched_rows = {k: dict(v) for k, v in store.watched_nodes().items()}
        _, ranked = build_profiles(
            payload,
            related=store.related_for_watched(),
            watched_rows=watched_rows,
            movie_rows={},
            user_ratings=store.user_ratings(),
            watchlist=set(),
            stored_labels=[],
        )
        taken: dict[int | None, int] = {}
        wanted = []
        for cand in ranked:
            if taken.get(cand.cluster, 0) < per_cluster:
                taken[cand.cluster] = taken.get(cand.cluster, 0) + 1
                wanted.append(cand.id)
        missing = store.missing_meta(wanted)
        if not quiet:
            print(f"Fetching details for {len(missing)} recommendation candidates ...")

        progress = Progress(len(missing), enabled=not quiet)
        sem = asyncio.Semaphore(workers)

        async def fetch(trakt_id: int) -> None:
            async with sem:
                try:
                    movie = await client.movie(trakt_id)
                except Exception:
                    stats.candidates_failed += 1
                    progress.tick("failed")
                    return
            store.upsert_movie_meta([movie])
            stats.candidates_fetched += 1
            progress.tick()

        await asyncio.gather(*(fetch(i) for i in missing))
        progress.finish()

    return stats
