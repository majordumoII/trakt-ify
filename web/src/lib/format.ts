import type { ClusterProfile, Recommendation } from "./graph";

export function era(c: ClusterProfile): string | null {
  if (c.eraStart == null || c.eraEnd == null) return null;
  return c.eraStart === c.eraEnd ? `${c.eraStart}` : `${c.eraStart}–${c.eraEnd}`;
}

export function genreName(g: string): string {
  const name = g.replace(/-/g, " ");
  return name.charAt(0).toUpperCase() + name.slice(1);
}

export function genreList(genres: string[] | undefined, max = 3): string {
  return (genres ?? []).slice(0, max).map(genreName).join(", ").toLowerCase();
}

export type Tier = { label: string; level: 3 | 2 | 1 };

/** Bands follow the hold-out test: a pick's confidence is the share of titles
 *  at its support level that turned out to be films the viewer had watched. */
export function tier(r: Recommendation): Tier {
  const c = r.confidence ?? 0;
  if (c >= 0.25) return { label: "Strong pick", level: 3 };
  if (c >= 0.1) return { label: "Good pick", level: 2 };
  return { label: "Worth a look", level: 1 };
}

export function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}
