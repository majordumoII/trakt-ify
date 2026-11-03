// Community hues, tuned to read on the navy field. Index 0 is the largest
// community (the pipeline ranks them by size), so the strongest hues go to the
// clusters people will see most. Beyond fourteen, the smallest communities fall back to slate.
export const COMMUNITY_COLORS = [
  "#F2B544", // marquee amber
  "#5FB4F2", // sky
  "#F07167", // coral
  "#43C6A8", // teal
  "#B892F0", // violet
  "#A9D673", // lime
  "#F49CBB", // rose
  "#E6A26B", // copper
  "#6FD3E8", // cyan
  "#D9C98F", // sand
  "#8E9BFF", // periwinkle
  "#E07FD2", // orchid
  "#6FDB9E", // mint
  "#C9A83A", // ochre
] as const;

export const FALLBACK_COLOR = "#7A819C";

export function communityColor(community: number | null | undefined): string {
  if (community == null || community >= COMMUNITY_COLORS.length) return FALLBACK_COLOR;
  return COMMUNITY_COLORS[community];
}

export function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
