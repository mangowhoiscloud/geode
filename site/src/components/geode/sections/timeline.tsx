"use client";

import Image from "next/image";
import Link from "next/link";
import { ScrollReveal, ScrollRevealGroup, revealChild } from "../scroll-reveal";
import { motion } from "framer-motion";
import { useLocale, t } from "../locale-context";

type Accent = "artifact" | "line";

type Chapter = {
  id: string;
  range: string;
  period: string;
  titleKo: string;
  titleEn: string;
  bodyKo: string;
  bodyEn: string;
  accent: Accent;
  chips: { v: string; ko: string; en: string }[];
};

const accentVar = (a: Accent) => (a === "artifact" ? "var(--acc-artifact)" : "var(--acc-line)");

const chapters: Chapter[] = [
  {
    id: "C1",
    range: "v0.6.0 → v0.10.0",
    period: "2026-03-10 → 03-13",
    accent: "line",
    titleKo: "Game IP 가치추론 DAG",
    titleEn: "Game IP value-inference DAG",
    bodyKo:
      "넥슨 네비게이터실 코딩 과제로 시작했습니다. LangGraph StateGraph 7-노드 파이프라인 위에 14축 루브릭과 PSM 인과추론을 얹었습니다. v0.8에서 자연어 Plan/Sub-agent 통합, v0.10에서 SubAgent 병렬 실행과 SchedulerService 프로덕션 와이어링이 들어왔습니다.",
    bodyEn:
      "Started as a Nexon Navigator team take-home. A 7-node LangGraph StateGraph pipeline was wired with a 14-axis rubric and PSM causal inference. v0.8 added natural-language Plan / Sub-agent integration, v0.10 brought SubAgent parallel execution and SchedulerService production wiring.",
    chips: [
      { v: "v0.6.0", ko: "MVP · 56 commits · 1,879 tests", en: "MVP · 56 commits · 1,879 tests" },
      { v: "v0.7.0", ko: "NL Router 17 tools", en: "NL Router 17 tools" },
      { v: "v0.8.0", ko: "Plan / Sub-agent NL", en: "Plan / Sub-agent NL" },
      { v: "v0.10.0", ko: "SubAgent 병렬 + Scheduler", en: "SubAgent parallel + Scheduler" },
    ],
  },
  {
    id: "C2",
    range: "v0.10.0 → v0.20.0",
    period: "2026-03-12 → 03-19",
    accent: "artifact",
    titleKo: "DomainPort + Agentic Loop",
    titleEn: "DomainPort + Agentic Loop",
    bodyKo:
      "DomainPort Protocol로 도메인 파이프라인을 교체 가능한 플러그인으로 분리했습니다. v0.16에서 while(tool_use) AgenticLoop primitive가 자리잡았고, v0.20에서 .geode/(프로젝트)와 ~/.geode/(사용자) 두 영역이 분리되며 시스템 골격이 잡혔습니다. 이 구간의 v0.12에서 REODE가 분기되어 Java 1.8 → 22 마이그레이션 fork가 시작됩니다.",
    bodyEn:
      "DomainPort Protocol separated domain pipelines into swappable plugins. v0.16 settled the while(tool_use) AgenticLoop primitive, and v0.20 split the system into two regions — `.geode/` (project) and `~/.geode/` (user). REODE was forked from this band at v0.12 to drive the Java 1.8 → 22 migration line.",
    chips: [
      { v: "v0.12.0", ko: "DomainPort · REODE fork", en: "DomainPort · REODE fork" },
      { v: "v0.14.0", ko: "Token Guard · MCP", en: "Token Guard · MCP" },
      { v: "v0.16.0", ko: "AgenticLoop primitive", en: "AgenticLoop primitive" },
      { v: "v0.20.0", ko: ".geode 시스템 정착", en: ".geode system settled" },
    ],
  },
  {
    id: "C3",
    range: "v0.20.0 → v0.40.0",
    period: "2026-03-19 → 03-31",
    accent: "line",
    titleKo: "Hook System + 4-Layer 바인딩",
    titleEn: "Hook System + 4-layer binding",
    bodyKo:
      "HookSystem 이벤트 버스를 키우면서 v0.24 codebase audit 베이스라인, v0.30 MCP simplify, v0.34 subprocess isolation, v0.37 Bootstrap 통합과 queue refactor, 4-Layer 디렉토리 바인딩이 차례로 합쳐졌습니다. v0.40은 long-context 한계를 강제하는 200K token guard로 마감됩니다.",
    bodyEn:
      "The HookSystem event bus grew, and the line was sealed in this order: v0.24 codebase-audit baseline, v0.30 MCP simplify, v0.34 subprocess isolation, v0.37 unified bootstrap + queue refactor + 4-layer directory binding. v0.40 closed the band with a 200K token guard that enforces the long-context limit.",
    chips: [
      { v: "v0.24.0", ko: "Codebase audit", en: "Codebase audit" },
      { v: "v0.30.0", ko: "MCP simplify", en: "MCP simplify" },
      { v: "v0.34.0", ko: "Subprocess isolation", en: "Subprocess isolation" },
      { v: "v0.37.0", ko: "4-Layer · Bootstrap 통합", en: "4-Layer · unified bootstrap" },
      { v: "v0.40.0", ko: "200K token guard", en: "200K token guard" },
    ],
  },
  {
    id: "C4",
    range: "v0.40.0 → v0.49.0",
    period: "2026-03-31 → 04-23",
    accent: "artifact",
    titleKo: "Hook Interceptor + OSS 공개",
    titleEn: "Hook interceptor + OSS opening",
    bodyKo:
      "v0.48에서 Hook이 observer에서 observer + interceptor로 진화하면서 USER_INPUT_RECEIVED, TOOL_EXEC_START/END, COST_WARNING/LIMIT_EXCEEDED, EXECUTION_CANCELLED 6개 이벤트가 추가됐습니다. v0.49에서 GEODE를 OSS로 공개했고 Claude Opus 4.7과 GLM-5.1을 1차 모델로 승격했습니다.",
    bodyEn:
      "v0.48 evolved Hooks from observer to observer + interceptor and added six events — USER_INPUT_RECEIVED, TOOL_EXEC_START/END, COST_WARNING/LIMIT_EXCEEDED, EXECUTION_CANCELLED. v0.49 opened GEODE as OSS and promoted Claude Opus 4.7 and GLM-5.1 to primary models.",
    chips: [
      { v: "v0.45–47", ko: "Scheduler hardening", en: "Scheduler hardening" },
      { v: "v0.48.0", ko: "Hook interceptor · 55 events", en: "Hook interceptor · 55 events" },
      { v: "v0.49.0", ko: "OSS · Opus 4.7 · GLM-5.1", en: "OSS · Opus 4.7 · GLM-5.1" },
    ],
  },
  {
    id: "C5",
    range: "v0.50.0 → v0.53.0",
    period: "2026-04-25 → 04-27",
    accent: "line",
    titleKo: "/login 통합 + 4-프로세스 분할",
    titleEn: "/login unification + 4-process split",
    bodyKo:
      "Plan + ProviderSpec 모델로 `/key` `/auth` `/login` 분기를 단일 dashboard로 통합했습니다. v0.52에서 cli / server / agent / channels 네 프로세스 경계를 디렉토리 위치로 가시화하고 import-linter 4 contract으로 잠갔습니다. v0.53은 fail-fast governance redesign입니다.",
    bodyEn:
      "A Plan + ProviderSpec model unified the `/key` `/auth` `/login` split into a single dashboard. v0.52 surfaced four process boundaries — cli / server / agent / channels — as directory locations and locked them with four import-linter contracts. v0.53 is a fail-fast governance redesign.",
    chips: [
      { v: "v0.50.0", ko: "/login · Plan model · auth.toml", en: "/login · Plan model · auth.toml" },
      { v: "v0.51.0", ko: "manage_login tool", en: "manage_login tool" },
      { v: "v0.52.0", ko: "4-process binding · import-linter", en: "4-process binding · import-linter" },
      { v: "v0.53.0", ko: "Fail-fast governance", en: "Fail-fast governance" },
    ],
  },
  {
    id: "C6",
    range: "v0.55.0 → v0.62.0",
    period: "2026-04-28 (하루 안에 8개 릴리스)",
    accent: "artifact",
    titleKo: "R-Series. Reasoning Wire Audit",
    titleEn: "R-Series. Reasoning wire audit",
    bodyKo:
      "9-cycle reasoning depth audit를 네 개 프로바이더에 정렬했습니다. R1 Codex Plus encrypted_content replay walker, R2 GLM thinking field 활성화, R3-mini PAYG OpenAI Responses parity, R4-mini Anthropic Opus 4.7 xhigh effort, R6 reasoning summary IPC 표면화, R9 라이브 와이어 테스트. v0.59에서 model × effort 두 축 /model picker가 들어왔습니다. 8 릴리스가 같은 날에 들어왔습니다.",
    bodyEn:
      "A 9-cycle reasoning depth audit was aligned across four providers — R1 Codex Plus encrypted_content replay walker, R2 GLM thinking field activation, R3-mini PAYG OpenAI Responses parity, R4-mini Anthropic Opus 4.7 xhigh effort, R6 reasoning-summary IPC surfacing, R9 live wire tests. v0.59 added a two-axis (model × effort) `/model` picker. Eight releases shipped on the same day.",
    chips: [
      { v: "v0.55.0", ko: "R1 · Codex replay", en: "R1 · Codex replay" },
      { v: "v0.56.0", ko: "R4-mini · xhigh effort", en: "R4-mini · xhigh effort" },
      { v: "v0.57.0", ko: "R6 · reasoning IPC", en: "R6 · reasoning IPC" },
      { v: "v0.58.0", ko: "R2 · GLM thinking", en: "R2 · GLM thinking" },
      { v: "v0.59.0", ko: "Two-axis /model picker", en: "Two-axis /model picker" },
      { v: "v0.60.0", ko: "R3-mini · PAYG parity", en: "R3-mini · PAYG parity" },
      { v: "v0.62.0", ko: "R9 · live wire tests", en: "R9 · live wire tests" },
    ],
  },
  {
    id: "C7",
    range: "v0.63.0 → v0.65.0",
    period: "2026-04-29 → 05-02",
    accent: "line",
    titleKo: "Plugin Split + Messages Cache",
    titleEn: "Plugin split + messages cache",
    bodyKo:
      "v0.63 Lifecycle command suite(`/stop` `/clean` `/uninstall` `/status`). v0.64에서 Game IP 도메인을 `plugins/game_ip/`으로 분리해 \"도메인은 플러그인\" 테제의 구조적 증거를 만들었습니다. v0.65에서 Anthropic messages cache_control breakpoint(Hermes system_and_3 parity)를 도입해 멀티턴 입력 토큰 비용을 크게 낮췄습니다.",
    bodyEn:
      "v0.63 added a lifecycle command suite (`/stop` `/clean` `/uninstall` `/status`). v0.64 extracted the Game IP domain into `plugins/game_ip/`, structural evidence for the \"domain is a plugin\" thesis. v0.65 introduced Anthropic messages cache_control breakpoints (Hermes system_and_3 parity), cutting multi-turn input token cost.",
    chips: [
      { v: "v0.63.0", ko: "Lifecycle commands", en: "Lifecycle commands" },
      { v: "v0.64.0", ko: "plugins/game_ip 분리", en: "plugins/game_ip extracted" },
      { v: "v0.65.0", ko: "Messages cache_control", en: "Messages cache_control" },
    ],
  },
];

