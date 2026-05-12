"use client";

import { ScrollReveal, ScrollRevealGroup, revealChild } from "../scroll-reveal";
import { motion } from "framer-motion";

const bigNumbers = [
  {
    value: "5",
    label: "LLM Providers",
    detail: "Opus · Sonnet · Haiku · GPT-5 · Gemini Flash",
    color: "#F4B8C8",
  },
  {
    value: "21",
    label: "Runtime Skills",
    detail: "도메인별 전문 지식 런타임 주입",
    color: "#F5C542",
  },
  {
    value: "5",
    label: "Max SubAgents",
    detail: "병렬 실행 · token guard · 상속",
    color: "#4ECDC4",
  },
  {
    value: "4",
    label: "Trigger Types",
    detail: "CLI · Cron · Event Hook · Webhook",
    color: "#C084FC",
  },
];

const orchestrationItems = [
  { name: "TaskGraph DAG", detail: "의존성 기반 병렬/순차 스케줄링", color: "#818CF8" },
  { name: "PlanMode", detail: "전략 수립 → 사용자 승인 → 실행", color: "#818CF8" },
  { name: "LaneQueue", detail: "채널별 요청 직렬화 (Slack)", color: "#818CF8" },
  { name: "CoalescingQueue", detail: "중복 요청 병합", color: "#818CF8" },
];

export function OrchestrationSection() {
  return (
    <section className="relative py-36 px-6">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(129,140,248,0.03)_0%,transparent_60%)] pointer-events-none" />

      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#818CF8]/60 uppercase tracking-[0.25em] mb-3">
            Orchestration · L3
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-white/90 mb-14">
            Wired together
          </h2>
        </ScrollReveal>

        {/* Big numbers */}
        <ScrollRevealGroup
          className="grid grid-cols-2 md:grid-cols-4 gap-px bg-white/[0.04] rounded-2xl overflow-hidden border border-white/[0.06] mb-12"
          stagger={0.08}
        >
          {bigNumbers.map((item) => (
            <motion.div
              key={item.label}
              variants={revealChild}
              className="bg-black/20 p-7 flex flex-col"
            >
              <div className="text-4xl font-black tracking-tighter leading-none mb-2" style={{ color: item.color }}>
                {item.value}
              </div>
              <div className="text-sm font-semibold text-white/70 mb-1.5">{item.label}</div>
              <div className="text-[10px] font-mono text-[#7A8CA8] leading-relaxed mt-auto">{item.detail}</div>
            </motion.div>
          ))}
        </ScrollRevealGroup>

        {/* L3 Orchestration detail */}
        <ScrollReveal delay={0.2}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {orchestrationItems.map((item) => (
              <div
                key={item.name}
                className="rounded-lg border border-white/[0.04] bg-white/[0.01] px-4 py-3"
              >
                <div className="text-xs font-semibold text-[#818CF8]/80 mb-1">{item.name}</div>
                <div className="text-[10px] text-[#7A8CA8]">{item.detail}</div>
              </div>
            ))}
          </div>
        </ScrollReveal>

        <ScrollReveal delay={0.3}>
          <p className="mt-10 text-center text-xs text-[#7A8CA8] font-mono">
            Slack Gateway · 4-Tier Memory · Worktree 격리 · CI 5-Job Ratchet
          </p>
        </ScrollReveal>
      </div>
    </section>
  );
}
