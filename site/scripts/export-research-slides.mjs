// Publish only the reviewed deck, preserving the canonical research/ bytes.
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";

const filename = "jevdb-seminar-v25.pptx";
const source = new URL(`../../research/${filename}`, import.meta.url);
const destination = new URL("../public/research/", import.meta.url);
const expected = "83d9b2ca13bc7af604927b885b0cce3ba6a43ca96e86b657f4771ae69ac51d8c";
const bytes = await readFile(source);
const actual = createHash("sha256").update(bytes).digest("hex");
if (actual !== expected) throw new Error(`Unreviewed research slides: ${actual}`);
if (!process.argv.includes("--check")) {
  await mkdir(destination, { recursive: true });
  await writeFile(new URL(filename, destination), bytes);
}
console.log(`Research slides verified: ${filename} (${bytes.length} bytes)`);
