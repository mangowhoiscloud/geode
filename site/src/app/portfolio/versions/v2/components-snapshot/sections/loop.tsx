"use client";

import { useEffect, useState, useRef } from "react";
import { ScrollReveal } from "../scroll-reveal";

/* ── Terminal scenarios (geode.html 실제 출력 기반) ── */
type Line = { type: string; text: string; input?: boolean };

const scenarios: { tab: string; lines: Line[] }[] = [
  {
    tab: "repl",
    lines: [
      { type: "prompt", text: "$ uv run geode", input: true },
      { type: "status", text: "● GEODE v0.30 Interactive REPL" },
      { type: "prompt", text: '> Cowboy Bebop 분석해줘', input: true },
      { type: "tool", text: '  → analyze "Cowboy Bebop" --mode full' },
      { type: "exec", text: "  ✓ score: 69.4 A · 14축 완료 · 4.1s" },
      { type: "prompt", text: "> Berserk 점수만 보여줘", input: true },
      { type: "tool", text: '  → analyze "Berserk" --mode scoring' },
      { type: "exec", text: "  ✓ score: 82.2 S · quick mode · 1.8s" },
      { type: "prompt", text: '> Ghost in the Shell 평가해', input: true },
      { type: "tool", text: '  → analyze "GitS" --mode evaluation' },
      { type: "exec", text: "  ✓ score: 54.0 B · evaluation 완료 · 3.6s" },
      { type: "prompt", text: "> exit", input: true },
      { type: "done", text: "✓ session: 3 analyses · $0.087 · 9.5s" },
    ],
  },
  {
    tab: "agent-ux",
    lines: [
      { type: "prompt", text: '▸ tool_call: analyze_ip("Berserk")', input: true },
      { type: "exec", text: '  ✓ result: {score: 81.2, tier: "S", cause: "conversion_failure"}' },
      { type: "error", text: "  ✗ error: rate_limit_exceeded → retry 2/3 (10s backoff)" },
      { type: "token", text: "  ✢ tokens: input=1,240 output=856 cost=$0.032" },
      { type: "status", text: '  ● plan: "Berserk 분석 계획" → APPROVED → EXECUTING' },
    ],
  },
  {
    tab: "cli",
    lines: [
      { type: "prompt", text: '$ uv run geode analyze "Cowboy Bebop"', input: true },
      { type: "prompt", text: '$ uv run geode analyze "Berserk" --dry-run', input: true },
      { type: "prompt", text: "$ uv run geode analyze \"Berserk\" --verbose", input: true },
      { type: "prompt", text: "$ uv run geode  # Interactive REPL", input: true },
    ],
  },
];

const colorMap: Record<string, string> = {
  prompt: "text-white/70",
  status: "text-[#34D399]",
  phase: "text-[#818CF8]",
  tool: "text-[#F5C542]",
  exec: "text-[#4ECDC4]",
  verify: "text-[#C084FC]",
  done: "text-[#34D399] font-bold",
  error: "text-[#E87080]",
  token: "text-[#7A8CA8]",
};

const tabLabels: Record<string, string> = {
  repl: "Interactive REPL",
  "agent-ux": "Agent UX",
  cli: "Typer CLI",
};

/* ── Orbital Cycle ── */
const STEPS = [
  { label: "THINK", color: "#818CF8" },
  { label: "SELECT", color: "#F5C542" },
  { label: "EXECUTE", color: "#4ECDC4" },
  { label: "VERIFY", color: "#C084FC" },
] as const;

const SIZE = 260;
const CX = SIZE / 2;
const CY = SIZE / 2;
const R = 88;
const ANGLES = [-90, 0, 90, 180];

