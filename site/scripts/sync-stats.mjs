#!/usr/bin/env node
// sync-stats.mjs — pull live GEODE metrics into src/data/geode/sot.ts and
// the full CHANGELOG into src/data/geode/changelog.ts.
//
// Reads from the GEODE repo at GEODE_REPO (default ../geode):
//   - pyproject.toml         → version
//   - filesystem (core/, plugins/) → module counts
//   - CHANGELOG.md           → release count (excludes [Unreleased]) plus
//                              the full per-version body for changelog.ts
//   - git log                → first commit YYYY-MM
//   - CLAUDE.md              → test counts (avoids slow pytest --collect-only)
//
// Run:  npm run sync-stats
// Override GEODE repo: GEODE_REPO=/abs/path npm run sync-stats

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { execSync } from "node:child_process";
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

function countModules(dir) {
  const out = execSync(
    `find ${dir} -name "*.py" -type f -not -path "*/.*" | wc -l`,
    { cwd: GEODE_REPO, encoding: "utf8" }
  );
  return parseInt(out.trim(), 10);
}

function countReleases() {
  const changelog = readFileSync(resolve(GEODE_REPO, "CHANGELOG.md"), "utf8");
  const matches = changelog.match(/^## \[([^\]]+)\]/gm) ?? [];
  return matches.filter((line) => !/Unreleased/i.test(line)).length;
}

function readSince() {
  const out = execSync(
    `git log --reverse --pretty=format:"%ad" --date=format:"%Y-%m" | head -1`,
    { cwd: GEODE_REPO, encoding: "utf8", shell: "/bin/bash" }
  );
  return out.trim();
}

function readTestCounts() {
  const claudeMd = readFileSync(resolve(GEODE_REPO, "CLAUDE.md"), "utf8");
  const m =
    claudeMd.match(/Tests\*{0,2}\s*[:|]\s*(\d[\d,]*)\s*\(\+\s*(\d+)\s*live\)/i) ??
    claudeMd.match(/(\d{3,})\s*\+\s*(\d+)\s*live/i);
  if (!m) {
    console.warn("sync-stats: could not parse test counts from CLAUDE.md; using 0/0");
    return { standard: 0, live: 0 };
  }
  return {
    standard: parseInt(m[1].replace(/,/g, ""), 10),
    live: parseInt(m[2], 10),
  };
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
  const total = v.core + v.plugins;
  const totalTests = v.standard + v.live;

  const body = `/**
 * GEODE Single Source of Truth — site-wide metrics.
 *
 * Auto-synced from the GEODE repo via \`npm run sync-stats\`.
 * Do not edit manually. Edit the GEODE repo and re-run sync.
 *
 * Last sync: ${today}
 */

export const GEODE_SOT = {
  version: "${v.version}",
  modules: {
    core: ${v.core},
    plugins: ${v.plugins},
    total: ${total},
  },
  tests: {
    standard: ${v.standard},
    live: ${v.live},
    total: ${totalTests},
  },
  releases: ${v.releases},
  since: "${v.since}",
  syncedAt: "${today}",
} as const;

export const GEODE_CUMULATIVE_KO =
  \`v\${GEODE_SOT.version} · \${GEODE_SOT.modules.total} 모듈 · \` +
  \`\${GEODE_SOT.tests.standard.toLocaleString()} 테스트 · \` +
  \`\${GEODE_SOT.releases} 릴리스 · 단독 개발 · since \${GEODE_SOT.since}\`;

export const GEODE_CUMULATIVE_EN =
  \`v\${GEODE_SOT.version} · \${GEODE_SOT.modules.total} modules · \` +
  \`\${GEODE_SOT.tests.standard.toLocaleString()} tests · \` +
  \`\${GEODE_SOT.releases} releases · solo · since \${GEODE_SOT.since}\`;
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

function main() {
  console.log(`sync-stats: reading from ${GEODE_REPO}`);
  const version = readVersion();
  const core = countModules("core");
  const plugins = countModules("plugins");
  const releases = countReleases();
  const since = readSince();
  const { standard, live } = readTestCounts();

  console.log(`  version  : ${version}`);
  console.log(`  modules  : ${core} core + ${plugins} plugins = ${core + plugins}`);
  console.log(`  tests    : ${standard} standard + ${live} live`);
  console.log(`  releases : ${releases}`);
  console.log(`  since    : ${since}`);

  writeSot({ version, core, plugins, standard, live, releases, since });
  console.log(`sync-stats: wrote ${SOT_FILE}`);

  const entries = parseChangelog();
  writeChangelog(entries);
  console.log(`sync-stats: wrote ${CHANGELOG_FILE} (${entries.length} entries)`);
}

main();
