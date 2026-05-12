"use client";

import Image from "next/image";
import Link from "next/link";
import { ScrollReveal, ScrollRevealGroup, revealChild } from "../scroll-reveal";
import { motion } from "framer-motion";

const phases = [
  {
    phase: "Phase 1",
    period: "2025.01.31 — 02.28",
    title: "Game IP 가치추론 DAG",
    desc: "넥슨 네비게이터실 과제 전형. 게임/IP 저평가 분석 파이프라인 설계 — 14축 루브릭 + PSM 인과추론 + LangGraph StateGraph.",
    badge: "과제 합격",
    badgeColor: "#34D399",
    versions: ["v0.6 MVP", "v0.8 Multi-LLM"],
  },
  {
    phase: "Phase 2",
    period: "2025.03 — 03.06",
    title: "면접 탈락 → Autonomous Pivot",
    desc: "과제 전형 합격, 면접 탈락. 도메인 종속적 파이프라인에서 범용 자율 실행 하네스로 전환. DomainPort Protocol로 파이프라인을 교체 가능한 플러그인으로 분리.",
    badge: "PIVOT",
    badgeColor: "#F5C542",
    versions: ["v0.10 DomainPort", "v0.16 AgenticLoop"],
  },
  {
    phase: "Phase 3",
    period: "2025.03 — 2026.Q1",
    title: "Autonomous Execution Harness",
    desc: "Scaffold(CLAUDE.md + CI) → Runtime(45 Hooks + 21 Skills) → Loop(while tool_use) 3중 구조 완성. Slack Gateway, SubAgent DAG, 4-Tier Memory.",
    badge: "CURRENT",
    badgeColor: "#4ECDC4",
    versions: ["v0.24 Harness", "v0.28 Gateway", "v0.30 Signal Live"],
  },
  {
    phase: "Fork",
    period: "2026.03.16 — 05.16 (@pinxlab, 프리랜스)",
    title: "REODE — Domain Pivot 실증",
    desc: "산업 적용 전 DomainPort 교체 가능성 실증. Java 1.8→22 + Spring 4.3→6.1 자동 마이그레이션. 5,523파일 엔터프라이즈 프로젝트 83/83 테스트 통과. 에러 4분류 라우팅(CONFIG/CODE/BEHAVIOR/ENV) + Architect/Editor 분리. 5시간 30분, 1,153턴 자율 수행.",
    badge: "FORK",
    badgeColor: "#C084FC",
    versions: ["v0.21", "83/83 tests", "$388 / 1,133 rounds"],
  },
];

export function TimelineSection() {
  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">

      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#4ECDC4]/60 uppercase tracking-[0.25em] mb-3">
            Timeline
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-white/90 mb-4">
            Domain → Autonomous
          </h2>
          <p className="text-[#8B9CC0] max-w-lg mb-16">
            과제 전형용 도메인 파이프라인에서 범용 자율 실행 하네스로.
            <br />
            <span className="text-white/40">35일 만에 피봇, 총 3개월 — 현재 진행형.</span>
          </p>
        </ScrollReveal>

        <ScrollRevealGroup className="relative" stagger={0.1}>
          {/* Vertical line */}
          <div className="absolute left-[19px] top-4 bottom-4 w-px bg-gradient-to-b from-white/10 via-white/5 to-transparent" />

          <div className="flex flex-col gap-10">
            {phases.map((p) => (
              <motion.div
                key={p.phase}
                variants={revealChild}
                className="flex items-start gap-5"
              >
                {/* Dot */}
                <div className="relative shrink-0 mt-2">
                  <div
                    className="w-[10px] h-[10px] rounded-full border-2"
                    style={{
                      borderColor: `${p.badgeColor}60`,
                      backgroundColor: p.phase === "Phase 3" ? p.badgeColor : "transparent",
                      boxShadow: p.phase === "Phase 3" ? `0 0 12px ${p.badgeColor}40` : "none",
                    }}
                  />
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2.5 mb-1.5">
                    <span className="text-xs font-mono font-bold text-white/40">{p.phase}</span>
                    <span className="text-[10px] font-mono text-[#7A8CA8]">{p.period}</span>
                    <span
                      className="px-1.5 py-0.5 rounded text-[11px] font-mono font-bold border"
                      style={{
                        color: `${p.badgeColor}C0`,
                        backgroundColor: `${p.badgeColor}10`,
                        borderColor: `${p.badgeColor}25`,
                      }}
                    >
                      {p.badge}
                    </span>
                  </div>

                  <h3 className="text-base font-semibold text-white/80 mb-1.5">{p.title}</h3>
                  <p className="text-sm text-[#7A8CA8] leading-relaxed mb-3">{p.desc}</p>

                  <div className="flex flex-wrap gap-1.5">
                    {p.versions.map((v) => (
                      <span
                        key={v}
                        className="px-2 py-0.5 rounded text-[10px] font-mono text-white/40 bg-white/[0.02] border border-white/[0.04]"
                      >
                        {v}
                      </span>
                    ))}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </ScrollRevealGroup>

        <ScrollReveal delay={0.4}>
          <div className="mt-20 flex items-center justify-center gap-4">
            <Image src="/geode/images/geode-idle.png" alt="Geodi" width={32} height={32} className="opacity-40" />
            <Link href="/" className="text-xs font-mono text-[#7A8CA8] hover:text-[#8B9CC0] transition-colors">
              ← Back to portfolio
            </Link>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
