import type { Metadata } from "next";
import { GeodeLanding } from "@/components/geode/landing-page";

export const metadata: Metadata = {
  title: "GEODE | Autonomous Agent Harness & Experimental Loop",
  description:
    "An autonomous agent harness with an outer Experimental Loop. Explore scaffold search, scenario generation, and source-bound evaluation evidence.",
  openGraph: {
    title: "GEODE | Autonomous Agent Harness & Experimental Loop",
    description: "Autonomous task execution. Experimental scaffold search. Inspect the design, observations, and limits.",
    type: "website",
  },
};

/** Historical URL retained as an alias of the current GEODE landing. */
export default function GeodePortfolioPage() {
  return <GeodeLanding />;
}
