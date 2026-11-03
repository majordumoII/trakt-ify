"""Hold-out test: would the recommender have found films you actually watched?

Each fold hides a share of your watched films, rebuilds the graph and clusters
from the rest, and ranks unwatched films. A pick is a hit if it's one of the
hidden films (and you didn't rate it 5 or lower).

That makes the hit rate a *lower bound* on "you'd like it": a film you'd love
but haven't logged on Trakt counts as a miss.

Outputs:
- calibration: hit rate by support level, which becomes each pick's confidence
- top-k hit rate of the shipped ranking
- the same for the rejected cluster-local ranking, kept for transparency

Quality filtering (community rating) is not applied here: it needs metadata
that hidden films always have and unwatched candidates often don't, which would
bias the test.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .graph import GraphConfig, build_graph
from .insights import rating_weight, score_candidates
from .models import CalibrationBucket, Evaluation
from .store import Store

# Support per 1,000 library films; bucket lower edges.
BUCKET_EDGES = [0.0, 2.0, 3.5, 5.0, 7.5, 11.0, 16.0]


def evaluate(
    store: Store,
    *,
    folds: int = 5,
    k: int = 30,
    config: GraphConfig | None = None,
    seed: int = 7,
    quiet: bool = False,
) -> Evaluation:
    related = store.related_for_watched()
    watched_rows = {key: dict(v) for key, v in store.watched_nodes().items()}
    ratings = store.user_ratings()
    weights = {i: rating_weight(r) for i, r in ratings.items()}
    disliked = {i for i, r in ratings.items() if r <= 5}

    films = sorted(watched_rows)
    random.Random(seed).shuffle(films)

    top_hits = top_picks = local_hits = local_picks = 0
    bucket_hits: Counter[int] = Counter()
    bucket_n: Counter[int] = Counter()

    for fold in range(folds):
        hidden = set(films[fold::folds])
        train = set(films) - hidden
        positives = hidden - disliked

        train_related = {s: t for s, t in related.items() if s in train}
        payload = build_graph(train_related, {f: watched_rows[f] for f in train}, "eval", config)
        communities = {n.id: n.community for n in payload.nodes if n.community is not None}
        ranked = score_candidates(train_related, communities, train, weights, min_support=1)

        for cand in ranked:
            per_thousand = cand.support / len(train) * 1000
            bucket = max(i for i, edge in enumerate(BUCKET_EDGES) if per_thousand >= edge)
            bucket_n[bucket] += 1
            bucket_hits[bucket] += cand.id in positives

        for cand in ranked[:k]:
            top_picks += 1
            top_hits += cand.id in positives

        # Rejected alternative: rank inside each cluster by that cluster's
        # share of pointers, take the same number of picks round-robin.
        local: dict[int, list] = defaultdict(list)
        for cand in ranked:
            if cand.cluster is not None and cand.cluster_support >= 3:
                local[cand.cluster].append(cand)
        for cands in local.values():
            cands.sort(key=lambda c: -c.cluster_support / c.support * c.cluster_support)
        chosen = []
        depth = 0
        while len(chosen) < k and any(depth < len(c) for c in local.values()):
            for cands in local.values():
                if depth < len(cands) and len(chosen) < k:
                    chosen.append(cands[depth])
            depth += 1
        local_picks += len(chosen)
        local_hits += sum(c.id in positives for c in chosen)

        if not quiet:
            print(f"  fold {fold + 1}/{folds}: top-{k} hit rate so far "
                  f"{top_hits / max(1, top_picks):.1%}")

    calibration = [
        CalibrationBucket(
            min_per_thousand=BUCKET_EDGES[i],
            hit_rate=round(bucket_hits[i] / bucket_n[i], 4),
            samples=bucket_n[i],
        )
        for i in range(len(BUCKET_EDGES))
        if bucket_n[i]
    ]
    return Evaluation(
        folds=folds,
        holdout_share=round(1 / folds, 3),
        k=k,
        top_k_hit_rate=round(top_hits / max(1, top_picks), 4),
        cluster_local_hit_rate=round(local_hits / max(1, local_picks), 4),
        calibration=calibration,
        tested_at=datetime.now(timezone.utc),
    )
