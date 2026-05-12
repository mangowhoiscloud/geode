"use client";

import { LocaleProvider } from "@/components/geode/locale-context";
import { GeodeNav } from "@/components/geode/sections/nav";
import { HeroSection } from "@/components/geode/sections/hero";
import { SelfHostingDefinitionSection } from "@/components/geode/sections/self-hosting-definition";
import { OsThesisSection } from "@/components/geode/sections/os-thesis";
import { OsPrimitivesMapSection } from "@/components/geode/sections/os-primitives-map";
import { RecursionSection } from "@/components/geode/sections/recursion";
import { ComputeAbiSection } from "@/components/geode/sections/compute-abi";
import { RoutingIqSection } from "@/components/geode/sections/routing-iq";
import { TwoAppsSection } from "@/components/geode/sections/two-apps";
import { KanbanSection } from "@/components/geode/sections/kanban";
import { ScaffoldSection } from "@/components/geode/sections/scaffold";
import { LoopSection } from "@/components/geode/sections/loop";
import { ReasoningSection } from "@/components/geode/sections/reasoning";
import { ArchitectureSection } from "@/components/geode/sections/architecture";
import { GatewaySection } from "@/components/geode/sections/gateway";
import { ConcurrencySection } from "@/components/geode/sections/concurrency";
import { HeadlessSection } from "@/components/geode/sections/headless";
import { SchedulerSection } from "@/components/geode/sections/scheduler";
import { HooksSection } from "@/components/geode/sections/hooks";
import { AgentsTasksSection } from "@/components/geode/sections/agents-tasks";
import { ToolUseSection } from "@/components/geode/sections/tool-use";
import { ContextTiersSection } from "@/components/geode/sections/context-tiers";
import { MultiLlmSection } from "@/components/geode/sections/multi-llm";
import { DomainDagSection } from "@/components/geode/sections/domain-dag";
import { ScoringSection } from "@/components/geode/sections/scoring";
import { FeedbackSection } from "@/components/geode/sections/feedback";
import { VerificationSection } from "@/components/geode/sections/verification";
import { OrchestrationSection } from "@/components/geode/sections/orchestration";
import { AutomationSection } from "@/components/geode/sections/automation";
import { BootstrapSection } from "@/components/geode/sections/bootstrap";
import { TimelineSection } from "@/components/geode/sections/timeline";
import { GeodeFooter } from "@/components/geode/sections/footer";

const Divider = () => <div className="max-w-3xl mx-auto border-t border-[var(--rule)]" />;

export default function GeodePage() {
  return (
    <LocaleProvider>
    <main className="min-h-screen bg-[var(--paper)] text-[var(--ink)] overflow-x-hidden">
      <GeodeNav />
      <div id="hero"><HeroSection /></div>
      <div id="definition"><SelfHostingDefinitionSection /></div>
      <div id="thesis"><OsThesisSection /></div>
      <div id="primitives"><OsPrimitivesMapSection /></div>
      <div id="recursion"><RecursionSection /></div>
      <div id="bootstrap"><BootstrapSection /></div>
      <Divider />
      <div id="compute-abi"><ComputeAbiSection /></div>
      <div id="routing-iq"><RoutingIqSection /></div>
      <Divider />
      <div id="two-apps"><TwoAppsSection /></div>
      <Divider />
      <div id="scaffold"><ScaffoldSection /></div>
      <div id="kanban"><KanbanSection /></div>
      <Divider />
      <div id="loop"><LoopSection /></div>
      <div id="reasoning"><ReasoningSection /></div>
      <Divider />
      <div id="architecture"><ArchitectureSection /></div>
      <div id="gateway"><GatewaySection /></div>
      <div id="concurrency"><ConcurrencySection /></div>
      <div id="headless"><HeadlessSection /></div>
      <div id="scheduler"><SchedulerSection /></div>
      <Divider />
      <div id="hooks"><HooksSection /></div>
      <div id="agents"><AgentsTasksSection /></div>
      <div id="tools"><ToolUseSection /></div>
      <Divider />
      <div id="context"><ContextTiersSection /></div>
      <div id="llm"><MultiLlmSection /></div>
      <Divider />
      <div id="domain"><DomainDagSection /></div>
      <div id="orchestration"><OrchestrationSection /></div>
      <div id="scoring"><ScoringSection /></div>
      <div id="feedback"><FeedbackSection /></div>
      <div id="automation"><AutomationSection /></div>
      <Divider />
      <div id="verify"><VerificationSection /></div>
      <div id="timeline"><TimelineSection /></div>
      <GeodeFooter />
    </main>
    </LocaleProvider>
  );
}
