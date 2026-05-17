"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { TabBar } from "../ui/tab-bar";
import { useLocale, t } from "../locale-context";

/* ── Pipeline Verification (Output Validation) ── */
const pipelineLayers = [
  {
    tier: 1,
    title: "Per-Agent Guardrails",
    items: ["G1 Schema", "G2 Range", "G3 Grounding", "G4 Consistency"],
    accent: "#34D399",
    description: "모든 에이전트의 매 라운드 출력을 즉시 검증합니다. Haiku가 4가지 규칙으로 게이트킵. 스키마 위반, 범위 이탈, 근거 부재, 내부 모순을 걸러냅니다.",
    descriptionEn: "Immediately validates every agent's output each round. Haiku gatekeeps with 4 rules, filtering schema violations, range deviations, missing grounding, and internal contradictions.",
  },
  {
    tier: 2,
    title: "Confidence Gate",
    items: ["threshold 0.7", "max 5 iterations", "cortex loopback"],
    accent: "#818CF8",
    description: "Scoring 신뢰도가 0.7 미만이면 Cortex부터 자동 재실행합니다. 최대 5회 반복 후에도 미달이면 low-confidence 경고와 함께 결과를 반환합니다.",
    descriptionEn: "Auto-reruns from Cortex if scoring confidence is below 0.7. Returns results with a low-confidence warning if still below threshold after 5 iterations.",
  },
  {
    tier: 3,
    title: "Rights Risk Check",
    items: ["subject 권리 검증", "CLEAR/RESTRICTED", "라이선스 체크"],
    accent: "#E87080",
    description: "분석 대상 subject의 권리 상태를 사전 검증합니다. RESTRICTED 또는 UNKNOWN이면 분석을 중단하고 경고를 반환합니다.",
    descriptionEn: "Pre-validates the rights status of the target subject. Halts analysis and returns a warning if RESTRICTED or UNKNOWN.",
  },
  {
    tier: 4,
    title: "panel guard",
    items: ["confirmation", "recency", "anchoring", "position", "verbosity", "self_enhancement"],
    accent: "#F5C542",
    description: "6종 인지 바이어스를 탐지합니다. CV < 0.05(n≥4)이면 앵커링 플래그. Fast path(CV ≥ 0.10, range ≥ 0.5)는 LLM 생략. 4단계 교정: RECOGNIZE → EXPLAIN → ALTER → EVALUATE.",
    descriptionEn: "Detects 6 types of cognitive bias. Anchoring flag if CV < 0.05 (n>=4). Fast path (CV >= 0.10, range >= 0.5) skips LLM. 4-stage correction: RECOGNIZE → EXPLAIN → ALTER → EVALUATE.",
  },
  {
    tier: 5,
    title: "Cross-LLM Validation",
    items: ["Multi-model", "agreement ≥0.67", "Krippendorff α≥0.80"],
    accent: "#C084FC",
    description: "다른 LLM(Claude vs GPT)과 교차 검증합니다. Agreement coefficient가 0.67 미만이면 합의 실패로 판정하고 재실행합니다.",
    descriptionEn: "Cross-validates with another LLM (Claude vs GPT). If agreement coefficient is below 0.67, consensus fails and a rerun is triggered.",
  },
  {
    tier: 6,
    title: "Calibration",
    items: ["Golden Set", "per-axis ±0.5", "threshold 80.0"],
    accent: "#60A5FA",
    description: "전문가 주석 Golden Set과 비교하여 분석 정확도를 검증합니다. 축별 허용 오차 ±0.5, 전체 통과 기준 80.0점입니다.",
    descriptionEn: "Verifies analysis accuracy against an expert-annotated Golden Set. Per-axis tolerance ±0.5, overall pass threshold 80.0.",
  },
];

