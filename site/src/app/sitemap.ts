import type { MetadataRoute } from "next";

import { flattenSitemap } from "@/lib/geode-docs/sitemap";

const SITE = "https://mangowhoiscloud.github.io/geode";

export const dynamic = "force-static";

export default function sitemap(): MetadataRoute.Sitemap {
  const paths = [
    "",
    "about",
    "portfolio",
    "benchmarks/terminal-bench/replay",
    ...flattenSitemap().map((page) => `docs${page.slug ? `/${page.slug}` : ""}`),
  ];
  return paths.map((path) => ({ url: `${SITE}/${path}${path ? "/" : ""}` }));
}
