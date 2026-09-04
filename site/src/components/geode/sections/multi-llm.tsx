"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { TabBar } from "../ui/tab-bar";
import { useLocale, t } from "../locale-context";

type Mode = "pipeline" | "agentic" | "safeguards";

/* ── Pipeline pricing ── */
const pipelinePricing = [
  { model: "claude-opus-4-6", role: "전 노드 Primary", roleEn: "All-Node Primary", input: "$5.00", output: "$25.00", color: "#F4B8C8" },
  { model: "gpt-5.4", role: "Cross-LLM 검증 Secondary", roleEn: "Cross-LLM Validation Secondary", input: "$2.50", output: "$15.00", color: "#34D399" },
];

/* ── Agentic pricing ── */
const agenticPricing = [
  { model: "claude-opus-4-6", role: "Primary (기본)", roleEn: "Primary (Default)", input: "$5.00", output: "$25.00", color: "#F4B8C8" },
  { model: "claude-sonnet-4-6", role: "선택 가능 경로", roleEn: "Selectable Route", input: "$3.00", output: "$15.00", color: "#818CF8" },
  { model: "gpt-5.4", role: "선택 가능 경로", roleEn: "Selectable Route", input: "$2.50", output: "$15.00", color: "#34D399" },
  { model: "glm-5", role: "저비용 선택 경로", roleEn: "Lower-Cost Route", input: "$0.72", output: "$2.30", color: "#F5C542" },
  { model: "claude-haiku-4-5", role: "Token Guard (budget)", roleEn: "Token Guard (Budget)", input: "$1.00", output: "$5.00", color: "#4ECDC4" },
];

