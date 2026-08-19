import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function jsonLd(path, type) {
  const html = readFileSync(join(root, "out", path), "utf8");
  const records = [...html.matchAll(/<script[^>]+type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g)]
    .map((match) => JSON.parse(match[1]));
  const record = records.find((item) => item["@type"] === type);
  if (!record) throw new Error(`${path}: missing ${type} JSON-LD`);
  return { html, record };
}

const packageText = readFileSync(join(root, "..", "pyproject.toml"), "utf8");
function projectField(name) {
  const value = packageText.match(new RegExp(`^${name} = "([^"]+)"`, "m"))?.[1];
  if (!value) throw new Error(`pyproject.toml: missing ${name}`);
  return value;
}

const version = projectField("version");
const license = projectField("license");
const python = projectField("requires-python").replace(/^>=/, "Python ") + "+";
const author = packageText.match(/^authors = \[\{ name = "([^"]+)" \}\]/m)?.[1];
const repository = packageText.match(/^Repository = "([^"]+)"/m)?.[1];
if (!author || !repository) throw new Error("pyproject.toml: missing author or repository");

const home = jsonLd("index.html", "SoftwareSourceCode").record;
if (home["@context"] !== "https://schema.org") throw new Error("landing @context drifted");
if (home.version !== version) throw new Error(`landing version ${home.version} != ${version}`);
if (home.codeRepository !== repository) throw new Error("landing codeRepository drifted");
if (home.programmingLanguage !== "Python" || home.runtimePlatform !== python) {
  throw new Error("landing language or runtime drifted");
}
if (home.license !== `https://www.apache.org/licenses/LICENSE-2.0` || license !== "Apache-2.0") {
  throw new Error("landing license drifted");
}
if (home.author?.name !== author || home.author?.url !== repository.replace(/\/[^/]+$/, "")) {
  throw new Error("landing author drifted");
}

const lineage = jsonLd("docs/capabilities/lineage/index.html", "TechArticle");
if (lineage.record["@context"] !== "https://schema.org") {
  throw new Error("lineage @context drifted");
}
const citations = lineage.record.citation;
if (!Array.isArray(citations) || citations.length !== 13) {
  throw new Error("lineage must expose exactly 13 citations");
}
const urls = citations.map((item) => item.url);
if (
  citations.some(
    (item) => item["@type"] !== "CreativeWork" || !item.name || !item.url?.startsWith("https://"),
  ) ||
  new Set(urls).size !== urls.length ||
  urls.some((url) => !lineage.html.includes(`href="${url}"`))
) {
  throw new Error("lineage citation URLs must be unique visible links");
}

console.log(`structured metadata OK: SoftwareSourceCode v${version}, ${urls.length} citations`);
