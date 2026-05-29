"use client";

import { useState } from "react";
import { useLocale, t } from "../locale-context";

/**
 * CapabilitiesTabsSection. The keystone map.
 *
 * The portfolio used to carry roughly 23 flat co-equal subsystem sections.
 * This block compresses that into one tabbed map of 6 capabilities. Each tab
 * shows a short paragraph, a tight inline list of what is inside, and one
 * docs deep link. It is a teaser, not the full section, the depth lives in
 * the docs. The tab strip reuses the hero's underline visual: the active tab
 * sits in --ink with a citrine bottom border, inactive tabs in --ink-3, over
 * a single hairline under the whole strip.
 */
type Tab = {
  id: string;
  labelKo: string;
  labelEn: string;
  bodyKo: string;
  bodyEn: string;
  insideKo: string[];
  insideEn: string[];
  href: string;
  linkKo: string;
  linkEn: string;
};

const tabs: Tab[] = [
  {
    id: "runtime",
    labelKo: "런타임",
    labelEn: "Runtime",
    bodyKo: "모델 라우팅과 도구 실행을 맡는 LLM-OS 계층입니다. 요청은 프로바이더 어댑터로 라우팅되고, 도구는 레지스트리에서 필요할 때 불려 나옵니다.",
    bodyEn: "The LLM-OS layer that handles model routing and tool execution. A request routes through a provider adapter, and tools are pulled from the registry when they are needed.",
    insideKo: ["프로바이더 어댑터", "폴백 체인", "지연 로딩 도구 레지스트리", "MCP"],
    insideEn: ["provider adapters", "fallback chains", "tool registry with deferred loading", "MCP"],
    href: "/geode/docs/runtime/llm/providers",
    linkKo: "프로바이더 문서",
    linkEn: "Providers",
  },
  {
    id: "agentic-loop",
    labelKo: "에이전트 루프",
    labelEn: "Agentic loop",
    bodyKo: "while(tool_use) 형태의 내부 루프입니다. 추론하고, 컨텍스트를 조립하고, 도구를 호출하기를 종료 조건에 닿을 때까지 반복합니다.",
    bodyEn: "The while(tool_use) inner loop. It reasons, assembles context, and calls tools, repeating until it reaches a termination path.",
    insideKo: ["ReAct + plan-and-execute", "5계층 컨텍스트", "종료 경로"],
    insideEn: ["ReAct + plan-and-execute", "5-tier context", "termination paths"],
    href: "/geode/docs/concepts/two-loops",
    linkKo: "두 개의 루프",
    linkEn: "Two loops",
  },
  {
    id: "self-improving",
    labelKo: "자기 개선 루프",
    labelEn: "Self-improving loop",
    bodyKo: "스스로의 스캐폴드를 변형하고 감사하는 외부 루프입니다. 변화는 베이스라인과 비교해 승격하거나 되돌립니다.",
    bodyEn: "The outer loop that mutates its own scaffolding and audits it. A change is promoted or reverted against the baseline.",
    insideKo: ["mutations", "baseline", "promote / revert", "co-scientist 시드 파이프라인"],
    insideEn: ["mutations", "baseline", "promote / revert", "the co-scientist seed pipeline"],
    href: "/geode/docs/capabilities/autoresearch",
    linkKo: "autoresearch",
    linkEn: "autoresearch",
  },
  {
    id: "orchestration",
    labelKo: "오케스트레이션",
    labelEn: "Orchestration",
    bodyKo: "서빙과 동시성을 맡습니다. serve 데몬이 메시징 게이트웨이를 통해 요청을 받고, 작업은 동시성 레인과 스케줄러를 거칩니다.",
    bodyEn: "Serving and concurrency. The serve daemon takes requests through a messaging gateway, and work runs across concurrency lanes and the scheduler.",
    insideKo: ["serve 데몬과 메시징 게이트웨이", "동시성 레인", "스케줄러", "headless 실행 모드", "서브 에이전트"],
    insideEn: ["the serve daemon and messaging gateway", "concurrency lanes", "the scheduler", "headless run mode", "sub-agents"],
    href: "/geode/docs/harness/serve-gateway",
    linkKo: "serve 게이트웨이",
    linkEn: "Serve gateway",
  },
  {
    id: "memory-hooks",
    labelKo: "메모리와 훅",
    labelEn: "Memory and hooks",
    bodyKo: "상태와 이벤트 버스입니다. 메모리는 5계층 위계로 나뉘고, 생명주기 훅이 부트스트랩 순서대로 이벤트에 반응합니다.",
    bodyEn: "State and the event bus. Memory splits into a 5-tier hierarchy, and lifecycle hooks react to events in bootstrap order.",
    insideKo: ["5계층 메모리 위계", "생명주기 훅 시스템", "부트스트랩 순서"],
    insideEn: ["the 5-tier memory hierarchy", "the lifecycle hook system", "bootstrap order"],
    href: "/geode/docs/runtime/memory/5-tier",
    linkKo: "5계층 메모리",
    linkEn: "5-tier memory",
  },
  {
    id: "verification",
    labelKo: "검증",
    labelEn: "Verification",
    bodyKo: "LLM 출력 위에 놓이는 가드레일입니다. 스키마와 범위, 근거, 일관성을 거른 뒤 교차 검증과 원인 분류로 다음 행동을 정합니다.",
    bodyEn: "Guardrails over LLM output. It filters schema, range, grounding, and consistency, then settles the next action with cross-verification and a cause decision tree.",
    insideKo: ["G1-G4 가드레일", "BiasBuster", "교차 LLM 검증", "원인 결정 트리"],
    insideEn: ["G1-G4 guardrails", "BiasBuster", "cross-LLM verification", "the cause decision tree"],
    href: "/geode/docs/verification/guardrails",
    linkKo: "가드레일",
    linkEn: "Guardrails",
  },
];