/* ── Safeguards timeline steps ── */
const safeguardSteps = [
  {
    id: "A2-a", color: "#E87080",
    nameKo: "Error Classification", nameEn: "Error Classification",
    descKo: "LLM 에러 발생 즉시 classify_llm_error()가 (type, severity, hint) 3-tuple을 반환합니다. 에러 유형별로 재시도 전략이 분기됩니다.",
    descEn: "On LLM error, classify_llm_error() returns a (type, severity, hint) 3-tuple. Retry strategy branches by error type.",
    tags: ["auth → stop", "rate_limit → backoff", "context → prune", "network → same model"],
    tradeoffKo: "요청 오류·인증·결제 한도는 즉시 중단하고, 일시적 연결·서버·rate limit만 제한된 예산 안에서 재시도합니다.",
    tradeoffEn: "Request, auth, and billing failures stop immediately; only transient connection, server, and rate-limit failures consume the bounded retry budget.",
  },
  {
    id: "A2-b + C1", color: "#F5C542",
    nameKo: "Retry + Jitter Backoff", nameEn: "Retry + Jitter Backoff",
    descKo: "Full jitter(random.uniform)와 2~30초 지연 설정을 사용합니다. 실제 다음 호출이 예약된 경우에만 llm_retry 이벤트를 표시합니다.",
    descEn: "Full jitter (random.uniform) uses the configured 2–30 second bounds. An llm_retry event is shown only when another call is actually scheduled.",
    tags: ["full jitter", "configurable backoff", "default: 3 total attempts", "llm_retry"],
    tradeoffKo: "무작위 지연은 동시 재호출 집중을 줄이지만 완료 시간은 변동합니다. 서버가 60초를 넘는 대기를 요구하면 조용히 멈춰 있지 않고 운영자에게 반환합니다.",
    tradeoffEn: "Random delay reduces synchronized retries but makes completion time variable. Provider waits above 60 seconds return control instead of silently stalling.",
  },
  {
    id: "C1-b", color: "#818CF8",
    nameKo: "Explicit Model Chain", nameEn: "Explicit Model Chain",
    descKo: "대화형 루프는 선택한 모델을 자동 변경하지 않습니다. 보조 작업만 호출자가 명시한 허용 모델 체인을 순서대로 이동할 수 있습니다.",
    descEn: "The interactive loop never changes the selected model automatically. Auxiliary jobs may traverse only the ordered, allowed model chain supplied by their caller.",
    tags: ["interactive → same model", "auxiliary only", "allowlist", "no hidden switch"],
    tradeoffKo: "자동 전환보다 장애가 더 빨리 드러나지만 모델·비용·동작이 사용자 몰래 바뀌지 않습니다.",
    tradeoffEn: "Failures surface sooner than with automatic switching, but model, cost, and behavior never change behind the operator's back.",
  },
  {
    id: "A3", color: "#4ECDC4",
    nameKo: "Retry Checkpoint", nameEn: "Retry Checkpoint",
    descKo: "실패를 분류한 뒤 메시지와 세션 체크포인트를 저장하고 재시도 또는 운영자 반환을 결정합니다. 재개는 저장된 세션 상태를 사용합니다.",
    descEn: "After classifying a failure, GEODE saves messages and a session checkpoint before deciding to retry or return control. Resume uses that persisted session state.",
    tags: ["messages", "session state", "before retry", "--resume"],
    tradeoffKo: "실패마다 작은 로컬 쓰기가 추가되지만 재시도 한도 소진 뒤에도 같은 세션 상태에서 복구할 수 있습니다.",
    tradeoffEn: "Each failure adds a small local write, preserving a resumable session state after the retry budget is exhausted.",
  },
  {
    id: "A2-c + A2-d", color: "#F4B8C8",
    nameKo: "Budget + Context Guard", nameEn: "Budget + Context Guard",
    descKo: "비용 80% 도달 시 emit_budget_warning(세션당 1회). 컨텍스트 프루닝 시 제거 메시지 수와 토큰 절감량을 명시합니다.",
    descEn: "emit_budget_warning at 80% cost (once per session). Shows removed message count and estimated token savings on context pruning.",
    tags: ["80% threshold", "1x per session", "prune detail", "provider-aware"],
    tradeoffKo: "80% 경고는 세션당 1회로 사용자 피로를 방지합니다. 프루닝 상세 표시는 ~200 tokens를 소모하지만, 사용자 신뢰가 더 중요합니다.",
    tradeoffEn: "Once-per-session warning prevents alert fatigue. Pruning detail costs ~200 tokens, but user trust matters more.",
  },
];

