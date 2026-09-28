// Package an approved film source, not a second slide or metric generator.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

export const EVIDENCE = "https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/3bcf4044eb5c2411dd48122d672aef72a83fb30e/reports/e2e-validation/jev-v3-20260927/";
const PUBLIC_URL = "https://mangowhoiscloud.github.io/geode/research/jev/";
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const escape = (text) => text.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const privatePath = /(?:file:\/\/|\/(?:Users|home)\/|localhost|127\.0\.0\.1|research-team-20260926)/i;

export function safeRelative(path) {
  assert(typeof path === "string" && path.length > 0 && !isAbsolute(path), "Asset paths must be relative");
  assert(!/[\\?#\s]/.test(path) && !path.split("/").some((part) => !part || part === ".." || part === "."), "Unsafe asset path");
  return path;
}

export function projectPreview(source, { date, assets, videoUrl = null }) {
  assert(/^\d{4}-\d{2}-\d{2}$/.test(date), "A publication date is required");
  assert(source.includes("window.__film=") && source.includes('id="overview"'), "Unsupported preview contract");
  if (videoUrl) assert(/^https:\/\/(?:www\.)?(?:youtube\.com|youtu\.be)\//.test(videoUrl), "Use the approved public video URL");
  let html = source
    .replaceAll("jev-film-sources.md", EVIDENCE + "README.md")
    .replaceAll("Full claim/source map and historical receipts", "Public study evidence and archived records")
    .replaceAll("full source map", "public study evidence").replaceAll("전체 출처 지도", "공개 연구 근거")
    .replace(/<!--[^]*?-->/g, "")
    .replace(/\sdata-note(?:-[\w-]+)?="[^"]*"/g, "")
    .replace(/\sdata-(?:replay-manifest|film-edition)="[^"]*"/g, "")
    .replace(/<button\b[^>]*id="notesButton"[^>]*>[^]*?<\/button>/, "")
    .replace(/<aside\b[^>]*id="notes"[^>]*>[^]*?<\/aside>/, "")
    .replace(/\/\/ User-supplied MP3[^]*?(?=if\(english\))/, "")
    .replace(/if\(\['timeline','mix'\]\.includes\(params\.get\('music'\)\)\)\{[^]*?(?=<\/script>)/, "")
    .replace("['timeline','mix'].includes(params.get('music'))||", "")
    .replace("document.getElementById('notes').textContent=slides[state.index].dataset.note;", "")
    .replace(/document\.getElementById\('notesButton'\)\.onclick=\(\)=>\{[^]*?\};/, "")
    .replace("if(e.key.toLowerCase()==='n')document.getElementById('notesButton').click();", "")
    .replaceAll(" · N Notes", "").replaceAll(" · N 노트", "")
    .replace(/Research film \/ Revised [^<]+/, `Research report / ${date}`)
    .replace(/<div class="below">[^]*?(?=<\/main>)/, `<div class="below"><p data-en="One source for the interactive report and both PDFs. Historical failures, partial analyses and synthetic-task limits remain separate.">웹 보고서와 두 언어 PDF는 같은 원고를 사용합니다. 과거 실패·부분 분석·합성 과제의 한계는 별도로 보존합니다.</p><p><a href="${EVIDENCE}README.md" data-en="Study evidence">연구 근거</a> · <a href="${EVIDENCE}SCORING.md" data-en="Scoring rules">채점 기준</a> · <a href="${EVIDENCE}REPRODUCE.md" data-en="Reproduction guide">재현 안내</a></p></div>`);
  // Preserve scholarly/public evidence links; local production destinations are not public evidence.
  html = html.replace(/<a\b([^>]*?)href="([^"]*)"([^>]*)>([^]*?)<\/a>/g, (whole, before, href, after, text) => {
    if (/^(?:https:\/\/|#|\?)/.test(href)) return whole;
    return `<span${before}${after}>${text}</span>`;
  });
  html = html.replace(/&lt;a\b[^]*?href=&quot;([^]*?)&quot;[^]*?&gt;([^]*?)&lt;\/a&gt;/g, (whole, href, text) => /^(?:https:\/\/|#|\?)/.test(href) ? whole : text);
  html = html.replace(/\b(src|poster|data-src-en|data-poster-en)="([^"]+)"/g, (whole, attr, value) => {
    if (value.startsWith("data:")) return whole;
    assert(assets.has(value), `Unapproved media reference: ${value}`);
    return `${attr}="${escape(assets.get(value))}"`;
  }).replace(/url\((['"]?)([^)'"\s]+)\1\)/g, (whole, quote, value) => {
    if (value.startsWith("#") || value.startsWith("data:")) return whole;
    assert(assets.has(value), `Unapproved CSS asset: ${value}`);
    return `url('${assets.get(value)}')`;
  });
  html = html.replace(/<video\b/g, "<video muted");
  const controls = `<a href="?lang=ko" lang="ko">한국어</a><a href="?lang=en" lang="en">English</a><a id="reportDownload" href="report-ko.pdf" download data-en="Download PDF">PDF 다운로드</a>${videoUrl ? `<a href="${escape(videoUrl)}" data-en="Watch film">영상 보기</a>` : ""}`;
  html = html.replace('<div class="toolbar">', `<div class="toolbar">${controls}`);
  html = html.replace("if(english){", "if(english){document.getElementById('reportDownload').href='report-en.pdf';");
  html = html.replace("</script>", "document.querySelectorAll('.toolbar a[lang]').forEach(a=>a.onclick=()=>{a.href='?lang='+a.lang+'#'+document.querySelector('.stage>.slide.active').id;});\n</script>");
  html = html.replace("</head>", `<link rel="canonical" href="${PUBLIC_URL}"><meta name="description" content="Jev decision offloading: an evidence-bound bilingual research report."><style id="public-report-controls">.toolbar{flex-wrap:wrap}.toolbar a{display:inline-flex;align-items:center;min-height:38px;padding:7px 12px;border:1px solid var(--hairline);border-radius:3px;text-decoration:none}.toolbar a[download]{font-weight:600}.masthead .eyebrow{letter-spacing:0;text-transform:none}</style></head>`);
  assert(!privatePath.test(html), "Private/local path remains in public HTML");
  assert(!/review-with-music|musicTracks|musicFilm|notesButton|data-note=/i.test(html), "Production-only content remains");
  assert(!/<audio\b/i.test(html), "The report links to the music edition; it does not embed a soundtrack");
  // A source change must not silently remove the report's navigation/build API.
  for (const token of ["window.__film=", 'id="contentsButton"', 'id="overviewButton"', 'id="previous"', 'id="next"']) assert(html.includes(token), `Lost control: ${token}`);
  return html;
}

function approvedAssets(root, rows) {
  assert(Array.isArray(rows) && rows.length > 0, "An explicit approved asset list is required");
  const paths = new Set();
  return rows.map((row) => {
    safeRelative(row.source); safeRelative(row.target);
    assert(/\.(?:otf|ttf|woff2|svg|png|jpg|txt|mp4)$/i.test(row.target), "Unsupported asset type");
    assert(!paths.has(row.target), "Duplicate public asset target"); paths.add(row.target);
    const source = realpathSync(join(root, row.source));
    const outside = relative(root, source).startsWith("..") || isAbsolute(relative(root, source));
    assert(!outside || row.dereference === true, `External asset alias needs explicit approval: ${row.source}`);
    const bytes = readFileSync(source);
    assert(sha(bytes) === row.sha256, `Asset digest mismatch: ${row.source}`);
    assert(bytes.length < 100 * 1024 * 1024, "Asset exceeds regular Git file limit");
    if (/\.mp4$/i.test(source)) {
      const check = spawnSync("ffprobe", ["-v", "error", "-show_entries", "stream=codec_type", "-of", "json", source], { encoding: "utf8" });
      assert(check.status === 0, "ffprobe is required to verify replay streams");
      assert(!JSON.parse(check.stdout).streams.some((stream) => stream.codec_type === "audio"), "Only verified audio-free replay assets are allowed");
    }
    return { ...row, sourceRef: row.source, source, bytes: bytes.length };
  });
}

export async function freezeReplayFrames(page) {
  for (const video of await page.locator('.stage>.slide.active video').elementHandles()) {
    let src = await video.getAttribute('poster');
    if (!src) {
      await video.evaluate(async element => {
        element.controls = false; element.muted = true; element.pause();
        if (element.readyState < 2) await new Promise((resolve, reject) => {
          const timer = setTimeout(() => reject(Error('Replay first frame did not load')), 15000);
          element.addEventListener('loadeddata', () => { clearTimeout(timer); resolve(); }, { once: true });
          element.addEventListener('error', () => { clearTimeout(timer); reject(Error('Replay decode failed')); }, { once: true });
          element.preload = 'auto'; element.load();
        });
      });
      src = 'data:image/png;base64,' + (await video.screenshot({ type: 'png' })).toString('base64');
    }
    await video.evaluate((element, src) => {
      const still = document.createElement('img'), style = getComputedStyle(element);
      still.src = src; still.alt = element.getAttribute('aria-label') || 'Recorded replay frame';
      still.className = element.className;
      for (const key of ['position', 'top', 'right', 'bottom', 'left', 'display', 'width', 'height', 'margin', 'padding', 'object-fit', 'border', 'border-radius', 'background']) still.style.setProperty(key, style.getPropertyValue(key));
      element.replaceWith(still);
    }, src);
  }
  await page.evaluate(() => Promise.all([...document.querySelectorAll('.stage>.slide.active img')].map(image => image.decode())));
}

async function exportPdfs(out, expectedPages) {
  // Use the existing/bundled browser and PDF packages via NODE_PATH; install nothing.
  const require = createRequire(import.meta.url);
  const { chromium } = require("playwright");
  const { PDFDocument } = require("pdf-lib");
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const editions = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
    await context.route("**/*", (route) => /^(?:file:|data:)/.test(route.request().url()) ? route.continue() : route.abort());
    for (const lang of ["ko", "en"]) {
      console.log(`Exporting ${lang}: ${expectedPages} settled builds`);
      const page = await context.newPage(), errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(pathToFileURL(join(out, "index.html")).href + `?render=1&lang=${lang}`, { waitUntil: "load" });
      await page.emulateMedia({ media: "screen" });
      const inventory = await page.evaluate(async () => {
        await Promise.all([...document.fonts].map((font) => font.load())); await document.fonts.ready;
        return window.__film.pages();
      });
      const localLinks = await page.evaluate(() => [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href')).filter(href => !/^(?:https:\/\/|#|\?|report-(?:ko|en)\.pdf$)/.test(href)));
      assert.deepEqual(localLinks, [], "Unpublished link restored after language selection");
      assert.equal(inventory.reduce((n, scene) => n + scene.steps, 0), expectedPages, "Unexpected build count");
      const pdf = await PDFDocument.create(), pages = [];
      for (const scene of inventory) for (let step = 1; step <= scene.steps; step++) {
        await page.evaluate(({ id, step }) => {
          window.__film.go(id, step);
          document.querySelectorAll("video").forEach((video) => { video.pause(); video.muted = true; });
          for (const animation of document.getAnimations()) if (Number.isFinite(animation.effect?.getComputedTiming().endTime)) animation.finish();
        }, { id: scene.id, step });
        await freezeReplayFrames(page);
        const bytes = await page.pdf({ width: "1920px", height: "1080px", printBackground: true, preferCSSPageSize: false, margin: { top: "0", bottom: "0", left: "0", right: "0" } });
        const single = await PDFDocument.load(bytes);
        assert.equal(single.getPageCount(), 1, `${lang}/${scene.id}/${step} spans multiple PDF pages`);
        for (const copied of await pdf.copyPages(single, [0])) pdf.addPage(copied);
        pages.push({ scene_id: scene.id, build: step });
        if (pages.length % 20 === 0) console.log(`${lang}: ${pages.length}/${expectedPages} pages`);
      }
      assert.deepEqual(errors, [], "Browser errors during PDF export");
      assert.equal(pdf.getPageCount(), expectedPages);
      const file = `report-${lang}.pdf`, bytes = await pdf.save();
      assert(bytes.length < 100 * 1024 * 1024, "PDF exceeds regular Git file limit");
      writeFileSync(join(out, file), bytes);
      editions.push({ language: lang, file, sha256: sha(bytes), bytes: bytes.length, pages });
      await page.close();
    }
    assert.deepEqual(editions[0].pages, editions[1].pages, "KO/EN build inventories differ");
  } finally { await browser.close(); }
  return editions;
}

export async function main(args) {
  const { values } = parseArgs({ args, options: {
    source: { type: "string" }, "source-sha": { type: "string" }, assets: { type: "string" }, out: { type: "string" },
    date: { type: "string" }, "video-url": { type: "string" }, pdf: { type: "boolean", default: false },
    "expected-pages": { type: "string" }, release: { type: "boolean", default: false },
  } });
  for (const key of ["source", "source-sha", "assets", "out", "date"]) assert(values[key], `Missing --${key}`);
  const sourcePath = realpathSync(resolve(values.source)), source = readFileSync(sourcePath);
  assert.equal(sha(source), values["source-sha"], "Source changed since approval");
  const out = resolve(values.out), publicRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../public");
  if (out === publicRoot || out.startsWith(publicRoot + "/")) assert(values.release && values.pdf, "Public output requires explicit --release and --pdf");
  assert(!existsSync(out), "Refuse to overwrite an existing output directory");
  const rows = approvedAssets(dirname(sourcePath), JSON.parse(readFileSync(values.assets, "utf8")));
  const assets = new Map(rows.map((row) => [row.sourceRef, row.target]));
  assert.equal(assets.size, rows.length, "Duplicate source asset");
  const html = projectPreview(source.toString("utf8"), { date: values.date, assets, videoUrl: values["video-url"] });
  const count = Number(values["expected-pages"]);
  if (values.pdf) assert(Number.isInteger(count) && count > 0, "--pdf requires --expected-pages from the final audit");
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, "index.html"), html);
  for (const row of rows) { const target = join(out, row.target); mkdirSync(dirname(target), { recursive: true }); copyFileSync(row.source, target); }
  const receipt = {
    schema: "jev-report-publication-v1", status: "prepared-not-published", source_sha256: sha(source), html_sha256: sha(html),
    generator_sha256: sha(readFileSync(fileURLToPath(import.meta.url))), evidence_readme: EVIDENCE + "README.md",
    date: values.date, video_url: values["video-url"] || null, video_sha256: null, report_audio_streams: 0,
    music_publication: "User selected the existing six-track music edition; the report preserves its credits and cover art",
    rights_documentation_verified: false,
    assets: rows.map(({ target, sha256, bytes }) => ({ path: target, sha256, bytes })), pdfs: [],
    unverified: ["Final visual review", "Video export identity", "Public URL readback"],
  };
  writeFileSync(join(out, "publication.json"), JSON.stringify(receipt, null, 2) + "\n");
  if (values.pdf) receipt.pdfs = await exportPdfs(out, count);
  assert.equal(sha(readFileSync(sourcePath)), receipt.source_sha256, "Source changed during export");
  receipt.total_bytes = statSync(join(out, "index.html")).size + rows.reduce((n, row) => n + row.bytes, 0) + receipt.pdfs.reduce((n, pdf) => n + pdf.bytes, 0);
  writeFileSync(join(out, "publication.json"), JSON.stringify(receipt, null, 2) + "\n");
  console.log(JSON.stringify({ status: receipt.status, source_sha256: receipt.source_sha256, pdf_pages: receipt.pdfs.map((pdf) => pdf.pages.length), output: out }));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main(process.argv.slice(2));