/* ── Agentic Safety (Autonomous Agent — Input Gating) ── */
const agenticLayers = [
  {
    tier: 1,
    title: "Tool Classification",
    items: ["SAFE 13 (auto)", "STANDARD 25 (auto)", "WRITE 10 (gate)", "EXPENSIVE 3 ($)", "DANGEROUS 1 (bash)"],
    accent: "#4ECDC4",
    description: "43개 도구를 5단계로 분류합니다. SAFE/STANDARD는 자동 실행, WRITE/EXPENSIVE/DANGEROUS는 사용자 승인. Action Summary로 도구별 결정적 요약을 제공합니다.",
    descriptionEn: "Classifies 43 tools into 5 tiers. SAFE/STANDARD auto-execute, WRITE/EXPENSIVE/DANGEROUS require user approval. Action Summary provides deterministic per-tool summaries.",
  },
  {
    tier: 2,
    title: "HITL [Y/n/A]",
    items: ["Y: 1회 승인", "N: 거부 (Ctrl+C 포함)", "A: 세션 전체 Always"],
    itemsEn: ["Y: Approve once", "N: Reject (incl. Ctrl+C)", "A: Always for session"],
    accent: "#818CF8",
    description: "모든 승인 프롬프트에 [Y/n/A] 3선택지. A 응답 시 해당 카테고리(bash, write, cost, mcp:서버)가 세션 내 자동 승인. approval_history.jsonl에 결정 이력을 기록하고, 5회 연속 승인 시 자동 승인을 제안합니다.",
    descriptionEn: "All approval prompts offer 3 choices: [Y/n/A]. Answering A auto-approves the category (bash, write, cost, mcp:server) for the session. Decisions logged to approval_history.jsonl, auto-approve suggested after 5 consecutive approvals.",
  },
  {
    tier: 3,
    title: "HITL Levels (0/1/2)",
    items: ["Level 0: 전체 자율", "Level 1: WRITE만 승인", "Level 2: 전체 승인 (기본값)"],
    itemsEn: ["Level 0: Full autonomy", "Level 1: WRITE approval only", "Level 2: Full approval (default)"],
    accent: "#60A5FA",
    description: "hitl_level로 승인 강도를 3단계 제어합니다. Level 0은 Headless/Scheduler에서 사용(hitl_level=0), Level 2가 REPL 기본값. SubAgent는 STANDARD 도구에 한해 auto_approve=True.",
    descriptionEn: "Controls approval intensity in 3 levels via hitl_level. Level 0 used in Headless/Scheduler (hitl_level=0), Level 2 is REPL default. SubAgents use auto_approve=True for STANDARD tools only.",
  },
  {
    tier: 4,
    title: "Bash 3-Layer",
    items: ["41 safe prefixes (auto)", "9 blocking patterns", "non-safe → [Y/n/A]"],
    accent: "#E87080",
    description: "Layer 1: rm -rf /, sudo 등 9개 위험 패턴 무조건 차단. Layer 2: cat, ls, git log 등 41개 읽기 전용 접두사 자동 승인. Layer 3: 나머지 명령 [Y/n/A] 승인. 자원 제한(CPU 30s, FSIZE 50MB).",
    descriptionEn: "Layer 1: 9 dangerous patterns (rm -rf /, sudo, etc.) unconditionally blocked. Layer 2: 41 read-only prefixes (cat, ls, git log, etc.) auto-approved. Layer 3: remaining commands require [Y/n/A]. Resource limits (CPU 30s, FSIZE 50MB).",
  },
  {
    tier: 5,
    title: "Cost + MCP Gate",
    items: ["expensive tool cost gate", "MCP per-server 1회", "steam/arxiv auto"],
    itemsEn: ["expensive tool cost gate", "MCP per-server once", "steam/arxiv auto"],
    accent: "#F5C542",
    description: "EXPENSIVE 도구는 실행 전 비용 표시 후 [Y/n/A] 확인. MCP는 서버별 첫 호출 시 승인, 이후 세션 내 캐시. steam, arxiv, linkedin-reader는 사전 승인.",
    descriptionEn: "EXPENSIVE tools show cost before execution and require [Y/n/A]. MCP requires approval on first call per server, then cached for the session. steam, arxiv, linkedin-reader are pre-approved.",
  },
];

/* ── Concentric Rings (Onion) ── */
function OnionDiagram({
  layers,
  activeLayer,
  onHover,
  mode = "pipeline",
}: {
  layers: typeof pipelineLayers;
  activeLayer: number;
  onHover: (i: number) => void;
  mode?: string;
}) {
  const SIZE = 300;
  const CX = SIZE / 2;
  const CY = SIZE / 2;
  const count = layers.length;
  // Generate radii dynamically based on layer count
  const baseR = 30;
  const step = count <= 5 ? 24 : 20;
  const radii = layers.map((_, i) => baseR + i * step);

  return (
    <div className="relative mx-auto" style={{ width: SIZE, height: SIZE }}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="w-full h-full">
        {layers
          .slice()
          .reverse()
          .map((layer, ri) => {
            const i = count - 1 - ri;
            const r = radii[i];
            const isActive = activeLayer === i;

            return (
              <g key={layer.tier}>
                <circle
                  cx={CX}
                  cy={CY}
                  r={r}
                  fill={isActive ? layer.accent : "transparent"}
                  fillOpacity={isActive ? 0.06 : 0}
                  stroke={layer.accent}
                  strokeWidth={isActive ? 1.5 : 0.6}
                  strokeOpacity={isActive ? 0.6 : 0.2}
                  style={{ transition: "all 0.4s ease", cursor: "pointer" }}
                  onMouseEnter={() => onHover(i)}
                />
                <text
                  x={CX}
                  y={CY - r + 12}
                  textAnchor="middle"
                  fill={layer.accent}
                  fontSize={8}
                  fontFamily="ui-monospace, monospace"
                  fontWeight={600}
                  opacity={isActive ? 0.9 : 0.25}
                  style={{ transition: "opacity 0.3s", pointerEvents: "none" }}
                >
                  L{layer.tier}
                </text>
              </g>
            );
          })}

        {/* Center pulse */}
        <circle cx={CX} cy={CY} r={0} fill="none" stroke={mode === "agentic" ? "#4ECDC4" : "#34D399"} strokeWidth={0.8} strokeOpacity={0}>
          <animate attributeName="r" values={`0;${radii[radii.length - 1]}`} dur="4s" repeatCount="indefinite" />
          <animate attributeName="stroke-opacity" values="0.15;0" dur="4s" repeatCount="indefinite" />
        </circle>

        <text x={CX} y={CY - 5} textAnchor="middle" fill="white" fillOpacity={0.3} fontSize={9} fontFamily="ui-monospace, monospace">
          Agent
        </text>
        <text x={CX} y={CY + 8} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>
          {mode === "agentic" ? "Input" : "Output"}
        </text>
      </svg>
    </div>
  );
}


