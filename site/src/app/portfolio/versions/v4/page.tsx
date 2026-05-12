import { HeroSection } from "@/components/geode/sections/hero";
import { ScaffoldSection } from "@/components/geode/sections/scaffold";
import { LoopSection } from "@/components/geode/sections/loop";
import { ReasoningSection } from "@/components/geode/sections/reasoning";
import { ArchitectureSection } from "@/components/geode/sections/architecture";
import { HooksSection } from "@/components/geode/sections/hooks";
import { AgentsTasksSection } from "@/components/geode/sections/agents-tasks";
import { AutomationSection } from "@/components/geode/sections/automation";
import { BootstrapSection } from "@/components/geode/sections/bootstrap";
import { ContextTiersSection } from "@/components/geode/sections/context-tiers";
import { GatewaySection } from "@/components/geode/sections/gateway";
import { DomainDagSection } from "@/components/geode/sections/domain-dag";
import { ScoringSection } from "@/components/geode/sections/scoring";
import { MultiLlmSection } from "@/components/geode/sections/multi-llm";
import { VerificationSection } from "@/components/geode/sections/verification";
import { TimelineSection } from "@/components/geode/sections/timeline";

export default function GeodePage() {
  return (
    <main className="min-h-screen bg-[linear-gradient(180deg,#0B1628_0%,#0D1A30_15%,#0A1220_30%,#0E1525_45%,#0B1628_55%,#080E1A_70%,#0A1220_85%,#0B1628_100%)] text-[#F0F0FF] overflow-x-hidden">
      <HeroSection />
      <ScaffoldSection />
      <LoopSection />
      <ReasoningSection />
      <ArchitectureSection />
      <HooksSection />
      <AgentsTasksSection />
      <AutomationSection />
      <BootstrapSection />
      <ContextTiersSection />
      <GatewaySection />
      <DomainDagSection />
      <ScoringSection />
      <MultiLlmSection />
      <VerificationSection />
      <TimelineSection />
    </main>
  );
}
