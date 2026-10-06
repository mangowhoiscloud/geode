import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { Linter } from "eslint";

const require = createRequire(import.meta.url);
const site = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const vendor = path.join(site, "vendor/eslint-plugin-next");
const plugin = require("@next/eslint-plugin-next").default;
const { getRootDirs } = require("@next/eslint-plugin-next/dist/utils/get-root-dirs");
const fixture = realpathSync(mkdtempSync(path.join(tmpdir(), "geode-next-roots-")));
const previousCwd = process.cwd();
try {
  for (const file of ["apps/web/pages/about.js", "apps/admin/src/pages/dashboard.js", "apps/router/app/account/page.js", "apps/.hidden/pages/secret.js", "packages/01/pages/one.js", "packages/02/pages/two.js", "packages/03/pages/three.js", "steps/1/pages/one.js", "steps/3/pages/three.js", "steps/5/pages/five.js"]) {
    const target = path.join(fixture, file);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, "export default function Page() {}\n");
  }
  symlinkSync("web", path.join(fixture, "apps/linked"), "dir");
  symlinkSync("missing", path.join(fixture, "apps/broken"), "dir");
  process.chdir(fixture);
  const inputs = [undefined, null, 42, [], "apps/web", "apps/web/", "./apps/web", "apps/*", "apps/**", "apps/w?b", "apps/[wa]*", "apps/{web,admin}", "apps/{web,{admin,router}}", "apps/@(web|admin)", "apps/!(admin)", "apps/.hidden", "apps/.*", "missing/*", "apps/web/pages/about.js", "apps\\web", "packages/{01..03}", "steps/{1..5..2}", "!apps/*", ["apps/web", "apps/admin", 42], ["apps/*", "!apps/admin"], path.join(fixture, "apps/*"), path.join(fixture, "apps/web/"), "apps/linked", "apps/linked/**", "apps/broken"];
  const normalize = value => path.relative(fixture, path.resolve(value)).replaceAll(path.sep, "/") || ".";
  const roots = inputs.map(rootDir => getRootDirs({ cwd: fixture, settings: { next: { rootDir } } }).map(normalize).sort());
  const linter = new Linter();
  const cases = [
    { rootDir: "apps/web", code: '<a href="/about">About</a>' },
    { rootDir: "apps/*", code: '<a href="/dashboard">Dashboard</a>' },
    { rootDir: "apps/{web,router}", code: '<a href="/account">Account</a>' },
    { rootDir: "apps/linked", code: '<a href="/about">About</a>' },
    { rootDir: "packages/{01..03}", code: '<a href="/two">Two</a>' },
    { rootDir: "steps/{1..5..2}", code: '<a href="/three">Three</a>' },
    { rootDir: path.join(fixture, "apps/*"), code: '<a href="/about">About</a>' },
    ...['<Link href="/about">About</Link>', '<a href="https://example.com/about">External</a>', '<a href="/about" target="_blank">Tab</a>', '<a href="/about" download>Download</a>', '<a href="/unmatched">Unknown</a>'].map(code => ({ rootDir: "apps/web", code })),
  ];
  const diagnostics = cases.map(({ rootDir, code }) => linter.verify(code, {
    languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
    plugins: { "@next/next": plugin },
    settings: { next: { rootDir } },
    rules: { "@next/next/no-html-link-for-pages": "error" },
  }).map(({ ruleId, severity, message }) => ({ ruleId, severity, message })).sort((a, b) => a.message.localeCompare(b.message)));
  const actual = { roots, diagnostics, rules: Object.keys(plugin.rules).sort(), configs: Object.fromEntries(Object.entries(plugin.configs).map(([name, config]) => [name, config.rules])) };
  const baseline = path.join(site, "scripts/fixtures/next-eslint-16.3.8.json");
  assert.deepEqual(actual, JSON.parse(readFileSync(baseline, "utf8")), "Root discovery and actual lint diagnostics must match the upstream fixture");
  assert.ok(require.resolve("@next/eslint-plugin-next").startsWith(vendor + path.sep), "The configured plugin must resolve to the reviewed local patch");
  assert.deepEqual(getRootDirs({ cwd: fixture, settings: { next: { rootDir: "{apps/*,!apps/admin}" } } }).map(normalize).sort(), ["apps/linked", "apps/router", "apps/web"]);
  assert.ok(getRootDirs({ cwd: fixture, settings: { next: { rootDir: "{apps/**,!./apps/admin}" } } }).every(dir => !normalize(dir).startsWith("apps/admin")), "An excluded directory must prune its descendants");
  for (const rootDir of ["apps/../apps/web", "apps//web", "apps/linked/../web", ".", `../${path.basename(fixture)}/apps/web`]) {
    assert.deepEqual(getRootDirs({ cwd: fixture, settings: { next: { rootDir } } }).map(normalize), [normalize(rootDir)], `Literal directory semantics: ${rootDir}`);
  }
  assert.deepEqual(getRootDirs({ cwd: fixture, settings: { next: { rootDir: "apps//*/pages" } } }).map(normalize).sort(), ["apps/linked/pages", "apps/web/pages"]);
  for (const rootDir of ["apps/../apps/*", `../${path.basename(fixture)}/apps/*`, "apps/././*", "apps/*/../web"]) {
    const expected = rootDir === "apps/*/../web" ? [] : ["apps/admin", "apps/linked", "apps/router", "apps/web"];
    assert.deepEqual(getRootDirs({ cwd: fixture, settings: { next: { rootDir } } }).map(normalize).sort(), expected, `Dynamic directory semantics: ${rootDir}`);
  }
  assert.deepEqual(getRootDirs({ cwd: path.join(fixture, "apps/admin"), settings: {} }), [path.join(fixture, "apps/admin")]);
  assert.deepEqual(getRootDirs({ cwd: path.join(fixture, "apps/admin"), settings: { next: { rootDir: "apps/web" } } }).map(normalize), ["apps/web"]);
  const manifest = JSON.parse(readFileSync(path.join(vendor, "upstream.json"), "utf8"));
  for (const [file, digest] of Object.entries(manifest.sha256)) {
    assert.equal(createHash("sha256").update(readFileSync(path.join(vendor, file))).digest("hex"), manifest.patchedSha256[file] ?? digest, `Vendored file drift: ${file}`);
  }
  const walk = dir => readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? walk(path.join(dir, entry.name)) : [path.relative(vendor, path.join(dir, entry.name)).replaceAll(path.sep, "/")]);
  assert.deepEqual(walk(path.join(vendor, "dist")).sort(), Object.keys(manifest.sha256).filter(file => file.startsWith("dist/")).sort(), "No rule or utility may be removed/added");
  const lock = JSON.parse(readFileSync(path.join(site, "package-lock.json"), "utf8"));
  assert.ok(!Object.keys(lock.packages).some(name => /node_modules\/(braces|fast-glob|micromatch)$/.test(name)), "The vulnerable dependency path must be absent from the actual lock");
  for (const depth of [1000, 3500, 20000]) {
    const probe = spawnSync(process.execPath, ["-e", `const {getRootDirs}=require(${JSON.stringify(require.resolve("@next/eslint-plugin-next/dist/utils/get-root-dirs"))}); try { getRootDirs({cwd:process.cwd(),settings:{next:{rootDir:'{'.repeat(${depth})+'a,b'+'}'.repeat(${depth})}}}); } catch (error) { if (!(error instanceof SyntaxError) || !/depth/.test(error.message)) throw error; }`], { cwd: fixture, timeout: 5000, encoding: "utf8" });
    assert.equal(probe.error, undefined, `Nested-pattern probe failed: ${probe.error}`);
    assert.equal(probe.status, 0, probe.stderr);
  }
  console.log(`Next ESLint patch: ${inputs.length} directory patterns, ${cases.length} real lint cases, rule/config parity, source integrity and nested-pattern safety passed.`);
} finally {
  process.chdir(previousCwd);
  rmSync(fixture, { recursive: true, force: true });
}
