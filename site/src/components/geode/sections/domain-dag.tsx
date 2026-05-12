"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { DagRenderer } from "../dag-renderer";
import type { DagNode, DagEdge } from "../dag-renderer";
import { useLocale, t } from "../locale-context";


/* ── GameIP Pipeline DAG (9-node, code-verified) ── */
function PipelineDag() {
  const W = 840;
  const H = 260;
  const yMid = 120;
  const nR = 26; // node radius
  const aR = 22; // analyst radius

  // X positions for main flow
  const xRouter = 45;
  const xSignals = 135;
  const xAnalysts = 270;
  const xEval = 400;
  const xScoring = 500;
  const xVerify = 600;
  const xSynth = 720;
  // Gather (loopback) shown as arc below

  // Analyst Y positions
  const aY = [35, 85, 140, 195];

  function edge(x1: number, y1: number, x2: number, y2: number) {
    const dx = (x2 - x1) * 0.4;
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  }

  return (
    <div className="w-full overflow-x-auto -mx-6 px-6 pb-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[640px]" style={{ maxHeight: 300 }}>
        <defs>
          <linearGradient id="nodeGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#121A2E" />
            <stop offset="100%" stopColor="#080E1A" />
          </linearGradient>
        </defs>        {/* ── Edges ── */}
        <g stroke="white" strokeOpacity={0.2} strokeWidth={1.2} fill="none">
          {/* Router → Signals */}
          <path d={`M${xRouter + nR},${yMid} C${(xRouter + nR + xSignals - nR) / 2},${yMid - 4} ${(xRouter + nR + xSignals - nR) / 2},${yMid - 4} ${xSignals - nR},${yMid}`} />
          {/* Signals → 4 Analysts (fan-out) */}
          {aY.map((y) => (
            <path key={`s-${y}`} d={edge(xSignals + nR, yMid, xAnalysts - aR, y)} />
          ))}
          {/* 4 Analysts → Evaluators (fan-in) */}
          {aY.map((y) => (
            <path key={`e-${y}`} d={edge(xAnalysts + aR, y, xEval - nR, yMid)} />
          ))}
          {/* Eval → Scoring → Verify → Synth */}
          <path d={`M${xEval + nR},${yMid} C${(xEval + nR + xScoring - nR) / 2},${yMid - 4} ${(xEval + nR + xScoring - nR) / 2},${yMid - 4} ${xScoring - nR},${yMid}`} />
          <path d={`M${xScoring + nR},${yMid} C${(xScoring + nR + xVerify - nR) / 2},${yMid - 4} ${(xScoring + nR + xVerify - nR) / 2},${yMid - 4} ${xVerify - nR},${yMid}`} />
          <path d={`M${xVerify + nR},${yMid} C${(xVerify + nR + xSynth - nR) / 2},${yMid - 4} ${(xVerify + nR + xSynth - nR) / 2},${yMid - 4} ${xSynth - nR},${yMid}`} stroke="#34D399" strokeOpacity={0.2} />
        </g>

        {/* Confidence loopback: Verify → Gather → Signals */}
        <path
          d={`M${xVerify},${yMid + nR + 4} C${xVerify},${yMid + 65} ${xSignals},${yMid + 65} ${xSignals},${yMid + nR + 4}`}
          fill="none" stroke="#E87080" strokeOpacity={0.15} strokeWidth={1} strokeDasharray="4 4" className="animate-flow"
        />
        <text x={(xVerify + xSignals) / 2} y={yMid + 72} textAnchor="middle" fill="#E87080" fillOpacity={0.45} fontSize={9} fontFamily="ui-monospace, monospace">
          confidence &lt; 0.7 → gather → loopback (max 5)
        </text>

        {/* Labels */}
        <text x={(xSignals + xAnalysts) / 2} y={14} textAnchor="middle" fill="#F5C542" fillOpacity={0.45} fontSize={9} fontFamily="ui-monospace, monospace">Send API (fan-out ×4)</text>
        <text x={(xAnalysts + xEval) / 2} y={14} textAnchor="middle" fill="#818CF8" fillOpacity={0.45} fontSize={9} fontFamily="ui-monospace, monospace">fan-in ×3</text>

        {/* ── Nodes ── */}
        {/* Router */}
        <circle cx={xRouter} cy={yMid} r={nR} fill="url(#nodeGrad)" stroke="#4ECDC4" strokeWidth={1} strokeOpacity={0.4} />
        <text x={xRouter} y={yMid - 2} textAnchor="middle" fill="#4ECDC4" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Router</text>
        <text x={xRouter} y={yMid + 10} textAnchor="middle" fill="#9BB0CC" fontSize={8} fontFamily="ui-monospace, monospace">Memory</text>

        {/* Signals */}
        <circle cx={xSignals} cy={yMid} r={nR} fill="url(#nodeGrad)" stroke="#F5C542" strokeWidth={1} strokeOpacity={0.4} />
        <text x={xSignals} y={yMid - 2} textAnchor="middle" fill="#F5C542" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Signals</text>
        <text x={xSignals} y={yMid + 10} textAnchor="middle" fill="#9BB0CC" fontSize={8} fontFamily="ui-monospace, monospace">MCP</text>

        {/* 4 Analysts */}
        {["Market", "Creative", "Audience", "Risk"].map((name, i) => (
          <g key={name}>
            <circle cx={xAnalysts} cy={aY[i]} r={aR} fill="url(#nodeGrad)" stroke="#F5C542" strokeWidth={0.7} strokeOpacity={0.35} />
            <text x={xAnalysts} y={aY[i] + 1} textAnchor="middle" dominantBaseline="central" fill="#F5C542" fillOpacity={0.8} fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>{name}</text>
          </g>
        ))}

        {/* Evaluators */}
        <circle cx={xEval} cy={yMid} r={nR} fill="url(#nodeGrad)" stroke="#818CF8" strokeWidth={1} strokeOpacity={0.4} />
        <text x={xEval} y={yMid - 2} textAnchor="middle" fill="#818CF8" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Eval ×3</text>
        <text x={xEval} y={yMid + 10} textAnchor="middle" fill="#9BB0CC" fontSize={8} fontFamily="ui-monospace, monospace">Cross</text>

        {/* Scoring */}
        <circle cx={xScoring} cy={yMid} r={nR} fill="url(#nodeGrad)" stroke="#C084FC" strokeWidth={1} strokeOpacity={0.4} />
        <text x={xScoring} y={yMid - 2} textAnchor="middle" fill="#C084FC" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Scoring</text>
        <text x={xScoring} y={yMid + 10} textAnchor="middle" fill="#9BB0CC" fontSize={8} fontFamily="ui-monospace, monospace">PSM</text>

        {/* Verification */}
        <circle cx={xVerify} cy={yMid} r={nR} fill="url(#nodeGrad)" stroke="#34D399" strokeWidth={1} strokeOpacity={0.4} />
        <text x={xVerify} y={yMid - 2} textAnchor="middle" fill="#34D399" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Verify</text>
        <text x={xVerify} y={yMid + 10} textAnchor="middle" fill="#9BB0CC" fontSize={8} fontFamily="ui-monospace, monospace">5-Layer</text>

        {/* Synthesizer */}
        <circle cx={xSynth} cy={yMid} r={nR} fill="url(#nodeGrad)" stroke="#F4B8C8" strokeWidth={1} strokeOpacity={0.4} />
        <text x={xSynth} y={yMid - 2} textAnchor="middle" fill="#F4B8C8" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Synth</text>
        <text x={xSynth} y={yMid + 10} textAnchor="middle" fill="#9BB0CC" fontSize={8} fontFamily="ui-monospace, monospace">Report</text>
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

      <div className="min-h-[200px]">
      <AnimatePresence mode="wait">
      {/* Spring Migration — 7-node (DagRenderer) */}
      {pipe === "spring" && (
        <motion.div key="spring" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
        <DagRenderer
          nodes={[
            { id: "assess", label: "Assess", sub: "Spring", color: "#60A5FA", column: 0 },
            { id: "plan", label: "Plan", sub: "Recipe", color: "#818CF8", column: 1 },
            { id: "transform", label: "Transform", sub: "Sonnet", color: "#4ECDC4", column: 2 },
            { id: "validate", label: "Validate", sub: "Haiku", color: "#F5C542", column: 3 },
            { id: "fix", label: "Fix", sub: "Architect", color: "#E87080", column: 4 },
            { id: "startup", label: "Startup", sub: "verify", color: "#34D399", column: 5 },
            { id: "measure", label: "Measure", sub: "score", color: "#34D399", column: 6 },
          ]}
          edges={[
            { from: "assess", to: "plan" },
            { from: "plan", to: "transform" },
            { from: "transform", to: "validate" },
            { from: "validate", to: "fix" },
            { from: "fix", to: "startup" },
            { from: "startup", to: "measure" },
            { from: "fix", to: "transform", dashed: true, color: "#E87080", label: "fix loop", animated: true },
            { from: "startup", to: "fix", dashed: true, color: "#F5C542" },
          ]}
          annotations={[
            { x: 450, y: 10, text: "4-Class Error Routing: CONFIG · CODE · BEHAVIOR · ENV" },
          ]}
        />
        </motion.div>
      )}

      {/* Migration — 6-node (DagRenderer) */}
      {pipe === "migration" && (
        <motion.div key="migration" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
        <DagRenderer
          nodes={[
            { id: "assess", label: "Assess", color: "#60A5FA", column: 0 },
            { id: "plan", label: "Plan", color: "#818CF8", column: 1 },
            { id: "transform", label: "Transform", color: "#4ECDC4", column: 2 },
            { id: "validate", label: "Validate", color: "#F5C542", column: 3 },
            { id: "fix", label: "Fix", sub: "Architect", color: "#E87080", column: 4 },
            { id: "measure", label: "Measure", color: "#34D399", column: 5 },
          ]}
          edges={[
            { from: "assess", to: "plan" },
            { from: "plan", to: "transform" },
            { from: "transform", to: "validate" },
            { from: "validate", to: "fix" },
            { from: "validate", to: "measure", color: "#34D399" },
          ]}
          loopback={{ from: "fix", to: "validate", label: "fix loop", color: "#E87080" }}
        />
        </motion.div>
      )}

      {/* Porting — 4-node (DagRenderer) */}
      {pipe === "porting" && (
        <motion.div key="porting" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
        <DagRenderer
          nodes={[
            { id: "analyze", label: "Analyze", color: "#60A5FA", column: 0 },
            { id: "map", label: "Map Types", color: "#818CF8", column: 1 },
            { id: "generate", label: "Generate", color: "#4ECDC4", column: 2 },
            { id: "verify", label: "Verify", color: "#34D399", column: 3 },
          ]}
          edges={[
            { from: "analyze", to: "map" },
            { from: "map", to: "generate" },
            { from: "generate", to: "verify" },
          ]}
          loopback={{ from: "verify", to: "generate", label: "retry loop", color: "#4ECDC4" }}
          annotations={[
            { x: 280, y: 10, text: "Language Porting: Java ↔ Go ↔ Python" },
          ]}
        />
        </motion.div>
      )}
      </AnimatePresence>
      </div>
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

      <div className="min-h-[300px]">
      <AnimatePresence mode="wait">
        {activeDag === "gameip" && (
          <motion.div key="gameip" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <PipelineDag />
          </motion.div>
        )}
        {activeDag === "reode" && (
          <motion.div key="reode" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <ReodeDag />
          </motion.div>
        )}
      </AnimatePresence>
      </div>
    </ScrollReveal>
  );
}

