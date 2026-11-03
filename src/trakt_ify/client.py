"""Async, rate-limited Trakt API client.

Trakt permits 1000 GETs per 5 minutes, keyed on client ID + IP for
unauthenticated calls, and returns 429 with a Retry-After header when exceeded.
We stay under that with a sliding-window limiter and back off hard on 429 so a
long ingest doesn't get the client ID throttled.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from typing import Any, AsyncIterator

import httpx

from .models import Movie, RatedMovie, WatchedMovie, WatchlistMovie

BASE_URL = "https://api.trakt.tv"
API_VERSION = "2"

APP_NAME = "trakt-ify"
APP_VERSION = "0.1.0"

# Trakt asks integrations to identify themselves via User-Agent. Keep the
# default free of any personal account so forks don't advertise the original
# author; set TRAKT_IFY_USER_AGENT to identify your own deployment.
USER_AGENT = os.environ.get(
    "TRAKT_IFY_USER_AGENT", f"{APP_NAME}/{APP_VERSION} (trakt client)"
)


class RateLimiter:
    """Sliding-window limiter: at most `max_calls` starts per `period` seconds."""

    def __init__(self, max_calls: int, period: float) -> None:
        self._max_calls = max_calls
        self._period = period
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._blocked_until = 0.0

    def block_for(self, seconds: float) -> None:
        """Apply a global pause, e.g. after a 429."""
        self._blocked_until = max(self._blocked_until, time.monotonic() + seconds)

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                if self._blocked_until > now:
                    wait = self._blocked_until - now
                else:
                    while self._calls and now - self._calls[0] >= self._period:
                        self._calls.popleft()
                    if len(self._calls) < self._max_calls:
                        self._calls.append(now)
                        return
                    wait = self._period - (now - self._calls[0])
            await asyncio.sleep(max(wait, 0.01))


class TraktClient:
    def __init__(
        self,
        client_id: str,
        *,
        max_calls: int = 900,
        period: float = 300.0,
        concurrency: int = 8,
        max_retries: int = 5,
        timeout: float = 30.0,
    ) -> None:
        self._headers = {
            "Content-Type": "application/json",
            "trakt-api-key": client_id,
            "trakt-api-version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        self._limiter = RateLimiter(max_calls, period)
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            headers=self._headers, timeout=httpx.Timeout(timeout)
        )

    async def __aenter__(self) -> "TraktClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        url = f"{BASE_URL}{path}"
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            await self._limiter.acquire()
            try:
                async with self._semaphore:
                    response = await self._client.get(url, params=params)
            except httpx.RequestError as exc:
                last_error = exc
                await asyncio.sleep(min(2**attempt, 30))
                continue

            if response.status_code == 429:
                retry_after = float(response.headers.get("retry-after", 5))
                self._limiter.block_for(retry_after + 1.0)
                await asyncio.sleep(retry_after + 1.0)
                last_error = RuntimeError("rate limited")
                continue

            if response.status_code >= 500:
                last_error = RuntimeError(f"{response.status_code} from {path}")
                await asyncio.sleep(min(2**attempt, 30))
                continue

            response.raise_for_status()
            return response

        raise RuntimeError(f"GET {path} failed after {self._max_retries} attempts") from last_error

    async def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, page_size: int = 100
    ) -> AsyncIterator[list[Any]]:
        """Yield successive pages, driven by Trakt's pagination headers."""
        page = 1
        while True:
            query = dict(params or {})
            query["page"] = page
            query["limit"] = page_size

            response = await self.get(path, query)
            payload = response.json()

            total_pages = int(response.headers.get("x-pagination-page-count", "1"))
            if payload:
                yield payload
            if page >= total_pages:
                return
            page += 1

    async def watched_movies(
        self, username: str, *, extended: bool = False
    ) -> AsyncIterator[WatchedMovie]:
        path = f"/users/{username}/watched/movies"
        params = {"extended": "full"} if extended else None
        async for page in self.paginate(path, params):
            for item in page:
                yield WatchedMovie.model_validate(item)

    async def related_movies(self, trakt_id: int) -> list[Movie]:
        response = await self.get(f"/movies/{trakt_id}/related")
        return [Movie.model_validate(item) for item in response.json()]

    async def movie(self, trakt_id: int) -> Movie:
        response = await self.get(f"/movies/{trakt_id}", {"extended": "full"})
        return Movie.model_validate(response.json())

    async def ratings(self, username: str) -> list[RatedMovie]:
        response = await self.get(f"/users/{username}/ratings/movies")
        return [RatedMovie.model_validate(item) for item in response.json()]

    async def watchlist(self, username: str) -> list[WatchlistMovie]:
        out: list[WatchlistMovie] = []
        async for page in self.paginate(f"/users/{username}/watchlist/movies"):
            out.extend(WatchlistMovie.model_validate(item) for item in page)
        return out
