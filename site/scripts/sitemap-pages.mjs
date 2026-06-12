// sitemap-pages.mjs — the ONE parser for src/lib/geode-docs/sitemap.ts.
//
// Imported by sync-stats.mjs (llms.txt index) and export-docs-md.mjs
// (markdown twins + llms-full.txt). Single parser by design: the sitemap
// section shape drifted once already and silently dropped every section
// grouping (PR-LLMS-TXT, v0.99.156). One schema, one loader.
//
// We treat sitemap.ts as text and walk it line by line, capturing each
// page's slug/title/titleKo/summary/summaryKo plus its section header.
// Brittle but adequate for a tightly-controlled SOT file.

import { readFileSync } from "node:fs";

export function parseSitemap(sitemapTsPath) {
  const src = readFileSync(sitemapTsPath, "utf8");
  const pages = [];
  const lines = src.split("\n");
  let currentSection = null;
  let pendingSectionTitle = null;
  for (const line of lines) {
    // Section header: post-redesign sitemap puts title / titleKo on their own
    // lines inside the section object (pages carry slug on the same line).
    if (!line.includes("slug:")) {
      const titleOnly = line.match(/^\s*title:\s*"([^"]+)",\s*$/);
      if (titleOnly) {
        pendingSectionTitle = titleOnly[1];
        continue;
      }
      const titleKoOnly = line.match(/^\s*titleKo:\s*"([^"]+)",\s*$/);
      if (titleKoOnly && pendingSectionTitle) {
        currentSection = { title: pendingSectionTitle, titleKo: titleKoOnly[1] };
        pendingSectionTitle = null;
        continue;
      }
    }
    // Page entry. Inline object with slug.
    const pm = line.match(/{\s*slug:\s*"([^"]*)"/);
    if (!pm) continue;
    const slug = pm[1];
    const titleM = line.match(/title:\s*"([^"]*)"/);
    const titleKoM = line.match(/titleKo:\s*"([^"]*)"/);
    const summaryM = line.match(/summary:\s*"([^"]*)"/);
    const summaryKoM = line.match(/summaryKo:\s*"([^"]*)"/);
    pages.push({
      slug,
      title: titleM?.[1] ?? "",
      titleKo: titleKoM?.[1] ?? "",
      summary: summaryM?.[1] ?? "",
      summaryKo: summaryKoM?.[1] ?? "",
      section: currentSection,
    });
  }
  return pages;
}
