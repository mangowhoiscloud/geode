import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  // GitHub Pages 배포: mangowhoiscloud.github.io/geode
  // (A-2 계획: portfolio repo를 geode repo의 site/로 통합 후 Pages 활성화)
  basePath: "/geode",
  assetPrefix: "/geode",
  images: {
    unoptimized: true,
  },
  // Directory-style export (about/index.html): GitHub Pages serves both
  // /geode/docs and /geode/docs/ (301 to the slash form). With `false` the
  // slash form 404s — shared links with a trailing slash broke (2026-07-10).
  trailingSlash: true,
};

export default nextConfig;