const forkBand = {
  range: "REODE fork",
  period: "2026-03-16 → 05-16 (@pinxlab, freelance)",
  titleKo: "REODE. DomainPort 교체 가능성 실증",
  titleEn: "REODE. DomainPort swappability validation",
  bodyKo:
    "GEODE v0.12 분기. Java 1.8 → 22, Spring 4.3 → 6.1 자동 마이그레이션 에이전트로 5,523파일 엔터프라이즈 프로젝트에서 83/83 모듈 빌드를 통과했습니다. 에러 4분류 라우팅(CONFIG / CODE / BEHAVIOR / ENV)과 Architect/Editor 분리 위에 5시간 48분, 1,133턴 자율 수행, $388.",
  bodyEn:
    "Forked from GEODE v0.12. A Java 1.8 → 22, Spring 4.3 → 6.1 migration agent that passed 83/83 module builds across a 5,523-file enterprise project, on top of 4-class error routing (CONFIG / CODE / BEHAVIOR / ENV) and an Architect/Editor split. 5h 48m, 1,133 autonomous rounds, $388.",
  chips: [
    "Java 1.8 → 22",
    "Spring 4.3 → 6.1",
    "83 / 83 modules",
    "5,523 files",
    "5h 48m · $388",
  ],
};

export function TimelineSection() {
  const locale = useLocale();
  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-3xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold uppercase tracking-[0.25em] mb-3 text-[var(--ink-3)]">
            § Timeline
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-[var(--ink-1)] mb-3">
            {t(locale, "v0.6.0 → v0.65.0", "v0.6.0 → v0.65.0")}
          </h2>
          <p className="max-w-2xl text-[var(--ink-2)] text-[15px] leading-relaxed mb-8">
            {t(
              locale,
              "Game IP 도메인 파이프라인에서 시작해 자율 실행 하네스로 자라는 데 54일이 걸렸습니다. CHANGELOG에 기록된 64회 릴리스를 7개 챕터로 묶어 정리했습니다.",
              "From a Game IP domain pipeline to a general-purpose autonomous execution harness in 54 days. The 64 releases recorded in CHANGELOG are grouped here into seven chapters."
            )}
          </p>

          {/* Cadence stat strip */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-3 mb-12 pt-5 pb-5 border-t border-b border-[var(--rule)]">
            {[
              { kKo: "기간", kEn: "Span", v: "2026-03-10 → 05-02" },
              { kKo: "릴리스", kEn: "Releases", v: "64 · ≈1.2 / day" },
              { kKo: "테스트", kEn: "Tests", v: "1,879 → 4,380" },
              { kKo: "모듈", kEn: "Modules", v: "115 → 236" },
            ].map((s) => (
              <div key={s.kEn}>
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)] mb-0.5">
                  {locale === "en" ? s.kEn : s.kKo}
                </div>
                <div className="font-mono text-[12.5px] text-[var(--ink-1)]">{s.v}</div>
              </div>
            ))}
          </div>
        </ScrollReveal>

        <ScrollRevealGroup className="relative" stagger={0.08}>
          {/* Vertical line */}
          <div className="absolute left-[19px] top-3 bottom-3 w-px bg-[var(--rule)]" />

          <div className="flex flex-col gap-10">
            {chapters.map((c) => (
              <motion.div key={c.id} variants={revealChild} className="flex items-start gap-5">
                {/* Dot */}
                <div className="relative shrink-0 mt-2">
                  <div
                    className="w-[10px] h-[10px] rounded-full"
                    style={{
                      backgroundColor: accentVar(c.accent),
                      boxShadow: `0 0 0 3px var(--paper)`,
                    }}
                  />
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-1.5">
                    <span
                      className="font-mono text-[11px] tracking-[0.18em]"
                      style={{ color: accentVar(c.accent) }}
                    >
                      {c.id} · {c.range}
                    </span>
                    <span className="font-mono text-[11px] text-[var(--ink-3)]">{c.period}</span>
                  </div>

                  <h3 className="text-[17px] font-semibold text-[var(--ink-1)] mb-1.5 tracking-tight">
                    {locale === "en" ? c.titleEn : c.titleKo}
                  </h3>
                  <p className="text-[14px] text-[var(--ink-2)] leading-relaxed mb-3">
                    {locale === "en" ? c.bodyEn : c.bodyKo}
                  </p>

                  <div className="flex flex-wrap gap-1.5">
                    {c.chips.map((chip) => (
                      <span
                        key={chip.v}
                        className="px-2 py-0.5 rounded text-[10.5px] font-mono text-[var(--ink-2)] bg-[var(--paper-2)] border border-[var(--rule)]"
                      >
                        <span style={{ color: accentVar(c.accent) }}>{chip.v}</span>
                        <span className="mx-1.5 text-[var(--ink-3)]">·</span>
                        {locale === "en" ? chip.en : chip.ko}
                      </span>
                    ))}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </ScrollRevealGroup>

        {/* Fork band — REODE */}
        <ScrollReveal delay={0.1}>
          <div className="mt-12 rounded border border-[var(--rule)] bg-[var(--paper-2)] px-6 py-5">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-1.5">
              <span
                className="font-mono text-[11px] tracking-[0.18em]"
                style={{ color: "var(--acc-artifact)" }}
              >
                ⌥ {forkBand.range}
              </span>
              <span className="font-mono text-[11px] text-[var(--ink-3)]">{forkBand.period}</span>
            </div>
            <h3 className="text-[16px] font-semibold text-[var(--ink-1)] mb-1.5 tracking-tight">
              {locale === "en" ? forkBand.titleEn : forkBand.titleKo}
            </h3>
            <p className="text-[14px] text-[var(--ink-2)] leading-relaxed mb-3">
              {locale === "en" ? forkBand.bodyEn : forkBand.bodyKo}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {forkBand.chips.map((chip) => (
                <span
                  key={chip}
                  className="px-2 py-0.5 rounded text-[10.5px] font-mono text-[var(--ink-2)] bg-[var(--paper)] border border-[var(--rule)]"
                >
                  {chip}
                </span>
              ))}
            </div>
          </div>
        </ScrollReveal>

        <ScrollReveal delay={0.2}>
          <div className="mt-16 flex items-center justify-center gap-4">
            <Image
              src="/geode/images/geode-idle.png"
              alt="Geodi"
              width={32}
              height={32}
              className="opacity-60"
            />
            <Link
              href="/"
              className="font-mono text-[11px] text-[var(--ink-3)] hover:text-[var(--acc-artifact)] transition-colors"
            >
              {t(locale, "← 포트폴리오로 돌아가기", "← Back to portfolio")}
            </Link>
            <a
              href="https://github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md"
              target="_blank"
              rel="noreferrer"
              className="font-mono text-[11px] text-[var(--ink-3)] hover:text-[var(--acc-line)] transition-colors"
            >
              {t(locale, "→ CHANGELOG", "→ CHANGELOG")}
            </a>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