export function CapabilitiesTabsSection() {
  const locale = useLocale();
  const [active, setActive] = useState(tabs[0].id);
  const current = tabs.find((tab) => tab.id === active) ?? tabs[0];
  return (
    <section className="px-6 py-20">
      <div className="max-w-3xl mx-auto">
        <div className="font-mono text-[11px] tracking-[0.24em] uppercase text-[var(--acc-artifact)]">
          Capabilities
        </div>
        <h2 className="mt-3 font-display tracking-tight text-[var(--ink)] text-[clamp(1.7rem,3.6vw,2.4rem)] leading-[1.12] font-semibold">
          {t(locale, "구성", "What's inside")}
        </h2>
        <p className="mt-4 text-[var(--ink-2)] leading-[1.75] text-[16px]">
          {t(
            locale,
            "깊이는 문서에 있습니다. 여기는 6개 능력을 한눈에 짚는 지도입니다.",
            "The depth lives in the docs. This is the map across 6 capabilities, one place to start."
          )}
        </p>

        <div className="mt-8">
          <div className="flex flex-wrap gap-x-1 border-b border-[var(--rule)]">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActive(tab.id)}
                className="px-3 py-2 text-[12.5px] font-mono whitespace-nowrap transition-colors"
                style={{
                  color: active === tab.id ? "var(--ink)" : "var(--ink-3)",
                  borderBottom: `2px solid ${active === tab.id ? "var(--acc-line)" : "transparent"}`,
                  marginBottom: "-1px",
                }}
              >
                {t(locale, tab.labelKo, tab.labelEn)}
              </button>
            ))}
          </div>

          <div className="mt-6">
            <p className="text-[var(--ink-2)] leading-[1.75] text-[16px]">
              {t(locale, current.bodyKo, current.bodyEn)}
            </p>
            <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[12.5px] text-[var(--ink-3)]">
              {(locale === "en" ? current.insideEn : current.insideKo).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <a
              href={current.href}
              className="mt-6 inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--rule)] hover:border-[var(--acc-artifact)] text-[13px] font-mono text-[var(--ink-1)] hover:text-[var(--acc-artifact)] transition-colors"
            >
              {t(locale, current.linkKo, current.linkEn)} {"→"}
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
