import { parse } from "yaml";

/** Seed artifacts use an optional YAML mapping bounded by whole-line fences. */
export function parseSeedMarkdown(raw: string): {
  data: Record<string, unknown>;
  content: string;
} {
  const source = raw.replace(/^\uFEFF/, "");
  const opening = /^---[\t ]*\r?\n/.exec(source);
  if (!opening) return { data: {}, content: source };

  const closing = /^---[\t ]*\r?$/gm;
  closing.lastIndex = opening[0].length;
  const fence = closing.exec(source);
  if (!fence) throw new Error("Seed YAML frontmatter has no closing fence");

  const data: unknown = parse(source.slice(opening[0].length, fence.index));
  if (data !== null && (typeof data !== "object" || Array.isArray(data))) {
    throw new Error("Seed YAML frontmatter must be a mapping");
  }
  return {
    data: (data ?? {}) as Record<string, unknown>,
    content: source.slice(fence.index + fence[0].length).replace(/^\r?\n/, ""),
  };
}
