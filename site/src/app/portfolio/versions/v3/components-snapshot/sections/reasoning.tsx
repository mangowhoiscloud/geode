"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";

type Mode = "react" | "plan";

export function ReasoningSection() {
  const [mode, setMode] = useState<Mode>("react");

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#818CF8]/60 uppercase tracking-[0.25em] mb-3">
            Reasoning
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-2">
            ReAct · Plan-and-Execute
          </h2>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-8 leading-relaxed">
            안쪽 루프(L1-L2)는 ReAct로 매 턴마다 관측→추론→행동을 반복하고,
            바깥 레이어(L4)는 Plan-and-Execute로 복잡한 요청을 구조화된 계획으로 분할합니다.
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
              Plan-and-Execute
              <span className="ml-2 text-[10px] opacity-50">L4 Outer</span>
            </button>
          </div>
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          {/* ── ReAct ── */}
          {mode === "react" && (
            <div>
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 700 220" className="w-full min-w-[520px]" style={{ maxHeight: 250 }}>
                  {/* OBSERVE */}
                  <rect x={40} y={60} width={130} height={60} rx={10} fill="#0A0F1A" stroke="#60A5FA" strokeWidth={1} strokeOpacity={0.3} />
                  <text x={105} y={83} textAnchor="middle" fill="#60A5FA" fontSize={12} fontFamily="ui-monospace, monospace" fontWeight={700}>OBSERVE</text>
                  <text x={105} y={100} textAnchor="middle" fill="#60A5FA" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">LLM call + context</text>

                  <line x1={170} y1={90} x2={230} y2={90} stroke="white" strokeOpacity={0.14} strokeWidth={1} />

                  {/* ACT */}
                  <rect x={230} y={60} width={130} height={60} rx={10} fill="#0A0F1A" stroke="#4ECDC4" strokeWidth={1} strokeOpacity={0.3} />
                  <text x={295} y={83} textAnchor="middle" fill="#4ECDC4" fontSize={12} fontFamily="ui-monospace, monospace" fontWeight={700}>ACT</text>
                  <text x={295} y={100} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">tool execution</text>

                  <line x1={360} y1={90} x2={420} y2={90} stroke="white" strokeOpacity={0.14} strokeWidth={1} />

                  {/* REFLECT */}
                  <rect x={420} y={60} width={130} height={60} rx={10} fill="#0A0F1A" stroke="#C084FC" strokeWidth={1} strokeOpacity={0.3} />
                  <text x={485} y={83} textAnchor="middle" fill="#C084FC" fontSize={12} fontFamily="ui-monospace, monospace" fontWeight={700}>REFLECT</text>
                  <text x={485} y={100} textAnchor="middle" fill="#C084FC" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">result → context</text>

                  {/* Loop-back */}
                  <path d="M485,120 C485,160 295,170 105,160 L105,120" fill="none" stroke="#F5C542" strokeOpacity={0.18} strokeWidth={1.5} strokeDasharray="6 4" className="animate-flow" />
                  <text x={295} y={180} textAnchor="middle" fill="#F5C542" fillOpacity={0.2} fontSize={9} fontFamily="ui-monospace, monospace">while(tool_use) — max 50 rounds</text>

                  {/* GoalDecomposer fork */}
                  <rect x={560} y={40} width={110} height={50} rx={8} fill="#0A0F1A" stroke="#F4B8C8" strokeWidth={0.7} strokeOpacity={0.2} />
                  <text x={615} y={60} textAnchor="middle" fill="#F4B8C8" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>GoalDecomposer</text>
                  <text x={615} y={75} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">복합 요청 분해</text>
                  <line x1={550} y1={65} x2={560} y2={65} stroke="#F4B8C8" strokeOpacity={0.14} strokeWidth={1} />

                  {/* Tool tiers */}
                  <text x={295} y={40} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.30} fontSize={8} fontFamily="ui-monospace, monospace">
                    SAFE(auto) · STANDARD(auto) · WRITE(HITL) · DANGEROUS(gate)
                  </text>

                  {/* Error recovery */}
                  <text x={295} y={210} textAnchor="middle" fill="#E87080" fillOpacity={0.25} fontSize={8} fontFamily="ui-monospace, monospace">
                    consecutive failure ≥ 2 → adaptive recovery chain
                  </text>
                </svg>
              </div>
              <p className="text-sm text-[#8B9CC0] leading-relaxed">
                매 라운드마다 LLM이 관측(OBSERVE)하고, 도구를 선택·실행(ACT)하고, 결과를 컨텍스트에 반영(REFLECT)합니다.
                복합 요청이면 GoalDecomposer가 sub-goal로 분해하여 시스템 프롬프트에 주입합니다.
              </p>
            </div>
          )}

          {/* ── Plan-and-Execute ── */}
          {mode === "plan" && (
            <div>
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 760 200" className="w-full min-w-[560px]" style={{ maxHeight: 230 }}>
                  {/* Planner */}
                  <rect x={20} y={55} width={100} height={55} rx={10} fill="#0A0F1A" stroke="#60A5FA" strokeWidth={1} strokeOpacity={0.3} />
                  <text x={70} y={78} textAnchor="middle" fill="#60A5FA" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>Planner</text>
                  <text x={70} y={95} textAnchor="middle" fill="#60A5FA" fillOpacity={0.35} fontSize={8} fontFamily="ui-monospace, monospace">6 routes</text>

                  <line x1={120} y1={82} x2={155} y2={82} stroke="white" strokeOpacity={0.14} strokeWidth={1} />

                  {/* PlanMode lifecycle */}
                  {[
                    { label: "CREATE", x: 185, color: "#818CF8" },
                    { label: "PRESENT", x: 285, color: "#C084FC" },
                    { label: "APPROVE", x: 395, color: "#F5C542" },
                    { label: "EXECUTE", x: 505, color: "#4ECDC4" },
                    { label: "DONE", x: 605, color: "#34D399" },
                  ].map((s, i) => (
                    <g key={s.label}>
                      <rect x={s.x - 40} y={55} width={80} height={55} rx={8} fill="#0A0F1A" stroke={s.color} strokeWidth={0.8} strokeOpacity={0.25} />
                      <text x={s.x} y={78} textAnchor="middle" fill={s.color} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>{s.label}</text>
                      <text x={s.x} y={95} textAnchor="middle" fill={s.color} fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">
                        {["template", "user review", "HITL gate", "TaskSystem", "scorecard"][i]}
                      </text>
                      {i < 4 && (
                        <line x1={s.x + 40} y1={82} x2={[285, 395, 505, 605][i] - 40} y2={82} stroke="white" strokeOpacity={0.12} strokeWidth={1} />
                      )}
                    </g>
                  ))}

                  {/* Parallel batches */}
                  <text x={505} y={135} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.2} fontSize={8} fontFamily="ui-monospace, monospace">
                    execution_order() → parallel batches
                  </text>

                  {/* Templates */}
                  <rect x={660} y={30} width={80} height={38} rx={6} fill="#0A0F1A" stroke="#F5C542" strokeWidth={0.5} strokeOpacity={0.15} />
                  <text x={700} y={48} textAnchor="middle" fill="#F5C542" fillOpacity={0.5} fontSize={8} fontFamily="ui-monospace, monospace">full: $1.50</text>
                  <text x={700} y={60} textAnchor="middle" fill="#F5C542" fillOpacity={0.3} fontSize={7} fontFamily="ui-monospace, monospace">10 steps</text>
                  <rect x={660} y={74} width={80} height={38} rx={6} fill="#0A0F1A" stroke="#818CF8" strokeWidth={0.5} strokeOpacity={0.15} />
                  <text x={700} y={92} textAnchor="middle" fill="#818CF8" fillOpacity={0.5} fontSize={8} fontFamily="ui-monospace, monospace">prospect: $0.80</text>
                  <text x={700} y={104} textAnchor="middle" fill="#818CF8" fillOpacity={0.3} fontSize={7} fontFamily="ui-monospace, monospace">6 steps</text>

                  {/* REJECT feedback */}
                  <path d="M395,110 L395,160 L185,160 L185,110" fill="none" stroke="#E87080" strokeOpacity={0.18} strokeWidth={1} strokeDasharray="4 4" />
                  <text x={290} y={172} textAnchor="middle" fill="#E87080" fillOpacity={0.30} fontSize={8} fontFamily="ui-monospace, monospace">REJECTED → re-plan</text>

                  {/* Layer labels */}
                  <text x={380} y={20} textAnchor="middle" fill="white" fillOpacity={0.18} fontSize={9} fontFamily="ui-monospace, monospace" letterSpacing="0.1em">
                    L4 ORCHESTRATION — PLAN BEFORE EXECUTE
                  </text>
                </svg>
              </div>
              <p className="text-sm text-[#8B9CC0] leading-relaxed">
                복잡한 요청은 Planner가 6개 Route 중 하나로 분류하고, PlanMode가 구조화된 계획을 생성합니다.
                사용자 승인(HITL) 후 TaskSystem이 의존성 기반 병렬 배치로 실행합니다.
                REJECTED되면 CREATE로 복귀하여 재계획합니다.
              </p>
            </div>
          )}
        </ScrollReveal>
      </div>
    </section>
  );
}
