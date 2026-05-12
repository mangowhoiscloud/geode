"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";

/* ── Pipeline Verification (GameIP Domain — Output Validation) ── */
const pipelineLayers = [
  {
    tier: 1,
    title: "Per-Agent Guardrails",
    items: ["G1 Schema", "G2 Range", "G3 Grounding", "G4 Consistency"],
    accent: "#34D399",
    description: "모든 에이전트의 매 라운드 출력을 즉시 검증합니다. Haiku가 4가지 규칙으로 게이트킵 — 스키마 위반, 범위 이탈, 근거 부재, 내부 모순을 걸러냅니다.",
  },
  {
    tier: 2,
    title: "Confidence Gate",
    items: ["threshold 0.7", "max 5 iterations", "cortex loopback"],
    accent: "#818CF8",
    description: "Scoring 신뢰도가 0.7 미만이면 Cortex부터 자동 재실행합니다. 최대 5회 반복 후에도 미달이면 low-confidence 경고와 함께 결과를 반환합니다.",
  },
  {
    tier: 3,
    title: "Rights Risk Check",
    items: ["IP 권리 검증", "CLEAR/RESTRICTED", "라이선스 체크"],
    accent: "#E87080",
    description: "분석 대상 IP의 권리 상태를 사전 검증합니다. RESTRICTED 또는 UNKNOWN이면 분석을 중단하고 경고를 반환합니다.",
  },
  {
    tier: 4,
    title: "BiasBuster",
    items: ["RECOGNIZE", "EXPLAIN", "ALTER", "EVALUATE"],
    accent: "#F5C542",
    description: "앵커링 바이어스를 4단계로 탐지·교정합니다. CV < 0.05이면 앵커링 플래그, Clean Context에서 독립 재평가 후 교차 비교합니다.",
  },
  {
    tier: 5,
    title: "Cross-LLM Validation",
    items: ["Multi-model", "agreement ≥0.67", "Krippendorff α≥0.80"],
    accent: "#C084FC",
    description: "다른 LLM(Claude vs GPT)과 교차 검증합니다. Agreement coefficient가 0.67 미만이면 합의 실패로 판정하고 재실행합니다.",
  },
  {
    tier: 6,
    title: "Calibration",
    items: ["Golden Set", "per-axis ±0.5", "threshold 80.0"],
    accent: "#60A5FA",
    description: "전문가 주석 Golden Set과 비교하여 분석 정확도를 검증합니다. 축별 허용 오차 ±0.5, 전체 통과 기준 80.0점입니다.",
  },
];

/* ── Agentic Safety (Autonomous Agent — Input Gating) ── */
const agenticLayers = [
  {
    tier: 1,
    title: "Tool Classification",
    items: ["SAFE (auto)", "STANDARD (auto)", "WRITE (gate)", "DANGEROUS (always gate)"],
    accent: "#4ECDC4",
    description: "모든 도구를 위험도에 따라 4단계로 분류합니다. SAFE/STANDARD는 자동 실행, WRITE/DANGEROUS는 반드시 사용자 승인을 받아야 합니다.",
  },
  {
    tier: 2,
    title: "HITL Levels",
    items: ["Level 0: 자율", "Level 1: WRITE만", "Level 2: 전체 승인"],
    accent: "#818CF8",
    description: "Human-In-The-Loop 수준을 3단계로 제어합니다. SubAgent는 STANDARD에 한해 auto_approve=True를 상속받습니다.",
  },
  {
    tier: 3,
    title: "Bash Safety",
    items: ["safe prefix (read-only)", "dangerous pattern block", "non-safe → HITL"],
    accent: "#E87080",
    description: "Bash 명령어를 안전 접두사(cat, ls, grep, git log 등)와 위험 패턴으로 분류합니다. 안전하지 않은 명령은 반드시 사용자 승인이 필요합니다.",
  },
  {
    tier: 4,
    title: "Cost Gate",
    items: ["EXPENSIVE tools", "비용 확인", "hitl_level=0 bypass"],
    accent: "#F5C542",
    description: "analyze_ip($1.50), batch_analyze($5.00) 등 고비용 도구는 실행 전 비용을 확인합니다. hitl_level=0일 때만 자동 승인됩니다.",
  },
  {
    tier: 5,
    title: "MCP Server Approval",
    items: ["per-server cache", "auto: steam, arxiv", "session-level 'Always'"],
    accent: "#C084FC",
    description: "MCP 서버별 승인 캐시를 관리합니다. steam, arxiv 등 사전 승인 서버는 자동 실행, 나머지는 첫 호출 시 승인 후 세션 내 유지됩니다.",
  },
];

