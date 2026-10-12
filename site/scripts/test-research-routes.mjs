import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { exportResearchRoutes, legacyPath, legacyRedirect, projectReader, readerPath } from "./export-research-routes.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const packageDir = join(root, "public", legacyPath.slice(7));
const source = readFileSync(join(packageDir, "index.html"), "utf8");
const projected = projectReader(source);
const receipt = JSON.parse(readFileSync(join(packageDir, "publication.json"), "utf8"));
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
assert.equal(sha(source), receipt.html_sha256, "Projection must consume the approved frozen source");
assert(projected.includes(`rel="canonical" href="https://mangowhoiscloud.github.io${readerPath}"`));
assert(!projected.includes("<base"), "Language and scene anchors stay at the canonical resource");
assert(!/(["'])assets\//.test(projected), "All relative asset references must be rebased");
const stage = html => html.slice(html.indexOf('<div class="stage"'), html.indexOf('<script>'));
assert(stage(source).length > 100000, "Exercise actual scene content");
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
console.log("Research route projection: frozen scenes/assets/PDFs, canonical, writer, and 16 compatibility URLs passed.");
