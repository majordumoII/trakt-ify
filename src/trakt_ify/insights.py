"""Cluster profiles and recommendations.

How recommendations are scored (all of it is shown in the UI):

    support(C) = how many of your watched films list C as related on Trakt,
                 weighted by your own rating of each (loved x2, disliked x0.25)

Candidates are ranked by support, nudged by Trakt's community rating, and each
is filed under the cluster that contributes most of its support. That cluster's
films are the "because" shown with the pick.

Why not rank within clusters? `trakt-ify evaluate` tested it: hiding 20% of
your history, cluster-local scoring (coverage x specificity) found hidden films
less often than plain whole-library support. Clusters explain picks; they
don't improve them. The same test turns support into a calibrated confidence:
the share of titles at that support level that were films you'd watched.
"""

from __future__ import annotations

import json
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .models import CalibrationBucket, ClusterGenre, ClusterProfile, GraphPayload, Recommendation

MIN_SUPPORT = 3
"""A candidate needs at least this many of your films pointing at it."""

MIN_VOTES = 300
MIN_COMMUNITY_RATING = 6.0


def rating_weight(user_rating: int | None) -> float:
    """How much a film's vote counts, from your own 1-10 Trakt rating."""
    if user_rating is None:
        return 1.0
    if user_rating >= 8:
        return 2.0
    if user_rating >= 6:
        return 1.0
    return 0.25


@dataclass
class Candidate:
    id: int
    cluster: int | None
    score: float
    support: int
    weighted_support: float
    cluster_support: int
    because: list[int] = field(default_factory=list)


def score_candidates(
    related: dict[int, set[int]],
    communities: dict[int, int],
    watched: set[int],
    weights: dict[int, float] | None = None,
    *,
    min_support: int = MIN_SUPPORT,
) -> list[Candidate]:
    """Rank unwatched films by (rating-weighted) support across your library.

    `related` holds related-sets for your watched films; `watched` is excluded
    from the results. Pure: no metadata, no I/O.
    """
    weights = weights or {}
    support: Counter[int] = Counter()
    support_w: defaultdict[int, float] = defaultdict(float)
    by_cluster: defaultdict[int, Counter[int | None]] = defaultdict(Counter)
    pointers: defaultdict[int, list[int]] = defaultdict(list)

    for film, targets in related.items():
        if film not in watched:
            continue
        w = weights.get(film, 1.0)
        cluster = communities.get(film)
        for target in targets:
            if target in watched:
                continue
            support[target] += 1
            support_w[target] += w
            by_cluster[target][cluster] += 1
            pointers[target].append(film)

    out: list[Candidate] = []
    for target, n in support.items():
        if n < min_support:
            continue
        clusters = by_cluster[target]
        # File under the real cluster with the most pointers (unclustered
        # films can't host a pick).
        home, home_n = None, 0
        for cluster, count in clusters.items():
            if cluster is not None and count > home_n:
                home, home_n = cluster, count
        because = [f for f in pointers[target] if communities.get(f) == home]
        out.append(
            Candidate(
                id=target,
                cluster=home,
                score=support_w[target],
                support=n,
                weighted_support=support_w[target],
                cluster_support=home_n,
                because=because,
            )
        )
    out.sort(key=lambda c: (-c.score, c.id))
    return out


def confidence_for(support: int, library_size: int, calibration: list[CalibrationBucket]) -> float | None:
    """Look up the measured hit rate for this much support."""
    if not calibration or not library_size:
        return None
    per_thousand = support / library_size * 1000
    edges = [b.min_per_thousand for b in calibration]
    i = bisect_right(edges, per_thousand) - 1
    return calibration[i].hit_rate if i >= 0 else None


def quality_factor(rating: float | None, votes: int | None) -> float | None:
    """Bayesian-shrunk community rating mapped to a mild multiplier.

    Returns None when the film should be dropped as poorly regarded or too
    obscure to judge.
    """
    if rating is None or votes is None:
        return 1.0
    if votes < MIN_VOTES:
        return None
    shrunk = (votes * rating + 1000 * 6.5) / (votes + 1000)
    if shrunk < MIN_COMMUNITY_RATING:
        return None
    return min(1.25, max(0.6, (shrunk - 5.0) / 2.0))


# --------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------


def _genres(raw: str | None) -> list[str]:
    try:
        return json.loads(raw) if raw else []
    except ValueError:
        return []


def distinctive_genres(
    counts: Counter[str], size: int, library_share: dict[str, float], n: int = 2
) -> list[str]:
    """Genres this cluster has much more of than your library overall.

    Scored share x lift, so a genre must be both common here and unusual
    elsewhere; plain "drama" rarely wins.
    """
    scored = []
    for name, count in counts.items():
        share = count / size
        if share < 0.2:
            continue
        lift = share / max(library_share.get(name, 0.0), 1e-3)
        scored.append((share * lift, name))
    return [name for _, name in sorted(scored, reverse=True)[:n]]


