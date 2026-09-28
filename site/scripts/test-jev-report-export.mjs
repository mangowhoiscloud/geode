import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { EVIDENCE, PUBLIC_URL, approvedAssets, main, projectPreview, reusePdfs, safeRelative } from "./export-jev-report.mjs";

const sample = `<!doctype html><html><head><style>@font-face{src:url('assets/font.woff2')}</style></head><body data-film-edition="v20-final-candidate">
<header><span>Research film / Revised 25 September 2026</span><div class="toolbar"><button id="contentsButton">목차</button><button id="overviewButton">전체</button><button id="notesButton">연출 노트</button></div></header>
<main><div class="stage"><aside id="musicOverlay"><img src="assets/nemzzz-cover.jpg"></aside><section class="slide" data-note="private draft"><h2>Partial post-hoc analysis</h2><p>Past failure 0/6; synthetic limits</p><a href="https://arxiv.org/abs/2303.11366">Reflexion</a><a href="jev-update-plan.md">Production link</a><img src="assets/logo.svg"><g data-step="2">Result</g></section><aside class="toc-sound">Nemzzz soundtrack</aside></div><button id="previous">Back</button><button id="next">Next</button><aside id="notes"></aside><div class="below"><p>production draft</p></div></main><div id="overview"></div>
<details class="sources"><summary>Sources</summary><ul><li><a href="jev-film-sources.md">full source map</a></li><li><a href="https://arxiv.org/html/2303.11366v4">[N2] Reflexion</a></li><li><span>Historical record, not public</span></li></ul><p>Public source boundaries</p></details>
<script>const params=new URLSearchParams(location.search),english=params.get('lang')==='en';
// User-supplied MP3 decoded samples
const musicTracks=['Nemzzz'];
if(english){document.documentElement.lang='en';}
window.__film={pages:()=>[],go(){}};
document.getElementById('notes').textContent=slides[state.index].dataset.note;
document.getElementById('notesButton').onclick=()=>{state.notes=true;};
if(e.key.toLowerCase()==='n')document.getElementById('notesButton').click();
if(['timeline','mix'].includes(params.get('music'))){const filmSource='review-with-music.mp4';}
</script></body></html>`;
const settings = { date: "2026-09-28", assets: new Map([["assets/font.woff2", "assets/font.woff2"], ["assets/logo.svg", "assets/logo.svg"], ["assets/nemzzz-cover.jpg", "assets/nemzzz-cover.jpg"]]) };

test("keeps the existing build contract, scholarship and negative evidence", () => {
  const output = projectPreview(sample, settings);
  for (const item of ["window.__film=", 'data-step="2"', "Partial post-hoc analysis", "Past failure 0/6; synthetic limits", "Nemzzz soundtrack", "assets/nemzzz-cover.jpg", "https://arxiv.org/abs/2303.11366", EVIDENCE + "README.md"]) assert(output.includes(item), item);
  for (const item of ["musicTracks", "notesButton", "data-note", "jev-update-plan.md", "production draft", "v20-final-candidate"]) assert(!output.includes(item), item);
  assert(output.includes('href="report-ko.pdf" download'));
  assert(output.includes(".href='report-en.pdf'"));
  assert(output.includes('href="?lang=ko"') && output.includes('href="?lang=en"'));
  assert(output.includes(`rel="canonical" href="${PUBLIC_URL}"`));
  assert(output.includes('class="reader-download"') && output.includes('aria-current="page"'));
  assert(output.indexOf('id="contentsButton"') < output.indexOf("<main>"));
  assert(output.includes("updateReaderNavigation") && output.includes("a.lang+'#'+s.id"));
  assert(output.includes('aria-controls="readerScenes"') && output.includes("readerToc.showModal()"));
});

test("rejects unapproved assets, local paths and unapproved video hosts", () => {
  assert.throws(() => projectPreview(sample, { ...settings, assets: new Map() }), /Unapproved/);
  assert.throws(() => projectPreview(sample.replace("Partial post-hoc analysis", "file:///private/result.json"), settings), /Private/);
  assert.throws(() => projectPreview(sample, { ...settings, videoUrl: "https://example.com/film.mp4" }), /approved public video/);
});

