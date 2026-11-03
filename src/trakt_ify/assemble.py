"""One place that turns the database into the full payload the frontend reads."""

from __future__ import annotations

from .graph import GraphConfig, build_graph
from .insights import build_profiles
from .models import Evaluation, GraphPayload
from .store import Store


def assemble(store: Store, username: str, config: GraphConfig | None = None) -> GraphPayload:
    watched_rows = {k: dict(v) for k, v in store.watched_nodes().items()}
    payload = build_graph(
        related=store.related_for_watched(),
        watched=watched_rows,
        username=username,
        config=config,
    )

    evaluation = None
    if raw := store.get_meta("evaluation"):
        evaluation = Evaluation.model_validate_json(raw)

    related = store.related_for_watched()
    candidate_ids = {t for targets in related.values() for t in targets} - set(watched_rows)
    profiles, _ = build_profiles(
        payload,
        related=related,
        watched_rows=watched_rows,
        movie_rows={k: dict(v) for k, v in store.movie_rows(candidate_ids).items()},
        user_ratings=store.user_ratings(),
        watchlist=store.watchlist_ids(),
        stored_labels=store.cluster_labels(),
        calibration=evaluation.calibration if evaluation else None,
    )
    payload.clusters = profiles
    payload.evaluation = evaluation
    return payload
