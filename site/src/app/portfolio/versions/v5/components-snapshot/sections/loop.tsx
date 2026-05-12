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
      { type: "status", text: "● GEODE v0.32 Interactive REPL" },
      { type: "prompt", text: '> Cowboy Bebop 분석해줘', input: true },
      { type: "tool", text: '  → analyze "Cowboy Bebop" --mode full' },
      { type: "exec", text: "  ✓ score: 68.4 A · 14축 완료 · 4.1s" },
      { type: "prompt", text: "> Berserk 점수만 보여줘", input: true },
      { type: "tool", text: '  → analyze "Berserk" --mode scoring' },
      { type: "exec", text: "  ✓ score: 81.2 S · quick mode · 1.8s" },
      { type: "prompt", text: '> Ghost in the Shell 평가해', input: true },
      { type: "tool", text: '  → analyze "GitS" --mode evaluation' },
      { type: "exec", text: "  ✓ score: 51.7 B · evaluation 완료 · 3.6s" },
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
  { value: "∞", label: "while True" },
  { value: "52", label: "built-in tools" },
  { value: "44", label: "MCP catalog" },
  { value: "5", label: "safety guards" },
];

/* ── 5 Safety Guards ── */
const guards = [
  { name: "수렴 감지", trigger: "동일 에러 4회 연속", effect: "break", color: "#E87080" },
  { name: "시간 예산", trigger: "wall-clock 만료 (Karpathy P3)", effect: "wrap-up → end", color: "#F5C542" },
  { name: "컨텍스트 80%", trigger: "Provider별 자동 압축", effect: "요약 후 계속", color: "#818CF8" },
  { name: "컨텍스트 95%", trigger: "긴급 프루닝 + UI 알림", effect: "최근 N개만 유지", color: "#C084FC" },
  { name: "StuckDetector", trigger: "2시간 무응답", effect: "세션 자동 해제", color: "#4ECDC4" },
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
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-2">
            while True — Long-running Agent
          </h2>
          <p className="text-lg text-white/40 font-semibold mb-4">
            for range(50) → while True + 5 Guards
          </p>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-12 leading-relaxed">
            턴 제한이 아니라, 에이전트와 인프라가 함께 종료를 결정합니다.
            LLM이 <code className="text-[#4ECDC4]/70">tool_use</code>를 반환하는 한 궤도는 멈추지 않으며,
            수렴 감지 · 시간 예산 · 컨텍스트 압축 · StuckDetector 5개 가드가 무한 루프를 방지합니다.
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

        {/* ── 5 Safety Guards ── */}
        <ScrollReveal delay={0.2}>
          <div className="mt-10">
            <p className="text-sm font-mono font-bold text-[#E87080]/60 uppercase tracking-[0.25em] mb-4">
              Safety Guards
            </p>
            <div className="space-y-2">
              {guards.map((g) => (
                <div key={g.name} className="flex items-center gap-4 px-4 py-2.5 rounded-lg border border-white/[0.04]" style={{ background: `${g.color}03` }}>
                  <span className="shrink-0 w-2 h-2 rounded-full" style={{ background: g.color }} />
                  <span className="text-sm font-semibold text-white/80 w-[100px] sm:w-[120px] shrink-0">{g.name}</span>
                  <span className="text-sm text-[#7A8CA8] flex-1">{g.trigger}</span>
                  <span className="text-xs font-mono shrink-0" style={{ color: g.color }}>{g.effect}</span>
                </div>
              ))}
            </div>
            <p className="text-xs text-[#7A8CA8] font-mono mt-3">
              Wrap-Up Headroom: 만료 30초 전부터 tool_choice=none → 결과 정리 후 자연 종료
            </p>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