def heuristic_label(genres: list[str], era: tuple[int, int] | None) -> str:
    names = [g.replace("-", " ") for g in genres[:2]]
    label = " & ".join(names).capitalize() if names else "Mixed"
    if era:
        start, end = era
        decade = lambda y: f"{y // 10 * 10}s"  # noqa: E731
        label += f", {decade(start)}" if decade(start) == decade(end) else f", {decade(start)}–{decade(end)}"
    return label


def match_label(members: set[int], stored: list[dict]) -> dict | None:
    """Find the stored description whose member set best matches this cluster."""
    best, best_j = None, 0.0
    for entry in stored:
        other = entry["members"]
        j = len(members & other) / len(members | other) if members or other else 0.0
        if j > best_j:
            best, best_j = entry, j
    return best if best_j >= 0.5 else None


def build_profiles(
    payload: GraphPayload,
    *,
    related: dict[int, set[int]],
    watched_rows: dict[int, dict],
    movie_rows: dict[int, dict],
    user_ratings: dict[int, int],
    watchlist: set[int],
    stored_labels: list[dict],
    calibration: list[CalibrationBucket] | None = None,
    per_cluster: int = 12,
) -> tuple[list[ClusterProfile], list[Candidate]]:
    """Describe every cluster and attach its recommendations.

    Also returns the full ranked candidate list, which `enrich` uses to decide
    whose metadata to fetch.
    """
    communities = {n.id: n.community for n in payload.nodes if n.community is not None}
    weights = {i: rating_weight(r) for i, r in user_ratings.items()}
    ranked = score_candidates(related, communities, set(watched_rows), weights)
    degree = {n.id: n.degree for n in payload.nodes}
    library = len(watched_rows)
    library_genres: Counter[str] = Counter()
    for row in watched_rows.values():
        library_genres.update(_genres(row.get("genres")))
    library_share = {g: c / max(1, library) for g, c in library_genres.items()}

    recs_by_cluster: dict[int, list[Recommendation]] = defaultdict(list)
    for cand in ranked:
        if cand.cluster is None or len(recs_by_cluster[cand.cluster]) >= per_cluster:
            continue
        row = movie_rows.get(cand.id)
        if row is None:
            continue
        q = quality_factor(row.get("rating"), row.get("votes"))
        if q is None:
            continue
        recs_by_cluster[cand.cluster].append(
            Recommendation(
                id=cand.id,
                title=row["title"],
                year=row["year"],
                slug=row["slug"],
                poster=row.get("poster"),
                overview=row.get("overview"),
                genres=_genres(row.get("genres")),
                community_rating=round(row["rating"], 1) if row.get("rating") else None,
                votes=row.get("votes"),
                score=round(cand.score * q, 3),
                support=cand.support,
                cluster_support=cand.cluster_support,
                because=sorted(cand.because, key=lambda f: -degree.get(f, 0))[:8],
                on_watchlist=cand.id in watchlist,
                has_metadata=row.get("meta_fetched_at") is not None,
                confidence=confidence_for(cand.support, library, calibration or []),
            )
        )
    for recs in recs_by_cluster.values():
        recs.sort(key=lambda r: -r.score)

    by_cluster: dict[int, list[int]] = defaultdict(list)
    for film, cluster in communities.items():
        by_cluster[cluster].append(film)

    profiles: list[ClusterProfile] = []
    for cluster in sorted(by_cluster):
        films = by_cluster[cluster]
        size = len(films)

        genre_counts: Counter[str] = Counter()
        for f in films:
            genre_counts.update(_genres(watched_rows[f].get("genres")))
        genres = [
            ClusterGenre(name=name, share=round(count / size, 3))
            for name, count in genre_counts.most_common(5)
        ]

        years = sorted(y for f in films if (y := watched_rows[f].get("year")))
        era = None
        if len(years) >= 4:
            q = statistics.quantiles(years, n=4)
            era = (int(q[0]), int(q[2]))
        elif years:
            era = (years[0], years[-1])

        ratings = [user_ratings[f] for f in films if f in user_ratings]
        anchors = sorted(films, key=lambda f: -degree.get(f, 0))[:6]

        recs = recs_by_cluster.get(cluster, [])

        label = match_label(set(films), stored_labels)
        profiles.append(
            ClusterProfile(
                id=cluster,
                size=size,
                label=label["label"]
                if label
                else heuristic_label(
                    distinctive_genres(genre_counts, size, library_share)
                    or [g.name for g in genres], era
                ),
                summary=label["summary"] if label else None,
                themes=label["themes"] if label else [],
                label_source="model" if label else "heuristic",
                genres=genres,
                era_start=era[0] if era else None,
                era_end=era[1] if era else None,
                anchors=anchors,
                rated_count=len(ratings),
                avg_user_rating=round(statistics.mean(ratings), 1) if ratings else None,
                recommendations=recs,
            )
        )
    return profiles, ranked