export function MultiLlmSection() {
  const locale = useLocale();
  const [mode, setMode] = useState<Mode>("pipeline");
  const [activeStep, setActiveStep] = useState(0);

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#F4B8C8]/60 uppercase tracking-[0.25em] mb-3">
            Multi-LLM
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-2">
            LLM Resilience
          </h2>
          <p className="text-sm sm:text-base text-[#A0B4D4] max-w-xl mb-8 leading-relaxed">
            {t(locale,
              "파이프라인과 에이전트 루프에서 LLM을 다르게 운용합니다. 대화형 루프는 선택 모델을 유지하고, 보조 작업만 명시적으로 전달된 모델 체인을 사용할 수 있습니다.",
              "LLMs are operated differently in pipelines and agent loops. Interactive turns keep the selected model; only auxiliary jobs may use an explicitly supplied model chain."
            )}
          </p>
        </ScrollReveal>

        {/* ── Tab bar ── */}
        <ScrollReveal delay={0.05}>
          <TabBar
            variant="default"
            tabs={[
              { id: "pipeline", label: "Pipeline", sub: "LLM-as-Judge", color: "#C084FC" },
              { id: "agentic", label: "Agentic", sub: "Explicit Route", color: "#4ECDC4" },
              { id: "safeguards", label: "Safeguards", sub: "Recovery Chain", color: "#F4B8C8" },
            ]}
            activeId={mode}
            onSelect={(id) => { setMode(id as Mode); setActiveStep(0); }}
          />
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          <div className="min-h-[480px]">
          <AnimatePresence mode="wait">
          {/* ── Pipeline: LLM-as-Judge ── */}
          {mode === "pipeline" && (
            <motion.div key="pipeline" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <div>
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 760 280" className="w-full min-w-[580px]" style={{ maxHeight: 320 }}>
                  <defs>
                    <filter id="glow-merge" x="-30%" y="-30%" width="160%" height="160%">
                      <feGaussianBlur stdDeviation="3" result="blur" />
                      <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                    </filter>
                    <marker id="arr-gold" viewBox="0 0 7 5" refX="6" refY="2.5" markerWidth="6" markerHeight="5" orient="auto">
                      <path d="M0,0 L7,2.5 L0,5" fill="#F5C542" opacity={0.5} />
                    </marker>
                    <marker id="arr-teal" viewBox="0 0 7 5" refX="6" refY="2.5" markerWidth="6" markerHeight="5" orient="auto">
                      <path d="M0,0 L7,2.5 L0,5" fill="#34D399" opacity={0.5} />
                    </marker>
                    <marker id="arr-indigo" viewBox="0 0 7 5" refX="6" refY="2.5" markerWidth="6" markerHeight="5" orient="auto">
                      <path d="M0,0 L7,2.5 L0,5" fill="#818CF8" opacity={0.5} />
                    </marker>
                  </defs>
                  <rect x={20} y={20} width={280} height={150} rx={12} fill="rgba(245,197,66,0.04)" stroke="#F5C542" strokeWidth={1.5} strokeOpacity={0.35} />
                  <text x={160} y={42} textAnchor="middle" fill="#F5C542" fillOpacity={0.7} fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>PRIMARY — Opus 4.6</text>
                  <text x={160} y={58} textAnchor="middle" fill="#F5C542" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">primary_analysts + evaluators</text>
                  <rect x={35} y={70} width={120} height={30} rx={6} fill="#0C1220" stroke="#F5C542" strokeWidth={0.6} strokeOpacity={0.3} />
                  <text x={95} y={89} textAnchor="middle" fill="#F5C542" fillOpacity={0.6} fontSize={9} fontFamily="ui-monospace, monospace">Analyst ×4 (Send)</text>
                  <rect x={165} y={70} width={120} height={30} rx={6} fill="#0C1220" stroke="#F5C542" strokeWidth={0.6} strokeOpacity={0.3} />
                  <text x={225} y={89} textAnchor="middle" fill="#F5C542" fillOpacity={0.6} fontSize={9} fontFamily="ui-monospace, monospace">Eval ×3 + Scoring</text>
                  <rect x={80} y={115} width={160} height={28} rx={6} fill="#0C1220" stroke="#F5C542" strokeWidth={0.6} strokeOpacity={0.25} />
                  <text x={160} y={133} textAnchor="middle" fill="#F5C542" fillOpacity={0.5} fontSize={9} fontFamily="ui-monospace, monospace">Synthesizer + Report</text>
                  <rect x={20} y={185} width={280} height={65} rx={12} fill="rgba(52,211,153,0.04)" stroke="#34D399" strokeWidth={1.5} strokeOpacity={0.35} />
                  <text x={160} y={207} textAnchor="middle" fill="#34D399" fillOpacity={0.7} fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>SECONDARY — GPT-5.4</text>
                  <text x={160} y={225} textAnchor="middle" fill="#34D399" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">secondary_analysts · cross-eval</text>
                  <rect x={380} y={100} width={140} height={60} rx={12} fill="rgba(129,140,248,0.08)" stroke="#818CF8" strokeWidth={2} strokeOpacity={0.5} filter="url(#glow-merge)" />
                  <text x={450} y={125} textAnchor="middle" fill="#818CF8" fontSize={12} fontFamily="ui-monospace, monospace" fontWeight={700}>Score Merge</text>
                  <text x={450} y={145} textAnchor="middle" fill="#818CF8" fillOpacity={0.5} fontSize={9} fontFamily="ui-monospace, monospace">agreement ≥ 0.67</text>
                  <rect x={570} y={90} width={170} height={80} rx={12} fill="rgba(192,132,252,0.05)" stroke="#C084FC" strokeWidth={1.5} strokeOpacity={0.35} />
                  <text x={655} y={118} textAnchor="middle" fill="#C084FC" fillOpacity={0.7} fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>Reliability Check</text>
                  <text x={655} y={138} textAnchor="middle" fill="#C084FC" fillOpacity={0.45} fontSize={10} fontFamily="ui-monospace, monospace">Krippendorff α</text>
                  <text x={655} y={155} textAnchor="middle" fill="#C084FC" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">target: α ≥ 0.80</text>
                  <path d="M300,95 C340,95 360,120 380,125" stroke="#F5C542" strokeOpacity={0.4} strokeWidth={1.5} fill="none" markerEnd="url(#arr-gold)" />
                  <path d="M300,215 C340,215 360,145 380,140" stroke="#34D399" strokeOpacity={0.4} strokeWidth={1.5} fill="none" markerEnd="url(#arr-teal)" />
                  <path d="M520,130 C540,130 555,130 570,130" stroke="#818CF8" strokeOpacity={0.4} strokeWidth={1.5} fill="none" markerEnd="url(#arr-indigo)" />
                  <text x={630} y={195} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={9} fontFamily="ui-monospace, monospace">Supporting:</text>
                  {[
                    { label: "Sonnet 4.6", color: "#818CF8", x: 595, y: 210 },
                    { label: "Haiku 4.5", color: "#818CF8", x: 680, y: 210 },
                    { label: "GLM-5", color: "#34D399", x: 638, y: 238 },
                  ].map((m) => (
                    <g key={m.label}>
                      <rect x={m.x - 38} y={m.y - 10} width={76} height={22} rx={4} fill="#0C1220" stroke={m.color} strokeWidth={0.5} strokeOpacity={0.3} />
                      <text x={m.x} y={m.y + 5} textAnchor="middle" fill={m.color} fillOpacity={0.5} fontSize={8} fontFamily="ui-monospace, monospace">{m.label}</text>
                    </g>
                  ))}
                  <text x={638} y={268} textAnchor="middle" fill="white" fillOpacity={0.2} fontSize={8} fontFamily="ui-monospace, monospace">Judge · Guardrail · Planner</text>
                </svg>
              </div>
              <div className="overflow-x-auto -mx-4 px-4">
                <table className="w-full text-xs font-mono border-collapse min-w-[400px]">
                  <thead><tr className="border-b border-white/[0.06]"><th className="text-left py-2 px-3 text-[#9BB0CC]">Model</th><th className="text-left py-2 px-3 text-[#9BB0CC]">{locale === "en" ? "Role" : "역할"}</th><th className="text-right py-2 px-2 text-[#9BB0CC]">Input</th><th className="text-right py-2 px-2 text-[#9BB0CC]">Output</th></tr></thead>
                  <tbody>{pipelinePricing.map((p) => (<tr key={p.model} className="border-b border-white/[0.03]"><td className="py-2 px-3" style={{ color: p.color }}>{p.model}</td><td className="py-2 px-3 text-white/50">{locale === "en" ? p.roleEn : p.role}</td><td className="text-right py-2 px-2 text-white/40">{p.input}</td><td className="text-right py-2 px-2 text-white/40">{p.output}</td></tr>))}</tbody>
                </table>
              </div>
            </div>
            </motion.div>
          )}

          {/* ── Agentic Loop: explicit route + bounded retry ── */}
          {mode === "agentic" && (
            <motion.div key="agentic" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <div>
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 760 260" className="w-full min-w-[580px]" style={{ maxHeight: 300 }}>
                  <defs>
                    <marker id="arr-fail" viewBox="0 0 7 5" refX="6" refY="2.5" markerWidth="6" markerHeight="5" orient="auto">
                      <path d="M0,0 L7,2.5 L0,5" fill="#E87080" opacity={0.5} />
                    </marker>
                  </defs>
                  <text x={380} y={22} textAnchor="middle" fill="white" fillOpacity={0.4} fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>
                    {locale === "en" ? "LLM Resilience. Explicit Route + Bounded Retry" : "LLM Resilience. 명시적 경로 + 제한된 재시도"}
                  </text>
                  <rect x={20} y={35} width={310} height={100} rx={12} fill="rgba(217,119,87,0.04)" stroke="#D97757" strokeWidth={1.5} strokeOpacity={0.3} />
                  <text x={175} y={52} textAnchor="middle" fill="#D97757" fillOpacity={0.6} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>Anthropic Provider</text>
                  <rect x={35} y={65} width={130} height={55} rx={10} fill="#0C1220" stroke="#D97757" strokeWidth={1} strokeOpacity={0.4} />
                  <text x={100} y={88} textAnchor="middle" fill="#D97757" fontSize={12} fontFamily="ui-monospace, monospace" fontWeight={700}>Opus 4.6</text>
                  <text x={100} y={106} textAnchor="middle" fill="#D97757" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">Primary</text>
                  <path d="M165,92 C180,92 185,92 195,92" stroke="#E87080" strokeOpacity={0.35} strokeWidth={1.2} strokeDasharray="4 3" fill="none" markerEnd="url(#arr-fail)" />
                  <text x={180} y={84} textAnchor="middle" fill="#E87080" fillOpacity={0.45} fontSize={8} fontFamily="ui-monospace, monospace">choose</text>
                  <rect x={195} y={65} width={120} height={55} rx={10} fill="#0C1220" stroke="#818CF8" strokeWidth={0.8} strokeOpacity={0.35} />
                  <text x={255} y={88} textAnchor="middle" fill="#818CF8" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>Sonnet 4.6</text>
                  <text x={255} y={106} textAnchor="middle" fill="#818CF8" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">Manual option</text>
                  <path d="M330,92 C350,92 365,92 385,92" stroke="#E87080" strokeOpacity={0.35} strokeWidth={1.2} strokeDasharray="4 3" fill="none" markerEnd="url(#arr-fail)" />
                  <text x={358} y={84} textAnchor="middle" fill="#E87080" fillOpacity={0.45} fontSize={8} fontFamily="ui-monospace, monospace">choose</text>
                  <rect x={385} y={35} width={150} height={100} rx={12} fill="rgba(52,211,153,0.04)" stroke="#34D399" strokeWidth={1.5} strokeOpacity={0.3} />
                  <text x={460} y={52} textAnchor="middle" fill="#34D399" fillOpacity={0.6} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>OpenAI Provider</text>
                  <rect x={400} y={65} width={120} height={55} rx={10} fill="#0C1220" stroke="#34D399" strokeWidth={0.8} strokeOpacity={0.35} />
                  <text x={460} y={88} textAnchor="middle" fill="#34D399" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>GPT-5.4</text>
                  <text x={460} y={106} textAnchor="middle" fill="#34D399" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">Manual option</text>
                  <path d="M535,92 C555,92 565,92 580,92" stroke="#E87080" strokeOpacity={0.35} strokeWidth={1.2} strokeDasharray="4 3" fill="none" markerEnd="url(#arr-fail)" />
                  <text x={558} y={84} textAnchor="middle" fill="#E87080" fillOpacity={0.45} fontSize={8} fontFamily="ui-monospace, monospace">choose</text>
                  <rect x={580} y={35} width={150} height={100} rx={12} fill="rgba(245,197,66,0.04)" stroke="#F5C542" strokeWidth={1.5} strokeOpacity={0.3} />
                  <text x={655} y={52} textAnchor="middle" fill="#F5C542" fillOpacity={0.6} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>ZhipuAI Provider</text>
                  <rect x={595} y={65} width={120} height={55} rx={10} fill="#0C1220" stroke="#F5C542" strokeWidth={0.8} strokeOpacity={0.35} />
                  <text x={655} y={88} textAnchor="middle" fill="#F5C542" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>GLM-5</text>
                  <text x={655} y={106} textAnchor="middle" fill="#F5C542" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">Manual option</text>
                  <rect x={20} y={155} width={340} height={55} rx={10} fill="rgba(78,205,196,0.04)" stroke="#4ECDC4" strokeWidth={1} strokeOpacity={0.25} />
                  <text x={190} y={175} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.7} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>Haiku 4.5 Token Guard (Budget Tier)</text>
                  <text x={190} y={195} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">SubAgent summary cap · context budget enforcement</text>
                  <rect x={385} y={155} width={345} height={55} rx={10} fill="rgba(129,140,248,0.04)" stroke="#818CF8" strokeWidth={1} strokeOpacity={0.25} />
                  <text x={557} y={175} textAnchor="middle" fill="#818CF8" fillOpacity={0.7} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>Retry Policy</text>
                  <text x={557} y={195} textAnchor="middle" fill="#818CF8" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">default 3 total attempts · jitter · LLM_CALL_RETRIED</text>
                  <text x={380} y={235} textAnchor="middle" fill="white" fillOpacity={0.2} fontSize={9} fontFamily="ui-monospace, monospace">anthropic-payg · openai-payg · codex-oauth · glm-payg · glm-coding-plan</text>
                  <text x={380} y={252} textAnchor="middle" fill="white" fillOpacity={0.15} fontSize={8} fontFamily="ui-monospace, monospace">
                    {locale === "en" ? "operator update_model() · no automatic cross-provider switch" : "운영자 update_model() · 자동 cross-provider 전환 없음"}
                  </text>
                </svg>
              </div>
              <div className="overflow-x-auto -mx-4 px-4">
                <table className="w-full text-xs font-mono border-collapse min-w-[400px]">
                  <thead><tr className="border-b border-white/[0.06]"><th className="text-left py-2 px-3 text-[#9BB0CC]">Model</th><th className="text-left py-2 px-3 text-[#9BB0CC]">{locale === "en" ? "Role" : "역할"}</th><th className="text-right py-2 px-2 text-[#9BB0CC]">Input</th><th className="text-right py-2 px-2 text-[#9BB0CC]">Output</th></tr></thead>
                  <tbody>{agenticPricing.map((p) => (<tr key={p.model} className="border-b border-white/[0.03]"><td className="py-2 px-3" style={{ color: p.color }}>{p.model}</td><td className="py-2 px-3 text-white/50">{locale === "en" ? p.roleEn : p.role}</td><td className="text-right py-2 px-2 text-white/40">{p.input}</td><td className="text-right py-2 px-2 text-white/40">{p.output}</td></tr>))}</tbody>
                </table>
              </div>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {["anthropic-payg", "openai-payg", "codex-oauth", "glm-payg", "glm-coding-plan", locale === "en" ? "operator-selected route" : "운영자 선택 경로", "LLM_CALL_RETRIED hook"].map((tag) => (
                  <span key={tag} className="px-2 py-0.5 rounded text-[11px] font-mono text-[#4ECDC4]/70 bg-[#4ECDC4]/06 border border-[#4ECDC4]/12">{tag}</span>
                ))}
              </div>
            </div>
            </motion.div>
          )}

          {/* ── Safeguards: Recovery Chain ── */}
          {mode === "safeguards" && (
            <motion.div key="safeguards" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <div>
              {/* Headline metric */}
              <div className="flex items-center gap-4 px-5 py-3.5 rounded-xl border border-[#34D399]/15 mb-8" style={{ background: "rgba(52,211,153,0.03)" }}>
                <span className="text-4xl font-black font-mono text-[#34D399]">0</span>
                <span className="text-sm text-[#9BB0CC] leading-relaxed">
                  {locale === "en" ? (
                    <>lost sessions across 42+ releases.<br />In a 1,133-turn, 5h48m autonomous session, LLM failure is a certainty. The question is whether you lose progress.</>
                  ) : (
                    <>lost sessions across 42+ releases.<br />1,133턴 5시간 48분 자율 세션에서 LLM 장애는 확정입니다. 문제는 장애 시 진행분을 잃느냐입니다.</>
                  )}
                </span>
              </div>

              {/* Timeline + Detail grid */}
              <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-6 items-start">
                {/* Left: Vertical timeline */}
                <div className="relative pl-6">
                  <div className="absolute left-[7px] top-3 bottom-3 w-px" style={{ background: "linear-gradient(to bottom, rgba(232,112,128,0.4), rgba(245,197,66,0.3), rgba(129,140,248,0.3), rgba(78,205,196,0.4), rgba(244,184,200,0.3))" }} />
                  {safeguardSteps.map((s, i) => {
                    const isActive = activeStep === i;
                    return (
                      <div
                        key={s.id}
                        className="relative py-3 cursor-pointer transition-opacity duration-300"
                        style={{ opacity: isActive ? 1 : 0.45 }}
                        onClick={() => setActiveStep(i)}
                        onMouseEnter={() => setActiveStep(i)}
                      >
                        <div
                          className="absolute left-[-18px] top-[18px] w-3 h-3 rounded-full border-2 transition-all duration-400"
                          style={{
                            borderColor: s.color,
                            background: isActive ? s.color : "#0A0A10",
                            boxShadow: isActive ? `0 0 10px ${s.color}` : "none",
                          }}
                        />
                        <div className="text-[8px] font-mono font-bold tracking-wider" style={{ opacity: 0.4 }}>{s.id}</div>
                        <div className="text-[12px] font-semibold transition-colors duration-300" style={{ color: isActive ? s.color : "rgba(255,255,255,0.35)" }}>
                          {locale === "en" ? s.nameEn : s.nameKo}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Right: Detail card */}
                <div className="space-y-4">
                  {(() => {
                    const s = safeguardSteps[activeStep];
                    return (
                      <div
                        className="rounded-xl border px-5 py-5 transition-all duration-300"
                        style={{ borderColor: `${s.color}15`, background: `linear-gradient(145deg, ${s.color}04, transparent 70%)` }}
                      >
                        <div className="flex items-center gap-2.5 mb-3">
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold" style={{ color: s.color, background: `${s.color}12` }}>{s.id}</span>
                          <span className="text-[15px] font-bold" style={{ color: `${s.color}D0` }}>{locale === "en" ? s.nameEn : s.nameKo}</span>
                        </div>
                        <p className="text-sm text-[#A0B4D4] leading-relaxed mb-4">
                          {locale === "en" ? s.descEn : s.descKo}
                        </p>
                        <div className="flex flex-wrap gap-1.5 mb-4">
                          {s.tags.map((tag) => (
                            <span key={tag} className="px-2 py-0.5 rounded text-[11px] font-mono" style={{ color: `${s.color}80`, background: `${s.color}08`, border: `1px solid ${s.color}15` }}>{tag}</span>
                          ))}
                        </div>
                        <div className="border-l-[3px] pl-3 rounded-r-lg" style={{ borderColor: s.color, background: "rgba(255,255,255,0.015)" }}>
                          <div className="text-[9px] font-mono font-bold mb-1" style={{ opacity: 0.5 }}>TRADE-OFF</div>
                          <div className="text-[11px] text-[#9BB0CC] leading-relaxed">
                            {locale === "en" ? s.tradeoffEn : s.tradeoffKo}
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </div>
              </div>
            </div>
            </motion.div>
          )}
          </AnimatePresence>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