/* ── Section ── */
export function VerificationSection() {
  const locale = useLocale();
  const [mode, setMode] = useState<"pipeline" | "agentic">("pipeline");
  const [activeLayer, setActiveLayer] = useState(0);

  const layers = mode === "pipeline" ? pipelineLayers : agenticLayers;
  const active = layers[Math.min(activeLayer, layers.length - 1)];

  function switchMode(m: "pipeline" | "agentic") {
    setMode(m);
    setActiveLayer(0);
  }

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(52,211,153,0.015)_0%,transparent_60%)] pointer-events-none" />
      <div className="relative z-10 max-w-5xl mx-auto">
        {/* Geodi focus */}
        <div className="absolute top-8 right-8 opacity-[0.08] pointer-events-none hidden md:block">
          <img src="/geode/images/geode-focus.png" alt="" width={48} height={48} />
        </div>        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#34D399]/60 uppercase tracking-[0.25em] mb-3">
            Verification
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-white/90 mb-3">
            Block & Verify
          </h2>
          <p className="text-[#A0B4D4] max-w-lg mb-8 leading-relaxed">
            {locale === "en" ? (
              <>Autonomous agents <span className="text-[#4ECDC4]/80">block dangerous inputs before execution</span>, analysis pipelines <span className="text-[#C084FC]/80">verify outputs after execution</span>. Neither side trusts the other by default.</>
            ) : (
              <>자율 에이전트는 <span className="text-[#4ECDC4]/80">실행 전 위험 입력을 차단</span>하고, 분석 파이프라인은 <span className="text-[#C084FC]/80">실행 후 출력을 검증</span>합니다. 양쪽 모두 기본적으로 상대를 신뢰하지 않습니다.</>
            )}
          </p>
        </ScrollReveal>

        {/* Mode switcher */}
        <ScrollReveal delay={0.05}>
          <TabBar
            variant="pill"
            tabs={[
              { id: "agentic", label: "Agentic Safety", color: "#4ECDC4" },
              { id: "pipeline", label: "Pipeline Verification", color: "#C084FC" },
            ]}
            activeId={mode}
            onSelect={(id) => switchMode(id as "pipeline" | "agentic")}
          />
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-8 items-center">
            {/* Left — Onion diagram */}
            <OnionDiagram layers={layers} activeLayer={activeLayer} onHover={setActiveLayer} mode={mode as string} />

            {/* Right — Active layer detail */}
            <div className="space-y-4">
              {/* Layer selector tabs */}
              <div className="flex flex-wrap gap-1.5 mb-4">
                {layers.map((layer, i) => (
                  <button
                    key={layer.tier}
                    onMouseEnter={() => setActiveLayer(i)}
                    onClick={() => setActiveLayer(i)}
                    className="px-2.5 py-1.5 rounded-lg text-[10px] font-mono font-bold transition-all duration-300"
                    style={{
                      color: activeLayer === i ? active.accent : "#5A6A8A",
                      background: activeLayer === i ? `${layer.accent}10` : "transparent",
                      border: `1px solid ${activeLayer === i ? `${layer.accent}25` : "transparent"}`,
                    }}
                  >
                    L{layer.tier}
                  </button>
                ))}
              </div>

              {/* Detail card */}
              <div className="min-h-[160px]">
              <AnimatePresence mode="wait">
              <motion.div
                key={`${mode}-${activeLayer}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.2 }}
                className="rounded-xl border px-5 py-4"
                style={{
                  borderColor: `${active.accent}15`,
                  background: `linear-gradient(135deg, ${active.accent}05, transparent 60%)`,
                }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-mono font-black"
                    style={{ background: `${active.accent}15`, color: active.accent }}>
                    L{active.tier}
                  </span>
                  <span className="font-semibold text-sm" style={{ color: `${active.accent}D0` }}>
                    {active.title}
                  </span>
                </div>
                <p className="text-sm text-[#A0B4D4] leading-relaxed mb-3">
                  {locale === "en" && "descriptionEn" in active ? (active as { descriptionEn: string }).descriptionEn : active.description}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {(locale === "en" && "itemsEn" in active ? (active as { itemsEn: string[] }).itemsEn : active.items).map((item) => (
                    <span
                      key={item}
                      className="px-2 py-0.5 rounded text-[11px] font-mono"
                      style={{
                        color: `${active.accent}80`,
                        background: `${active.accent}08`,
                        border: `1px solid ${active.accent}15`,
                      }}
                    >
                      {item}
                    </span>
                  ))}
                </div>
              </motion.div>
              </AnimatePresence>
              </div>

            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
