#!/usr/bin/env node
// sync-stats.mjs — sync functional metadata from the GEODE repo into the site.
//
// Reads from the GEODE repo at GEODE_REPO (default ../geode):
//   - pyproject.toml → version (written to src/data/geode/sot.ts)
//   - CHANGELOG.md   → the full per-version body (src/data/geode/changelog.ts)
//   - sitemap.ts     → the page list for public/llms.txt + llms-full.txt
//
// Inventory counts (modules / tests / releases) are intentionally NOT synced:
// the docs describe what the system does, not how much of it there is.
//
// Run:  npm run sync-stats
// Override GEODE repo: GEODE_REPO=/abs/path npm run sync-stats

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SITE_ROOT = resolve(__dirname, "..");

function detectGeodeRepo() {
  if (process.env.GEODE_REPO) return resolve(process.env.GEODE_REPO);
  const asSibling = resolve(SITE_ROOT, "..", "geode");
  const asChild = resolve(SITE_ROOT, "..");
  if (existsSync(resolve(asChild, "pyproject.toml"))) return asChild;
  if (existsSync(resolve(asSibling, "pyproject.toml"))) return asSibling;
  console.error("sync-stats: could not locate GEODE repo. Set GEODE_REPO env var.");
  process.exit(1);
}

const GEODE_REPO = detectGeodeRepo();
const SOT_FILE = resolve(SITE_ROOT, "src/data/geode/sot.ts");
const CHANGELOG_FILE = resolve(SITE_ROOT, "src/data/geode/changelog.ts");
const LLMS_TXT_FILE = resolve(SITE_ROOT, "public/llms.txt");
const LLMS_FULL_TXT_FILE = resolve(SITE_ROOT, "public/llms-full.txt");
const SITEMAP_TS_FILE = resolve(SITE_ROOT, "src/lib/geode-docs/sitemap.ts");

function fail(msg) {
  console.error(`sync-stats: ${msg}`);
  process.exit(1);
}

function readVersion() {
  const pyproject = readFileSync(resolve(GEODE_REPO, "pyproject.toml"), "utf8");
  const m = pyproject.match(/^version\s*=\s*"([^"]+)"/m);
  if (!m) fail("could not parse version from pyproject.toml");
  return m[1];
}

