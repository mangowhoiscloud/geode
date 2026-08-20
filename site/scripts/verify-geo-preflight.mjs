import { existsSync, readFileSync, statSync } from "node:fs";
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
const expectedUrls = expectedPaths.map((path) => `${publicBase}/${path}`);
if (urls.length !== new Set(urls).size) throw new Error("sitemap.xml contains duplicate URLs");
const missingUrls = expectedUrls.filter((url) => !urls.includes(url));
const extraUrls = urls.filter((url) => !expectedUrls.includes(url));
if (missingUrls.length || extraUrls.length) {
  throw new Error(
    `sitemap drift: missing=${JSON.stringify(missingUrls)} extra=${JSON.stringify(extraUrls)}`,
  );
}

for (const path of expectedPaths) {
  const htmlPath = join(out, path, "index.html");
  if (!existsSync(htmlPath)) throw new Error(`${path || "/"}: exported HTML is missing`);
  const html = readFileSync(htmlPath, "utf8");
  if (!/<title>[^<]+<\/title>/.test(html)) throw new Error(`${path || "/"}: title is missing`);
  if (/name="robots"[^>]+noindex/i.test(html)) throw new Error(`${path || "/"}: noindex detected`);
}

for (const name of ["llms.txt", "llms-full.txt"]) {
  const path = join(out, name);
  if (!existsSync(path) || statSync(path).size === 0) throw new Error(`${name}: missing or empty`);
}

console.log(
  JSON.stringify(
    {
      schema: "geode.geo-preflight.v1",
      status: "pass",
      exported_pages: expectedPaths.length,
      sitemap_urls: urls.length,
      noindex_pages: 0,
      llm_indexes: ["llms.txt", "llms-full.txt"],
      unmeasured: ["search_activation", "selection", "citation", "absorption", "outcome"],
    },
    null,
    2,
  ),
);
