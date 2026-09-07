/**
 * GEODE's product landing. The manual stays at /docs and the author at
 * /about; /portfolio remains an alias of this page.
 */
import type { Metadata } from "next";
import { GeodeLanding } from "@/components/geode/landing-page";
import { JsonLd } from "@/components/json-ld";
import { GEODE_SOT } from "@/data/geode/sot";

export const metadata: Metadata = {
  title: "GEODE | An agent runtime for tool-driven work",
  description:
    "Run tasks with your models and tools. Inspect execution records and source-bound Harbor / Terminal-Bench comparisons against native Codex.",
  openGraph: {
    title: "GEODE | An agent runtime for tool-driven work",
    description: "Run the task. Inspect the result. A self-hosting runtime with public execution evidence.",
    type: "website",
  },
  alternates: { canonical: "https://mangowhoiscloud.github.io/geode/" },
};

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
      <GeodeLanding />
    </>
  );
}
