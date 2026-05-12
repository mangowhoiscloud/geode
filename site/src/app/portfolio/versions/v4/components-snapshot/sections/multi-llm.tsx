"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";

type Mode = "pipeline" | "agentic";

/* ── Pipeline pricing (actually used) ── */
const pipelinePricing = [
  { model: "claude-opus-4-6", role: "전 노드 Primary", input: "$5.00", output: "$25.00", color: "#F4B8C8" },
  { model: "gpt-5.4", role: "Cross-LLM 검증 Secondary", input: "$2.50", output: "$15.00", color: "#34D399" },
];

/* ── Agentic pricing (failover chain) ── */
const agenticPricing = [
  { model: "claude-opus-4-6", role: "Primary (기본)", input: "$5.00", output: "$25.00", color: "#F4B8C8" },
  { model: "claude-sonnet-4-6", role: "Failover #1", input: "$3.00", output: "$15.00", color: "#818CF8" },
  { model: "gpt-5.4", role: "Cross-Provider Failover", input: "$2.50", output: "$15.00", color: "#34D399" },
  { model: "glm-5", role: "Budget / Cross-Provider", input: "$0.72", output: "$2.30", color: "#F5C542" },
  { model: "claude-haiku-4-5", role: "Token Guard (budget)", input: "$1.00", output: "$5.00", color: "#4ECDC4" },
];

