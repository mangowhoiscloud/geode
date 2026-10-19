// Publish only the reviewed deck, preserving the canonical research/ bytes.
import { createHash } from "node:crypto";
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";

const filename = "jevdb-seminar-v25.pptx";
const source = new URL(`../../research/${filename}`, import.meta.url);
const destination = new URL("../public/research/", import.meta.url);
const expected = "83d9b2ca13bc7af604927b885b0cce3ba6a43ca96e86b657f4771ae69ac51d8c";
const bytes = await readFile(source);
const actual = createHash("sha256").update(bytes).digest("hex");
if (actual !== expected) throw new Error(`Unreviewed research slides: ${actual}`);
const preview = new URL("../public/research/jevdb-slides-v25/", import.meta.url);
const manifest = JSON.parse(await readFile(new URL("manifest.json", preview), "utf8"));
const scenes = JSON.parse(await readFile(new URL("../src/data/geode/jevdb-slides.json", import.meta.url), "utf8"));
assert.equal(manifest.pptx_sha256, expected, "Reader must reference the published PPT");
assert.equal(manifest.slides.length, 19);
assert.equal(scenes.length, manifest.slides.length);
for (const [index, item] of manifest.slides.entries()) {
  assert.equal(item.image, `${String(index + 1).padStart(2, "0")}.png`);
  assert.equal(scenes[index].image, item.image);
  assert.equal(scenes[index].number, index + 1);
  assert.equal(scenes[index].sha256, item.sha256);
  const image = await readFile(new URL(item.image, preview));
  assert.equal(image.length, item.bytes);
  assert.equal(createHash("sha256").update(image).digest("hex"), item.sha256, `Changed slide: ${item.image}`);
}
if (!process.argv.includes("--check")) {
  await mkdir(destination, { recursive: true });
  await writeFile(new URL(filename, destination), bytes);
}
console.log(`Research slides verified: ${filename} (${bytes.length} bytes)`);
console.log(`Reader previews verified: ${manifest.slides.length} unchanged v25 images`);
