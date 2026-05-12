"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";

/* ── DAG Node data ── */
const analysts = [
  { label: "Market", sub: "A–C", y: 25 },
  { label: "Creative", sub: "D–F", y: 80 },
  { label: "Audience", sub: "G–I", y: 135 },
  { label: "Risk", sub: "J–L", y: 190 },
];

/* ── SVG DAG with fan-out / fan-in ── */
function PipelineDag() {
  const W = 720;
  const H = 220;

  // Column X positions
  const xRouter = 45;
  const xCortex = 145;
  const xSignals = 145;
  const xAnalysts = 300;
  const xEval = 450;
  const xScoring = 555;
  const xSynth = 660;

  // Y positions
  const yMid = H / 2;
  const yCortex = 80;
  const ySignals = 155;

  const nodeR = 28;
  const analystR = 22;

  function edge(x1: number, y1: number, x2: number, y2: number) {
    const dx = (x2 - x1) * 0.4;
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  }

  return (
    <div className="w-full overflow-x-auto -mx-6 px-6 pb-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[600px]" style={{ maxHeight: 260 }}>
        <defs>
          <marker id="arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="white" fillOpacity={0.25} />
          </marker>
        </defs>

        {/* ── Edges ── */}
        <g stroke="white" strokeOpacity={0.14} strokeWidth={1} fill="none" markerEnd="url(#arrow)">
          {/* Router → Cortex, Signals */}
          <path d={edge(xRouter + nodeR, yMid, xCortex - nodeR, yCortex)} />
          <path d={edge(xRouter + nodeR, yMid, xSignals - nodeR, ySignals)} />

          {/* Cortex/Signals → each Analyst (fan-out) */}
          {analysts.map((a) => (
            <path key={`c-${a.label}`} d={edge(xCortex + nodeR, yCortex, xAnalysts - analystR, a.y)} />
          ))}
          {analysts.map((a) => (
            <path key={`s-${a.label}`} d={edge(xSignals + nodeR, ySignals, xAnalysts - analystR, a.y)} strokeOpacity={0.04} />
          ))}

          {/* Analysts → Evaluators (fan-in) */}
          {analysts.map((a) => (
            <path key={`a-${a.label}`} d={edge(xAnalysts + analystR, a.y, xEval - nodeR, yMid)} />
          ))}

          {/* Evaluators → Scoring → Synthesizer */}
          <path d={`M${xEval + nodeR},${yMid} L${xScoring - nodeR},${yMid}`} />
          <path d={`M${xScoring + nodeR},${yMid} L${xSynth - nodeR},${yMid}`} />
        </g>

        {/* ── Fan-out / Fan-in labels ── */}
        <text x={(xCortex + nodeR + xAnalysts - analystR) / 2} y={12} textAnchor="middle" fill="#F5C542" fillOpacity={0.25} fontSize={8} fontFamily="ui-monospace, monospace">
          Send API (fan-out)
        </text>
        <text x={(xAnalysts + analystR + xEval - nodeR) / 2} y={12} textAnchor="middle" fill="#818CF8" fillOpacity={0.25} fontSize={8} fontFamily="ui-monospace, monospace">
          fan-in
        </text>

        {/* ── Nodes ── */}
        {/* Router */}
        <circle cx={xRouter} cy={yMid} r={nodeR} fill="#0A0F1A" stroke="#4ECDC4" strokeWidth={1} strokeOpacity={0.3} />
        <text x={xRouter} y={yMid - 3} textAnchor="middle" fill="#4ECDC4" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Router</text>
        <text x={xRouter} y={yMid + 9} textAnchor="middle" fill="#5A6A8A" fontSize={7} fontFamily="ui-monospace, monospace">6-Route</text>

        {/* Cortex */}
        <circle cx={xCortex} cy={yCortex} r={nodeR} fill="#0A0F1A" stroke="#60A5FA" strokeWidth={1} strokeOpacity={0.3} />
        <text x={xCortex} y={yCortex - 3} textAnchor="middle" fill="#60A5FA" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Cortex</text>
        <text x={xCortex} y={yCortex + 9} textAnchor="middle" fill="#5A6A8A" fontSize={7} fontFamily="ui-monospace, monospace">SQL</text>

        {/* Signals */}
        <circle cx={xSignals} cy={ySignals} r={nodeR} fill="#0A0F1A" stroke="#F5C542" strokeWidth={1} strokeOpacity={0.3} />
        <text x={xSignals} y={ySignals - 3} textAnchor="middle" fill="#F5C542" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Signals</text>
        <text x={xSignals} y={ySignals + 9} textAnchor="middle" fill="#5A6A8A" fontSize={7} fontFamily="ui-monospace, monospace">MCP</text>

        {/* 4 Analysts (fan-out) */}
        {analysts.map((a) => (
          <g key={a.label}>
            <circle cx={xAnalysts} cy={a.y} r={analystR} fill="#0A0F1A" stroke="#F5C542" strokeWidth={0.8} strokeOpacity={0.25} />
            <text x={xAnalysts} y={a.y - 2} textAnchor="middle" fill="#F5C542" fillOpacity={0.8} fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>{a.label}</text>
            <text x={xAnalysts} y={a.y + 9} textAnchor="middle" fill="#5A6A8A" fontSize={7} fontFamily="ui-monospace, monospace">{a.sub}</text>
          </g>
        ))}

        {/* Evaluators */}
        <circle cx={xEval} cy={yMid} r={nodeR} fill="#0A0F1A" stroke="#818CF8" strokeWidth={1} strokeOpacity={0.3} />
        <text x={xEval} y={yMid - 3} textAnchor="middle" fill="#818CF8" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Eval ×3</text>
        <text x={xEval} y={yMid + 9} textAnchor="middle" fill="#5A6A8A" fontSize={7} fontFamily="ui-monospace, monospace">Cross</text>

        {/* Scoring */}
        <circle cx={xScoring} cy={yMid} r={nodeR} fill="#0A0F1A" stroke="#C084FC" strokeWidth={1} strokeOpacity={0.3} />
        <text x={xScoring} y={yMid - 3} textAnchor="middle" fill="#C084FC" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Scoring</text>
        <text x={xScoring} y={yMid + 9} textAnchor="middle" fill="#5A6A8A" fontSize={7} fontFamily="ui-monospace, monospace">PSM</text>

        {/* Synthesizer */}
        <circle cx={xSynth} cy={yMid} r={nodeR} fill="#0A0F1A" stroke="#F4B8C8" strokeWidth={1} strokeOpacity={0.3} />
        <text x={xSynth} y={yMid - 3} textAnchor="middle" fill="#F4B8C8" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Synth</text>
        <text x={xSynth} y={yMid + 9} textAnchor="middle" fill="#5A6A8A" fontSize={7} fontFamily="ui-monospace, monospace">Report</text>
      </svg>
    </div>
  );
}