// Parse CHANGELOG.md into structured entries.
// Each `## [version] — date` heading begins a new entry; everything until the
// next `## [` heading (or `## ` of a non-version section) is the body.
function parseChangelog() {
  const raw = readFileSync(resolve(GEODE_REPO, "CHANGELOG.md"), "utf8");
  const lines = raw.split(/\r?\n/);
  const entries = [];
  let cur = null;
  for (const line of lines) {
    const m = line.match(/^## \[([^\]]+)\](?:\s*[—\-]\s*(.+))?$/);
    if (m) {
      if (cur) entries.push(cur);
      cur = { version: m[1].trim(), date: (m[2] ?? "").trim(), body: [] };
      continue;
    }
    // A non-version `## ` heading (e.g. "## Scope Rules") starts a non-entry
    // section. If we're currently inside an entry, stop appending.
    if (line.startsWith("## ") && cur) {
      entries.push(cur);
      cur = null;
      continue;
    }
    if (cur) cur.body.push(line);
  }
  if (cur) entries.push(cur);
  // Trim trailing horizontal rules and blank lines from each body.
  for (const e of entries) {
    while (
      e.body.length &&
      (e.body[e.body.length - 1].trim() === "" ||
        e.body[e.body.length - 1].trim() === "---")
    ) {
      e.body.pop();
    }
    // Also trim leading blanks.
    while (e.body.length && e.body[0].trim() === "") e.body.shift();
  }
  return entries;
}

function writeSot(v) {
  const today = new Date().toISOString().slice(0, 10);

  // PR-DOCS-REDESIGN (2026-05-30) — the SOT no longer carries inventory counts
  // (modules / tests / releases). The docs describe what the system does, not
  // how much of it there is, so only the functional fields remain: the package
  // version (used in the footer, system-index, and the portfolio hero badge)
  // and the sync date.
  const body = `/**
 * GEODE Single Source of Truth — site-wide functional metadata.
 *
 * Auto-synced from the GEODE repo via \`npm run sync-stats\`.
 * Do not edit manually. Edit the GEODE repo and re-run sync.
 *
 * Last sync: ${today}
 */

export const GEODE_SOT = {
  version: "${v.version}",
  syncedAt: "${today}",
} as const;
`;
  writeFileSync(SOT_FILE, body);
}

function writeChangelog(entries) {
  const today = new Date().toISOString().slice(0, 10);
  // JSON.stringify handles escaping cleanly for embed-as-TS-literal.
  const data = entries.map((e) => ({
    version: e.version,
    date: e.date,
    body: e.body.join("\n"),
  }));

  const body = `/**
 * GEODE CHANGELOG, auto-synced from the GEODE repo via \`npm run sync-stats\`.
 * Do not edit manually. Edit CHANGELOG.md in the GEODE repo and re-run sync.
 *
 * Last sync: ${today}
 *
 * Each entry's \`body\` is the raw markdown between two version headings.
 * The Changelog page renders the body with a minimal markdown renderer
 * (\`MarkdownLite\`) defined under \`src/components/geode-docs/\`.
 */

export type ChangelogEntry = {
  version: string;
  date: string;
  body: string;
};

export const CHANGELOG: ChangelogEntry[] = ${JSON.stringify(data, null, 2)};

export const CHANGELOG_SYNCED_AT = "${today}";
`;
  writeFileSync(CHANGELOG_FILE, body);
}

/**
 * Parse the sitemap.ts file to extract the list of pages. We treat the file
 * as text and walk it line by line, capturing each page's slug/title/titleKo/
 * summary/summaryKo. Brittle but adequate for a tightly-controlled SOT file.
 */
function parseSitemap() {
  const src = readFileSync(SITEMAP_TS_FILE, "utf8");
  const pages = [];
  const lines = src.split("\n");
  let currentSection = null;
  for (const line of lines) {
    const sectMatch = line.match(/title:\s*"([^"]+)",\s*titleKo:\s*"([^"]+)"/);
    if (sectMatch && !line.includes("slug:")) {
      // Heuristic: section header has title + titleKo on same line without slug.
      currentSection = { title: sectMatch[1], titleKo: sectMatch[2] };
      continue;
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

/**
 * llms.txt — flat LLM-friendly index of every public page.
 *
 * Pattern adopted from Hermes Agent (NousResearch). Plain text, one line per
 * page, structured: title (slug) URL — summary. LLMs can grep this without
 * parsing HTML.
 */
function writeLlmsTxt(pages, version) {
  const base = "https://mangowhoiscloud.github.io/geode";
  const today = new Date().toISOString().slice(0, 10);

  const lines = [];
  lines.push("# GEODE");
  lines.push("");
  lines.push(`GEODE v${version}. A self-evolving autonomous execution agent.`);
  lines.push("");
  lines.push(`Last sync: ${today}`);
  lines.push("");
  lines.push("## Top-level pages");
  lines.push("");
  lines.push(`- Portfolio  ${base}/portfolio`);
  lines.push(`- Docs       ${base}/docs`);
  lines.push(`- About      ${base}/about`);
  lines.push(`- Source     https://github.com/mangowhoiscloud/geode`);
  lines.push("");
  lines.push("## Documentation");
  lines.push("");

  let currentSection = null;
  for (const p of pages) {
    if (p.section && p.section.title !== currentSection) {
      currentSection = p.section.title;
      lines.push("");
      lines.push(`### ${p.section.title} (${p.section.titleKo})`);
      lines.push("");
    }
    const url = p.slug ? `${base}/docs/${p.slug}` : `${base}/docs`;
    const title = p.title || "(index)";
    const summary = p.summary || "";
    lines.push(`- ${title}  ${url}${summary ? "  — " + summary : ""}`);
  }
  lines.push("");
  lines.push("## Authoritative sources");
  lines.push("");
  lines.push(`- CHANGELOG  https://github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md`);
  lines.push(`- CLAUDE.md  https://github.com/mangowhoiscloud/geode/blob/main/CLAUDE.md`);
  lines.push(`- AGENTS.md  https://github.com/mangowhoiscloud/geode/blob/main/AGENTS.md`);
  lines.push(`- llms-full  ${base}/llms-full.txt`);

  writeFileSync(LLMS_TXT_FILE, lines.join("\n") + "\n");
}

/**
 * llms-full.txt — the same index plus per-page summaries in both languages.
 * Reasonable plain-text scan target. Stays well under 1MB.
 */
function writeLlmsFullTxt(pages, version) {
  const base = "https://mangowhoiscloud.github.io/geode";
  const today = new Date().toISOString().slice(0, 10);

  const lines = [];
  lines.push("# GEODE");
  lines.push("");
  lines.push(`GEODE v${version}. A self-evolving autonomous execution agent.`);
  lines.push(`스스로 진화하는 자율 실행 에이전트.`);
  lines.push("");
  lines.push(`Last sync: ${today}`);
  lines.push("");
  lines.push("---");
  lines.push("");

  let currentSection = null;
  for (const p of pages) {
    if (p.section && p.section.title !== currentSection) {
      currentSection = p.section.title;
      lines.push("");
      lines.push(`## ${p.section.title} . ${p.section.titleKo}`);
      lines.push("");
    }
    const url = p.slug ? `${base}/docs/${p.slug}` : `${base}/docs`;
    lines.push(`### ${p.title || "(index)"} (${p.titleKo || ""})`);
    lines.push(`URL: ${url}`);
    if (p.summary) lines.push(`EN: ${p.summary}`);
    if (p.summaryKo) lines.push(`KO: ${p.summaryKo}`);
    lines.push("");
  }

  writeFileSync(LLMS_FULL_TXT_FILE, lines.join("\n") + "\n");
}

function main() {
  console.log(`sync-stats: reading from ${GEODE_REPO}`);
  const version = readVersion();
  console.log(`  version  : ${version}`);

  writeSot({ version });
  console.log(`sync-stats: wrote ${SOT_FILE}`);

  const entries = parseChangelog();
  writeChangelog(entries);
  console.log(`sync-stats: wrote ${CHANGELOG_FILE} (${entries.length} entries)`);

  const pages = parseSitemap();
  writeLlmsTxt(pages, version);
  writeLlmsFullTxt(pages, version);
  console.log(`sync-stats: wrote ${LLMS_TXT_FILE} (${pages.length} pages)`);
  console.log(`sync-stats: wrote ${LLMS_FULL_TXT_FILE}`);
}

main();
