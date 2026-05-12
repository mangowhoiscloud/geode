"use client";

import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { useLocale, t } from "../locale-context";

/* ── 4-Layer data ── */
const ALL = [0, 1, 2, 3, 4]; // all components highlighted (shared resources)
const layers = [
  { id: "Model",   color: "#818CF8", y: 10,  components: ["ClaudeAdapter", "OpenAIAdapter", "GLMAdapter"], highlight: { ipc: [0, 1, 2], daemon: [0, 1, 2], scheduler: [0, 1, 2] } },
  { id: "Runtime", color: "#4ECDC4", y: 78,  components: ["ToolRegistry(43)", "MCP", "Skills(18)", "Memory(4.5T)"], highlight: { ipc: [0, 1, 2, 3], daemon: [0, 1, 2, 3], scheduler: [0, 1, 2, 3] } },
  { id: "Harness", color: "#F5C542", y: 146, components: ["SessionLane", "Lane(global,8)", "PolicyChain", "HookSystem(48)"], highlight: { ipc: [0, 1, 2, 3], daemon: [0, 1, 2, 3], scheduler: [0, 1, 2, 3] } },
  { id: "Agent",   color: "#F4B8C8", y: 214, components: ["AgenticLoop", "SubAgent", "CLIPoller", "Gateway", "Scheduler"], highlight: { ipc: [0, 1, 2], daemon: [0, 1, 3], scheduler: [0, 1, 4] } },
];

type Mode = "ipc" | "daemon" | "scheduler";
const modeLabels: Record<Mode, { ko: string; en: string; color: string }> = {
  ipc:       { ko: "CLI (IPC)",  en: "CLI (IPC)",  color: "#4ECDC4" },
  daemon:    { ko: "Daemon",     en: "Daemon",     color: "#818CF8" },
  scheduler: { ko: "Scheduler",  en: "Scheduler",  color: "#F5C542" },
};