/* ── Concentric Rings (Onion) ── */
function OnionDiagram({
  layers,
  activeLayer,
  onHover,
}: {
  layers: typeof pipelineLayers;
  activeLayer: number;
  onHover: (i: number) => void;
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
                  strokeOpacity={isActive ? 0.5 : 0.12}
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

        <text x={CX} y={CY - 5} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={8} fontFamily="ui-monospace, monospace">
          Agent
        </text>
        <text x={CX} y={CY + 8} textAnchor="middle" fill="white" fillOpacity={0.2} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>
          Output
        </text>
      </svg>
    </div>
  );
}

/* ── Section ── */
export function VerificationSection() {
  const [mode, setMode] = useState<"pipeline" | "agentic">("pipeline");
  const [activeLayer, setActiveLayer] = useState(0);

  const layers = mode === "pipeline" ? pipelineLayers : agenticLayers;
  const active = layers[activeLayer];

  function switchMode(m: "pipeline" | "agentic") {
    setMode(m);
    setActiveLayer(0);
  }

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#34D399]/60 uppercase tracking-[0.25em] mb-3">
            Verification
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-white/90 mb-3">
            Dual Trust Model
          </h2>
          <p className="text-[#8B9CC0] max-w-lg mb-8 leading-relaxed">
            GEODE는 두 가지 신뢰 모델을 병행합니다.
            자율 에이전트는 <span className="text-[#4ECDC4]/80">실행 전 입력을 차단</span>하고,
            분석 파이프라인은 <span className="text-[#C084FC]/80">실행 후 출력을 검증</span>합니다.
          </p>
        </ScrollReveal>

        {/* Mode switcher */}
        <ScrollReveal delay={0.05}>
          <div className="flex gap-2 mb-10">
            <button
              onClick={() => switchMode("agentic")}
              className="px-4 py-2 rounded-lg text-xs font-mono font-bold transition-all duration-300"
              style={{
                color: mode === "agentic" ? "#4ECDC4" : "#5A6A8A",
                background: mode === "agentic" ? "rgba(78,205,196,0.08)" : "transparent",
                border: `1px solid ${mode === "agentic" ? "rgba(78,205,196,0.2)" : "rgba(255,255,255,0.04)"}`,
              }}
            >
              Agentic Safety
              <span className="ml-2 text-[11px] opacity-50">Input Gating</span>
            </button>
            <button
              onClick={() => switchMode("pipeline")}
              className="px-4 py-2 rounded-lg text-xs font-mono font-bold transition-all duration-300"
              style={{
                color: mode === "pipeline" ? "#C084FC" : "#5A6A8A",
                background: mode === "pipeline" ? "rgba(192,132,252,0.08)" : "transparent",
                border: `1px solid ${mode === "pipeline" ? "rgba(192,132,252,0.2)" : "rgba(255,255,255,0.04)"}`,
              }}
            >
              Pipeline Verification
              <span className="ml-2 text-[11px] opacity-50">Output Validation</span>
            </button>
          </div>
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-8 items-center">
            {/* Left — Onion diagram */}
            <OnionDiagram layers={layers} activeLayer={activeLayer} onHover={setActiveLayer} />

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
              <div
                className="rounded-xl border px-5 py-4 transition-all duration-300"
                style={{
                  borderColor: `${active.accent}15`,
                  background: `linear-gradient(135deg, ${active.accent}05, transparent 60%)`,
                }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-semibold text-sm" style={{ color: `${active.accent}D0` }}>
                    {active.title}
                  </span>
                </div>
                <p className="text-sm text-[#8B9CC0] leading-relaxed mb-3">
                  {active.description}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {active.items.map((item) => (
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
              </div>
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
