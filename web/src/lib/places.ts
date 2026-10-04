/**
 * Which kinds of place a screen is about. One rule shared by the sidebar finder and the map, so the two never disagree:
 * "New question" (the home page) is about everything the country holds; an index is about its own places only.
 */
export type PlaceKind = "site" | "bathing-water";

const BATHING_INDICES = new Set(["bathing-classes", "bathing-samples"]);

export function indexIdFromPath(pathname: string): string | null {
  const m = /^\/(?:i|labs)\/([^/]+)/.exec(pathname);
  return m?.[1] ?? null;
}

export function isBathingIndex(indexId: string | null): boolean {
  return indexId !== null && BATHING_INDICES.has(indexId);
}

/** Kinds shown on the map: all of them on the home page, only the index's own kind inside an index. */
export function mapKinds(pathname: string): PlaceKind[] {
  const indexId = indexIdFromPath(pathname);
  if (indexId === null) return ["site", "bathing-water"];
  return isBathingIndex(indexId) ? ["bathing-water"] : ["site"];
}

/**
 * Kinds the sidebar finder searches: sites only (a simple name search). Bathing waters are picked on the map, so the
 * finder is hidden in the bathing indices and where no place can be picked (labs, settings).
 */
export function finderKinds(pathname: string): PlaceKind[] {
  if (pathname.startsWith("/labs/") || pathname.startsWith("/settings")) return [];
  return isBathingIndex(indexIdFromPath(pathname)) ? [] : ["site"];
}
