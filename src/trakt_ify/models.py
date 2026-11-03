"""Trakt API response models, plus the cross-language graph contract.

The graph models are the seam between the Python pipeline and the frontend.
They are serialised with camelCase aliases so the generated TypeScript types
read naturally; `trakt-ify schema` dumps the JSON Schema for codegen.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# --------------------------------------------------------------------------
# Trakt API
# --------------------------------------------------------------------------


class TraktIds(BaseModel):
    """Trakt's stable external identifiers for a media item."""

    model_config = ConfigDict(extra="ignore")

    trakt: int
    slug: str
    imdb: str | None = None
    tmdb: int | None = None


class Movie(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    year: int | None = None
    ids: TraktIds
    # Present only on `?extended=full` responses.
    genres: list[str] | None = None
    rating: float | None = None
    votes: int | None = None
    overview: str | None = None
    tagline: str | None = None
    runtime: int | None = None
    certification: str | None = None
    language: str | None = None
    released: str | None = None
    images: dict | None = None

    @property
    def is_extended(self) -> bool:
        return self.genres is not None

    @property
    def poster(self) -> str | None:
        posters = (self.images or {}).get("poster") or []
        return f"https://{posters[0]}" if posters else None


class RatedMovie(BaseModel):
    """One row from /users/{id}/ratings/movies."""

    model_config = ConfigDict(extra="ignore")

    rating: int
    rated_at: datetime | None = None
    movie: Movie


class WatchlistMovie(BaseModel):
    model_config = ConfigDict(extra="ignore")

    listed_at: datetime | None = None
    movie: Movie


class WatchedMovie(BaseModel):
    """One row from /users/{id}/watched/movies."""

    model_config = ConfigDict(extra="ignore")

    plays: int = 0
    last_watched_at: datetime | None = None
    movie: Movie


# --------------------------------------------------------------------------
# Graph contract (Python -> TypeScript)
# --------------------------------------------------------------------------


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class GraphNode(CamelModel):
    id: int
    label: str
    year: int | None = None
    slug: str | None = None
    imdb: str | None = None
    tmdb: int | None = None
    """Degree within the pruned graph — drives node size."""
    degree: int = 0
    """Louvain community index, 0 = largest."""
    community: int | None = None
    plays: int = 0
    last_watched_at: datetime | None = None
    genres: list[str] = []
    user_rating: int | None = None


class GraphEdge(CamelModel):
    source: int
    target: int
    """Jaccard similarity over the two related-sets: |A n B| / |A u B|."""
    weight: float
    """Raw size of the intersection, i.e. how many titles both relate to."""
    shared: int


class GraphMeta(CamelModel):
    username: str
    generated_at: datetime
    movie_count: int
    node_count: int
    edge_count: int
    community_count: int
    min_weight: float
    top_k: int


class ClusterGenre(CamelModel):
    name: str
    share: float


class Recommendation(CamelModel):
    """An unwatched film, with the evidence for recommending it."""

    id: int
    title: str
    year: int | None = None
    slug: str | None = None
    poster: str | None = None
    overview: str | None = None
    genres: list[str] = []
    community_rating: float | None = None
    votes: int | None = None
    score: float
    """Rating-weighted count of your films that list this one as related."""
    support: int
    """Unweighted count of your films that list this one."""
    cluster_support: int
    """How many of those are in the cluster it's filed under."""
    because: list[int]
    on_watchlist: bool = False
    has_metadata: bool = False
    confidence: float | None = None


class ClusterProfile(CamelModel):
    id: int
    size: int
    label: str
    summary: str | None = None
    themes: list[str] = []
    label_source: str
    genres: list[ClusterGenre]
    era_start: int | None = None
    era_end: int | None = None
    anchors: list[int]
    rated_count: int = 0
    avg_user_rating: float | None = None
    recommendations: list[Recommendation] = []


class CalibrationBucket(CamelModel):
    """Hit rate for candidates whose support (per 1,000 library films) is at
    least `min_per_thousand`, up to the next bucket."""

    min_per_thousand: float
    hit_rate: float
    samples: int


class Evaluation(CamelModel):
    """Hold-out test of the recommender against your real history."""

    folds: int
    holdout_share: float
    k: int
    top_k_hit_rate: float
    """Hit rate of the top-k picks overall (per fold)."""
    cluster_local_hit_rate: float
    """The rejected alternative: top picks ranked within each cluster."""
    calibration: list[CalibrationBucket]
    tested_at: datetime


class GraphPayload(CamelModel):
    meta: GraphMeta
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    clusters: list[ClusterProfile] = []
    evaluation: Evaluation | None = None
