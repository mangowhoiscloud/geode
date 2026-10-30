import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { exportResearchRoutes, legacyPath, legacyRedirect, projectReader, readerPath } from "./export-research-routes.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const packageDir = join(root, "public", legacyPath.slice(7));
const source = readFileSync(join(packageDir, "index.html"), "utf8");
const projected = projectReader(source);
const receipt = JSON.parse(readFileSync(join(packageDir, "publication.json"), "utf8"));
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const selection = {};
const selectionCode = ts.transpileModule(readFileSync(join(root, "src/lib/research-selection.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
new Function("exports", selectionCode)(selection);
for (const [hash, expected, index] of [
  ["", "", 0], ["#research", "", 0], ["#geode", "", 0], ["#research-geode", "", 0],
  ["#jev", "#jev", 1], ["#research-jev", "#jev", 1],
  ["#jevdb", "#jevdb", 2], ["#jevdb-paper-review", "#jevdb", 2],
  ["#unrelated", "#unrelated", -1], ["#research-geode?lang=en", "#research-geode?lang=en", -1],
]) {
  for (const search of ["", "?lang=ko", "?lang=en&source=shared"]) {
    const url = new URL(`https://mangowhoiscloud.github.io/geode/research/${search}${hash}`);
    const normalized = selection.normalizeResearchSelection(url);
    assert.equal(normalized.hash, expected);
    assert.equal(normalized.search, search, "Selection must not consume or reorder the language query");
    assert.equal(normalized.pathname, url.pathname, "Selection cannot become a resource route");
    assert.equal(url.hash, hash, "Normalization must not mutate its input");
    assert.equal(selection.researchSelectionIndex(hash), index);
    assert.equal(selection.normalizeResearchSelection(normalized).href, normalized.href);
  }
}
assert.equal(sha(source), receipt.html_sha256, "Projection must consume the approved frozen source");
assert(projected.includes(`rel="canonical" href="https://mangowhoiscloud.github.io${readerPath}"`));
assert(!projected.includes("<base"), "Language and scene anchors stay at the canonical resource");
assert(projected.includes("href='/geode/research/'+(english?'?lang=en':'')+'#jev';"), "Jev return links retain language and the concise collection selection");
assert(!/(["'])assets\//.test(projected), "All relative asset references must be rebased");
const stage = html => html.slice(html.indexOf('<div class="stage"'), html.indexOf('<script>'));
assert(stage(source).length > 100000, "Exercise actual scene content");
// Native scroll input must not select scenes; the archived film stays intact.
assert(!/document\.addEventListener\(['"]keydown/.test(projected));
assert(!/addEventListener\(['"](?:wheel|touchstart|touchmove|touchend)['"]/.test(projected));
assert(!/\.(?:scrollIntoView|scrollTo|scrollBy)\(/.test(projected));
assert(!/(?:touch-action|overscroll-behavior)\s*:/.test(projected));
assert(!/html[^{}]*\{[^}]*overflow\s*:\s*hidden/.test(projected));
for (const action of ["document.getElementById('previous').onclick=()=>advance(-1)",
  "document.getElementById('next').onclick=()=>advance(1)", "window.__film="])
  assert(projected.includes(action), `Explicit publication control remains: ${action}`);

assert.equal(stage(projected).replaceAll(legacyPath, ""), stage(source), "No scene text, figures, or ordering changes");
for (const item of [...receipt.assets, ...receipt.pdfs]) {
  const path = item.path ?? item.file;
  assert.equal(sha(readFileSync(join(packageDir, path))), item.sha256, `Frozen artifact: ${path}`);
}
for (const search of ["", "?lang=ko", "?lang=en", "?next=https://example.com/&lang=en"]) {
  for (const hash of ["", "#cover", "#v3-e2e-injected", "#readerSources"]) {
    let replaced;
    const anchor = {};
    runInNewContext(legacyRedirect().match(/<script>([^]*?)<\/script>/)[1], {
      location: { search, hash, replace: target => { replaced = target; } },
      document: { getElementById: () => anchor },
    });
    assert.equal(replaced, readerPath + search + hash);
    assert.equal(anchor.href, replaced);
  }
}
const temporary = mkdtempSync(join(tmpdir(), "geode-routes-"));
try {
  exportResearchRoutes(temporary);
  assert.equal(readFileSync(join(temporary, readerPath.slice(7), "index.html"), "utf8"), projected);
  assert.equal(readFileSync(join(temporary, legacyPath.slice(7), "index.html"), "utf8"), legacyRedirect());
} finally { rmSync(temporary, { recursive: true }); }
console.log("Research routes: 30 selection cases, frozen scenes/assets/PDFs, canonical, writer, and 16 compatibility URLs passed.");
