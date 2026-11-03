/* Generated from the pydantic graph contract. Run `npm run types`; do not edit. */

export type Username = string;
export type Generatedat = string;
export type Moviecount = number;
export type Nodecount = number;
export type Edgecount = number;
export type Communitycount = number;
export type Minweight = number;
export type Topk = number;
export type Id = number;
export type Label = string;
export type Year = number | null;
export type Slug = string | null;
export type Imdb = string | null;
export type Tmdb = number | null;
export type Degree = number;
export type Community = number | null;
export type Plays = number;
export type Lastwatchedat = string | null;
export type Genres = string[];
export type Userrating = number | null;
export type Nodes = GraphNode[];
export type Source = number;
export type Target = number;
export type Weight = number;
export type Shared = number;
export type Edges = GraphEdge[];
export type Id1 = number;
export type Size = number;
export type Label1 = string;
export type Summary = string | null;
export type Themes = string[];
export type Labelsource = string;
export type Name = string;
export type Share = number;
export type Genres1 = ClusterGenre[];
export type Erastart = number | null;
export type Eraend = number | null;
export type Anchors = number[];
export type Ratedcount = number;
export type Avguserrating = number | null;
export type Id2 = number;
export type Title = string;
export type Year1 = number | null;
export type Slug1 = string | null;
export type Poster = string | null;
export type Overview = string | null;
export type Genres2 = string[];
export type Communityrating = number | null;
export type Votes = number | null;
export type Score = number;
export type Support = number;
export type Clustersupport = number;
export type Because = number[];
export type Onwatchlist = boolean;
export type Hasmetadata = boolean;
export type Confidence = number | null;
export type Recommendations = Recommendation[];
export type Clusters = ClusterProfile[];
export type Folds = number;
export type Holdoutshare = number;
export type K = number;
export type Topkhitrate = number;
export type Clusterlocalhitrate = number;
export type Minperthousand = number;
export type Hitrate = number;
export type Samples = number;
export type Calibration = CalibrationBucket[];
export type Testedat = string;

export interface GraphPayload {
  meta: GraphMeta;
  nodes: Nodes;
  edges: Edges;
  clusters?: Clusters;
  evaluation?: Evaluation | null;
  [k: string]: unknown;
}
export interface GraphMeta {
  username: Username;
  generatedAt: Generatedat;
  movieCount: Moviecount;
  nodeCount: Nodecount;
  edgeCount: Edgecount;
  communityCount: Communitycount;
  minWeight: Minweight;
  topK: Topk;
  [k: string]: unknown;
}
export interface GraphNode {
  id: Id;
  label: Label;
  year?: Year;
  slug?: Slug;
  imdb?: Imdb;
  tmdb?: Tmdb;
  degree?: Degree;
  community?: Community;
  plays?: Plays;
  lastWatchedAt?: Lastwatchedat;
  genres?: Genres;
  userRating?: Userrating;
  [k: string]: unknown;
}
export interface GraphEdge {
  source: Source;
  target: Target;
  weight: Weight;
  shared: Shared;
  [k: string]: unknown;
}
export interface ClusterProfile {
  id: Id1;
  size: Size;
  label: Label1;
  summary?: Summary;
  themes?: Themes;
  labelSource: Labelsource;
  genres: Genres1;
  eraStart?: Erastart;
  eraEnd?: Eraend;
  anchors: Anchors;
  ratedCount?: Ratedcount;
  avgUserRating?: Avguserrating;
  recommendations?: Recommendations;
  [k: string]: unknown;
}
export interface ClusterGenre {
  name: Name;
  share: Share;
  [k: string]: unknown;
}
/**
 * An unwatched film, with the evidence for recommending it.
 */
export interface Recommendation {
  id: Id2;
  title: Title;
  year?: Year1;
  slug?: Slug1;
  poster?: Poster;
  overview?: Overview;
  genres?: Genres2;
  communityRating?: Communityrating;
  votes?: Votes;
  score: Score;
  support: Support;
  clusterSupport: Clustersupport;
  because: Because;
  onWatchlist?: Onwatchlist;
  hasMetadata?: Hasmetadata;
  confidence?: Confidence;
  [k: string]: unknown;
}
/**
 * Hold-out test of the recommender against your real history.
 */
export interface Evaluation {
  folds: Folds;
  holdoutShare: Holdoutshare;
  k: K;
  topKHitRate: Topkhitrate;
  clusterLocalHitRate: Clusterlocalhitrate;
  calibration: Calibration;
  testedAt: Testedat;
  [k: string]: unknown;
}
/**
 * Hit rate for candidates whose support (per 1,000 library films) is at
 * least `min_per_thousand`, up to the next bucket.
 */
export interface CalibrationBucket {
  minPerThousand: Minperthousand;
  hitRate: Hitrate;
  samples: Samples;
  [k: string]: unknown;
}
