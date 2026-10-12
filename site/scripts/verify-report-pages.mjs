// Verify the source-to-reader boundary without invoking a renderer in CI.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";

const publicRoot = new URL("../public/", import.meta.url);
const root = new URL("research/geode-report/", publicRoot);
const read = (path) => readFileSync(path);
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
// Independent identity of the PDFs at source commit 7374167; a receipt cannot repin it.
const sourceHashes = {
  ko: "af5dfb59a511714bb2b152e2a06f3e5d1db8af6afa598aec4734c24d0036d3f0",
  en: "bd5332dbb0b35094c934ab803c63cc47ab6c27e217ac0c22367cdc73212284c0",
};
const manifest = JSON.parse(read(new URL("manifest.json", root)));
const textData = read(new URL("../src/data/geode/report-pages.json", import.meta.url));
assert(textData.length < 2 * 1024 * 1024, "Bound the preserved source transcript");
assert.equal(sha(textData), manifest.text_sha256);
const editions = JSON.parse(textData);
assert.equal(manifest.schema, "geode-report-pages-v1");
assert.equal(manifest.source_commit, "737416726cf68bde2ad7e7838133715a0a4e89c4");
assert.equal(manifest.images.length, 184);
for (const language of ["ko", "en"]) {
  const edition = editions[language];
  const pdf = language === "ko" ? "report.pdf" : "report-en.pdf";
  assert.equal(edition.pdf, `/geode/${pdf}`);
  assert.equal(manifest.sources[language].sha256, sourceHashes[language], "Frozen PDF identity");
  assert.equal(sha(read(new URL(pdf, publicRoot))), manifest.sources[language].sha256, pdf);
  assert.equal(edition.sha256, manifest.sources[language].sha256);
  assert.equal(edition.pages.length, 92);
  assert.equal(readdirSync(new URL(`${language}/`, root)).length, 92);
  for (const [index, page] of edition.pages.entries()) {
    const filename = `${String(index + 1).padStart(2, "0")}.webp`;
    assert.equal(page.number, index + 1);
    assert.equal(page.image, filename);
    assert(page.title.trim() && page.text.trim(), `Missing text: ${language}/${filename}`);
    const record = manifest.images.find(item => item.path === `${language}/${filename}`);
    assert(record, `Missing manifest record: ${language}/${filename}`);
    const image = read(new URL(record.path, root));
    assert(image.length < 500 * 1024, record.path);
    assert.equal(sha(image), record.sha256, record.path);
    assert.equal(image.length, record.bytes);
    assert.equal(record.width, 1600);
    assert.equal(record.height, 900);
  }
}
const previews = JSON.parse(read(new URL("research/previews/manifest.json", publicRoot)));
assert.equal(previews.length, 2);
for (const item of previews) {
  assert.equal(item.page, 1);
  assert.equal(sha(read(new URL(item.source_pdf, publicRoot))), item.source_sha256);
  assert.equal(sha(read(new URL(`research/previews/${item.path}`, publicRoot))), item.sha256);
}
console.log("Report reader: 2 unchanged PDFs, 184 page images, and 2 source-bound Jev covers verified");
