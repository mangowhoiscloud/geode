"use client";

import { useState } from "react";
import { useLocale, t, type Locale } from "../locale-context";

/**
 * CapabilitiesTabsSection. The keystone map.
 *
 * The portfolio used to carry roughly 23 flat co-equal subsystem sections.
 * This block compresses that into one tabbed map of 6 capabilities. Each tab
 * BODY is a simulated GEODE session, Claude-Code style: a prompt line, a few
 * action lines marked with the petri-blue dot, and one qualitative result.
 * Action lines describe what the agent does, never fabricated outputs or
 * numbers. A one-line caption and a docs deep link sit under each session.
 * The tab strip reuses the hero's underline visual: the active tab sits in
 * --ink with a citrine bottom border, inactive tabs in --ink-3, over a single
 * hairline under the whole strip.
 */
type Line = { ko: string; en: string };

type Tab = {
  id: string;
  labelKo: string;
  labelEn: string;
  prompt: Line;
  /** Whether the prompt is a CLI invocation (mono, no leading "geode >"). */
  cli?: boolean;
  actions: Line[];
  result: Line;
  captionKo: string;
  captionEn: string;
  href: string;
  linkKo: string;
  linkEn: string;
};

const tabs: Tab[] = [
  {
    id: "runtime",
    labelKo: "런타임",
    labelEn: "Runtime",
    prompt: {
      ko: "이 세 모델을 요약 작업 기준으로 비교해줘",
      en: "compare these three models for a summarization task",
    },
    actions: [
      { ko: "프로바이더 어댑터로 라우팅합니다", en: "Routing across providers" },
      { ko: "폴백 체인을 따라 실행합니다", en: "Running with fallback chain" },
      { ko: "지연 로딩 도구 레지스트리에서 도구를 불러옵니다", en: "Pulling tools from the deferred registry" },
    ],
    result: {
      ko: "세 모델의 응답을 한 표로 정리해 비교를 돌려줍니다.",
      en: "Returns a side-by-side comparison of the three responses.",
    },
    captionKo: "모델 라우팅과 도구 실행을 맡는 LLM-OS 계층입니다.",
    captionEn: "The LLM-OS layer that handles model routing and tool execution.",
    href: "/geode/docs/runtime/llm/providers",
    linkKo: "프로바이더 문서",
    linkEn: "Providers",
  },
  {
    id: "agentic-loop",
    labelKo: "에이전트 루프",
    labelEn: "Agentic loop",
    prompt: {
      ko: "이 저장소를 살펴보고 릴리스 블로커를 정리해줘",
      en: "inspect this repo and list release blockers",
    },
    actions: [
      { ko: "코드베이스를 읽습니다", en: "Reading the codebase" },
      { ko: "도구를 호출합니다", en: "Calling tools" },
      { ko: "결과를 종합해 추론합니다", en: "Reasoning over results" },
    ],
    result: {
      ko: "종료 경로에 닿을 때까지 반복하고, 블로커 목록을 정리해 돌려줍니다.",
      en: "Repeats until a termination path, then returns the blocker list.",
    },
    captionKo: "while(tool_use) 형태의 내부 루프입니다.",
    captionEn: "The while(tool_use) inner loop.",
    href: "/geode/docs/concepts/two-loops",
    linkKo: "두 개의 루프",
    linkEn: "Two loops",
  },
  {
    id: "self-improving",
    labelKo: "자기 개선 루프",
    labelEn: "Self-improving loop",
    prompt: { ko: "geode audit-loop run", en: "geode audit-loop run" },
    cli: true,
    actions: [
      { ko: "정책 파일을 변형합니다", en: "Mutating a policy file" },
      { ko: "안전 루브릭으로 감사합니다", en: "Auditing against the safety rubric" },
      { ko: "실제 이득이면 승격하고, 아니면 되돌립니다", en: "Promoting on a real gain, else reverting" },
    ],
    result: {
      ko: "변경은 베이스라인과 비교해 승격하거나 되돌립니다.",
      en: "The change is promoted or reverted against the baseline.",
    },
    captionKo: "스스로의 스캐폴드를 변형하고 감사하는 외부 루프입니다.",
    captionEn: "The outer loop that mutates its own scaffolding and audits it.",
    href: "/geode/docs/capabilities/autoresearch",
    linkKo: "autoresearch",
    linkEn: "autoresearch",
  },
  {
    id: "orchestration",
    labelKo: "오케스트레이션",
    labelEn: "Orchestration",
    prompt: { ko: "geode serve", en: "geode serve" },
    cli: true,
    actions: [
      { ko: "게이트웨이 메시지를 세션 레인으로 라우팅합니다", en: "Routing a gateway message to a session lane" },
      { ko: "격리된 서브 에이전트를 띄웁니다", en: "Spawning isolated sub-agents" },
      { ko: "스케줄러로 작업을 넘깁니다", en: "Handing work to the scheduler" },
    ],
    result: {
      ko: "데몬이 메시징 게이트웨이로 받은 요청에 응답을 돌려줍니다.",
      en: "The daemon replies to the request taken through the gateway.",
    },
    captionKo: "서빙과 동시성을 맡는 계층입니다.",
    captionEn: "The serving and concurrency layer.",
    href: "/geode/docs/harness/serve-gateway",
    linkKo: "serve 게이트웨이",
    linkEn: "Serve gateway",
  },
  {
    id: "memory-hooks",
    labelKo: "메모리와 훅",
    labelEn: "Memory and hooks",
    prompt: {
      ko: "내 프로젝트 배포 절차를 기억해둬",
      en: "remember my project's deploy steps",
    },
    actions: [
      { ko: "5계층 메모리에 기록합니다", en: "Writing to the 5-tier memory" },
      { ko: "생명주기 훅을 부트스트랩 순서대로 발화합니다", en: "Firing the lifecycle hooks" },
      { ko: "다음 세션에서 다시 읽을 수 있게 고정합니다", en: "Pinning it for the next session" },
    ],
    result: {
      ko: "배포 절차를 메모리에 저장했다고 확인을 돌려줍니다.",
      en: "Confirms the deploy steps are saved to memory.",
    },
    captionKo: "상태와 이벤트 버스입니다.",
    captionEn: "State and the event bus.",
    href: "/geode/docs/runtime/memory/5-tier",
    linkKo: "5계층 메모리",
    linkEn: "5-tier memory",
  },
  {
    id: "verification",
    labelKo: "검증",
    labelEn: "Verification",
    prompt: {
      ko: "이 답변을 그대로 내보내도 될까",
      en: "is this answer safe to ship",
    },
    actions: [
      { ko: "출력을 G1-G4 기준으로 채점합니다", en: "Scoring output against G1-G4" },
      { ko: "교차 LLM으로 다시 확인합니다", en: "Cross-LLM re-check" },
      { ko: "플래그된 답변은 다시 프롬프트합니다", en: "Re-prompting on a flagged answer" },
    ],
    result: {
      ko: "가드레일에 걸린 부분을 잡아 다음 행동을 정해 돌려줍니다.",
      en: "Catches what the guardrails flag and settles the next action.",
    },
    captionKo: "LLM 출력 위에 놓이는 가드레일입니다.",
    captionEn: "Guardrails over LLM output.",
    href: "/geode/docs/verification/guardrails",
    linkKo: "가드레일",
    linkEn: "Guardrails",
  },
];

