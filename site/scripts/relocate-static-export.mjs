// Copy the complete Pages export to /products/geode without rebuilding its UI.
// Usage: node scripts/relocate-static-export.mjs <original out> <new out>
// The destination and its sibling <new out>.manifest.json must not exist.
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs';
import { basename, dirname, extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const SOURCE_BASE = 'https://mangowhoiscloud.github.io/geode';
const TARGET_BASE = 'https://mangowhois.ai/products/geode';
const TEXT_EXTENSIONS = new Set(['.html', '.txt', '.js', '.css', '.json', '.jsonl', '.xml', '.md', '.svg', '.template']);
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

export function relocateUrls(text) {
  return text
    .replace(/https:\/\/mangowhoiscloud\.github\.io\/geode(?=[/?#"'`\\\s)<>]|$)/g, TARGET_BASE)
    // Quoted URLs, Next's compiled basePath, CSS url(), HTML and Markdown links.
    // A slash inside a GitHub URL, source path, filename or longer slug is not ours.
    .replace(/(^|["'`(=>\[])\/geode(?=[/?#"'`\\\s)<>]|$)/g, '$1/products/geode');
}

export function relocateExport(input, destination) {
  const source = realpathSync(input);
  const output = join(realpathSync(dirname(resolve(destination))), basename(resolve(destination)));
  const manifestPath = `${output}.manifest.json`;
  if (output === source || output.startsWith(source + sep) || source.startsWith(output + sep)) {
    throw new Error('Source and destination must be separate trees');
  }
  if (existsSync(output) || existsSync(manifestPath)) throw new Error('Destination or manifest already exists');
  if (!existsSync(join(source, 'index.html')) || !existsSync(join(source, '_next'))) {
    throw new Error('Input must be a complete Next.js export');
  }
  if (readFileSync(join(source, 'index.html'), 'utf8').includes('<title>Moved to mangowhois.ai</title>')) {
    throw new Error('Input has already been replaced by redirect pages');
  }
  const paths = [];
  function collect(directory = '') {
    for (const entry of readdirSync(join(source, directory), { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) collect(path);
      else if (entry.isFile()) paths.push(path);
      else throw new Error(`Unsupported export entry: ${path}`);
    }
  }
  collect();
  paths.sort();

  const files = [];
  const decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
  for (const path of paths) {
    const original = readFileSync(join(source, path));
    const bytes = TEXT_EXTENSIONS.has(extname(path))
      ? Buffer.from(relocateUrls(decoder.decode(original))) : original;
    mkdirSync(dirname(join(output, path)), { recursive: true });
    writeFileSync(join(output, path), bytes);
    files.push({ path, sourceBytes: original.length, bytes: bytes.length, sourceSha256: sha256(original), sha256: sha256(bytes) });
  }
  const manifest = {
    schema: 'geode-relocated-export@1',
    sourceBase: SOURCE_BASE,
    targetBase: TARGET_BASE,
    fileCount: files.length,
    sourceBytes: files.reduce((sum, file) => sum + file.sourceBytes, 0),
    bytes: files.reduce((sum, file) => sum + file.bytes, 0),
    changedFiles: files.filter((file) => file.sourceSha256 !== file.sha256).length,
    sourceTreeSha256: sha256(files.map((file) => `${file.path}\0${file.sourceSha256}\n`).join('')),
    treeSha256: sha256(files.map((file) => `${file.path}\0${file.sha256}\n`).join('')),
    over25MiB: files.filter((file) => file.bytes > 25 * 1024 * 1024).map(({ path, bytes, sha256 }) => ({ path, bytes, sha256 })),
    files,
  };
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  return manifest;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [input, output, ...extra] = process.argv.slice(2);
  if (!input || !output || extra.length) throw new Error('usage: relocate-static-export.mjs <original out> <new out>');
  const manifest = relocateExport(input, output);
  console.log(`Relocated ${manifest.changedFiles}/${manifest.fileCount} files; ${manifest.bytes} bytes; ${manifest.over25MiB.length} downloads exceed 25 MiB. Manifest: ${output}.manifest.json`);
}
