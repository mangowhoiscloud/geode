#!/usr/bin/env node
// sync-stats.mjs — pull live GEODE metrics into src/data/geode/sot.ts.
//
// Reads from the GEODE repo at GEODE_REPO (default ../geode):
//   - pyproject.toml         → version
//   - filesystem (core/, plugins/) → module counts
//   - CHANGELOG.md           → release count (excludes [Unreleased])
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

// Auto-detect GEODE repo:
//   1) GEODE_REPO env var (explicit override)
//   2) ../pyproject.toml exists → we live inside geode/site/, so geode root = ..
//   3) ../geode/pyproject.toml exists → standalone portfolio repo next to geode
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
  // Match formats like: "Tests**: 4346 (+24 live)" or "Tests: 4346 (+24 live)"
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

function writeSot(v) {
  const today = new Date().toISOString().slice(0, 10);
  const total = v.core + v.plugins;
  const totalTests = v.standard + v.live;

  const body = `/**
 * GEODE Single Source of Truth — site-wide metrics.
 *
 * Auto-synced from /Users/mango/workspace/geode via \`npm run sync-stats\`.
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

/**
 * Cumulative one-liner for hero / chapter intros.
 * KO/EN parity. Single source. Never duplicate these numbers elsewhere.
 */
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
}

main();