function TabSession({ tab, locale }: { tab: Tab; locale: Locale }) {
  return (
    <div className="rounded-lg border border-[var(--rule)] bg-[var(--code-bg)] p-5 font-mono text-[13px] leading-relaxed text-[var(--code-text)]">
      <div>
        {!tab.cli && <span className="text-[var(--acc-artifact)] font-medium">geode &gt;</span>}{" "}
        <span className="text-[var(--ink)]">{t(locale, tab.prompt.ko, tab.prompt.en)}</span>
      </div>
      {tab.actions.map((action) => (
        <div key={action.en} className="mt-2.5 text-[var(--ink-2)]">
          <span className="text-[var(--acc-artifact)] text-[15px]">{"⏺"}</span>{" "}
          {t(locale, action.ko, action.en)}
        </div>
      ))}
      <div className="mt-4 text-[var(--ink-1)]">{t(locale, tab.result.ko, tab.result.en)}</div>
    </div>
  );
}

export function CapabilitiesTabsSection() {
  const locale = useLocale();
  const [active, setActive] = useState(tabs[0].id);
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0];
  return (
    <section className="px-6 py-24">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center gap-2">
          <span className="h-px w-6 bg-[var(--acc-artifact)]" />
          <span className="text-[12px] tracking-[0.22em] uppercase text-[var(--acc-artifact)] font-medium">
            Capabilities
          </span>
        </div>
        <h2 className="mt-4 font-display tracking-tight text-[var(--ink)] text-[clamp(1.85rem,3.8vw,2.6rem)] leading-[1.12] font-semibold">
          {t(locale, "구성", "What's inside")}
        </h2>
        <p className="mt-4 text-[var(--ink-2)] leading-[1.75] text-[16px]">
          {t(
            locale,
            "깊이는 문서에 있습니다. 여기는 6개 능력을 한눈에 짚는 지도이고, 각 탭은 그 능력이 실제로 도는 세션을 보여줍니다.",
            "The depth lives in the docs. This is the map across 6 capabilities, and each tab shows a session of that capability running."
          )}
        </p>

        <div className="mt-10">
          <div className="flex flex-wrap gap-x-1 border-b border-[var(--rule)]">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActive(tab.id)}
                className="px-3.5 py-2.5 text-[13px] font-mono whitespace-nowrap transition-colors"
                style={{
                  color: active === tab.id ? "var(--acc-artifact)" : "var(--ink-3)",
                  fontWeight: active === tab.id ? 500 : 400,
                  borderBottom: `2px solid ${active === tab.id ? "var(--acc-artifact)" : "transparent"}`,
                  marginBottom: "-1px",
                }}
              >
                {t(locale, tab.labelKo, tab.labelEn)}
              </button>
            ))}
          </div>

          <div className="mt-6">
            <TabSession tab={current} locale={locale} />
            <p className="mt-4 text-[var(--ink-2)] leading-[1.75] text-[14px]">
              {t(locale, current.captionKo, current.captionEn)}
            </p>
            <a
              href={current.href}
              className="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--rule)] hover:border-[var(--acc-artifact)] text-[13px] font-mono text-[var(--ink-1)] hover:text-[var(--acc-artifact)] transition-colors"
            >
              {t(locale, current.linkKo, current.linkEn)} {"→"}
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
