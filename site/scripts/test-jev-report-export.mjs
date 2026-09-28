import assert from "node:assert/strict";
import test from "node:test";
import { lstatSync, readFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { EVIDENCE, projectPreview, safeRelative } from "./export-jev-report.mjs";

const sample = `<!doctype html><html><head><style>@font-face{src:url('assets/font.woff2')}</style></head><body data-film-edition="v20-final-candidate">
<header><span>Research film / Revised 25 September 2026</span><div class="toolbar"><button id="contentsButton">목차</button><button id="overviewButton">전체</button><button id="notesButton">연출 노트</button></div></header>
<main><div class="stage"><aside id="musicOverlay"><img src="assets/nemzzz-cover.jpg"></aside><section class="slide" data-note="private draft"><h2>Partial post-hoc analysis</h2><p>Past failure 0/6; synthetic limits</p><a href="https://arxiv.org/abs/2303.11366">Reflexion</a><a href="jev-update-plan.md">Production link</a><img src="assets/logo.svg"><g data-step="2">Result</g></section><aside class="toc-sound">Nemzzz soundtrack</aside></div><button id="previous">Back</button><button id="next">Next</button><aside id="notes"></aside><div class="below"><p>production draft</p></div></main><div id="overview"></div>
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

test("explicit public media remains a link, never autoplay or audio", () => {
  const output = projectPreview(sample, { ...settings, videoUrl: "https://www.youtube.com/watch?v=approved" });
  assert(output.includes("Watch film"));
  assert(!output.includes("autoplay") && !output.includes("<audio"));
});

test("asset paths cannot escape the package or collide through normalization", () => {
  for (const path of ["../secret", "/tmp/secret", "assets/../secret", "assets\\secret", "assets//secret", "./secret", "assets/image?x", "assets/image#x", "assets/a b"]) assert.throws(() => safeRelative(path));
  assert.equal(safeRelative("assets/fonts/font.woff2"), "assets/fonts/font.woff2");
});

test("the checked-in report matches its frozen asset and PDF receipt", () => {
  const root = new URL("../public/research/jev/", import.meta.url);
  const receipt = JSON.parse(readFileSync(new URL("publication.json", root), "utf8"));
  assert.equal(receipt.source_sha256, "708b2e7b6526c1c6ed4b8aa6c4dafea6618308ca6bed80724eb4b11ac8417e8a");
  assert.deepEqual(receipt.pdfs.map(pdf => [pdf.language, pdf.pages.length]), [["ko", 82], ["en", 82]]);
  assert.deepEqual(receipt.pdfs[0].pages, receipt.pdfs[1].pages);
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
