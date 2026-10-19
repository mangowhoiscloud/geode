import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { relocateExport, relocateUrls } from './relocate-static-export.mjs';

const old = 'https://mangowhoiscloud.github.io/geode';
const target = 'https://mangowhois.ai/products/geode';
for (const suffix of ['', '/', '/docs/Agent_Loop/?lang=en#start', '/report.pdf', '?lang=ko#cover']) {
  assert.equal(relocateUrls(`"${old}${suffix}"`), `"${target}${suffix}"`);
  for (const quote of ['"', "'", '`']) {
    assert.equal(relocateUrls(`${quote}/geode${suffix}${quote}`), `${quote}/products/geode${suffix}${quote}`);
  }
}
const untouched = 'https://github.com/mangowhoiscloud/geode/blob/main/docs /tmp/geode/file site/src/data/geode/sot.ts ./geode/file ../geode/file "/geode-extra/" "https://example.com/geode/"';
assert.equal(relocateUrls(untouched), untouched);
assert.equal(relocateUrls('url(/geode/font.woff2) [x](/geode/docs/) content="0;url=/geode/"'), 'url(/products/geode/font.woff2) [x](/products/geode/docs/) content="0;url=/products/geode/"');
const hydration = String.raw`self.__next_f.push([1,"href=\"/geode/docs/Agent_Loop/?lang=en#start\""]);basePath="/geode";`;
assert.equal(relocateUrls(hydration), hydration.replaceAll('/geode', '/products/geode'));
assert.equal(relocateUrls(relocateUrls(hydration)), relocateUrls(hydration));

const directory = mkdtempSync(join(tmpdir(), 'geode-relocate-'));
const source = join(directory, 'original');
const output = join(directory, 'product');
const write = (path, bytes) => {
  mkdirSync(dirname(join(source, path)), { recursive: true });
  writeFileSync(join(source, path), bytes);
};
try {
  const html = '<html><head><style>.original{color:red}</style></head><body class="original"><script src="/geode/_next/app.js"></script><a href="/geode/research/?lang=ko#cover">Research</a></body></html>';
  write('index.html', html);
  write('_next/app.js', hydration);
  write('docs/Agent_Loop/index.txt', '\ufeff"/geode/docs/Agent_Loop/"');
  write('archive.jsonl', '{"source":"https://github.com/mangowhoiscloud/geode"}\n');
  const pdf = Buffer.alloc(25 * 1024 * 1024 + 1);
  pdf.write('%PDF /geode/ binary must remain identical');
  write('report.pdf', pdf);
  const manifest = relocateExport(source, output);
  assert.equal(manifest.fileCount, 5);
  assert.equal(manifest.changedFiles, 3);
  assert.equal(manifest.over25MiB[0].path, 'report.pdf');
  assert.deepEqual(readFileSync(join(output, 'report.pdf')), pdf);
  assert.equal(readFileSync(join(output, 'index.html'), 'utf8'), html.replaceAll('/geode', '/products/geode'));
  assert.equal(readFileSync(join(output, 'docs/Agent_Loop/index.txt'), 'utf8'), '\ufeff"/products/geode/docs/Agent_Loop/"');
  assert.equal(readFileSync(join(source, 'index.html'), 'utf8'), html);
  assert.deepEqual(JSON.parse(readFileSync(`${output}.manifest.json`, 'utf8')), manifest);
  assert.deepEqual(relocateExport(source, join(directory, 'second')), manifest);
  assert.throws(() => relocateExport(source, output), /already exists/);
  assert.throws(() => relocateExport(source, join(source, 'nested')), /separate trees/);
  symlinkSync(join(source, 'report.pdf'), join(source, 'symlink.pdf'));
  assert.throws(() => relocateExport(source, join(directory, 'unsafe')), /Unsupported export entry/);
  assert.equal(existsSync(join(directory, 'unsafe')), false);
  rmSync(join(source, 'symlink.pdf'));
  write('index.html', '<title>Moved to mangowhois.ai</title>');
  assert.throws(() => relocateExport(source, join(directory, 'redirects')), /redirect pages/);
  console.log('Export relocation: owned URL boundaries, hydration, languages/fragments, original styling, immutable input/binaries, deterministic manifest and unsafe destinations passed.');
} finally {
  rmSync(directory, { recursive: true, force: true });
}
