#!/usr/bin/env node
// export-docs-md.mjs — markdown twins for every docs page + llms-full.txt.
//
// llms.txt convention, publication side, step 2 (PR-LLMS-TXT-MD-TWINS).
// The index (llms.txt) already existed; what was missing is the thing the
// convention actually promises: a clean markdown version of each page, so
// an agent following an index link does not pay for Next.js hydration
// payloads and navigation chrome. Frontier docs sites all serve .md twins
// (platform.claude.com, docs.langchain.com, Mintlify-hosted sites).
//
// Runs AFTER `next build` (out/ must exist):
//   1. For every sitemap page, read out/docs/<slug>.html, extract the
//      <article class="docs-prose"> body, convert to markdown (turndown +
//      GFM tables), absolutize /geode/ links, write out/docs/<slug>.md.
//      Rendered page URL + ".md" = the twin URL.
//   2. Assemble llms-full.txt — the TRUE full-content dump (replacing the
//      summary-only index this file used to be) — into site/public/
//      (committed SoT) and site/out/ (deployed artifact).
//
// Single writer: sync-stats.mjs writes llms.txt, this script writes
// llms-full.txt and the .md twins. A missing html for a sitemap page or a
// page without the docs-prose article FAILS the build (sitemap/build
// drift must not ship silently).
//
// Run:  npm run export-md

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";
import { parseSitemap } from "./sitemap-pages.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SITE_ROOT = resolve(__dirname, "..");
const OUT_DIR = resolve(SITE_ROOT, "out");
const PAGES_BASE_URL = "https://mangowhoiscloud.github.io/geode";
const SITEMAP_TS_FILE = resolve(SITE_ROOT, "src/lib/geode-docs/sitemap.ts");
const SOT_FILE = resolve(SITE_ROOT, "src/data/geode/sot.ts");
const LLMS_FULL_PUBLIC = resolve(SITE_ROOT, "public/llms-full.txt");
const LLMS_FULL_OUT = resolve(OUT_DIR, "llms-full.txt");

const ARTICLE_RE = /<article class="docs-prose">([\s\S]*?)<\/article>/;

function fail(msg) {
  console.error(`export-docs-md: ${msg}`);
  process.exit(1);
}

function readVersion() {
  const sot = readFileSync(SOT_FILE, "utf8");
  const m = sot.match(/version:\s*"([^"]+)"/);
  if (!m) fail(`could not parse version from ${SOT_FILE} (run sync-stats first)`);
  return m[1];
}

function buildTurndown() {
  const td = new TurndownService({
    headingStyle: "atx",
    codeBlockStyle: "fenced",
    hr: "---",
    bulletListMarker: "-",
  });
  td.use(gfm);
  td.remove(["script", "style"]);
  // Docs code blocks are bare <pre> (no nested <code>) — turndown's default
  // fenced rule only fires on pre>code, so without this rule every shell
  // snippet flattens into plain paragraphs.
  td.addRule("barePre", {
    filter: (node) => node.nodeName === "PRE" && !node.querySelector("code"),
    replacement: (_content, node) =>
      "\n\n```\n" + node.textContent.replace(/\n+$/, "") + "\n```\n\n",
  });
  return td;
}

/**
 * Absolutize site-internal links (](/geode/... -> full URL) and retarget
 * docs-page links at their .md twins so an agent reading one twin can hop
 * twin-to-twin without ever paying for a rendered page. Slug paths carry
 * no dots, so asset/file links are untouched by construction.
 */
function absolutizeLinks(markdown) {
  const absolute = markdown
    .replaceAll("](/geode/", `](${PAGES_BASE_URL}/`)
    .replaceAll("](/geode)", `](${PAGES_BASE_URL})`);
  const docsLink = new RegExp(
    `\\((${PAGES_BASE_URL.replaceAll(".", "\\.")}/docs(?:/[a-z0-9\\-/]+)?)(#[^)\\s]*)?\\)`,
    "g",
  );
  return absolute.replace(docsLink, (_m, pageUrl, fragment) => `(${pageUrl}.md${fragment ?? ""})`);
}