test("sanitizes links that language switching restores from encoded markup", () => {
  const translated = sample.replace("<h2>", '<p data-en="See &lt;a href=&quot;local-notes.md&quot;&gt;notes&lt;/a&gt; and &lt;a href=&quot;jev-film-sources.md&quot;&gt;full source map&lt;/a&gt;"></p><h2>');
  const output = projectPreview(translated, settings);
  assert(!output.includes("local-notes.md"));
  assert(!output.includes("jev-film-sources.md"));
  assert(output.includes(`href=&quot;${EVIDENCE}README.md&quot;`));
});

test("sources preserve destinations and boundaries in a native sheet without nested disclosure", () => {
  const output = projectPreview(sample, settings);
  assert(!/<details\b|<summary\b/.test(output));
  for (const text of ['id="readerSourcesTitle"', "Public source boundaries", "Historical record, not public", "https://arxiv.org/html/2303.11366v4", EVIDENCE + "SCORING.md", EVIDENCE + "REPRODUCE.md"]) assert(output.includes(text), text);
  assert(output.includes('<dialog class="sources reader-sources"'));
  assert.equal((output.match(/id="openReaderSources"/g) || []).length, 1);
  assert(output.includes('aria-haspopup="dialog"') && output.includes('readerSources.showModal()'));
  assert(output.includes("readerSources.addEventListener('keydown',e=>{e.stopPropagation()"));
  assert(output.includes("location.hash==='#readerSources'"));
  assert(output.includes('<span>DATA</span> <span') && output.includes('<span>N2</span> <span'));
  assert.throws(() => projectPreview(sample.replace("[N2]", "[UNKNOWN]"), settings), /Unclassified public source/);
});

test("explicit public media remains a link, never autoplay or audio", () => {
  const output = projectPreview(sample, { ...settings, videoUrl: "https://www.youtube.com/watch?v=approved" });
  assert(output.includes("Watch film"));
  assert(!output.includes("autoplay") && !output.includes("<audio"));
});

test("asset paths cannot escape the package or collide through normalization", () => {
  for (const path of ["../secret", "/tmp/secret", "assets/../secret", "assets\\secret", "assets//secret", "./secret", "assets/image?x", "assets/image#x", "assets/a b"]) assert.throws(() => safeRelative(path));
  assert.equal(safeRelative("assets/fonts/font.woff2"), "assets/fonts/font.woff2");
});

