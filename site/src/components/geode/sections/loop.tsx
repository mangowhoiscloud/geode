"use client";

import { useEffect, useState, useRef } from "react";
import { ScrollReveal } from "../scroll-reveal";
import { useLocale, t } from "../locale-context";

/* ── Terminal scenarios (geode.html 실제 출력 기반) ── */
type Line = { type: string; text: string; input?: boolean; rich?: React.ReactNode };

const scenarios: { tab: string; lines: Line[] }[] = [
  {
    tab: "agentic",
    lines: [
      { type: "prompt", text: "mango@mangoui-MacBookAir geode % geode" },
      { type: "dots", text: "", rich: <><br/></> },
      { type: "dots", text: '  ╲╲( ◕ ᵕ ◕ )╱╱  GEODE', rich: <>{`  `}<span style={{color:"#9775c4"}}>╲╲</span><span style={{color:"#fff"}}>{`( ◕ ᵕ ◕ )`}</span><span style={{color:"#9775c4"}}>╱╱</span>{`  `}<span style={{color:"#5f9ea0",fontWeight:700}}>GEODE</span></> },
      { type: "dots", text: "                       claude-opus-4-7 · autonomous execution agent", rich: <span style={{color:"#d4a0a0",opacity:0.5}}>{`                       claude-opus-4-7 · autonomous execution agent`}</span> },
      { type: "dots", text: "                       ~/workspace/geode", rich: <span style={{opacity:0.35}}>{`                       ~/workspace/geode`}</span> },
      { type: "dots", text: "" },
      { type: "dots", text: "  harness: GEODE", rich: <>{`  `}<span style={{opacity:0.35}}>harness:</span>{` `}<span style={{color:"#5f9ea0"}}>GEODE</span></> },
      { type: "dots", text: "  ✓ LLM Analysis  ✓ Project Memory  ✓ User Profile", rich: <>{`  `}<span style={{color:"#22c55e",fontWeight:700}}>✓</span>{` LLM Analysis  `}<span style={{color:"#22c55e",fontWeight:700}}>✓</span>{` Project Memory  `}<span style={{color:"#22c55e",fontWeight:700}}>✓</span>{` User Profile`}</> },
      { type: "dots", text: "  ✓ Dry-Run Analysis  ✓ Project Search", rich: <>{`  `}<span style={{color:"#22c55e",fontWeight:700}}>✓</span>{` Dry-Run Analysis  `}<span style={{color:"#22c55e",fontWeight:700}}>✓</span>{` Project Search`}</> },
      { type: "dots", text: "" },
      { type: "dots", text: "  /help for commands  ·  type naturally", rich: <span style={{opacity:0.35}}>{`  /help for commands  ·  type naturally`}</span> },
      { type: "dots", text: "" },
      { type: "dots", text: "  Connected to serve via IPC", rich: <>{`  Connected to `}<span style={{color:"#5f9ea0"}}>serve</span>{` via `}<span style={{color:"#e0b040"}}>IPC</span></> },
      { type: "dots", text: "  Session: cli-2f985c53", rich: <>{`  `}<span style={{color:"#22c55e",fontWeight:700}}>Session: cli-2f985c53</span></> },
      { type: "dots", text: "" },
      { type: "prompt", text: "> OpenAI로 변경 부탁해.", input: true },
      { type: "status", text: "● AgenticLoop" },
      { type: "dots", text: "" },
      { type: "verify", text: "  Write tool requires approval" },
      { type: "tool", text: "  ⎿ ▸ switch_model" },
      { type: "verify", text: "  Allow? [Y/n/A] A" },
      { type: "exec", text: "  ⎿ ✓ switch_model → ok (31.8s)" },
      { type: "token", text: "  ✢ Worked for 1m 4s · gpt-5.4 · ↓84.0k ↑107 · $0.3359" },
      { type: "done", text: "  변경됐습니다. 현재 라운드는 gpt-5.4입니다." },
      { type: "dots", text: "" },
      { type: "prompt", text: "> GLM-5로 스위칭해.", input: true },
      { type: "tool", text: "  ⎿ ▸ switch_model" },
      { type: "verify", text: "  Allow? [Y/n/A] A" },
      { type: "exec", text: "  ⎿ ✓ switch_model → ok (28.4s)" },
      { type: "token", text: "  ✢ Worked for 52s · glm-5 · ↓71.2k ↑89 · $0.2140" },
      { type: "done", text: "  GLM-5로 전환됐습니다." },
      { type: "dots", text: "" },
      { type: "prompt", text: "> 다시 Opus로 돌아와.", input: true },
      { type: "tool", text: "  ⎿ ▸ switch_model" },
      { type: "verify", text: "  Allow? [Y/n/A] A" },
      { type: "exec", text: "  ⎿ ✓ switch_model → ok (24.1s)" },
      { type: "token", text: "  ✢ Worked for 48s · claude-opus-4-7 · ↓68.5k ↑94 · $0.2801" },
      { type: "done", text: "  Opus 4.7으로 복귀. 3-provider 순환 완료." },
    ],
  },
  {
    tab: "explore",
    lines: [
      { type: "prompt", text: "> 최신 AI agent 논문 3편 찾아서 요약해줘", input: true },
      { type: "tool", text: '  ⎿ ▸ general_web_search(query="AI agent papers 2026")' },
      { type: "exec", text: "  ⎿ ✓ general_web_search → 8 results" },
      { type: "tool", text: '  ⎿ ▸ web_fetch(url="https://arxiv.org/abs/2603.xxxxx")' },
      { type: "exec", text: "  ⎿ ✓ web_fetch → 12,400 chars" },
      { type: "tool", text: '  ⎿ ▸ web_fetch(url="https://arxiv.org/abs/2603.yyyyy")' },
      { type: "exec", text: "  ⎿ ✓ web_fetch → 9,800 chars" },
      { type: "tool", text: '  ⎿ ▸ note_save(title="AI Agent Survey 2026-03")' },
      { type: "verify", text: "    Write operation [Y/n/A] > A" },
      { type: "exec", text: "  ⎿ ✓ note_save → saved" },
      { type: "token", text: "  ⎿ ✢ claude-opus-4-7 · ↓18.2k ↑3.4k · $0.176 · 14.1s" },
      { type: "done", text: "  3편 요약 완료. .geode/vault/research/에 저장." },
    ],
  },
  {
    tab: "plan-mode",
    lines: [
      { type: "prompt", text: "> CHANGELOG 정리하고 다음 릴리즈 준비해", input: true },
      { type: "status", text: '  ● plan: "release prep" (3 steps)' },
      { type: "phase", text: "    1. CHANGELOG [Unreleased] → 릴리즈 버전으로 정리" },
      { type: "phase", text: "    2. 4곳 버전 동기화 (pyproject, CLAUDE, README, CHANGELOG)" },
      { type: "phase", text: "    3. git tag + PR 생성" },
      { type: "prompt", text: "  approve? [Y/n/A] > A", input: true },
      { type: "tool", text: '  ⎿ ▸ run_bash(command="sed -i \'s/Unreleased/.../\' ...")' },
      { type: "tool", text: '  ⎿ ▸ note_save(title="CHANGELOG release prep")' },
      { type: "exec", text: "  ⎿ ✓ 3/3 steps · PR #524 생성" },
      { type: "token", text: "  ⎿ ✢ claude-opus-4-7 · ↓6.8k ↑2.1k · $0.066 · 8.2s" },
    ],
  },
];

