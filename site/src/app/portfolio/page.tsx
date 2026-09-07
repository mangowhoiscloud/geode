import type { Metadata } from "next";
import { GeodeLanding } from "@/components/geode/landing-page";

export const metadata: Metadata = {
  title: "GEODE | An agent runtime for tool-driven work",
  description:
    "Run tasks with your models and tools. Inspect execution records and source-bound Harbor / Terminal-Bench comparisons against native Codex.",
  openGraph: {
    title: "GEODE | An agent runtime for tool-driven work",
    description: "Run the task. Inspect the result. A self-hosting runtime with public execution evidence.",
    type: "website",
  },
};

/** Historical URL retained as an alias of the current GEODE landing. */
export default function GeodePortfolioPage() {
  return <GeodeLanding />;
}
