"""trakt-ify: a Trakt watch-graph explorer.

Pipeline: ingest your Trakt history -> derive pairwise co-occurrence over
Trakt's "related" sets -> export a graph contract the frontend renders.
"""

from __future__ import annotations


def main() -> int:
    from .cli import main as cli_main

    return cli_main()


__all__ = ["main"]
