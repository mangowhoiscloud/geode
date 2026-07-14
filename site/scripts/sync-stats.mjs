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
import { parseSitemap } from "./sitemap-pages.mjs";
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
// Published-site + repo URL anchors — single definition per surface
// (python-side anchor: core/paths.py GEODE_PAGES_BASE_URL).
const PAGES_BASE_URL = "https://mangowhoiscloud.github.io/geode";
const REPO_URL = "https://github.com/mangowhoiscloud/geode";
const SOT_FILE = resolve(SITE_ROOT, "src/data/geode/sot.ts");
const CHANGELOG_FILE = resolve(SITE_ROOT, "src/data/geode/changelog.ts");
const LLMS_TXT_FILE = resolve(SITE_ROOT, "public/llms.txt");
const SITEMAP_TS_FILE = resolve(SITE_ROOT, "src/lib/geode-docs/sitemap.ts");

function fail(msg) {
  console.error(`sync-stats: ${msg}`);
  process.exit(1);
}

function generationDate(version) {
  const epoch = process.env.SOURCE_DATE_EPOCH;
  if (epoch !== undefined) {
    if (!/^\d+$/.test(epoch)) fail(`invalid SOURCE_DATE_EPOCH: ${epoch}`);
    const date = new Date(Number(epoch) * 1000);
    if (Number.isNaN(date.getTime())) fail(`invalid SOURCE_DATE_EPOCH: ${epoch}`);
    return date.toISOString().slice(0, 10);
  }

  // A same-version verification or repair run must not dirty committed docs
  // merely because the wall clock advanced. Preserve the existing sync date;
  // a new version (or a missing snapshot) receives today's UTC date.
  if (existsSync(SOT_FILE)) {
    const previous = readFileSync(SOT_FILE, "utf8");
    const previousVersion = previous.match(/version:\s*"([^"]+)"/)?.[1];
    const previousDate = previous.match(/syncedAt:\s*"(\d{4}-\d{2}-\d{2})"/)?.[1];
    if (previousVersion === version && previousDate) return previousDate;
  }
  return new Date().toISOString().slice(0, 10);
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

function writeSot(v, today) {

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

function writeChangelog(entries, today) {
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
 * llms.txt — spec-conformant (llmstxt.org) index of every public page.
 *
 * Shape: H1 name → blockquote summary → detail line → one H2 file-list
 * section per docs section, each item `- [name](url): notes` → `## Optional`
 * for the bulk/auxiliary links agents can skip on a short context budget.
 * Consumed by LLM agents that fetch /llms.txt before exploring the site
 * (the convention GEODE's own router prompt follows for external docs).
 */
function writeLlmsTxt(pages, version, today) {
  const base = PAGES_BASE_URL;

  const lines = [];
  lines.push("# GEODE");
  lines.push("");
  lines.push(
    "> GEODE is a self-evolving autonomous execution agent: an inner agentic loop runs tasks" +
      " (research, analysis, automation, scheduling) and an outer self-improving loop" +
      " (Petri audit -> fitness gate) tunes the system that runs them.",
  );
  lines.push("");
  lines.push(
    `Version v${version}. Last sync ${today}. Docs links point to clean markdown twins (.md);` +
      " drop the .md suffix for the rendered page.",
  );
  lines.push("");
  lines.push("## Start here");
  lines.push("");
  lines.push(`- [Docs](${base}/docs.md): documentation root, what GEODE is and where to go next`);
  lines.push(`- [Portfolio](${base}/portfolio): capability overview with demos`);
  lines.push(`- [About](${base}/about): project background`);
  lines.push(`- [Source](${REPO_URL}): GitHub repository`);

  let currentSection = null;
  for (const p of pages) {
    if (p.section && p.section.title !== currentSection) {
      currentSection = p.section.title;
      lines.push("");
      lines.push(`## ${p.section.title}`);
      lines.push("");
    }
    const url = p.slug ? `${base}/docs/${p.slug}.md` : `${base}/docs.md`;
    const title = p.title || "Docs index";
    const summary = p.summary || "";
    lines.push(`- [${title}](${url})${summary ? ": " + summary : ""}`);
  }
  lines.push("");
  lines.push("## Optional");
  lines.push("");
  lines.push(
    `- [llms-full.txt](${base}/llms-full.txt): the entire docs content in one file (large)`,
  );
  lines.push(
    `- [CHANGELOG](${REPO_URL}/blob/main/CHANGELOG.md): full release history`,
  );
  lines.push(
    `- [CLAUDE.md](${REPO_URL}/blob/main/CLAUDE.md): development scaffold and quality gates`,
  );
  lines.push(
    `- [AGENTS.md](${REPO_URL}/blob/main/AGENTS.md): agent-facing repo guide`,
  );

  writeFileSync(LLMS_TXT_FILE, lines.join("\n") + "\n");
}

// llms-full.txt is written by export-docs-md.mjs (post-build, real page
// content) — single writer per file. This script only writes the index.

function main() {
  console.log(`sync-stats: reading from ${GEODE_REPO}`);
  const version = readVersion();
  const syncDate = generationDate(version);
  console.log(`  version  : ${version}`);

  writeSot({ version }, syncDate);
  console.log(`sync-stats: wrote ${SOT_FILE}`);

  const entries = parseChangelog();
  writeChangelog(entries, syncDate);
  console.log(`sync-stats: wrote ${CHANGELOG_FILE} (${entries.length} entries)`);

  const pages = parseSitemap(SITEMAP_TS_FILE);
  writeLlmsTxt(pages, version, syncDate);
  console.log(`sync-stats: wrote ${LLMS_TXT_FILE} (${pages.length} pages)`);
  console.log("sync-stats: llms-full.txt is owned by export-docs-md.mjs (run after build)");
}

main();
