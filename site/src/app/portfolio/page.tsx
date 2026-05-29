"use client";

import { LocaleProvider } from "@/components/geode/locale-context";
import { GeodeNav } from "@/components/geode/sections/nav";
import { HeroSection } from "@/components/geode/sections/hero";
import { TwoLoopsSection } from "@/components/geode/sections/two-loops";
import { SelfEvolvingSection } from "@/components/geode/sections/self-evolving";
import { AuditEvidenceSection } from "@/components/geode/sections/audit-evidence";
import { CapabilitiesTabsSection } from "@/components/geode/sections/capabilities-tabs";
import { LineagePositioningSection } from "@/components/geode/sections/lineage-positioning";
import { GeodeFooter } from "@/components/geode/sections/footer";

/**
 * GEODE intro page.
 *
 * PR-PORTFOLIO-INTRO (2026-05-30). Rebuilt from a flat scroll of ~26 co-equal
 * subsystem sections into an agent-intro page: a small number of narrative
 * beats (hero + demo, the two-loop mental model, the self-evolving
 * differentiator, the audit evidence, a tabbed capability map, and the honest
 * lineage), with the technical depth living in /docs. The hero keeps the three
 * demo videos in the first scroll.
 */
export default function GeodePage() {
  return (
    <LocaleProvider>
      <main className="min-h-screen bg-[var(--paper)] text-[var(--ink)] overflow-x-hidden">
        <GeodeNav />
        <div id="hero"><HeroSection /></div>
        <div id="two-loops"><TwoLoopsSection /></div>
        <div id="self-evolving"><SelfEvolvingSection /></div>
        <div id="audit"><AuditEvidenceSection /></div>
        <div id="capabilities"><CapabilitiesTabsSection /></div>
        <div id="lineage"><LineagePositioningSection /></div>
        <GeodeFooter />
      </main>
    </LocaleProvider>
  );
}