function OrbitalCycle() {
  const [activePhase, setActivePhase] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => setIsVisible(entry.isIntersecting),
      { threshold: 0.3 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!isVisible) return;
    const interval = setInterval(() => {
      setActivePhase((p) => (p + 1) % 4);
    }, 1500);
    return () => clearInterval(interval);
  }, [isVisible]);

  return (
    <div ref={containerRef} className="relative mx-auto" style={{ width: SIZE, height: SIZE }}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="w-full h-full">
        {/* Orbit ring */}
        <circle
          cx={CX} cy={CY} r={R}
          fill="none" stroke="white" strokeOpacity={0.05}
          strokeWidth={1} strokeDasharray="4 6"
        />

        {/* Direction dots */}
        {[-45, 45, 135, 225].map((deg) => {
          const rad = (deg * Math.PI) / 180;
          return (
            <circle
              key={deg}
              cx={CX + R * Math.cos(rad)}
              cy={CY + R * Math.sin(rad)}
              r={1.2}
              fill="white"
              fillOpacity={0.18}
            />
          );
        })}

        {/* Nodes */}
        {STEPS.map((step, i) => {
          const rad = (ANGLES[i] * Math.PI) / 180;
          const x = CX + R * Math.cos(rad);
          const y = CY + R * Math.sin(rad);
          const isActive = activePhase === i;

          return (
            <g key={step.label}>
              {isActive && (
                <circle cx={x} cy={y} r={28} fill={step.color} fillOpacity={0.18}>
                  <animate
                    attributeName="fill-opacity"
                    values="0.03;0.09;0.03"
                    dur="2s"
                    repeatCount="indefinite"
                  />
                </circle>
              )}
              <circle
                cx={x} cy={y} r={22}
                fill="#0A0F1A"
                stroke={step.color}
                strokeWidth={isActive ? 1.5 : 0.5}
                strokeOpacity={isActive ? 0.6 : 0.1}
                style={{ transition: "stroke-width 0.4s, stroke-opacity 0.4s" }}
              />
              <text
                x={x} y={y + 1}
                textAnchor="middle"
                dominantBaseline="central"
                fill={step.color}
                fontSize={9}
                fontFamily="ui-monospace, monospace"
                fontWeight={600}
                opacity={isActive ? 1 : 0.3}
                style={{ transition: "opacity 0.4s" }}
              >
                {step.label}
              </text>
            </g>
          );
        })}

        {/* Center label */}
        <text x={CX} y={CY - 4} textAnchor="middle" fill="white" fillOpacity={0.20} fontSize={8} fontFamily="ui-monospace, monospace">
          while
        </text>
        <text x={CX} y={CY + 9} textAnchor="middle" fill="white" fillOpacity={0.30} fontSize={9.5} fontFamily="ui-monospace, monospace" fontWeight={600}>
          (tool_use)
        </text>
      </svg>
    </div>
  );
}