/* ── Particle lifecycle animation ── */
function useParticle(paused: boolean) {
  const [pos, setPos] = useState(0);
  const raf = useRef<number>(0);
  const time = useRef(0);

  useEffect(() => {
    if (paused) return;
    let running = true;
    const tick = () => {
      if (!running) return;
      time.current += 0.008;
      if (time.current > 1) time.current = 0;
      setPos(time.current);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { running = false; cancelAnimationFrame(raf.current); };
  }, [paused]);

  return pos;
}

/* ── Component ── */
export function ArchitectureSection() {
  const locale = useLocale();
  const [mode, setMode] = useState<Mode>("ipc");
  const [hovered, setHovered] = useState<number | null>(null);
  const particlePos = useParticle(false);

  // Particle path: Agent(bottom) → Harness → Runtime → Model(top) → back down
  // pos 0~0.5 = up (Agent→Model), 0.5~1 = down (Model→Agent)
  const going = particlePos <= 0.5;
  const t2 = going ? particlePos * 2 : (particlePos - 0.5) * 2;
  const layerOrder = going ? [3, 2, 1, 0] : [0, 1, 2, 3];
  const currentLayerIdx = Math.min(Math.floor(t2 * 4), 3);
  const activeLayer = layerOrder[currentLayerIdx];
  const particleY = going
    ? 240 - t2 * 230  // bottom to top
    : 10 + t2 * 230;  // top to bottom
  const particleColor = going ? "#4ECDC4" : "#34D399";

  const BAR_W = 660;
  const BAR_H = 52;
  const BAR_X = 70;

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-6xl mx-auto">
        <ScrollReveal>
          <div className="flex flex-col md:flex-row md:items-end md:gap-12 mb-6">
            <div>
              <p className="text-sm font-mono font-bold text-[#818CF8]/60 uppercase tracking-[0.25em] mb-3">Architecture</p>
              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90">
                4-Layer Stack
              </h2>
            </div>
            <p className="text-sm text-[#A0B4D4] max-w-md leading-relaxed mt-3 md:mt-0 md:pb-1">
              {t(locale,
                "기존 L0-L5 6-Layer는 경계가 모호하여 모듈 배치 논쟁이 반복되었습니다. Model(LLM 추상화), Runtime(도구+MCP+스킬), Harness(동시성+정책), Agent(실행 루프) 4계층으로 단순화하니 각 모듈의 소속이 명확해졌습니다.",
                "The prior L0-L5 6-Layer had blurry boundaries, causing recurring module placement debates. Simplifying to 4 layers (Model, Runtime, Harness, Agent) made each module's ownership unambiguous."
              )}
            </p>
          </div>
        </ScrollReveal>

        {/* ── Mode selector ── */}
        <ScrollReveal delay={0.03}>
          <div className="flex items-center gap-2 mb-6">
            <span className="text-[10px] font-mono text-white/25 mr-1">
              {t(locale, "실행 경로", "Execution Path")}
            </span>
            {(["ipc", "daemon", "scheduler"] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className="px-3 py-1 rounded-full text-[10px] font-mono font-bold transition-all duration-300"
                style={{
                  color: mode === m ? modeLabels[m].color : "#5A6A8A",
                  background: mode === m ? `${modeLabels[m].color}12` : "transparent",
                  border: `1px solid ${mode === m ? `${modeLabels[m].color}30` : "transparent"}`,
                }}
              >
                {modeLabels[m][locale]}
              </button>
            ))}
          </div>
        </ScrollReveal>

        {/* ── Animated SVG ── */}
        <ScrollReveal delay={0.05}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
            <svg viewBox="0 0 800 290" className="w-full min-w-[640px]" style={{ maxHeight: 320 }}>

              {/* Layer bars */}
              {layers.map((layer, i) => {
                const isActive = activeLayer === i;
                const highlightedComps = layer.highlight[mode];

                return (
                  <g key={layer.id}
                    onMouseEnter={() => setHovered(i)}
                    onMouseLeave={() => setHovered(null)}
                    style={{ cursor: "default" }}
                  >
                    {/* Glow on active */}
                    {isActive && (
                      <rect x={BAR_X - 4} y={layer.y - 4} width={BAR_W + 8} height={BAR_H + 8} rx={14}
                        fill={layer.color} fillOpacity={0.04}
                        stroke={layer.color} strokeWidth={0.5} strokeOpacity={0.15} />
                    )}

                    {/* Main bar */}
                    <rect x={BAR_X} y={layer.y} width={BAR_W} height={BAR_H} rx={10}
                      fill="#0C1220"
                      stroke={layer.color}
                      strokeWidth={isActive || hovered === i ? 1.2 : 0.6}
                      strokeOpacity={isActive || hovered === i ? 0.6 : 0.25}
                      style={{ transition: "stroke-width 0.3s, stroke-opacity 0.3s" }}
                    />

                    {/* Layer name */}
                    <text x={BAR_X + 16} y={layer.y + 22} fill={layer.color}
                      fillOpacity={isActive || hovered === i ? 1 : 0.6}
                      fontSize={13} fontFamily="ui-monospace, monospace" fontWeight={800}
                      style={{ transition: "fill-opacity 0.3s" }}>
                      {layer.id}
                    </text>

                    {/* Components as inline badges */}
                    {layer.components.map((comp, ci) => {
                      const isHighlighted = highlightedComps.includes(ci);
                      const bx = BAR_X + 100 + ci * (BAR_W - 120) / layer.components.length;
                      return (
                        <g key={comp}>
                          <rect x={bx} y={layer.y + 10} width={comp.length * 7 + 16} height={20} rx={5}
                            fill={isHighlighted ? `${layer.color}15` : "#0A0F1A"}
                            stroke={layer.color}
                            strokeWidth={isHighlighted ? 0.8 : 0.3}
                            strokeOpacity={isHighlighted ? 0.5 : 0.1}
                            style={{ transition: "all 0.4s" }}
                          />
                          <text x={bx + 8} y={layer.y + 24}
                            fill={layer.color}
                            fillOpacity={isHighlighted ? 0.9 : 0.25}
                            fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={isHighlighted ? 700 : 400}
                            style={{ transition: "fill-opacity 0.4s" }}>
                            {comp}
                          </text>
                        </g>
                      );
                    })}
                  </g>
                );
              })}

              {/* Arrows between layers */}
              {[0, 1, 2].map((i) => (
                <line key={`arr-${i}`} x1={400} y1={layers[i].y + BAR_H + 2} x2={400} y2={layers[i + 1].y - 2}
                  stroke="white" strokeOpacity={0.08} strokeWidth={1} />
              ))}

              {/* Particle */}
              <circle cx={50} cy={particleY} r={5}
                fill={particleColor} fillOpacity={0.8}>
                <animate attributeName="r" values="4;6;4" dur="1s" repeatCount="indefinite" />
              </circle>
              <circle cx={50} cy={particleY} r={12}
                fill={particleColor} fillOpacity={0.1}>
                <animate attributeName="r" values="8;14;8" dur="1.5s" repeatCount="indefinite" />
              </circle>
              {/* Particle label */}
              <text x={50} y={particleY - 14} textAnchor="middle"
                fill={particleColor} fillOpacity={0.5}
                fontSize={7} fontFamily="ui-monospace, monospace">
                {going ? "▲ request" : "▼ response"}
              </text>

              {/* Particle trail line */}
              <line x1={50} y1={10} x2={50} y2={265}
                stroke="white" strokeOpacity={0.04} strokeWidth={1} strokeDasharray="2 4" />

              {/* Cross-cutting: HookSystem */}
              <rect x={745} y={10} width={24} height={255} rx={5}
                fill="none" stroke="#34D399" strokeWidth={0.6} strokeOpacity={0.15} strokeDasharray="3 3" />
              <text x={757} y={140} textAnchor="middle" fill="#34D399" fillOpacity={0.25}
                fontSize={7} fontFamily="ui-monospace, monospace"
                style={{ writingMode: "vertical-rl" } as React.CSSProperties}>
                HOOKS 48
              </text>

              {/* Cross-cutting: DomainPort */}
              <rect x={30} y={78} width={24} height={187} rx={5}
                fill="none" stroke="#C084FC" strokeWidth={0.6} strokeOpacity={0.12} strokeDasharray="3 3" />
              <text x={42} y={174} textAnchor="middle" fill="#C084FC" fillOpacity={0.2}
                fontSize={7} fontFamily="ui-monospace, monospace"
                style={{ writingMode: "vertical-rl" } as React.CSSProperties}>
                DOMAIN
              </text>

              {/* Mode path indicator */}
              <text x={400} y={286} textAnchor="middle" fill={modeLabels[mode].color} fillOpacity={0.35}
                fontSize={8} fontFamily="ui-monospace, monospace">
                acquire_all(key, [&quot;session&quot;, &quot;global&quot;]) → create_session({mode.toUpperCase()})
              </text>
            </svg>
          </div>
        </ScrollReveal>

        {/* ── Layer summary cards ── */}
        <ScrollReveal delay={0.1}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {layers.map((layer) => (
              <motion.div
                key={layer.id}
                className="rounded-xl border border-white/[0.05] px-4 py-3 cursor-default"
                style={{ background: `linear-gradient(160deg, ${layer.color}06, transparent 70%)` }}
                whileHover={{ y: -2, borderColor: `${layer.color}20` }}
                transition={{ duration: 0.2 }}
              >
                <div className="text-xs font-mono font-bold mb-1.5" style={{ color: layer.color }}>{layer.id}</div>
                <div className="flex flex-wrap gap-1">
                  {layer.components.map((c) => (
                    <span key={c} className="text-[9px] font-mono text-white/35">{c}</span>
                  ))}
                </div>
              </motion.div>
            ))}
          </div>
        </ScrollReveal>

        {/* Cross-cutting */}
        <ScrollReveal delay={0.15}>
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl border border-dashed border-[#34D399]/15 bg-[#34D399]/[0.02]">
              <span className="text-[#34D399] text-sm">⟂</span>
              <span className="text-xs text-[#9BB0CC]">
                <span className="font-medium text-[#34D399]/70">HookSystem</span>
                {" "}{t(locale, "58 events, 4계층 수직 관통", "58 events across all 4 layers")}
              </span>
            </div>
            <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl border border-dashed border-[#C084FC]/15 bg-[#C084FC]/[0.02]">
              <span className="text-[#C084FC] text-sm">⟂</span>
              <span className="text-xs text-[#9BB0CC]">
                <span className="font-medium text-[#C084FC]/70">DomainPort</span>
                {" "}{t(locale, "Protocol 직교. GameIP, REODE 교체 가능", "Orthogonal protocol. Swappable: GameIP, REODE")}
              </span>
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