const colorMap: Record<string, string> = {
  prompt: "text-white/70",
  status: "text-[#34D399]",
  dots: "text-white/25",
  phase: "text-[#818CF8]",
  tool: "text-[#F5C542]",
  exec: "text-[#4ECDC4]",
  verify: "text-[#C084FC]",
  done: "text-[#34D399] font-bold",
  error: "text-[#E87080]",
  token: "text-[#7A8CA8]",
};

const tabLabels: Record<string, string> = {
  agentic: "Agentic",
  explore: "Explore",
  "plan-mode": "Plan",
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
                strokeOpacity={isActive ? 0.7 : 0.2}
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
                opacity={isActive ? 1 : 0.45}
                style={{ transition: "opacity 0.4s" }}
              >
                {step.label}
              </text>
            </g>
          );
        })}

        {/* Center pulse */}
        <circle cx={CX} cy={CY} r={0} fill="none" stroke="#4ECDC4" strokeWidth={0.8} strokeOpacity={0}>
          <animate attributeName="r" values="0;88" dur="3s" repeatCount="indefinite" />
          <animate attributeName="stroke-opacity" values="0.15;0" dur="3s" repeatCount="indefinite" />
        </circle>

        {/* Center label */}
        <text x={CX} y={CY - 4} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={9} fontFamily="ui-monospace, monospace">
          while
        </text>
        <text x={CX} y={CY + 9} textAnchor="middle" fill="white" fillOpacity={0.35} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>
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
  const scrollRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedRef = useRef(false);

  const lines = scenarios[activeTab].lines;

  // Auto-scroll to bottom as new lines appear
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [visibleLines, currentChars]);

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
      className="rounded-xl border border-white/[0.04] bg-[#060B14] overflow-hidden h-[420px] flex flex-col"
    >
      {/* Tab bar */}
      <div className="flex items-center gap-0 border-b border-white/[0.04] px-3 shrink-0">
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
      <div ref={scrollRef} className="p-5 font-mono text-[12.5px] leading-[1.9] flex-1 overflow-y-scroll overflow-x-hidden [&::-webkit-scrollbar]:!w-0" style={{ scrollbarWidth: "none" }}>
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
                {line.rich || line.text}
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
  { value: "∞", label: "while True", sub: "" },
  { value: "8", label: "Safety Guards", sub: "convergence · time budget · stuck · HITL" },
  { value: "3", label: "Modes", sub: "IPC(thin CLI) · Daemon(Slack) · Scheduler" },
  { value: "5", label: "Tool Routes", sub: "Bash · Tool · MCP · Skill · Task" },
];

