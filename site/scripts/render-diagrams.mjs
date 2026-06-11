#!/usr/bin/env node
// render-diagrams — build-time Mermaid -> SVG pre-render.
//
// SoT:        site/diagrams/*.mmd            (git-tracked sources)
// Artifacts:  site/public/diagrams/<name>.svg (git-committed, served at
//             /geode/diagrams/<name>.svg via the Next.js basePath)
// Theme:      site/diagrams/mermaid-theme.json pins themeVariables to the
//             Axolotl Rose tokens in site/DESIGN.md section 2.
//
// This script is deliberately NOT part of `npm run build`. The rendered SVGs
// are committed artifacts; editing any .mmd requires re-running
//   npm run render-diagrams
// and committing the regenerated SVGs in the same change.
//
// Hand-authored signature SVGs (five-layer-stack.svg, two-loops.svg,
// champion-chain.svg) live directly in site/public/diagrams/ and are not
// touched by this script.

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const siteRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const sourceDir = path.join(siteRoot, "diagrams");
const outputDir = path.join(siteRoot, "public", "diagrams");
const themeConfig = path.join(sourceDir, "mermaid-theme.json");

mkdirSync(outputDir, { recursive: true });

// mermaid-cli rides puppeteer-core, which cannot auto-resolve a browser.
// Resolution order: PUPPETEER_EXECUTABLE_PATH env, then the newest chrome in
// the puppeteer cache (~/.cache/puppeteer, populated by
// `npx puppeteer browsers install chrome`). Fail loudly otherwise.
function resolveChromeExecutable() {
  const fromEnv = process.env.PUPPETEER_EXECUTABLE_PATH;
  if (fromEnv && existsSync(fromEnv)) return fromEnv;
  const cacheRoot = path.join(os.homedir(), ".cache", "puppeteer", "chrome");
  if (existsSync(cacheRoot)) {
    const installs = readdirSync(cacheRoot).sort().reverse();
    for (const install of installs) {
      const candidates = [
        path.join(
          cacheRoot,
          install,
          "chrome-mac-arm64",
          "Google Chrome for Testing.app",
          "Contents",
          "MacOS",
          "Google Chrome for Testing",
        ),
        path.join(cacheRoot, install, "chrome-mac-x64", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"),
        path.join(cacheRoot, install, "chrome-linux64", "chrome"),
      ];
      const found = candidates.find((candidate) => existsSync(candidate));
      if (found) return found;
    }
  }
  console.error(
    "no chrome for puppeteer. Run `npx puppeteer browsers install chrome` or set PUPPETEER_EXECUTABLE_PATH.",
  );
  process.exit(1);
}

const puppeteerConfig = path.join(os.tmpdir(), "geode-render-diagrams-puppeteer.json");
writeFileSync(puppeteerConfig, JSON.stringify({ executablePath: resolveChromeExecutable() }));

const mermaidSources = readdirSync(sourceDir)
  .filter((name) => name.endsWith(".mmd"))
  .sort();

if (mermaidSources.length === 0) {
  console.error(`no .mmd sources found in ${sourceDir}`);
  process.exit(1);
}

for (const sourceName of mermaidSources) {
  const outputName = sourceName.replace(/\.mmd$/, ".svg");
  console.log(`render diagrams/${sourceName} -> public/diagrams/${outputName}`);
  execFileSync(
    "npx",
    [
      "-y",
      "@mermaid-js/mermaid-cli",
      "-i",
      path.join(sourceDir, sourceName),
      "-o",
      path.join(outputDir, outputName),
      "-c",
      themeConfig,
      "-b",
      "transparent",
      "-p",
      puppeteerConfig,
    ],
    { stdio: "inherit" },
  );
}

console.log(`done: ${mermaidSources.length} diagram(s)`);
