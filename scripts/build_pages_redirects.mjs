#!/usr/bin/env node
// Build the redirect-only GitHub Pages site for mangowhoiscloud.github.io/geode/.
//
// GEODE's docs, experiment hub and research readers moved to mangowhois.ai and tech.mangowhois.ai.
// GitHub Pages cannot answer 301, so every frozen page path (github-pages/redirect-paths.json) gets a
// static stub: a meta refresh, a canonical link, a visible link and noindex, plus a script that keeps
// the query and fragment. Markdown and text files get a one-line note. Any other old address reaches
// 404.html, which applies the same rules (github-pages/rules.js) in the browser.
//
// Usage: node scripts/build_pages_redirects.mjs --out DIR
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { HOSTS, pagesRedirect } from '../github-pages/rules.js';

const SOURCE = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'github-pages');
const BASE = '/geode/';
const [flag, outArg] = process.argv.slice(2);
if (flag !== '--out' || !outArg) {
  console.error('usage: node scripts/build_pages_redirects.mjs --out DIR');
  process.exit(2);
}
const out = resolve(outArg);

const esc = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const stub = (target) => `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="robots" content="noindex">
<link rel="canonical" href="${esc(target)}">
<meta http-equiv="refresh" content="0; url=${esc(target)}">
<title>GEODE has moved</title>
<script>(function () { var t = ${JSON.stringify(target)}, q = location.search; if (q) t += (t.indexOf('?') < 0 ? q : '&' + q.slice(1)); location.replace(t + location.hash); })();</script>
</head>
<body>
<p>This page moved to <a href="${esc(target)}">${esc(target)}</a>.</p>
</body>
</html>
`;

const { paths } = JSON.parse(readFileSync(join(SOURCE, 'redirect-paths.json'), 'utf8'));
const files = new Map();
for (const path of paths) {
  if (!path.startsWith(BASE) || path.split('/').some((part) => part === '..' || part === '.')) {
    throw new Error(`invalid frozen path: ${path}`);
  }
  const target = pagesRedirect(path);
  const url = new URL(target);
  if (url.protocol !== 'https:' || !HOSTS.has(url.hostname)) throw new Error(`invalid target for ${path}: ${target}`);
  const rel = path.slice(BASE.length);
  const page = path.endsWith('/') || path.endsWith('.html');
  const file = path.endsWith('/') ? `${rel}index.html` : rel;
  if (!page && !/\.(md|txt)$/.test(path)) throw new Error(`frozen path is neither a page nor text: ${path}`);
  if (files.has(file)) throw new Error(`duplicate output file: ${file}`);
  files.set(file, page ? stub(target) : `This file moved to ${target}\n`);
}

for (const [file, body] of files) {
  const dest = join(out, file);
  mkdirSync(dirname(dest), { recursive: true });
  writeFileSync(dest, body);
}
copyFileSync(join(SOURCE, '404.html'), join(out, '404.html'));
copyFileSync(join(SOURCE, 'rules.js'), join(out, 'rules.js'));
writeFileSync(join(out, '.nojekyll'), '');
console.log(`${files.size} redirect files plus 404.html and rules.js -> ${out}`);
