"use client";

import { ScrollReveal, ScrollRevealGroup, revealChild } from "../scroll-reveal";
import { motion } from "framer-motion";

const layers = [
  {
    id: "L0",
    name: "CLI & Agent",
    detail: "AgenticLoop · SubAgent(max 5) · Batch · Slack Gateway",
    color: "#4ECDC4",
    modules: "core/agent, core/cli, core/gateway",
  },
  {
    id: "L1",
    name: "Infrastructure",
    detail: "Claude · OpenAI · GLM Adapters — Port/Adapter DI",
    color: "#60A5FA",
    modules: "core/llm, core/infrastructure",
  },
  {
    id: "L2",
    name: "Memory",
    detail: "4-Tier: User Profile → Org → Project → Session",
    color: "#F4B8C8",
    modules: "core/memory",
  },
  {
    id: "L3",
    name: "Orchestration",
    detail: "TaskGraph DAG · PlanMode · LaneQueue · CoalescingQueue",
    color: "#818CF8",
    modules: "core/orchestration",
  },
  {
    id: "L4",
    name: "Extensibility",
    detail: "54 Tools + 44 MCP · PolicyChain · 21 Skills",
    color: "#F5C542",
    modules: "core/tools, core/skills, core/mcp",
  },
  {
    id: "L5",
    name: "Domain Plugins",
    detail: "DomainPort Protocol — GameIP · REODE(Java Migration)",
    color: "#C084FC",
    modules: "core/domains, core/graph",
  },
];

export function ArchitectureSection() {
  // Render L0 first in DOM → with flex-col-reverse, L0 appears at bottom
  // Stagger animation plays L0 first, creating a bottom-up "stacking" effect
  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#818CF8]/60 uppercase tracking-[0.25em] mb-3">
            Architecture
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-white/90 mb-3">
            6-Layer Stack
          </h2>
          <p className="text-[#8B9CC0] max-w-lg mb-4 leading-relaxed">
            6개 레이어, 26개 포트. 의존성 주입으로 결합된 전 계층이{" "}
            <code className="text-[#818CF8]/70 text-[13px]">compile_graph()</code> 한 번에
            부팅됩니다 — cold start ~15초.
          </p>
        </ScrollReveal>

        {/* Stack container */}
        <div className="relative mt-14">
          {/* HookSystem vertical bar — cross-cutting concern */}
          <div className="absolute -right-2 md:right-4 top-0 bottom-0 z-10 flex flex-col items-center pointer-events-none">
            <div className="flex-1 w-px border-l border-dashed border-[#4ECDC4]/20" />
          </div>

          {/* Layers: rendered L0→L5 in DOM, flex-col-reverse for visual L5-top L0-bottom */}
          <ScrollRevealGroup
            className="flex flex-col-reverse gap-0 rounded-2xl overflow-hidden border border-white/[0.05]"
            stagger={0.06}
          >
            {layers.map((layer) => (
              <motion.div
                key={layer.id}
                variants={revealChild}
                className="group relative flex items-center gap-4 px-5 py-3.5 border-b border-white/[0.05] first:border-b-0 cursor-default transition-all duration-300 hover:translate-x-1"
                style={{
                  background: `linear-gradient(90deg, ${layer.color}0A, transparent 40%)`,
                }}
              >
                {/* Layer ID badge */}
                <div
                  className="shrink-0 w-10 text-center text-[10px] font-mono font-bold py-1 rounded"
                  style={{ color: layer.color, background: `${layer.color}10` }}
                >
                  {layer.id}
                </div>

                {/* Name */}
                <div className="font-medium text-sm text-white/80 w-[110px] md:w-[130px] shrink-0">
                  {layer.name}
                </div>

                {/* Detail — hidden on mobile */}
                <div className="text-xs text-[#7A8CA8] hidden md:block flex-1 pr-12">
                  {layer.detail}
                </div>

                {/* Modules path — very subtle */}
                <div className="text-[11px] font-mono text-white/20 hidden lg:block absolute right-16 top-1/2 -translate-y-1/2">
                  {layer.modules}
                </div>

                {/* Hover glow */}
                <div
                  className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
                  style={{ boxShadow: `inset 0 0 40px ${layer.color}08, 0 0 20px ${layer.color}05` }}
                />
              </motion.div>
            ))}
          </ScrollRevealGroup>

          {/* HookSystem label */}
          <div
            className="absolute -right-2 md:right-4 top-1/2 -translate-y-1/2 z-10 pointer-events-none"
            style={{ writingMode: "vertical-lr" }}
          >
            <span className="text-[10px] font-mono text-[#4ECDC4]/25 tracking-widest rotate-180 block">
              HOOKS · 45 EVENTS
            </span>
          </div>
        </div>

        {/* Cross-cutting callout */}
        <ScrollReveal delay={0.5}>
          <div className="mt-6 flex items-center gap-3 px-4 py-3 rounded-xl border border-dashed border-[#4ECDC4]/15 bg-[#4ECDC4]/[0.02]">
            <span className="text-[#4ECDC4] text-lg">⟂</span>
            <div>
              <span className="text-sm font-medium text-[#4ECDC4]/70">HookSystem</span>
              <span className="text-sm text-[#7A8CA8] ml-2">
                45 events · 우선순위 기반 · 비차단 실행 — L0~L5 전 레이어를 수직 관통하는 교차 관심사
              </span>
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