/* ── REODE DAGs (3 pipelines) ── */
type ReodePipeline = "migration" | "spring" | "porting";

function ReodeDag() {
  const [pipe, setPipe] = useState<ReodePipeline>("spring");

  return (
    <div>
      {/* Sub-toggle */}
      <div className="flex gap-1.5 mb-3">
        {([
          { id: "spring" as ReodePipeline, label: "Spring Migration", sub: "7-node + startup_verify" },
          { id: "migration" as ReodePipeline, label: "Migration", sub: "6-node" },
          { id: "porting" as ReodePipeline, label: "Porting", sub: "4-node" },
        ]).map((p) => (
          <button key={p.id} onClick={() => setPipe(p.id)}
            className="px-2.5 py-1 rounded text-[10px] font-mono transition-all duration-200"
            style={{
              color: pipe === p.id ? "#34D399" : "#5A6A8A",
              background: pipe === p.id ? "rgba(52,211,153,0.06)" : "transparent",
              border: `1px solid ${pipe === p.id ? "rgba(52,211,153,0.15)" : "transparent"}`,
            }}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Spring Migration — 7-node with startup_verify */}
      {pipe === "spring" && (
        <div className="w-full overflow-x-auto -mx-6 px-6 pb-4">
          <svg viewBox="0 0 800 220" className="w-full min-w-[600px]" style={{ maxHeight: 260 }}>
            <g stroke="white" strokeOpacity={0.14} strokeWidth={1} fill="none">
              <line x1={75} y1={110} x2={130} y2={110} />
              <line x1={185} y1={110} x2={240} y2={110} />
              <line x1={295} y1={110} x2={350} y2={110} />
              <line x1={405} y1={110} x2={460} y2={110} />
              <line x1={515} y1={110} x2={570} y2={110} />
              <line x1={625} y1={110} x2={680} y2={110} />
              {/* Fix → Transform feedback */}
              <path d="M530,85 C530,50 270,50 270,85" stroke="#E87080" strokeOpacity={0.12} strokeDasharray="4 4" className="animate-flow" />
              {/* startup_verify → fix (fail) */}
              <path d="M600,85 C600,60 530,60 530,85" stroke="#F5C542" strokeOpacity={0.18} strokeDasharray="3 3" />
            </g>
            <text x={400} y={42} textAnchor="middle" fill="#E87080" fillOpacity={0.2} fontSize={8} fontFamily="ui-monospace, monospace">fix loop (validate/startup fail)</text>
            <text x={600} y={195} textAnchor="middle" fill="#F5C542" fillOpacity={0.2} fontSize={8} fontFamily="ui-monospace, monospace">startup_verify: java_app_start → health check → HTTP 200</text>
            {/* 4-class labels */}
            {[
              { label: "CONFIG", x: 395, y: 175, color: "#F5C542" },
              { label: "CODE", x: 455, y: 175, color: "#60A5FA" },
              { label: "BEHAVIOR", x: 525, y: 175, color: "#C084FC" },
              { label: "ENV", x: 580, y: 175, color: "#E87080" },
            ].map((c) => (
              <text key={c.label} x={c.x} y={c.y} textAnchor="middle" fill={c.color} fillOpacity={0.25} fontSize={8} fontFamily="ui-monospace, monospace">{c.label}</text>
            ))}
            {/* Nodes */}
            {[
              { x: 55, label: "Assess", sub: "Spring", color: "#60A5FA" },
              { x: 155, label: "Plan", sub: "Recipe", color: "#818CF8" },
              { x: 270, label: "Transform", sub: "Sonnet", color: "#4ECDC4" },
              { x: 380, label: "Validate", sub: "Haiku ×4", color: "#F5C542" },
              { x: 490, label: "Fix", sub: "Architect", color: "#E87080" },
              { x: 600, label: "Startup", sub: "verify", color: "#34D399" },
              { x: 710, label: "Measure", sub: "Haiku", color: "#34D399" },
            ].map((n) => (
              <g key={n.label}>
                <circle cx={n.x} cy={110} r={22} fill="#0A0F1A" stroke={n.color} strokeWidth={0.8} strokeOpacity={0.3} />
                <text x={n.x} y={107} textAnchor="middle" fill={n.color} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>{n.label}</text>
                <text x={n.x} y={120} textAnchor="middle" fill={n.color} fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">{n.sub}</text>
              </g>
            ))}
          </svg>
        </div>
      )}

      {/* Migration — 6-node */}
      {pipe === "migration" && (
        <div className="w-full overflow-x-auto -mx-6 px-6 pb-4">
          <svg viewBox="0 0 720 200" className="w-full min-w-[560px]" style={{ maxHeight: 240 }}>
            <g stroke="white" strokeOpacity={0.14} strokeWidth={1} fill="none">
              <line x1={85} y1={100} x2={155} y2={100} />
              <line x1={215} y1={100} x2={285} y2={100} />
              <line x1={345} y1={100} x2={415} y2={100} />
              <line x1={475} y1={100} x2={545} y2={100} />
              <path d="M560,75 C560,45 430,45 430,75" stroke="#E87080" strokeOpacity={0.12} strokeDasharray="4 4" className="animate-flow" />
              <line x1={475} y1={100} x2={615} y2={100} stroke="#34D399" strokeOpacity={0.12} />
            </g>
            {[
              { x: 60, label: "Assess", color: "#60A5FA" },
              { x: 185, label: "Plan", color: "#818CF8" },
              { x: 315, label: "Transform", color: "#4ECDC4" },
              { x: 445, label: "Validate", color: "#F5C542" },
              { x: 560, label: "Fix", color: "#E87080" },
              { x: 650, label: "Measure", color: "#34D399" },
            ].map((n) => (
              <g key={n.label}>
                <circle cx={n.x} cy={100} r={22} fill="#0A0F1A" stroke={n.color} strokeWidth={0.8} strokeOpacity={0.3} />
                <text x={n.x} y={104} textAnchor="middle" dominantBaseline="central" fill={n.color} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>{n.label}</text>
              </g>
            ))}
            <text x={495} y={40} textAnchor="middle" fill="#E87080" fillOpacity={0.2} fontSize={8} fontFamily="ui-monospace, monospace">fix loop</text>
            <text x={560} y={145} textAnchor="middle" fill="#E87080" fillOpacity={0.30} fontSize={8} fontFamily="ui-monospace, monospace">Architect → Editor</text>
          </svg>
        </div>
      )}

      {/* Porting — 4-node */}
      {pipe === "porting" && (
        <div className="w-full overflow-x-auto -mx-6 px-6 pb-4">
          <svg viewBox="0 0 560 180" className="w-full min-w-[440px]" style={{ maxHeight: 220 }}>
            <g stroke="white" strokeOpacity={0.14} strokeWidth={1} fill="none">
              <line x1={95} y1={90} x2={175} y2={90} />
              <line x1={265} y1={90} x2={345} y2={90} />
              <line x1={435} y1={90} x2={500} y2={90} />
              <path d="M395,65 C395,35 225,35 225,65" stroke="#4ECDC4" strokeOpacity={0.18} strokeDasharray="4 4" className="animate-flow" />
            </g>
            {[
              { x: 65, label: "Analyze", color: "#60A5FA" },
              { x: 220, label: "Map Types", color: "#818CF8" },
              { x: 390, label: "Generate", color: "#4ECDC4" },
              { x: 520, label: "Verify", color: "#34D399" },
            ].map((n) => (
              <g key={n.label}>
                <circle cx={n.x} cy={90} r={22} fill="#0A0F1A" stroke={n.color} strokeWidth={0.8} strokeOpacity={0.3} />
                <text x={n.x} y={94} textAnchor="middle" dominantBaseline="central" fill={n.color} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>{n.label}</text>
              </g>
            ))}
            <text x={310} y={30} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.2} fontSize={8} fontFamily="ui-monospace, monospace">retry loop (equivalence fail)</text>
            <text x={280} y={150} textAnchor="middle" fill="white" fillOpacity={0.20} fontSize={9} fontFamily="ui-monospace, monospace">Language Porting: Java↔Go↔Python</text>
          </svg>
        </div>
      )}
    </div>
  );
}

/* ── DAG Viewer with toggle ── */
function DagViewer() {
  const [activeDag, setActiveDag] = useState<"gameip" | "reode">("gameip");

  return (
    <ScrollReveal delay={0.2}>
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setActiveDag("gameip")}
          className="px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all duration-300"
          style={{
            color: activeDag === "gameip" ? "#C084FC" : "#5A6A8A",
            background: activeDag === "gameip" ? "rgba(192,132,252,0.08)" : "transparent",
            border: `1px solid ${activeDag === "gameip" ? "rgba(192,132,252,0.2)" : "rgba(255,255,255,0.04)"}`,
          }}
        >
          GameIP DAG
          <span className="ml-2 text-[10px] opacity-50">7-node fan-out/in</span>
        </button>
        <button
          onClick={() => setActiveDag("reode")}
          className="px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all duration-300"
          style={{
            color: activeDag === "reode" ? "#34D399" : "#5A6A8A",
            background: activeDag === "reode" ? "rgba(52,211,153,0.08)" : "transparent",
            border: `1px solid ${activeDag === "reode" ? "rgba(52,211,153,0.2)" : "rgba(255,255,255,0.04)"}`,
          }}
        >
          REODE DAG
          <span className="ml-2 text-[10px] opacity-50">6-node fix loop</span>
        </button>
      </div>

      {activeDag === "gameip" && <PipelineDag />}
      {activeDag === "reode" && <ReodeDag />}
    </ScrollReveal>
  );
}

