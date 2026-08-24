import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { parseSitemap } from "./sitemap-pages.mjs";

const siteRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(siteRoot, "out");
const publicBase = "https://mangowhoiscloud.github.io/geode";
const pages = parseSitemap(join(siteRoot, "src/lib/geode-docs/sitemap.ts"));
const expectedPaths = [
  "",
  "about",
  "portfolio",
  ...pages.map(({ slug }) => `docs${slug ? `/${slug}` : ""}`),
];

const sitemapPath = join(out, "sitemap.xml");
if (!existsSync(sitemapPath)) throw new Error("out/sitemap.xml is missing; run npm run build");
const xml = readFileSync(sitemapPath, "utf8");
const urls = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
const expectedUrls = expectedPaths.map(
  (path) => `${publicBase}/${path}${path ? "/" : ""}`,
);
if (urls.length !== new Set(urls).size) throw new Error("sitemap.xml contains duplicate URLs");
const missingUrls = expectedUrls.filter((url) => !urls.includes(url));
const extraUrls = urls.filter((url) => !expectedUrls.includes(url));
if (missingUrls.length || extraUrls.length) {
  throw new Error(
    `sitemap drift: missing=${JSON.stringify(missingUrls)} extra=${JSON.stringify(extraUrls)}`,
  );
}

const canonicalUrls = [];
for (const path of expectedPaths) {
  const htmlPath = join(out, path, "index.html");
  if (!existsSync(htmlPath)) throw new Error(`${path || "/"}: exported HTML is missing`);
  const html = readFileSync(htmlPath, "utf8");
  if (!/<title>[^<]+<\/title>/.test(html)) throw new Error(`${path || "/"}: title is missing`);
  if (/name="robots"[^>]+noindex/i.test(html)) throw new Error(`${path || "/"}: noindex detected`);
  const canonicals = [...html.matchAll(/<link\b[^>]*>/gi)]
    .map((match) => match[0])
    .filter((tag) => /\brel="canonical"/i.test(tag))
    .map((tag) => tag.match(/\bhref="([^"]+)"/i)?.[1]);
  const expectedCanonical = `${publicBase}/${path}${path ? "/" : ""}`;
  if (canonicals.length !== 1 || canonicals[0] !== expectedCanonical) {
    throw new Error(
      `${path || "/"}: expected one self-canonical ${expectedCanonical}, got ${JSON.stringify(canonicals)}`,
    );
  }
  canonicalUrls.push(canonicals[0]);
}

for (const name of ["llms.txt", "llms-full.txt"]) {
  const path = join(out, name);
  if (!existsSync(path) || statSync(path).size === 0) throw new Error(`${name}: missing or empty`);
}

const llmIndexes = ["llms.txt", "llms-full.txt"];
const urlsetSha256 = createHash("sha256")
  .update(JSON.stringify(expectedUrls))
  .digest("hex");

const receipt = JSON.stringify(
  {
      schema: "geode.geo-preflight.v2",
      status: "pass",
      checks: {
        export: { numerator: expectedPaths.length, denominator: expectedPaths.length },
        sitemap: { numerator: urls.length, denominator: expectedUrls.length },
        self_canonical: { numerator: canonicalUrls.length, denominator: expectedUrls.length },
        indexable: { numerator: expectedPaths.length, denominator: expectedPaths.length },
        llm_indexes: { numerator: llmIndexes.length, denominator: llmIndexes.length },
      },
      noindex: { count: 0, audited_pages: expectedPaths.length },
      urlset_sha256: urlsetSha256,
      llm_indexes: llmIndexes,
      locators: ["out/sitemap.xml", "out/**/index.html", "out/llms.txt", "out/llms-full.txt"],
      unmeasured: ["retrieval", "citation", "placement", "absorption", "quality", "outcome"],
  },
  null,
  2,
);
const receiptFlag = process.argv.indexOf("--receipt");
if (receiptFlag >= 0) {
  const destination = process.argv[receiptFlag + 1];
  if (!destination) throw new Error("--receipt requires a destination path");
  writeFileSync(destination, `${receipt}\n`, { encoding: "utf8", flag: "wx" });
} else {
  console.log(receipt);
}
