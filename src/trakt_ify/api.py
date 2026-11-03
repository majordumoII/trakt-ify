"""FastAPI app serving the computed graph and, in a built deployment, the SPA."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import PROJECT_ROOT, Settings
from .assemble import assemble
from .graph import GraphConfig
from .store import Store

app = FastAPI(title="trakt-ify graph API", version="0.1.0")

# The Vite dev server runs on a different origin; allow it during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

WEB_DIST = PROJECT_ROOT / "web" / "dist"


def _settings() -> Settings:
    return Settings.from_env()


def _db_version(settings: Settings) -> float:
    """Changes whenever ingest writes, so cached graphs never go stale."""
    paths = [settings.db_path, settings.db_path.with_name(settings.db_path.name + "-wal")]
    return max((p.stat().st_mtime for p in paths if p.exists()), default=0.0)


def _load_graph(
    min_weight: float, top_k: int, min_shared: int, drop_isolated: bool
) -> dict:
    return _build_graph_cached(
        min_weight, top_k, min_shared, drop_isolated, _db_version(_settings())
    )


@lru_cache(maxsize=8)
def _build_graph_cached(
    min_weight: float, top_k: int, min_shared: int, drop_isolated: bool, _version: float
) -> dict:
    """Build the graph payload. Cached per parameter set and DB version."""
    settings = _settings()
    config = GraphConfig(
        min_weight=min_weight,
        top_k=top_k,
        min_shared=min_shared,
        drop_isolated=drop_isolated,
    )
    with Store(settings.db_path) as store:
        store.init_schema()
        counts = store.counts()
        if counts["watched"] == 0:
            raise HTTPException(
                status_code=409,
                detail="No data ingested yet. Run: uv run trakt-ify ingest",
            )
        payload = assemble(store, settings.username, config)
    return json.loads(payload.model_dump_json(by_alias=True))


@app.get("/api/health")
def health() -> dict:
    settings = _settings()
    try:
        with Store(settings.db_path) as store:
            store.init_schema()
            counts = store.counts()
        return {"ok": True, "username": settings.username, "counts": counts}
    except Exception as exc:
        return JSONResponse(
            status_code=503, content={"ok": False, "error": str(exc)}
        )


@app.get("/api/graph")
def graph(
    min_weight: float = Query(0.05, ge=0.0, le=1.0),
    top_k: int = Query(12, ge=1, le=50),
    min_shared: int = Query(1, ge=1, le=20),
    drop_isolated: bool = Query(True),
) -> dict:
    return _load_graph(min_weight, top_k, min_shared, drop_isolated)


@app.get("/api/ego/{trakt_id}")
def ego(
    trakt_id: int,
    depth: int = Query(1, ge=1, le=3),
    min_weight: float = Query(0.05, ge=0.0, le=1.0),
    top_k: int = Query(12, ge=1, le=50),
) -> dict:
    """Subgraph around one title, with an optional suggestion ring beyond it."""
    payload = _load_graph(min_weight, top_k, 1, True)
    nodes = {n["id"]: n for n in payload["nodes"]}
    if trakt_id not in nodes:
        raise HTTPException(status_code=404, detail=f"Title {trakt_id} not in graph")

    adjacency: dict[int, set[int]] = {}
    for edge in payload["edges"]:
        adjacency.setdefault(edge["source"], set()).add(edge["target"])
        adjacency.setdefault(edge["target"], set()).add(edge["source"])

    # BFS out to `depth` hops.
    selected = {trakt_id}
    frontier = {trakt_id}
    for _ in range(depth):
        nxt: set[int] = set()
        for node in frontier:
            nxt |= adjacency.get(node, set())
        frontier = nxt - selected
        selected |= frontier

    selected_edges = [
        e
        for e in payload["edges"]
        if e["source"] in selected and e["target"] in selected
    ]
    return {
        "meta": {**payload["meta"], "focus": trakt_id, "depth": depth},
        "nodes": [nodes[i] for i in sorted(selected)],
        "edges": selected_edges,
    }


@app.get("/api/search")
def search(q: str = Query("", min_length=0)) -> dict:
    """Label search over graph nodes, for the focus picker."""
    payload = _load_graph(0.05, 12, 1, True)
    query = q.strip().lower()
    matches = [
        {"id": n["id"], "label": n["label"], "year": n["year"], "degree": n["degree"]}
        for n in payload["nodes"]
        if query in n["label"].lower()
    ]
    matches.sort(key=lambda m: (-m["degree"], m["label"]))
    return {"query": q, "results": matches[:25]}


@app.get("/api/hubs")
def hubs(limit: int = Query(25, ge=1, le=200)) -> dict:
    """Highest-degree titles, useful as starting points and as a sanity check."""
    payload = _load_graph(0.05, 12, 1, True)
    ranked = sorted(payload["nodes"], key=lambda n: -n["degree"])[:limit]
    return {
        "hubs": [
            {
                "id": n["id"],
                "label": n["label"],
                "year": n["year"],
                "degree": n["degree"],
                "community": n["community"],
            }
            for n in ranked
        ]
    }


@app.get("/api/schema")
def schema() -> dict:
    from .models import GraphPayload

    return GraphPayload.model_json_schema(by_alias=True)


def _mount_spa() -> None:
    """Serve the built frontend when it exists, so one process serves both."""
    if not WEB_DIST.is_dir():
        return

    index = WEB_DIST / "index.html"

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(index)

    @app.get("/{path:path}")
    def static(path: str) -> FileResponse:
        candidate = (WEB_DIST / path).resolve()
        if candidate.is_file() and WEB_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


_mount_spa()
