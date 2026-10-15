import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';

const site = fileURLToPath(new URL('..', import.meta.url));
const script = join(site, 'scripts/redirect-to-mangowhois.mjs');
const mapFile = join(site, 'redirect-map.json');
const { geode } = JSON.parse(readFileSync(mapFile, 'utf8'));
const out = mkdtempSync(join(tmpdir(), 'geode-redirect-'));
const write = (path, value) => {
  mkdirSync(dirname(join(out, path)), { recursive: true });
  writeFileSync(join(out, path), value);
};
const read = (path) => readFileSync(join(out, path), 'utf8');
const navigate = (html, pathname, search = '', hash = '') => {
  let target;
  runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], {
    URLSearchParams,
    location: { pathname, search, hash, replace: (url) => { target = url; } },
  });
  return target;
};

try {
  for (const entry of geode) {
    const path = entry.from.slice('/geode/'.length);
    write(entry.kind === 'page' ? join(path, 'index.html') : path, 'original');
  }
  const retained = [
    'research/index.html', 'research/jevdb/index.html', 'resaerch/jev-system1-offloading/report-ko.pdf',
    'benchmarks/terminal-bench/replay/index.html', 'self-improving/index.html',
    'petri-bundle/index.html', 'docs/petri/bundle/index.html', 'report.pdf', 'report-en.pdf',
    'llms-full.txt', 'images/example.png', 'diagrams/example.svg',
  ];
  for (const path of retained) write(path, `preserve ${path}`);
  write('index.txt', 'old payload');
  write('__next._tree.txt', 'old payload');
  write('404/index.html', 'old 404');
  write('sitemap.xml', '<urlset><url><loc>https://mangowhoiscloud.github.io/geode/</loc></url><url><loc>https://mangowhoiscloud.github.io/geode/research/</loc></url></urlset>');
  const result = spawnSync(process.execPath, [script, out, mapFile], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  for (const entry of geode) {
    const path = entry.from.slice('/geode/'.length);
    const target = entry.to[entry.default];
    if (entry.kind === 'page') {
      const html = read(join(path, 'index.html'));
      assert.ok(html.includes(`<link rel="canonical" href="${target}">`));
      assert.ok(html.includes(`<meta http-equiv="refresh" content="0; url=${target}">`));
      assert.equal(navigate(html, entry.from), target);
      for (const language of ['ko', 'en']) {
        const destination = entry.to[language];
        assert.equal(navigate(html, entry.from, `?lang=${language}`, '#section'), destination + (destination.includes('#') ? '' : '#section'));
      }
      assert.equal(navigate(html, entry.from, '?lang=ja'), target);
    } else assert.ok(read(path).includes(target));
  }
  for (const path of retained) assert.equal(read(path), `preserve ${path}`);
  for (const path of ['index.txt', '__next._tree.txt', '404']) assert.ok(!existsSync(join(out, path)));
  assert.equal(read('sitemap.xml'), '<urlset><url><loc>https://mangowhoiscloud.github.io/geode/research/</loc></url></urlset>');
  const notFound = read('404.html');
  assert.equal(navigate(notFound, '/geode/docs/runtime/Agent_Loop/index.html', '?lang=en', '#setup'), 'https://mangowhois.ai/en/products/geode/docs/runtime/agent-loop/#setup');
  assert.equal(navigate(notFound, '/geode/docs/quick-start.md'), 'https://mangowhois.ai/products/geode/docs/quick-start/');
  assert.equal(navigate(notFound, '/geode/about/missing', '', '#other'), 'https://mangowhois.ai/#profile');
  const invalidMap = join(out, 'invalid-map.json');
  for (const badEntry of [
    { ...geode[0], from: '/geode/../outside/' },
    { ...geode[0], to: { ...geode[0].to, ko: 'https://example.com/' } },
    { ...geode[0], from: '/geode/missing/' },
  ]) {
    write('index.html', 'must remain');
    writeFileSync(invalidMap, JSON.stringify({ geode: [geode[0], badEntry] }));
    assert.notEqual(spawnSync(process.execPath, [script, out, invalidMap]).status, 0);
    assert.equal(read('index.html'), 'must remain');
  }
  console.log(`Redirects: ${geode.length} mapped routes, language/fragment selection, 404 aliases, retained archives and pre-write validation passed.`);
} finally {
  rmSync(out, { recursive: true, force: true });
}