/* ── 5+3 Safety Guards ── */
const guards = [
  { nameKo: "수렴 감지", nameEn: "Convergence Detection", triggerKo: "동일 에러 4회 연속", triggerEn: "Same error 4 times consecutively", effectKo: "break", effectEn: "break", color: "#E87080" },
  { nameKo: "시간 예산", nameEn: "Time Budget", triggerKo: "wall-clock 만료 (Karpathy P3)", triggerEn: "Wall-clock expiry (Karpathy P3)", effectKo: "wrap-up → end", effectEn: "wrap-up → end", color: "#F5C542" },
  { nameKo: "컨텍스트 80%", nameEn: "Context 80%", triggerKo: "Provider별 자동 압축 (Anthropic compact_20260112 / OpenAI client-side)", triggerEn: "Per-provider auto compaction (Anthropic compact_20260112 / OpenAI client-side)", effectKo: "요약 후 계속", effectEn: "Summarize, continue", color: "#818CF8" },
  { nameKo: "컨텍스트 95%", nameEn: "Context 95%", triggerKo: "긴급 프루닝 + UI 알림", triggerEn: "Emergency pruning + UI notification", effectKo: "최근 N개만 유지", effectEn: "Keep last N only", color: "#C084FC" },
  { nameKo: "StuckDetector", nameEn: "StuckDetector", triggerKo: "2시간 무응답", triggerEn: "2 hours unresponsive", effectKo: "세션 자동 해제", effectEn: "Auto-release session", color: "#4ECDC4" },
  { nameKo: "비용 자동 정지", nameEn: "Auto Cost Stop", triggerKo: "세션당 비용 상한 초과 + 80% 사전 경고", triggerEn: "Per-session cost cap + 80% proactive warning", effectKo: "자동 정지", effectEn: "Auto-stop", color: "#F4B8C8" },
  { nameKo: "래칫 에러 감지", nameEn: "Ratchet Error Detection", triggerKo: "결과 악화 패턴 (Karpathy P4)", triggerEn: "Result degradation pattern (Karpathy P4)", effectKo: "롤백", effectEn: "Rollback", color: "#60A5FA" },
  { nameKo: "다양성 강제", nameEn: "Diversity Enforcement", triggerKo: "동일 도구 5회 연속 호출", triggerEn: "Same tool called 5 times consecutively", effectKo: "다른 경로 시도", effectEn: "Try different route", color: "#34D399" },
];

