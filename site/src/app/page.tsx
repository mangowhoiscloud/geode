/**
 * GEODE's product landing. The manual stays at /docs and the author at
 * /about; /portfolio remains an alias of this page.
 */
import type { Metadata } from "next";
import { GeodeLanding } from "@/components/geode/landing-page";
import { JsonLd } from "@/components/json-ld";
import { GEODE_SOT } from "@/data/geode/sot";

export const metadata: Metadata = {
  title: "GEODE | Autonomous Agent Harness & Experimental Loop",
  description:
    "An autonomous agent harness with an outer Experimental Loop. Explore scaffold search, scenario generation, and source-bound evaluation evidence.",
  openGraph: {
    title: "GEODE | Autonomous Agent Harness & Experimental Loop",
    description: "Autonomous task execution. Experimental scaffold search. Inspect the design, observations, and limits.",
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
            "GEODE is an autonomous agent harness with a separate Experimental Loop for scaffold search and evaluation.",
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
