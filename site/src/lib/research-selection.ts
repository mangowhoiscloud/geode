/** Collection selection is separate from reader resource paths and scene hashes. */
export const publicationIds = ["research-geode", "research-jev", "jevdb-paper-review"] as const;
export const selectionHashes = ["", "#jev", "#jevdb"] as const;

export function researchSelectionIndex(hash: string): number {
  if (hash === "#research" || hash === "#geode") return 0;
  const current = selectionHashes.findIndex(value => value === hash);
  return current >= 0 ? current : publicationIds.findIndex(id => `#${id}` === hash);
}

/** Preserve language and unrelated query parameters while normalizing known aliases. */
export function normalizeResearchSelection(url: URL): URL {
  const normalized = new URL(url);
  const index = researchSelectionIndex(url.hash);
  if (index >= 0) normalized.hash = selectionHashes[index];
  return normalized;
}