function htmlPathFor(slug) {
  return slug ? resolve(OUT_DIR, "docs", `${slug}.html`) : resolve(OUT_DIR, "docs.html");
}

function mdPathFor(slug) {
  return slug ? resolve(OUT_DIR, "docs", `${slug}.md`) : resolve(OUT_DIR, "docs.md");
}

function renderedUrlFor(slug) {
  return slug ? `${PAGES_BASE_URL}/docs/${slug}` : `${PAGES_BASE_URL}/docs`;
}

function exportPage(td, page) {
  const htmlPath = htmlPathFor(page.slug);
  if (!existsSync(htmlPath)) {
    fail(`missing build output for sitemap page "${page.slug || "(docs root)"}": ${htmlPath}`);
  }
  const html = readFileSync(htmlPath, "utf8");
  const articleMatch = ARTICLE_RE.exec(html);
  if (!articleMatch) {
    fail(`no <article class="docs-prose"> in ${htmlPath} — docs layout drifted, fix ARTICLE_RE`);
  }
  const body = absolutizeLinks(td.turndown(articleMatch[1])).trim() + "\n";
  // The page h1 + summary live outside <article> (docs layout chrome), so
  // the twin gets a sitemap-derived header; llms-full.txt adds its own
  // per-page header and embeds the raw body instead.
  const heading = `# ${page.title || "Docs index"}${page.titleKo ? ` (${page.titleKo})` : ""}`;
  const summary = page.summary ? `\n> ${page.summary}\n` : "";
  const twin = `${heading}\n${summary}\n${body}`;
  const mdPath = mdPathFor(page.slug);
  mkdirSync(dirname(mdPath), { recursive: true });
  writeFileSync(mdPath, twin);
  return body;
}

function writeLlmsFull(pages, bodies, version) {
  const today = new Date().toISOString().slice(0, 10);
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
    `Version v${version}. Last sync ${today}. Full content of every docs page,` +
      ` one file (llms-full.txt convention). Per-page index: /llms.txt.`,
  );

  let currentSection = null;
  for (const page of pages) {
    if (page.section && page.section.title !== currentSection) {
      currentSection = page.section.title;
      lines.push("");
      lines.push(`## ${page.section.title} . ${page.section.titleKo}`);
    }
    lines.push("");
    lines.push(`### ${page.title || "Docs index"}${page.titleKo ? ` (${page.titleKo})` : ""}`);
    lines.push("");
    lines.push(`URL: ${renderedUrlFor(page.slug)}`);
    lines.push(`Markdown: ${renderedUrlFor(page.slug)}.md`);
    lines.push("");
    lines.push(bodies.get(page.slug).trim());
    lines.push("");
    lines.push("---");
  }
  const content = lines.join("\n") + "\n";
  writeFileSync(LLMS_FULL_PUBLIC, content);
  writeFileSync(LLMS_FULL_OUT, content);
  return content.length;
}

function main() {
  if (!existsSync(OUT_DIR)) fail("site/out missing — run `npm run build` first");
  const version = readVersion();
  const pages = parseSitemap(SITEMAP_TS_FILE);
  if (!pages.length) fail("sitemap parser returned 0 pages — sitemap.ts shape drifted");

  const td = buildTurndown();
  const bodies = new Map();
  for (const page of pages) {
    bodies.set(page.slug, exportPage(td, page));
  }
  console.log(`export-docs-md: wrote ${pages.length} markdown twins under ${OUT_DIR}/docs`);

  const bytes = writeLlmsFull(pages, bodies, version);
  console.log(
    `export-docs-md: wrote llms-full.txt (${(bytes / 1024).toFixed(0)} KB) to public/ + out/`,
  );
}

main();