export function DomainDagSection() {
  const locale = useLocale();
  return (
    <section className="relative py-32 px-6 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(192,132,252,0.02)_0%,transparent_70%)] pointer-events-none" />

      <div className="relative z-10 max-w-5xl mx-auto">
        {/* Geodi discover */}
        <div className="absolute top-8 right-8 opacity-[0.08] pointer-events-none hidden md:block">
          <img src="/geode/images/geode-discover.png" alt="" width={48} height={48} />
        </div>        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#C084FC]/60 uppercase tracking-[0.25em] mb-3">
            L5 Domain Plugin
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-white/90 mb-3">
            DomainPort Protocol
          </h2>
          <p className="text-[#A0B4D4] max-w-xl mb-4 leading-relaxed">
            {locale === "en" ? (
              <>Pipelines are <span className="text-white/70 font-medium">swappable plugins</span>. Just implement the DomainPort protocol, and any analysis domain runs the same autonomous execution flow on the GEODE Runtime.</>
            ) : (
              <>파이프라인은 <span className="text-white/70 font-medium">교체 가능한 플러그인</span>입니다. DomainPort 프로토콜을 구현하기만 하면, 어떤 분석 도메인이든 GEODE Runtime 위에서 동일한 자율 실행 흐름을 탑니다.</>
            )}
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
              <p className="text-sm text-[#A0B4D4] leading-relaxed mb-4">
                {t(locale,
                  "게임/IP 저평가 분석 파이프라인. 14축 루브릭 다면 평가 + PSM 인과추론 6종 원인 분류. LangGraph StateGraph 기반 7-node DAG.",
                  "Game/IP undervaluation analysis pipeline. 14-axis rubric multi-faceted evaluation + PSM causal inference with 6 cause categories. 7-node DAG based on LangGraph StateGraph."
                )}
              </p>
              <div className="space-y-1.5 font-mono text-[11px]">
                <div className="flex justify-between">
                  <span className="text-white/50">Berserk</span>
                  <span><span className="text-[#F5C542]">81.2</span> <span className="text-[#9BB0CC]">S</span></span>
                </div>
                <div className="flex justify-between">
                  <span className="text-white/50">Cowboy Bebop</span>
                  <span><span className="text-[#818CF8]">68.4</span> <span className="text-[#9BB0CC]">A</span></span>
                </div>
                <div className="flex justify-between">
                  <span className="text-white/50">Ghost in the Shell</span>
                  <span><span className="text-[#4ECDC4]">51.7</span> <span className="text-[#9BB0CC]">B</span></span>
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
              <p className="text-sm text-[#A0B4D4] leading-relaxed mb-4">
                {t(locale,
                  "Java 1.8→22 + Spring 4.3→6.1 자동 마이그레이션. 5,523파일 엔터프라이즈 프로젝트 83/83 테스트 통과. 에러 4분류 라우팅 + Architect/Editor 분리. 5시간 30분, 1,153턴 자율 수행.",
                  "Java 1.8→22 + Spring 4.3→6.1 automated migration. 83/83 tests passing on a 5,523-file enterprise project. 4-class error routing + Architect/Editor separation. 5h 30m, 1,153 autonomous rounds."
                )}
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