/* ── Section ── */
export function LoopSection() {
  const locale = useLocale();
  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#4ECDC4]/60 uppercase tracking-[0.25em] mb-3">
            AgenticLoop
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-2">
            while True: Long-running Agent
          </h2>
          <p className="text-lg text-white/40 font-semibold mb-4">
            for range(50) → while True + 8 Guards
          </p>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-12 leading-relaxed">
            {locale === "ko" ? (
              <>max_rounds=50이었던 실행 제약을 <code className="text-[#4ECDC4]/70">time_budget_s</code>로 교체했습니다. LLM 출력 분산이 높아 라운드 수로는 종료 시점을 예측할 수 없지만, wall-clock은 일관됩니다. 8개 가드(수렴 감지, 시간 예산, 컨텍스트 압축, StuckDetector, 비용 상한, 래칫, 다양성 강제)가 무한 루프를 방지합니다.</>
            ) : (
              <>Replaced the old max_rounds=50 constraint with <code className="text-[#4ECDC4]/70">time_budget_s</code>. LLM output variance is too high for round-based prediction, but wall-clock time is consistent. Eight guards (convergence, time budget, context compaction, StuckDetector, cost cap, ratchet, diversity enforcement) prevent infinite loops.</>
            )}
          </p>
        </ScrollReveal>

        <div className="grid grid-cols-1 md:grid-cols-[0.8fr_1.4fr] gap-8 items-start">
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
                    {s.sub && <div className="text-[9px] font-mono text-[#4ECDC4]/50 mt-0.5">{s.sub}</div>}
                  </div>
                ))}
              </div>
            </div>
          </ScrollReveal>

          {/* Right — Terminal replay + RECORD */}
          <ScrollReveal delay={0.15}>
            <TypingTerminal />
            <div className="mt-3 rounded-lg border border-white/[0.06] bg-white/[0.01] px-4 py-2.5 flex items-center gap-5">
              <span className="text-[9px] font-mono font-bold text-[#E87080]/60 uppercase tracking-widest shrink-0">REC</span>
              {[
                { value: "∞", unit: "loop" },
                { value: "8", unit: "guards" },
                { value: "5", unit: "routes" },
              ].map((m) => (
                <div key={m.unit} className="text-center">
                  <div className="text-sm font-bold text-white/80">{m.value}</div>
                  <div className="text-[8px] font-mono text-[#7A8CA8] uppercase">{m.unit}</div>
                </div>
              ))}
              <div className="flex-1 text-right">
                <div className="text-[9px] font-mono text-white/30">AgenticLoop · async tools · IPC/daemon/scheduler</div>
                <div className="text-[8px] font-mono text-[#34D399]/50 mt-0.5">{t(locale, "긴 실행 세션 · 복구 가능 체크포인트 · 비용/컨텍스트 가드", "Long-running sessions · recoverable checkpoints · cost/context guards")}</div>
              </div>
            </div>
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
                <div key={g.nameKo} className="flex items-center gap-4 px-4 py-2.5 rounded-lg border border-white/[0.04]" style={{ background: `${g.color}03` }}>
                  <span className="shrink-0 w-2 h-2 rounded-full" style={{ background: g.color }} />
                  <span className="text-sm font-semibold text-white/80 w-[100px] sm:w-[120px] shrink-0">{locale === "en" ? g.nameEn : g.nameKo}</span>
                  <span className="text-sm text-[#7A8CA8] flex-1">{locale === "en" ? g.triggerEn : g.triggerKo}</span>
                  <span className="text-xs font-mono shrink-0" style={{ color: g.color }}>{locale === "en" ? g.effectEn : g.effectKo}</span>
                </div>
              ))}
            </div>
            <p className="text-xs text-[#7A8CA8] font-mono mt-3">
              {t(locale,
                "Wrap-Up Headroom: 만료 30초 전부터 tool_choice=none → 결과 정리 후 자연 종료",
                "Wrap-Up Headroom: 30s before expiry, tool_choice=none → finalize results, then graceful exit"
              )}
            </p>

            {/* Failure modes */}
            <div className="mt-6 rounded-xl border border-white/[0.04] px-5 py-4">
              <div className="text-sm font-semibold text-white/70 mb-3">Failure Recovery</div>
              <div className="space-y-1.5 text-sm">
                {(locale === "en" ? [
                  { scenario: "Full LLM outage", recovery: "Cross-provider failover (Anthropic → OpenAI → GLM)", color: "#E87080" },
                  { scenario: "MCP server unresponsive", recovery: "spawn retry + graceful skip", color: "#F5C542" },
                  { scenario: "Context overflow", recovery: "80% compaction → 95% emergency prune → UI notification", color: "#818CF8" },
                  { scenario: "Tool consecutive failures ≥2", recovery: "adaptive recovery chain + model escalation", color: "#C084FC" },
                ] : [
                  { scenario: "LLM 전체 장애", recovery: "Cross-provider failover (Anthropic → OpenAI → GLM)", color: "#E87080" },
                  { scenario: "MCP 서버 미응답", recovery: "spawn retry + graceful skip", color: "#F5C542" },
                  { scenario: "컨텍스트 오버플로우", recovery: "80% compaction → 95% emergency prune → UI 알림", color: "#818CF8" },
                  { scenario: "도구 연속 실패 ≥2", recovery: "adaptive recovery chain + 모델 에스컬레이션", color: "#C084FC" },
                ]).map((f) => (
                  <div key={f.scenario} className="flex items-start gap-3">
                    <span className="shrink-0 w-1.5 h-1.5 rounded-full mt-1.5" style={{ background: f.color }} />
                    <div>
                      <span className="text-white/60">{f.scenario}</span>
                      <span className="text-[#7A8CA8] ml-2">{f.recovery}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
