// redirect-to-mangowhois.mjs: the GEODE landing and docs moved to https://mangowhois.ai/products/geode/.
//
// GitHub Pages cannot answer 301, so after the static export is built (and uploaded whole as the
// `geode-site-export` artifact, which mangowhois.ai imports), every moved route in site/out is replaced by a
// small redirect page:
//   - <meta http-equiv="refresh"> to the exact new URL (works without JavaScript),
//   - <link rel="canonical"> to the same URL, so search engines consolidate on the new page,
//   - a visible link,
//   - a short script that keeps ?lang=en|ko (English or Korean page) and the #fragment, which a meta refresh drops.
// Markdown twins become one-line notes; llms.txt points to the new index; sitemap.xml keeps only routes that still
// live here; 404.html maps unknown old paths to the right new section. Routes not in the map (research readers,
// the Terminal-Bench replay, the self-improving hub, PDFs) are left exactly as built.
//
// Usage: node scripts/redirect-to-mangowhois.mjs <out dir> <redirect-map.json>
import { existsSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';

const [out, mapFile] = process.argv.slice(2);
if (!out || !mapFile) throw new Error('usage: redirect-to-mangowhois.mjs <out dir> <redirect-map.json>');
const { geode } = JSON.parse(readFileSync(mapFile, 'utf8'));
const BASE = '/geode/';
const esc = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// Validate the whole map before replacing any exported file.
const seen = new Set();
for (const entry of geode) {
  const path = resolve(out, entry.from.slice(BASE.length));
  if (!entry.from.startsWith(BASE) || (path !== resolve(out) && !path.startsWith(resolve(out) + sep)) || seen.has(path)) {
    throw new Error(`invalid or duplicate GEODE path: ${entry.from}`);
  }
  seen.add(path);
  if (!['page', 'text'].includes(entry.kind) || !['ko', 'en'].includes(entry.default)) throw new Error(`invalid redirect: ${entry.from}`);
  for (const language of ['ko', 'en']) {
    if (new URL(entry.to[language]).origin !== 'https://mangowhois.ai') throw new Error(`invalid target: ${entry.from}`);
  }
  if (!existsSync(entry.kind === 'page' ? join(path, 'index.html') : path)) throw new Error(`${entry.from}: no built file to replace`);
}

const stub = (entry) => {
  const target = entry.to[entry.default];
  const choose = `(function(){var q=new URLSearchParams(location.search).get('lang');var t=${JSON.stringify(entry.to)};var u=t[q==='en'||q==='ko'?q:${JSON.stringify(entry.default)}];if(location.hash&&u.indexOf('#')<0)u+=location.hash;location.replace(u);})();`;
  return `<!doctype html>
<html lang="${entry.default}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moved to mangowhois.ai</title>
<link rel="canonical" href="${esc(target)}">
<script>${choose}</script>
<meta http-equiv="refresh" content="0; url=${esc(target)}">
</head>
<body>
<p>This page moved to <a href="${esc(target)}">${esc(target)}</a>.</p>
<p lang="ko">이 페이지는 <a href="${esc(entry.to.ko)}">${esc(entry.to.ko)}</a>로 옮겼습니다.</p>
</body>
</html>
`;
};

// A moved route loses its page and the Next.js payloads that belong to it (index.txt, __next.*.txt); other files in
// the directory (the root's PDFs, favicon, llms-full.txt) and its subdirectories stay.
const clearFiles = (dir) => {
  for (const name of readdirSync(dir)) {
    if (/^(index\.html|index\.txt|__next\..*\.txt)$/.test(name) && statSync(join(dir, name)).isFile()) rmSync(join(dir, name));
  }
};

let pages = 0;
let texts = 0;
for (const entry of geode) {
  if (!entry.from.startsWith(BASE)) throw new Error(`not a GEODE path: ${entry.from}`);
  const rel = entry.from.slice(BASE.length);
  if (entry.kind === 'page') {
    const dir = join(out, rel);
    if (!existsSync(join(dir, 'index.html'))) throw new Error(`${entry.from}: no built page to replace`);
    clearFiles(dir);
    writeFileSync(join(dir, 'index.html'), stub(entry));
    pages += 1;
  } else {
    const target = entry.to[entry.default];
    const note = rel === 'llms.txt'
      ? `# GEODE\n\n> GEODE's documentation moved to https://mangowhois.ai/products/geode/.\n\nThe docs index for agents is now ${target}\n`
      : `# Moved\n\nThis page moved to ${target} (English: ${entry.to.en}).\n`;
    writeFileSync(join(out, rel), note);
    texts += 1;
  }
}

// The sitemap lists only what still lives here.
const sitemapFile = join(out, 'sitemap.xml');
if (existsSync(sitemapFile)) {
  const moved = new Set(geode.filter((entry) => entry.kind === 'page').map((entry) => `https://mangowhoiscloud.github.io${entry.from}`));
  const xml = readFileSync(sitemapFile, 'utf8').replace(/<url>\s*<loc>([^<]+)<\/loc>[\s\S]*?<\/url>\s*/g, (whole, loc) => (moved.has(loc) ? '' : whole));
  writeFileSync(sitemapFile, xml);
}

// Unknown old paths: the docs tree maps by prefix (kebab-case slugs), everything else to the product page.
const notFound = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moved to mangowhois.ai</title>
<meta name="robots" content="noindex">
<script>(function(){
var p=location.pathname,q=new URLSearchParams(location.search).get('lang'),en=q==='en';
var site='https://mangowhois.ai'+(en?'/en':'');
var u=site+'/products/geode/';
var m=p.match(/^\\/geode\\/docs(?:\\/(.*?))?(?:\\.md|\\.html|\\/index\\.html)?\\/?$/);
if(m){u=site+'/products/geode/docs/'+(m[1]?m[1].toLowerCase().replace(/_/g,'-')+'/':'');}
else if(/^\\/geode\\/portfolio\\/versions\\//.test(p)){u=site+'/';}
else if(/^\\/geode\\/about/.test(p)){u=site+'/#profile';}
if(location.hash&&u.indexOf('#')<0)u+=location.hash;
location.replace(u);
})();</script>
</head>
<body>
<h1>This page is not here</h1>
<p>GEODE's landing and documentation moved to mangowhois.ai:</p>
<ul>
<li><a href="https://mangowhois.ai/en/products/geode/">GEODE</a> · <a href="https://mangowhois.ai/products/geode/" lang="ko">한국어</a></li>
<li><a href="https://mangowhois.ai/en/products/geode/docs/">Documentation</a> · <a href="https://mangowhois.ai/products/geode/docs/" lang="ko">문서</a></li>
<li><a href="https://mangowhoiscloud.github.io/geode/research/">Research</a> and the <a href="https://mangowhoiscloud.github.io/geode/self-improving/">experiment hub</a> remain here.</li>
</ul>
</body>
</html>
`;
writeFileSync(join(out, '404.html'), notFound);
rmSync(join(out, '404'), { recursive: true, force: true });
console.log(`redirect-to-mangowhois: ${pages} pages and ${texts} text files now point to mangowhois.ai; 404.html maps the rest`);