test("asset-package supports fresh PDF preflight without original aliases or an export", async () => {
  const directory = mkdtempSync(join(tmpdir(), "jev-asset-package-"));
  const digest = bytes => createHash("sha256").update(bytes).digest("hex");
  try {
    const packageDir = join(directory, "package"), out = join(directory, "not-created");
    const rows = [...settings.assets].map(([source, target]) => ({ source, target, sha256: digest(source) }));
    for (const row of rows) {
      const file = join(packageDir, row.target);
      mkdirSync(dirname(file), { recursive: true });
      writeFileSync(file, row.source);
    }
    writeFileSync(join(packageDir, "publication.json"), JSON.stringify({ schema: "jev-report-publication-v1", assets: rows.map(row => ({ path: row.target, sha256: row.sha256 })) }));
    writeFileSync(join(directory, "source.html"), sample);
    writeFileSync(join(directory, "assets.json"), JSON.stringify(rows));
    assert.throws(() => approvedAssets(directory, rows), /ENOENT/);
    assert.equal(approvedAssets(directory, rows, packageDir).length, rows.length);
    await assert.rejects(main([
      "--source", join(directory, "source.html"), "--source-sha", digest(sample),
      "--assets", join(directory, "assets.json"), "--asset-package", packageDir,
      "--out", out, "--date", settings.date, "--pdf", "--expected-pages", "0",
    ]), /PDF output requires --expected-pages/);
    assert(!existsSync(out), "Preflight must not create output or launch the PDF renderer");
    assert.throws(() => approvedAssets(directory, [{ ...rows[0], sha256: "0".repeat(64) }], packageDir), /not approved by the package receipt/);
    writeFileSync(join(packageDir, rows[0].target), "changed bytes");
    assert.throws(() => approvedAssets(directory, rows, packageDir), /Asset digest mismatch/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("approved package assets retain the four replay digests without reading lost aliases", () => {
  const directory = fileURLToPath(new URL("../public/resaerch/jev-system1-offloading/", import.meta.url));
  const all = JSON.parse(readFileSync(new URL("../../docs/research/jev-report-assets.json", import.meta.url), "utf8"));
  const rows = all.filter(row => /motion-v20\/(?:u8c|i6-natural)-[ab]\.mp4$/.test(row.source));
  assert.equal(rows.length, 4);
  const loaded = approvedAssets(join(directory, "absent-original-root"), rows, directory);
  assert.deepEqual(loaded.map(row => row.source), rows.map(row => join(directory, row.target)));
  assert.deepEqual(loaded.map(row => row.sha256), rows.map(row => row.sha256));
});

test("the checked-in report matches its frozen asset and PDF receipt", () => {
  const root = new URL("../public/resaerch/jev-system1-offloading/", import.meta.url);
  const receipt = JSON.parse(readFileSync(new URL("publication.json", root), "utf8"));
  assert.equal(receipt.source_sha256, "37d8e11cabce01fe368d8c9f6d623a28a4ee7965d12bc8129e7efb529a73ff34");
  assert.deepEqual(receipt.pdfs.map(pdf => [pdf.language, pdf.pages.length]), [["ko", 81], ["en", 81]]);
  assert.deepEqual(receipt.pdfs[0].pages, receipt.pdfs[1].pages);
  assert.deepEqual(receipt.pdfs.map(pdf => pdf.sha256), ["37d1fca8d821eea0ad0febc081f1a97fbf4a25cad165e706361711ccbafe7dc2", "da05703b5052dc029db7ccdab94643f2c20322aa1b639b88009b9fb08c17ce92"]);
  assert.equal(receipt.pdf_generator_sha256, "2d3b336ba98802f1d7c876589fdd19357cb26adcdf9631fd9a3fffe19810956f");
  assert.equal(createHash("sha256").update(readFileSync(new URL("export-jev-report.mjs", import.meta.url))).digest("hex"), receipt.generator_sha256);
  const files = [{ path: "index.html", sha256: receipt.html_sha256 }, ...receipt.assets, ...receipt.pdfs.map(pdf => ({ ...pdf, path: pdf.file }))];
  const approved = JSON.parse(readFileSync(new URL("../../docs/research/jev-report-assets.json", import.meta.url), "utf8"));
  assert.deepEqual(receipt.assets.map(({ path, sha256 }) => [path, sha256]).sort(), approved.map(({ target, sha256 }) => [target, sha256]).sort());
  const inventory = readdirSync(root, { recursive: true }).filter(path => !lstatSync(new URL(path, root)).isDirectory());
  assert.deepEqual(inventory.sort(), ["publication.json", ...files.map(entry => entry.path)].sort());
  assert(readFileSync(new URL("publication.json", root)).length < 100 * 1024 * 1024);
  for (const entry of files) {
    safeRelative(entry.path);
    assert(lstatSync(new URL(entry.path, root)).isFile(), entry.path);
    const bytes = readFileSync(new URL(entry.path, root));
    assert(bytes.length < 100 * 1024 * 1024, entry.path);
    assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.sha256, entry.path);
  }
});

test("PDF reuse rejects a changed source, inventory, asset set or slide", () => {
  const root = new URL("../public/resaerch/jev-system1-offloading/", import.meta.url), directory = fileURLToPath(root);
  const receipt = JSON.parse(readFileSync(new URL("publication.json", root), "utf8"));
  const html = readFileSync(new URL("index.html", root), "utf8");
  const reused = reusePdfs(directory, receipt.source_sha256, 81, receipt.assets, html);
  assert.deepEqual(reused.pdfs, receipt.pdfs);
  assert.equal(reused.pdf_generator_sha256, receipt.pdf_generator_sha256);
  assert.throws(() => reusePdfs(directory, "0".repeat(64), 81, receipt.assets, html), /same approved source/);
  assert.throws(() => reusePdfs(directory, receipt.source_sha256, 80, receipt.assets, html), /page count/);
  assert.throws(() => reusePdfs(directory, receipt.source_sha256, 81, receipt.assets.slice(1), html), /approved assets/);
  assert.throws(() => reusePdfs(directory, receipt.source_sha256, 81, receipt.assets, html.replace('id="cover"', 'id="changed-cover"')), /slide content/);
  assert.throws(() => reusePdfs(directory, receipt.source_sha256, 81, receipt.assets, html.replace('id="v22-reading-guide"', 'id="changed-guide"')), /slide content/);
});