export function DomainDagSection() {
  return (
    <section className="relative py-32 px-6 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(192,132,252,0.02)_0%,transparent_70%)] pointer-events-none" />

      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#C084FC]/60 uppercase tracking-[0.25em] mb-3">
            L5 Domain Plugin
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-white/90 mb-3">
            DomainPort Protocol
          </h2>
          <p className="text-[#8B9CC0] max-w-xl mb-4 leading-relaxed">
            파이프라인은 <span className="text-white/70 font-medium">교체 가능한 플러그인</span>입니다.
            DomainPort 프로토콜을 구현하기만 하면, 어떤 분석 도메인이든
            GEODE Runtime 위에서 동일한 자율 실행 흐름을 탑니다.
          </p>
        </ScrollReveal>

        {/* Two domain plugins */}
        <ScrollReveal delay={0.1}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-12">
            {/* GameIP — active plugin */}
            <div className="rounded-xl border border-[#C084FC]/10 bg-[#C084FC]/[0.02] p-6">
              <div className="flex items-center gap-2 mb-3">
                <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-[#C084FC]/10 text-[#C084FC]/80 border border-[#C084FC]/20">
                  ACTIVE
                </span>
                <span className="text-sm font-semibold text-white/80">GameIPDomain</span>
              </div>
              <p className="text-sm text-[#8B9CC0] leading-relaxed mb-4">
                게임/IP 저평가 분석 파이프라인.
                14축 루브릭 다면 평가 + PSM 인과추론 6종 원인 분류.
                LangGraph StateGraph 기반 7-node DAG.
              </p>
              <div className="space-y-1.5 font-mono text-[11px]">
                <div className="flex justify-between">
                  <span className="text-white/50">Berserk</span>
                  <span><span className="text-[#F5C542]">82.2</span> <span className="text-[#5A6A8A]">S</span></span>
                </div>
                <div className="flex justify-between">
                  <span className="text-white/50">Cowboy Bebop</span>
                  <span><span className="text-[#818CF8]">69.4</span> <span className="text-[#5A6A8A]">A</span></span>
                </div>
                <div className="flex justify-between">
                  <span className="text-white/50">Ghost in the Shell</span>
                  <span><span className="text-[#4ECDC4]">54.0</span> <span className="text-[#5A6A8A]">B</span></span>
                </div>
              </div>
            </div>

            {/* REODE — domain pivot */}
            <div className="rounded-xl border border-[#34D399]/10 bg-[#34D399]/[0.02] p-6">
              <div className="flex items-center gap-2 mb-3">
                <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-[#34D399]/10 text-[#34D399]/80 border border-[#34D399]/20">
                  PIVOT
                </span>
                <span className="text-sm font-semibold text-white/80">REODE</span>
              </div>
              <p className="text-sm text-[#8B9CC0] leading-relaxed mb-4">
                Java 1.8→22 + Spring 4.3→6.1 자동 마이그레이션.
                5,523파일 엔터프라이즈 프로젝트 83/83 테스트 통과.
                에러 4분류 라우팅 + Architect/Editor 분리.
                5시간 30분, 1,153턴 자율 수행.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {["DomainPort", "4-Class Router", "Architect/Editor", "83/83 pass"].map((tag) => (
                  <span key={tag} className="px-2 py-0.5 rounded text-[10px] font-mono text-[#34D399]/60 bg-[#34D399]/5 border border-[#34D399]/10">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </ScrollReveal>

        {/* ── DAG Visualizations — toggle ── */}
        <DagViewer />
      </div>
    </section>
  );
}
