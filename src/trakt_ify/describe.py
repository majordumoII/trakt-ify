"""Name and describe clusters with Claude, from evidence we compute.

The model sees, per cluster: size, era, genre mix, your average rating, the
best-connected films, and what the cluster points toward (its top unwatched
picks). It names all clusters in one request so the names stay distinct.
Results are cached in `cluster_labels`, matched back to clusters by member
overlap, so re-running Louvain doesn't lose them.
"""

from __future__ import annotations

import json

import anthropic
from pydantic import BaseModel

from .models import ClusterProfile, GraphPayload
from .store import Store

MODEL = "claude-opus-5-5"

SYSTEM = """You name and describe clusters in one person's film-watching history.

How the clusters were made: each film is linked to others when their Trakt \
"people who watched this also watched" lists overlap, then communities were \
detected. So a cluster reflects shared audiences, which often but not always \
lines up with genre. It may be defined by tone, era, a franchise, a star, a \
director's orbit, or a type of night in.

For each cluster write:
- label: 2 to 5 words, plain and specific, the way a friend would name this \
shelf of their collection. Every label must be clearly distinct from the others. \
Avoid vague words like "eclectic", "mixed", "assorted", "various".
- summary: one or two sentences on what binds these films and what the cluster \
says about this viewer's taste. Ground it in the evidence given; don't invent \
facts about specific films.
- themes: three or four short lowercase tags (one to three words each).

Return every cluster id you were given, exactly once."""


class ClusterDescription(BaseModel):
    id: int
    label: str
    summary: str
    themes: list[str]


class Descriptions(BaseModel):
    clusters: list[ClusterDescription]


SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "label": {"type": "string"},
                    "summary": {"type": "string"},
                    "themes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "label", "summary", "themes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clusters"],
    "additionalProperties": False,
}


def _evidence(cluster: ClusterProfile, payload: GraphPayload) -> dict:
    nodes = {n.id: n for n in payload.nodes}
    members = sorted(
        (n for n in payload.nodes if n.community == cluster.id), key=lambda n: -n.degree
    )
    return {
        "id": cluster.id,
        "size": cluster.size,
        "era_middle_half": [cluster.era_start, cluster.era_end],
        "genre_shares": {g.name: g.share for g in cluster.genres},
        "viewer_avg_rating_out_of_10": cluster.avg_user_rating,
        "best_connected_films": [
            f"{n.label} ({n.year}) [{', '.join(n.genres[:3])}]" for n in members[:25]
        ],
        "points_toward_unwatched": [
            f"{r.title} ({r.year})" for r in cluster.recommendations[:8]
        ],
        "anchor_ids_for_reference": [nodes[a].label for a in cluster.anchors if a in nodes],
    }


def describe_clusters(store: Store, payload: GraphPayload, *, quiet: bool = False) -> int:
    clusters = [c for c in payload.clusters if c.size >= 3]
    evidence = [_evidence(c, payload) for c in clusters]
    if not quiet:
        print(f"Asking {MODEL} to describe {len(clusters)} clusters ...")

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(evidence, indent=1)}],
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError("ANTHROPIC_API_KEY was rejected. Check the key, or run `ant auth login`.") from exc
    except anthropic.BadRequestError as exc:
        raise RuntimeError(f"Claude API refused the request: {exc.message}") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError("Claude API rate limit hit; try again in a minute.") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError("Couldn't reach the Claude API. Check your connection.") from exc

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model declined to describe clusters (request {response._request_id})")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Cluster descriptions were cut off at max_tokens")

    text = next(b.text for b in response.content if b.type == "text")
    result = Descriptions.model_validate_json(text)

    members = {
        c.id: [n.id for n in payload.nodes if n.community == c.id] for c in clusters
    }
    written = 0
    for desc in result.clusters:
        if desc.id not in members:
            continue
        store.add_cluster_label(
            members[desc.id], desc.label.strip(), desc.summary.strip(),
            [t.strip().lower() for t in desc.themes][:4], response.model,
        )
        written += 1
    return written
