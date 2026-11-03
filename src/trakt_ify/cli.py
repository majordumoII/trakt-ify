"""Command line entry points: ingest, build, serve, schema, stats."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import Settings
from .assemble import assemble
from .graph import GraphConfig
from .pipeline import enrich, ingest
from .store import Store


def _store(settings: Settings) -> Store:
    store = Store(settings.db_path)
    store.init_schema()
    return store


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    with _store(settings) as store:
        stats = asyncio.run(
            ingest(
                settings,
                store=store,
                refresh=args.refresh,
                workers=args.workers,
                quiet=args.quiet,
            )
        )

    print()
    print(f"  watched titles:      {stats.watched}")
    print(f"  related-sets fetched: {stats.fetched}")
    print(f"  edges stored:         {stats.related_rows}")
    if stats.skipped:
        print(f"  skipped (cached):     {stats.skipped}")
    if stats.failed:
        print(f"  failed:               {len(stats.failed)} -> {stats.failed[:10]}")
        print("  (re-run without --refresh to retry only the failures)")
    return 0 if not stats.failed else 1


def cmd_build(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    config = GraphConfig(
        min_weight=args.min_weight, top_k=args.top_k, min_shared=args.min_shared
    )
    with _store(settings) as store:
        counts = store.counts()
        if counts["watched"] == 0:
            print("No data. Run: uv run trakt-ify ingest", file=sys.stderr)
            return 1
        payload = assemble(store, settings.username, config)

    out = Path(args.output) if args.output else settings.graph_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload.model_dump_json(by_alias=True, indent=2))

    meta = payload.meta
    print(f"  movies considered: {meta.movie_count}")
    print(f"  nodes:             {meta.node_count}")
    print(f"  edges:             {meta.edge_count}")
    print(f"  communities:       {meta.community_count}")
    print(f"  written to:        {out}")
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    with _store(settings) as store:
        stats = asyncio.run(
            enrich(settings, store=store, per_cluster=args.per_cluster, quiet=args.quiet)
        )
    print(f"  candidate details fetched: {stats.candidates_fetched}"
          + (f" ({stats.candidates_failed} failed; re-run to retry)" if stats.candidates_failed else ""))
    return 0 if not stats.candidates_failed else 1


def cmd_evaluate(args: argparse.Namespace) -> int:
    from .evaluate import evaluate

    settings = Settings.from_env()
    with _store(settings) as store:
        result = evaluate(store, folds=args.folds, k=args.k)
        store.set_meta("evaluation", result.model_dump_json(by_alias=True))

    print(f"\n  Hiding {result.holdout_share:.0%} of your history at a time:")
    print(f"  top-{result.k} picks that were films you'd watched: {result.top_k_hit_rate:.1%}")
    print(f"  same, ranking within clusters instead:     {result.cluster_local_hit_rate:.1%}")
    print("\n  Confidence by support (your films pointing at a pick, per 1,000):")
    for b in result.calibration:
        print(f"    >= {b.min_per_thousand:5.1f}   {b.hit_rate:6.1%}   (n={b.samples})")
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    from .describe import describe_clusters

    settings = Settings.from_env()
    with _store(settings) as store:
        payload = assemble(store, settings.username)
        written = describe_clusters(store, payload, quiet=args.quiet)
        payload = assemble(store, settings.username)
    print(f"  {written} clusters described.\n")
    for c in payload.clusters:
        print(f"  [{c.id:2}] {c.label}  ({c.size})")
        if c.summary:
            print(f"       {c.summary}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    with _store(settings) as store:
        for key, value in store.counts().items():
            print(f"  {key:18} {value}")

        if args.top:
            from collections import Counter

            related = store.related_for_watched()
            watched_ids = set(store.watched_ids())
            mentions: Counter[int] = Counter()
            for targets in related.values():
                for target in targets & watched_ids:
                    mentions[target] += 1
            nodes = store.watched_nodes()
            print(f"\n  Most co-occurring titles (appear in N related-sets):")
            for trakt_id, count in mentions.most_common(args.top):
                row = nodes.get(trakt_id)
                label = row["title"] if row else str(trakt_id)
                year = row["year"] if row else ""
                print(f"    {count:5}  {label} ({year})")
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    from .models import GraphPayload

    schema = GraphPayload.model_json_schema(by_alias=True)
    text = json.dumps(schema, indent=2)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
        print(f"  JSON Schema written to {out}")
    else:
        print(text)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "trakt_ify.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trakt-ify", description="Trakt watch-graph explorer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="fetch watched history and related-sets")
    p_ingest.add_argument("--refresh", action="store_true", help="re-fetch everything")
    p_ingest.add_argument("--workers", type=int, default=8, help="concurrent fetches")
    p_ingest.add_argument("--quiet", action="store_true")
    p_ingest.set_defaults(func=cmd_ingest)

    p_build = sub.add_parser("build", help="compute the graph and write JSON")
    p_build.add_argument("--min-weight", type=float, default=0.05)
    p_build.add_argument("--top-k", type=int, default=12)
    p_build.add_argument("--min-shared", type=int, default=1)
    p_build.add_argument("--output", type=str, default=None)
    p_build.set_defaults(func=cmd_build)

    p_enrich = sub.add_parser(
        "enrich", help="fetch genres, your ratings and watchlist, and candidate details"
    )
    p_enrich.add_argument("--per-cluster", type=int, default=40)
    p_enrich.add_argument("--quiet", action="store_true")
    p_enrich.set_defaults(func=cmd_enrich)

    p_eval = sub.add_parser("evaluate", help="hold-out test of the recommender")
    p_eval.add_argument("--folds", type=int, default=5)
    p_eval.add_argument("--k", type=int, default=30)
    p_eval.set_defaults(func=cmd_evaluate)

    p_describe = sub.add_parser("describe", help="name and describe clusters with Claude")
    p_describe.add_argument("--quiet", action="store_true")
    p_describe.set_defaults(func=cmd_describe)

    p_stats = sub.add_parser("stats", help="inspect the local database")
    p_stats.add_argument("--top", type=int, default=15)
    p_stats.set_defaults(func=cmd_stats)

    p_schema = sub.add_parser("schema", help="emit the graph JSON Schema")
    p_schema.add_argument("--output", type=str, default=None)
    p_schema.set_defaults(func=cmd_schema)

    p_serve = sub.add_parser("serve", help="run the API (and built frontend)")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
