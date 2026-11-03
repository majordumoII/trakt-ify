"""Pairwise co-occurrence over Trakt's "related" sets, then community detection.

Trakt's /related endpoint is unweighted: it returns up to 45 titles with no
frequency or popularity signal. So edge weight here is OUR derivation, not
Trakt's. For each pair of watched movies (A, B) we score how much their
related-sets overlap:

    Jaccard(A, B) = |R'(A) n R'(B)| / |R'(A) u R'(B)|,  R'(X) = R(X) + {X}

Both directions are considered, so an edge appears if A is in B's related set
*or* B is in A's related set *or* they merely share related titles. That last
case is the useful one: it surfaces "these two keep company" even when neither
is listed as related to the other.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

import networkx as nx

import json

from .models import GraphEdge, GraphMeta, GraphNode, GraphPayload


@dataclass(frozen=True)
class GraphConfig:
    """Tuning knobs for graph construction."""

    min_weight: float = 0.05
    """Drop edges below this Jaccard score. The main anti-hairball control."""
    min_shared: int = 1
    """Require at least this many titles in the intersection."""
    top_k: int = 12
    """Max edges retained per node, by weight. Caps hub blowout."""
    resolution: float = 1.0
    """Louvain resolution: higher yields more, smaller communities."""
    drop_isolated: bool = True
    """Remove nodes with no surviving edges, which cannot be drawn usefully."""


def build_graph(
    related: dict[int, set[int]],
    watched: dict[int, dict],
    username: str,
    config: GraphConfig | None = None,
) -> GraphPayload:
    """Turn raw related-sets into a layout-ready graph payload."""
    config = config or GraphConfig()

    # Nodes are watched titles only, but each node is described by its FULL
    # related-set (catalog-wide). Both endpoints of every edge are watched, so
    # both sets are known and the Jaccard denominator is real. Intersecting the
    # sets with the library first would discard ~73% of the signal (the density
    # probe measured only ~27% of a related-set landing in the library).
    watched_ids = set(watched)
    # Each title joins its own set, R'(A) = R(A) + {A}, so a direct listing
    # (B in R(A)) counts as overlap while Jaccard stays within [0, 1].
    features: dict[int, set[int]] = {
        source: targets | {source}
        for source, targets in related.items()
        if source in watched_ids
    }

    # Candidate pairs: any two watched titles whose R' sets intersect (this
    # includes direct listings, since each title is in its own set). An
    # inverted index keeps this to pairs with non-zero overlap, not all n^2.
    holders: dict[int, list[int]] = defaultdict(list)
    for source, targets in features.items():
        for target in targets:
            holders[target].append(source)

    candidate_pairs: set[tuple[int, int]] = set()
    for sources in holders.values():
        ordered = sorted(sources)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                candidate_pairs.add((a, b))

    scored: list[tuple[int, int, float, int]] = []
    for a, b in candidate_pairs:
        set_a = features.get(a, set())
        set_b = features.get(b, set())
        union = len(set_a | set_b)
        if union == 0:
            continue
        shared = len(set_a & set_b)
        if shared < config.min_shared:
            continue
        weight = shared / union
        if weight < config.min_weight:
            continue
        scored.append((a, b, weight, shared))

    # Keep each node's strongest top_k edges, then deduplicate.
    by_node: dict[int, list[tuple[int, int, float, int]]] = defaultdict(list)
    for edge in scored:
        by_node[edge[0]].append(edge)
        by_node[edge[1]].append(edge)

    retained: dict[tuple[int, int], tuple[float, int]] = {}
    for edges in by_node.values():
        for a, b, weight, shared in sorted(edges, key=lambda e: -e[2])[: config.top_k]:
            key = (a, b)
            if key not in retained or retained[key][0] < weight:
                retained[key] = (weight, shared)

    graph = nx.Graph()
    graph.add_nodes_from(watched_ids)
    for (a, b), (weight, _shared) in retained.items():
        graph.add_edge(a, b, weight=weight)

    if config.drop_isolated:
        graph.remove_nodes_from([n for n, d in graph.degree() if d == 0])

    communities: dict[int, int] = {}
    community_count = 0
    if graph.number_of_edges() > 0:
        detected = nx.community.louvain_communities(
            graph, weight="weight", resolution=config.resolution, seed=42
        )
        # Rank communities by size so index 0 is the largest, giving the
        # frontend a stable palette ordering.
        ordered = sorted(detected, key=len, reverse=True)
        for index, members in enumerate(ordered):
            for node in members:
                communities[node] = index
        community_count = len(ordered)

    nodes: list[GraphNode] = []
    for node_id in graph.nodes():
        row = watched.get(node_id, {})
        last_watched = row.get("last_watched_at")
        nodes.append(
            GraphNode(
                id=node_id,
                label=row.get("title") or str(node_id),
                year=row.get("year"),
                slug=row.get("slug"),
                imdb=row.get("imdb"),
                tmdb=row.get("tmdb"),
                degree=graph.degree(node_id),
                community=communities.get(node_id),
                plays=row.get("plays") or 0,
                last_watched_at=last_watched,
                genres=_genres(row.get("genres")),
                user_rating=row.get("user_rating"),
            )
        )

    edges = [
        GraphEdge(source=a, target=b, weight=round(weight, 4), shared=shared)
        for (a, b), (weight, shared) in retained.items()
        if graph.has_node(a) and graph.has_node(b)
    ]

    return GraphPayload(
        meta=GraphMeta(
            username=username,
            generated_at=datetime.now(timezone.utc),
            movie_count=len(watched),
            node_count=graph.number_of_nodes(),
            edge_count=graph.number_of_edges(),
            community_count=community_count,
            min_weight=config.min_weight,
            top_k=config.top_k,
        ),
        nodes=nodes,
        edges=edges,
    )


def _genres(raw: str | list | None) -> list[str]:
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw) if raw else []
    except ValueError:
        return []