export function MultiLlmSection() {
  const [mode, setMode] = useState<Mode>("pipeline");

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#F4B8C8]/60 uppercase tracking-[0.25em] mb-3">
            Multi-LLM
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-2">
            Port/Adapter 기반 LLM 교체
          </h2>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-8 leading-relaxed">
            파이프라인과 에이전트 루프에서 LLM을 다르게 운용합니다.
            Port/Adapter DI 패턴으로 런타임에 프로바이더를 교체하고,
            프로바이더 장애 시 자동 failover합니다.
          </p>
        </ScrollReveal>

        {/* ── Mode toggle ── */}
        <ScrollReveal delay={0.05}>
          <div className="flex gap-2 mb-8">
            <button
              onClick={() => setMode("pipeline")}
              className="px-4 py-2 rounded-lg text-xs font-mono font-bold transition-all duration-300"
              style={{
                color: mode === "pipeline" ? "#C084FC" : "#5A6A8A",
                background: mode === "pipeline" ? "rgba(192,132,252,0.08)" : "transparent",
                border: `1px solid ${mode === "pipeline" ? "rgba(192,132,252,0.2)" : "rgba(255,255,255,0.04)"}`,
              }}
            >
              Pipeline — LLM-as-Judge
              <span className="ml-2 text-[10px] opacity-50">Opus + GPT Cross</span>
            </button>
            <button
              onClick={() => setMode("agentic")}
              className="px-4 py-2 rounded-lg text-xs font-mono font-bold transition-all duration-300"
              style={{
                color: mode === "agentic" ? "#4ECDC4" : "#5A6A8A",
                background: mode === "agentic" ? "rgba(78,205,196,0.08)" : "transparent",
                border: `1px solid ${mode === "agentic" ? "rgba(78,205,196,0.2)" : "rgba(255,255,255,0.04)"}`,
              }}
            >
              Agentic Loop — Resilient Failover
              <span className="ml-2 text-[10px] opacity-50">5 Models · 3 Providers</span>
            </button>
          </div>
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          {/* ── Pipeline: LLM-as-Judge ── */}
          {mode === "pipeline" && (
            <div>
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 740 180" className="w-full min-w-[540px]" style={{ maxHeight: 210 }}>
                  {/* Opus block — covers all nodes */}
                  <rect x={20} y={20} width={520} height={140} rx={12} fill="none" stroke="#F4B8C8" strokeOpacity={0.12} strokeWidth={1} strokeDasharray="6 4" />
                  <text x={280} y={14} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.4} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>claude-opus-4-6 (Primary — 전 노드)</text>

                  {/* Pipeline nodes */}
                  {[
                    { x: 55, label: "Router" },
                    { x: 145, label: "Analyst×4" },
                    { x: 245, label: "Eval×3" },
                    { x: 335, label: "Scoring" },
                    { x: 435, label: "Synth" },
                  ].map((n, i) => (
                    <g key={n.label}>
                      <rect x={n.x - 38} y={50} width={76} height={40} rx={8} fill="#0A0F1A" stroke="#F4B8C8" strokeWidth={0.6} strokeOpacity={0.25} />
                      <text x={n.x} y={74} textAnchor="middle" fill="#F4B8C8" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>{n.label}</text>
                      {i < 4 && <line x1={n.x + 38} y1={70} x2={n.x + 52} y2={70} stroke="white" strokeOpacity={0.08} strokeWidth={1} />}
                    </g>
                  ))}

                  {/* Verification — dual model */}
                  <rect x={530} y={30} width={190} height={130} rx={12} fill="none" stroke="#34D399" strokeOpacity={0.12} strokeWidth={1} strokeDasharray="6 4" />
                  <text x={625} y={24} textAnchor="middle" fill="#34D399" fillOpacity={0.4} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>Cross-LLM Verification</text>

                  <rect x={550} y={50} width={75} height={40} rx={8} fill="#0A0F1A" stroke="#F4B8C8" strokeWidth={0.6} strokeOpacity={0.25} />
                  <text x={587} y={67} textAnchor="middle" fill="#F4B8C8" fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>Opus 4.6</text>
                  <text x={587} y={80} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">primary</text>

                  <rect x={640} y={50} width={75} height={40} rx={8} fill="#0A0F1A" stroke="#34D399" strokeWidth={0.6} strokeOpacity={0.25} />
                  <text x={677} y={67} textAnchor="middle" fill="#34D399" fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>GPT-5.4</text>
                  <text x={677} y={80} textAnchor="middle" fill="#34D399" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">secondary</text>

                  {/* Agreement */}
                  <rect x={570} y={105} width={120} height={36} rx={8} fill="#0A0F1A" stroke="#818CF8" strokeWidth={0.8} strokeOpacity={0.25} />
                  <text x={630} y={120} textAnchor="middle" fill="#818CF8" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Agreement</text>
                  <text x={630} y={133} textAnchor="middle" fill="#818CF8" fillOpacity={0.4} fontSize={8} fontFamily="ui-monospace, monospace">≥ 0.67 · α ≥ 0.80</text>

                  {/* Arrow from pipeline to verification */}
                  <line x1={473} y1={70} x2={530} y2={70} stroke="white" strokeOpacity={0.08} strokeWidth={1} />
                </svg>
              </div>

              {/* Pipeline pricing */}
              <div className="overflow-x-auto -mx-4 px-4">
                <table className="w-full text-xs font-mono border-collapse min-w-[400px]">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <th className="text-left py-2 px-3 text-[#7A8CA8]">Model</th>
                      <th className="text-left py-2 px-3 text-[#7A8CA8]">역할</th>
                      <th className="text-right py-2 px-2 text-[#7A8CA8]">Input</th>
                      <th className="text-right py-2 px-2 text-[#7A8CA8]">Output</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pipelinePricing.map((p) => (
                      <tr key={p.model} className="border-b border-white/[0.03]">
                        <td className="py-2 px-3" style={{ color: p.color }}>{p.model}</td>
                        <td className="py-2 px-3 text-white/50">{p.role}</td>
                        <td className="text-right py-2 px-2 text-white/40">{p.input}</td>
                        <td className="text-right py-2 px-2 text-white/40">{p.output}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── Agentic Loop: Resilient Failover ── */}
          {mode === "agentic" && (
            <div>
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 760 200" className="w-full min-w-[560px]" style={{ maxHeight: 230 }}>
                  {/* Primary */}
                  <rect x={40} y={55} width={130} height={55} rx={10} fill="#0A0F1A" stroke="#F4B8C8" strokeWidth={1} strokeOpacity={0.3} />
                  <text x={105} y={78} textAnchor="middle" fill="#F4B8C8" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>Opus 4.6</text>
                  <text x={105} y={95} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.35} fontSize={8} fontFamily="ui-monospace, monospace">Primary (기본)</text>

                  {/* Intra-provider failover */}
                  <line x1={170} y1={82} x2={220} y2={82} stroke="#E87080" strokeOpacity={0.2} strokeWidth={1} strokeDasharray="3 3" />
                  <text x={195} y={72} textAnchor="middle" fill="#E87080" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">fail</text>

                  <rect x={220} y={55} width={130} height={55} rx={10} fill="#0A0F1A" stroke="#818CF8" strokeWidth={0.8} strokeOpacity={0.25} />
                  <text x={285} y={78} textAnchor="middle" fill="#818CF8" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>Sonnet 4.6</text>
                  <text x={285} y={95} textAnchor="middle" fill="#818CF8" fillOpacity={0.35} fontSize={8} fontFamily="ui-monospace, monospace">Anthropic Failover</text>

                  {/* Cross-provider failover */}
                  <line x1={350} y1={82} x2={400} y2={82} stroke="#E87080" strokeOpacity={0.2} strokeWidth={1} strokeDasharray="3 3" />
                  <text x={375} y={72} textAnchor="middle" fill="#E87080" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">fail</text>

                  <rect x={400} y={55} width={130} height={55} rx={10} fill="#0A0F1A" stroke="#34D399" strokeWidth={0.8} strokeOpacity={0.25} />
                  <text x={465} y={78} textAnchor="middle" fill="#34D399" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>GPT-5.4</text>
                  <text x={465} y={95} textAnchor="middle" fill="#34D399" fillOpacity={0.35} fontSize={8} fontFamily="ui-monospace, monospace">Cross-Provider</text>

                  {/* GLM fallback */}
                  <line x1={530} y1={82} x2={580} y2={82} stroke="#E87080" strokeOpacity={0.2} strokeWidth={1} strokeDasharray="3 3" />
                  <text x={555} y={72} textAnchor="middle" fill="#E87080" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">fail</text>

                  <rect x={580} y={55} width={100} height={55} rx={10} fill="#0A0F1A" stroke="#F5C542" strokeWidth={0.8} strokeOpacity={0.25} />
                  <text x={630} y={78} textAnchor="middle" fill="#F5C542" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>GLM-5</text>
                  <text x={630} y={95} textAnchor="middle" fill="#F5C542" fillOpacity={0.35} fontSize={8} fontFamily="ui-monospace, monospace">Budget Fallback</text>

                  {/* Port/Adapter DI label */}
                  <text x={380} y={30} textAnchor="middle" fill="white" fillOpacity={0.2} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>
                    Port/Adapter DI — 런타임 프로바이더 교체
                  </text>

                  {/* Retry policy */}
                  <text x={380} y={145} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={9} fontFamily="ui-monospace, monospace">
                    max 3 retries · exponential backoff (2s base, 30s max) · MODEL_SWITCHED hook
                  </text>

                  {/* Haiku budget */}
                  <rect x={300} y={155} width={160} height={30} rx={6} fill="#0A0F1A" stroke="#4ECDC4" strokeWidth={0.5} strokeOpacity={0.15} />
                  <text x={380} y={174} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.4} fontSize={8} fontFamily="ui-monospace, monospace">claude-haiku-4-5 — Token Guard (budget tier)</text>
                </svg>
              </div>

              {/* Agentic pricing */}
              <div className="overflow-x-auto -mx-4 px-4">
                <table className="w-full text-xs font-mono border-collapse min-w-[400px]">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <th className="text-left py-2 px-3 text-[#7A8CA8]">Model</th>
                      <th className="text-left py-2 px-3 text-[#7A8CA8]">역할</th>
                      <th className="text-right py-2 px-2 text-[#7A8CA8]">Input</th>
                      <th className="text-right py-2 px-2 text-[#7A8CA8]">Output</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agenticPricing.map((p) => (
                      <tr key={p.model} className="border-b border-white/[0.03]">
                        <td className="py-2 px-3" style={{ color: p.color }}>{p.model}</td>
                        <td className="py-2 px-3 text-white/50">{p.role}</td>
                        <td className="text-right py-2 px-2 text-white/40">{p.input}</td>
                        <td className="text-right py-2 px-2 text-white/40">{p.output}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Port/Adapter explanation */}
              <div className="mt-4 flex flex-wrap gap-1.5">
                {["ClaudeAgenticAdapter", "OpenAIAgenticAdapter", "GlmAgenticAdapter", "update_model() 런타임 교체", "MODEL_SWITCHED hook"].map((t) => (
                  <span key={t} className="px-2 py-0.5 rounded text-[11px] font-mono text-[#4ECDC4]/70 bg-[#4ECDC4]/06 border border-[#4ECDC4]/12">{t}</span>
                ))}
              </div>
            </div>
          )}
        </ScrollReveal>
      </div>
    </section>
  );
}
