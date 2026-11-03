"""Empirical probe: does Trakt's /related data actually support a graph?

Motivation: /related returns 45 titles drawn from Trakt's whole catalog, not
from the user's library. Restricting to the induced subgraph over watched
titles may therefore leave almost no edges. This measures that directly before
we commit to a graph design.

Run: uv run python scripts/density_probe.py --sample 200
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
from collections import Counter

import networkx as nx

from trakt_ify.client import TraktClient
from trakt_ify.config import Settings


async def probe(sample_size: int, concurrency: int) -> None:
    settings = Settings.from_env()

    async with TraktClient(settings.client_id, concurrency=concurrency) as client:
        print("Fetching full watched history ...")
        watched: dict[int, dict] = {}
        async for entry in client.watched_movies(settings.username):
            movie = entry.movie
            watched[movie.ids.trakt] = {
                "title": movie.title,
                "year": movie.year,
                "last_watched_at": entry.last_watched_at,
            }
        print(f"  {len(watched)} watched titles\n")

        # Stride-sample across the whole history so we get popular and obscure
        # titles, not just the most recent ones.
        ordered = sorted(watched, key=lambda i: watched[i]["last_watched_at"] or "")
        stride = max(1, len(ordered) // sample_size)
        sampled = ordered[::stride][:sample_size]
        print(f"Fetching /related for {len(sampled)} sampled titles ...")

        sem = asyncio.Semaphore(concurrency)

        async def fetch(trakt_id: int) -> tuple[int, set[int]]:
            async with sem:
                movies = await client.related_movies(trakt_id)
                return trakt_id, {m.ids.trakt for m in movies}

        results = await asyncio.gather(*(fetch(i) for i in sampled))
        related: dict[int, set[int]] = dict(results)

        sizes = [len(v) for v in related.values()]
        print(
            f"  related-set size: min={min(sizes)} median={statistics.median(sizes):.0f} "
            f"max={max(sizes)}\n"
        )

        watched_ids = set(watched)

        # How much of each related-set lands inside the watched library?
        in_library = [len(v & watched_ids) for v in related.values()]
        nonzero = sum(1 for n in in_library if n > 0)
        print("Overlap of related-sets with the watched library")
        print(f"  mean in-library per set:   {statistics.mean(in_library):.2f}")
        print(f"  median:                    {statistics.median(in_library):.0f}")
        print(f"  max:                       {max(in_library)}")
        print(f"  sets with >=1 in-library:  {nonzero}/{len(related)} "
              f"({100 * nonzero / len(related):.0f}%)")
        print(f"  as % of a 45-item set:     "
              f"{100 * statistics.mean(in_library) / statistics.median(sizes):.1f}%\n")

        # ---- Option A: induced subgraph over watched titles -----------------
        sample_ids = set(related)
        filtered = {s: (t & sample_ids) for s, t in related.items()}
        g_a = nx.Graph()
        g_a.add_nodes_from(sample_ids)
        edges_a = 0
        for source, targets in filtered.items():
            for target in targets:
                if source != target and not g_a.has_edge(source, target):
                    g_a.add_edge(source, target)
                    edges_a += 1

        isolated = sum(1 for n in g_a.nodes() if g_a.degree(n) == 0)
        comps = list(nx.connected_components(g_a)) if edges_a else []
        big = max((len(c) for c in comps), default=0)

        print("Option A - induced subgraph over watched titles only")
        print(f"  nodes:        {g_a.number_of_nodes()}")
        print(f"  edges:        {edges_a}")
        print(f"  isolated:     {isolated} ({100 * isolated / max(1, g_a.number_of_nodes()):.0f}%)")
        print(f"  components:   {len(comps)}")
        print(f"  largest:      {big} nodes")

        # Jaccard distribution — the weights we would actually draw.
        weights: list[float] = []
        sources = [s for s in sample_ids]
        for i, a in enumerate(sources):
            for b in sources[i + 1:]:
                set_a, set_b = related[a], related[b]
                shared = len(set_a & set_b)
                if shared:
                    union = len(set_a | set_b)
                    weights.append(shared / union)
        if weights:
            weights.sort()
            print(f"  pairwise Jaccard: n={len(weights)} "
                  f"median={weights[len(weights) // 2]:.4f} "
                  f"p90={weights[int(len(weights) * 0.9)]:.4f} "
                  f"max={weights[-1]:.4f}")
            print(f"  pairs above 0.05: {sum(1 for w in weights if w >= 0.05)}")
        else:
            print("  pairwise Jaccard: no shared titles at all")
        print()

        # ---- Option B: include unwatched related titles as nodes ------------
        g_b = nx.Graph()
        g_b.add_nodes_from(sample_ids)
        for source, targets in related.items():
            for target in targets:
                g_b.add_edge(source, target)

        in_lib = [n for n in g_b.nodes() if n in watched_ids]
        print("Option B - expand to include unwatched related titles")
        print(f"  nodes:        {g_b.number_of_nodes()} "
              f"({len(in_lib)} watched, {g_b.number_of_nodes() - len(in_lib)} external)")
        print(f"  edges:        {g_b.number_of_edges()}")
        degree = Counter(dict(g_b.degree()))
        print(f"  mean degree:  {statistics.mean(degree.values()):.1f}")
        print(f"  components:   {len(list(nx.connected_components(g_b)))}")

        # Which titles act as bridges between sampled library titles? These are
        # the nodes that would carry the "you also watched" signal.
        external = g_b.nodes() - sample_ids
        bridges = []
        for node in external:
            neighbours = set(g_b.neighbors(node)) & sample_ids
            if len(neighbours) >= 2:
                bridges.append((len(neighbours), node, sorted(neighbours)[:4]))
        bridges.sort(reverse=True)
        print(f"  bridge nodes (>=2 watched neighbours): {len(bridges)}")
        for count, node, examples in bridges[:8]:
            label = watched.get(node, {}).get("title", f"id:{node}")
            print(f"    {count:3}x  {label[:36]}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    asyncio.run(probe(args.sample, args.concurrency))


if __name__ == "__main__":
    main()
