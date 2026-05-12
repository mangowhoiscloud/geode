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
  trailingSlash: false,
};

export default nextConfig;
