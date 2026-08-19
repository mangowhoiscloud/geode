/**
 * GEODE site landing — /geode/ IS the portfolio (operator-directed
 * 2026-07-10): the deploy link mangowhoiscloud.github.io/geode serves the
 * loop-punk portfolio directly. The reference manual stays at /docs, the
 * person page at /about; /portfolio remains as an alias of this page.
 */
import GeodePortfolioPage from "./portfolio/page";
import { JsonLd } from "@/components/json-ld";
import { GEODE_SOT } from "@/data/geode/sot";

export default function Page() {
  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "SoftwareSourceCode",
          "@id": "https://mangowhoiscloud.github.io/geode/#software",
          name: "GEODE",
          description:
            "GEODE is an agent runtime for long-running tool work and evaluation-ready execution evidence.",
          version: GEODE_SOT.version,
          codeRepository: "https://github.com/mangowhoiscloud/geode",
          programmingLanguage: "Python",
          runtimePlatform: "Python 3.12+",
          license: "https://www.apache.org/licenses/LICENSE-2.0",
          author: {
            "@type": "Person",
            name: "Jihwan Ryu",
            url: "https://github.com/mangowhoiscloud",
          },
        }}
      />
      <GeodePortfolioPage />
    </>
  );
}
