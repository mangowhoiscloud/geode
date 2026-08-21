"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";
import { useLocale, t } from "../locale-context";

type Mode = "react" | "plan";

export function ReasoningSection() {
  const locale = useLocale();
  const [mode, setMode] = useState<Mode>("react");

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#818CF8]/60 uppercase tracking-[0.25em] mb-3">
            Reasoning
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-2">
            ReAct · Advisory Plan
          </h2>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-8 leading-relaxed">
            {t(locale,
              "AgenticLoop는 관측→추론→행동을 반복합니다. 명시적 /plan은 2–4개 구조를 내부 비교한 뒤 최대 8개의 검증 가능한 advisory step만 설치합니다. 도구·인자·dependency를 미리 고정하지 않고, verify 실패나 low-confidence 관측이 있을 때만 plan을 수정합니다.",
              "AgenticLoop repeats observe, reason, and act. Explicit /plan compares 2–4 structures internally and installs at most eight verifiable advisory steps. It does not precommit tools, arguments, or dependencies, and revises the plan only from verify failure or observed low confidence."
            )}
          </p>
        </ScrollReveal>

        {/* Mode toggle */}
        <ScrollReveal delay={0.05}>
          <div className="flex gap-2 mb-8">
            <button
              onClick={() => setMode("react")}
              className="px-4 py-2 rounded-lg text-xs font-mono font-bold transition-all duration-300"
              style={{
                color: mode === "react" ? "#4ECDC4" : "#5A6A8A",
                background: mode === "react" ? "rgba(78,205,196,0.08)" : "transparent",
                border: `1px solid ${mode === "react" ? "rgba(78,205,196,0.2)" : "rgba(255,255,255,0.04)"}`,
              }}
            >
              ReAct Loop
              <span className="ml-2 text-[10px] opacity-50">L1-L2 Inner</span>
            </button>
            <button
              onClick={() => setMode("plan")}
              className="px-4 py-2 rounded-lg text-xs font-mono font-bold transition-all duration-300"
              style={{
                color: mode === "plan" ? "#F5C542" : "#5A6A8A",
                background: mode === "plan" ? "rgba(245,197,66,0.08)" : "transparent",
                border: `1px solid ${mode === "plan" ? "rgba(245,197,66,0.2)" : "rgba(255,255,255,0.04)"}`,
              }}
            >
              Advisory Plan
              <span className="ml-2 text-[10px] opacity-50">Observation-conditioned</span>
            </button>
          </div>
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          {/* ── ReAct ── */}
          {mode === "react" && (
            <div>
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 620 200" className="w-full min-w-[480px]" style={{ maxHeight: 230 }}>
                  {/* OBSERVE */}
                  <rect x={50} y={40} width={150} height={58} rx={12} fill="#0C1220" stroke="#60A5FA" strokeWidth={1.2} strokeOpacity={0.45} />
                  <text x={125} y={64} textAnchor="middle" fill="#60A5FA" fontSize={13} fontFamily="ui-monospace, monospace" fontWeight={700}>OBSERVE</text>
                  <text x={125} y={82} textAnchor="middle" fill="#60A5FA" fillOpacity={0.45} fontSize={9} fontFamily="ui-monospace, monospace">LLM call + context</text>

                  <path d="M200,69 C220,64 240,64 260,69" stroke="white" strokeOpacity={0.25} strokeWidth={1.2} fill="none" />

                  {/* ACT */}
                  <rect x={260} y={40} width={120} height={58} rx={12} fill="#0C1220" stroke="#4ECDC4" strokeWidth={1.2} strokeOpacity={0.45} />
                  <text x={320} y={64} textAnchor="middle" fill="#4ECDC4" fontSize={13} fontFamily="ui-monospace, monospace" fontWeight={700}>ACT</text>
                  <text x={320} y={82} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.45} fontSize={9} fontFamily="ui-monospace, monospace">tool execution</text>

                  <path d="M380,69 C400,64 420,64 440,69" stroke="white" strokeOpacity={0.25} strokeWidth={1.2} fill="none" />

                  {/* REFLECT */}
                  <rect x={440} y={40} width={130} height={58} rx={12} fill="#0C1220" stroke="#C084FC" strokeWidth={1.2} strokeOpacity={0.45} />
                  <text x={505} y={64} textAnchor="middle" fill="#C084FC" fontSize={13} fontFamily="ui-monospace, monospace" fontWeight={700}>REFLECT</text>
                  <text x={505} y={82} textAnchor="middle" fill="#C084FC" fillOpacity={0.45} fontSize={9} fontFamily="ui-monospace, monospace">result → context</text>

                  {/* Loop-back */}
                  <path d="M505,98 C510,132 460,148 310,148 C160,148 110,132 125,98" fill="none" stroke="#F5C542" strokeOpacity={0.3} strokeWidth={1.5} strokeDasharray="6 4" className="animate-flow" />
                  <text x={310} y={168} textAnchor="middle" fill="#F5C542" fillOpacity={0.55} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>while(tool_use)</text>

                  {/* Tool tiers + recovery */}
                  <text x={310} y={188} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.45} fontSize={9} fontFamily="ui-monospace, monospace">
                    SAFE(auto) · STANDARD(auto) · WRITE(HITL) · DANGEROUS(gate)
                  </text>
                </svg>
              </div>
              <p className="text-sm text-[#8B9CC0] leading-relaxed">
                {t(locale,
                  "매 라운드마다 LLM이 관측(OBSERVE)하고, 도구를 선택·실행(ACT)하고, 결과를 컨텍스트에 반영(REFLECT)합니다. 일반 입력은 별도 decomposer call 없이 이 루프로 바로 들어옵니다.",
                  "Each round, the LLM observes, selects and executes a tool, then reflects the result into context. Ordinary input enters this loop directly without a separate decomposer call."
                )}
              </p>
            </div>
          )}

          {/* ── Observation-conditioned advisory plan ── */}
          {mode === "plan" && (
            <div>
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 700 130" className="w-full min-w-[500px]" style={{ maxHeight: 150 }}>
                  {/* Explicit plan → observation-conditioned action → evidence replan */}
                  {[
                    { label: "/plan", x: 60, color: "#60A5FA", sub: "tools off" },
                    { label: "ADVISE", x: 180, color: "#818CF8", sub: "≤8 steps" },
                    { label: "OBSERVE", x: 310, color: "#F5C542", sub: "current state" },
                    { label: "ACT", x: 440, color: "#4ECDC4", sub: "AgenticLoop" },
                    { label: "VERIFY", x: 560, color: "#34D399", sub: "evidence" },
                  ].map((s, i) => (
                    <g key={s.label}>
                      <rect x={s.x - 50} y={30} width={100} height={50} rx={8} fill="#0A0F1A" stroke={s.color} strokeWidth={0.8} strokeOpacity={0.4} />
                      <text x={s.x} y={52} textAnchor="middle" fill={s.color} fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>{s.label}</text>
                      <text x={s.x} y={68} textAnchor="middle" fill={s.color} fillOpacity={0.35} fontSize={8} fontFamily="ui-monospace, monospace">{s.sub}</text>
                      {i < 4 && <line x1={s.x + 50} y1={55} x2={[180, 310, 440, 560][i] - 50} y2={55} stroke="white" strokeOpacity={0.1} strokeWidth={1} />}
                    </g>
                  ))}
                  <text x={620} y={45} fill="#F5C542" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">verify fail</text>
                  <text x={620} y={60} fill="#818CF8" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">low confidence</text>
                  <path d="M560,80 C560,108 420,115 310,80" fill="none" stroke="#E87080" strokeOpacity={0.22} strokeWidth={1} strokeDasharray="3 3" />
                  <text x={440} y={118} textAnchor="middle" fill="#E87080" fillOpacity={0.4} fontSize={8} fontFamily="ui-monospace, monospace">evidence → revise</text>
                </svg>
              </div>
              <p className="text-sm text-[#8B9CC0] leading-relaxed">
                {t(locale,
                  "Plan은 실행 그래프가 아니라 현재 의도입니다. AgenticLoop가 관측에 따라 다음 행동을 고르고, update_plan은 이미 관측된 완료만 기록합니다. Cognitive Loop의 verify 실패와 low-confidence edge만 replan을 발화합니다.",
                  "A Plan is current intent, not an execution graph. AgenticLoop chooses the next action from observations, while update_plan records only observed completion. Cognitive Loop verify failure and low-confidence edges are the only replan triggers."
                )}
              </p>
            </div>
          )}
        </ScrollReveal>
      </div>
    </section>
  );
}
