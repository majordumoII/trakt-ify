# trakt-ify

An interactive map of a Trakt movie history. Each watched film is a node. Two
films are linked when their Trakt "people who watched this also watched" lists
overlap, and clusters of films that keep company are coloured together.

## How the graph is built

1. **Ingest** (`trakt-ify ingest`) pulls `/users/{user}/watched/movies` and then
   `/movies/{id}/related` for every watched title into SQLite (`data/trakt.db`).
   Ingest is rate-limited to stay under Trakt's 1000 requests / 5 min, and it
   can resume: titles that are already fetched are skipped unless `--refresh`.
2. **Graph** (`graph.py`) scores every pair of watched films by Jaccard overlap
   of their *full* related-sets, with each film counted in its own set:
   `J(A,B) = |R'(A) ∩ R'(B)| / |R'(A) ∪ R'(B)|`, where `R'(X) = R(X) ∪ {X}`.
   Trakt's `/related` has no weights, so this overlap is our own derivation.
   Edges below `min_weight` are dropped, each node keeps its `top_k` strongest,
   and Louvain finds the communities (index 0 = largest).
3. **Insight** (`insights.py`, `describe.py`, `evaluate.py`):
   - Each cluster gets a profile: genre mix, era, defining films, your average
     rating. `trakt-ify describe` sends that evidence to Claude, which names
     and summarises every cluster in one pass so the names stay distinct.
     Names are cached and matched back to clusters by member overlap.
   - Recommendations are unwatched films ranked by how many of your films list
     them as related (films you rated 8+ count double, 5 or lower count a
     quarter), filtered by Trakt community rating, and filed under the cluster
     holding most of the films that point to them. Those films are the "why".
   - `trakt-ify evaluate` hides 20% of your history at a time and checks how
     often picks were films you had actually watched. That hit rate, by
     support level, is the confidence shown on each pick. It's a lower bound
     on "you'd like it", since unlogged films count as misses. The same test
     showed ranking *within* clusters did worse than whole-library support,
     so clusters explain picks rather than rank them.
4. **API** (`trakt-ify serve`, FastAPI) serves `/api/graph`, `/api/ego/{id}`,
   `/api/search` and `/api/hubs`, plus the built frontend from `web/dist`.
5. **Frontend** (`web/`, Svelte 5 + D3 on canvas) shows a force-directed map
   with focus + context. Picking a film lights up its neighbourhood, picking a
   cluster lights up its members, and labels appear with zoom.

The pydantic models in `models.py` are the contract. `npm run types` (in
`web/`) regenerates `web/src/lib/graph.ts` from them.

## Setup

```sh
cp .env.example .env          # set TRAKT_CLIENT_ID and TRAKT_USERNAME
uv sync
uv run trakt-ify ingest       # ~11 min for ~1900 films at the rate limit
uv run trakt-ify enrich       # genres, your ratings + watchlist, candidate details
uv run trakt-ify evaluate     # hold-out test; sets each pick's confidence
uv run trakt-ify describe     # cluster names via Claude (needs ANTHROPIC_API_KEY)
uv run trakt-ify stats
```

## Run

Development (two terminals):

```sh
uv run trakt-ify serve --reload        # API on :8000
cd web && npm install && npm run dev   # app on :5173, proxies /api
```

Single process:

```sh
cd web && npm run build && cd ..
uv run trakt-ify serve                 # http://127.0.0.1:8000
```

## Tests

```sh
uv run pytest
cd web && npm run check
```

## Later

- Re-run `describe` automatically when clusters drift
- Co-occurrence computed from many users' public histories instead of Trakt's
  `/related`
- Personal temporal co-watching (films watched within N days of each other)
- Chord or community-ordered matrix view for dense clusters