/* ── Terminal: input lines typed, output lines appear line-by-line ── */
function TypingTerminal() {
  const [activeTab, setActiveTab] = useState(0);
  const [visibleLines, setVisibleLines] = useState(0);
  const [currentChars, setCurrentChars] = useState(0);
  const [typingDone, setTypingDone] = useState(false); // true = current line fully revealed
  const containerRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedRef = useRef(false);

  const lines = scenarios[activeTab].lines;

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !startedRef.current) {
          startedRef.current = true;
          playLines(scenarios[0].lines);
        }
      },
      { threshold: 0.3 },
    );
    if (containerRef.current) observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      cleanup();
    };
  }, []);

  function cleanup() {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (intervalRef.current) clearInterval(intervalRef.current);
  }

  function switchTab(idx: number) {
    cleanup();
    setActiveTab(idx);
    setVisibleLines(0);
    setCurrentChars(0);
    setTypingDone(false);
    playLines(scenarios[idx].lines);
  }

  function playLines(target: Line[]) {
    let lineIdx = 0;

    function nextLine() {
      if (lineIdx >= target.length) return;

      const line = target[lineIdx];

      if (line.input) {
        // Type character by character
        let charIdx = 0;
        setVisibleLines(lineIdx);
        setCurrentChars(0);
        setTypingDone(false);

        intervalRef.current = setInterval(() => {
          charIdx += 2;
          if (charIdx >= line.text.length) {
            if (intervalRef.current) clearInterval(intervalRef.current);
            setVisibleLines(lineIdx + 1);
            setCurrentChars(0);
            setTypingDone(true);
            lineIdx++;
            timerRef.current = setTimeout(nextLine, 500);
          } else {
            setCurrentChars(charIdx);
          }
        }, 30);
      } else {
        // Output line: appear instantly
        setVisibleLines(lineIdx + 1);
        setCurrentChars(0);
        setTypingDone(true);
        lineIdx++;
        timerRef.current = setTimeout(nextLine, 120);
      }
    }

    nextLine();
  }

  return (
    <div
      ref={containerRef}
      className="rounded-xl border border-white/[0.04] bg-[#060B14] overflow-hidden max-h-[460px]"
    >
      {/* Tab bar */}
      <div className="flex items-center gap-0 border-b border-white/[0.04] px-3">
        {scenarios.map((s, i) => (
          <button
            key={s.tab}
            onClick={() => switchTab(i)}
            className="px-3 py-2 text-[10px] font-mono transition-colors duration-200"
            style={{
              color: activeTab === i ? "#4ECDC4" : "#5A6A8A",
              borderBottom: activeTab === i ? "1px solid #4ECDC4" : "1px solid transparent",
            }}
          >
            {tabLabels[s.tab]}
          </button>
        ))}
      </div>

      {/* Terminal content */}
      <div className="p-5 font-mono text-[12.5px] leading-[1.9]">
        <div className="flex items-center gap-1.5 mb-4">
          <div className="w-2.5 h-2.5 rounded-full bg-[#E87080]/60" />
          <div className="w-2.5 h-2.5 rounded-full bg-[#F5C542]/60" />
          <div className="w-2.5 h-2.5 rounded-full bg-[#34D399]/60" />
          <span className="ml-3 text-[10px] text-white/25">geode — {scenarios[activeTab].tab}</span>
        </div>
        {lines.map((line, i) => {
          if (i > visibleLines) return null;

          const isCurrentLine = i === visibleLines;
          const isInput = line.input;

          // Input line being typed
          if (isCurrentLine && isInput && !typingDone) {
            return (
              <div key={`${activeTab}-${i}`} className={`${colorMap[line.type] || "text-white/50"} whitespace-pre`}>
                {line.text.slice(0, currentChars)}
                <span className="animate-pulse">▌</span>
              </div>
            );
          }

          // Fully revealed line
          if (i < visibleLines) {
            return (
              <div key={`${activeTab}-${i}`} className={`${colorMap[line.type] || "text-white/50"} whitespace-pre`}>
                {line.text}
              </div>
            );
          }

          return null;
        })}
      </div>
    </div>
  );
}

/* ── Stats ── */
const loopStats = [
  { value: "50", label: "max rounds" },
  { value: "54", label: "built-in tools" },
  { value: "44", label: "MCP catalog" },
  { value: "4", label: "error recovery" },
];

/* ── Section ── */
export function LoopSection() {
  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#4ECDC4]/60 uppercase tracking-[0.25em] mb-3">
            AgenticLoop
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-white/90 mb-3">
            while(tool_use)
          </h2>
          <p className="text-[#8B9CC0] max-w-xl mb-12 leading-relaxed">
            사고 → 선택 → 실행 → 검증. LLM이 <code className="text-[#4ECDC4]/70 text-[13px]">tool_use</code>를
            반환하는 한 이 궤도는 멈추지 않습니다.
            매 라운드마다 4중 Guardrail(G1-G4)이 출력을 교차 검증하며,
            confidence ≥ 0.7에 도달해야 비로소 루프를 벗어납니다.
          </p>
        </ScrollReveal>

        <div className="grid grid-cols-1 md:grid-cols-[1fr_1.1fr] gap-8 items-start">
          {/* Left — Orbital + Stats */}
          <ScrollReveal>
            <div className="space-y-6">
              <OrbitalCycle />

              <div className="grid grid-cols-2 gap-3 text-center">
                {loopStats.map((s) => (
                  <div
                    key={s.label}
                    className="rounded-lg border border-white/[0.04] bg-white/[0.01] px-3 py-3"
                  >
                    <div className="text-xl font-bold text-white/80">{s.value}</div>
                    <div className="text-[11px] font-mono text-[#7A8CA8] uppercase">{s.label}</div>
                  </div>
                ))}
              </div>
            </div>
          </ScrollReveal>

          {/* Right — Terminal replay */}
          <ScrollReveal delay={0.15}>
            <TypingTerminal />
          </ScrollReveal>
        </div>
      </div>
    </section>
  );
}
