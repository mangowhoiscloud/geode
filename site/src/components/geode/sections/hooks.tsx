"use client";

import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { SectionHeader } from "../ui/section-header";
import { useLocale, t } from "../locale-context";

/* ── Event data ── */
const events = [
  { id: "pipeline_end", label: "PIPELINE_END", color: "#4ECDC4",
    handlers: ["RunLog", "Journal", "Snapshot", "MemWriteBack", "Notification"],
    priorities: [50, 60, 80, 85, 200],
    handlerColors: ["#60A5FA", "#34D399", "#4ECDC4", "#4ECDC4", "#F5C542"],
    descKo: "파이프라인 완료 시 5 핸들러 연쇄", descEn: "5 handlers chain on pipeline completion" },
  { id: "drift_detected", label: "DRIFT_DETECTED", color: "#F5C542",
    handlers: ["DriftLogger", "AutoSnapshot", "PipelineTrigger", "Notification"],
    priorities: [90, 80, 70, 200],
    handlerColors: ["#F5C542", "#4ECDC4", "#4ECDC4", "#F5C542"],
    descKo: "드리프트 감지 → 스냅샷 + 재분석 트리거", descEn: "Drift detected: snapshot + re-analysis trigger" },
  { id: "context_overflow", label: "CONTEXT_OVERFLOW", color: "#E87080",
    handlers: ["ContextAction"],
    priorities: [50],
    handlerColors: ["#E87080"],
    descKo: "유일한 feedback hook. 압축 전략을 핸들러가 결정", descEn: "The only feedback hook. Handler decides compaction strategy",
    isBoomerang: true },
  { id: "subagent_completed", label: "SUBAGENT_COMPLETED", color: "#C084FC",
    handlers: ["RunLog", "JournalSub"],
    priorities: [50, 60],
    handlerColors: ["#60A5FA", "#34D399"],
    descKo: "서브에이전트 완료 → 저널 기록", descEn: "Sub-agent complete: journal recording" },
  { id: "turn_complete", label: "TURN_COMPLETE", color: "#F4B8C8",
    handlers: ["RunLog", "AutoMemory"],
    priorities: [50, 85],
    handlerColors: ["#60A5FA", "#4ECDC4"],
    descKo: "매 턴 종료 → 자동 메모리 축적", descEn: "Each turn end: auto memory accumulation" },
];

/* ── Version timeline data ── */
const versions = [
  { ver: "v0.10", count: 26, descKo: "L1 관측만. RunLog 단독", descEn: "L1 observe only. RunLog alone" },
  { ver: "v0.31", count: 42, descKo: "L2 반응 추가. drift → 자동 재분석", descEn: "L2 react added. drift: auto-reanalysis" },
  { ver: "v0.35", count: 40, descKo: "6개 orphan 제거. CRITICAL 미연결 수정", descEn: "6 orphans removed. Fixed CRITICAL None bug" },
  { ver: "v0.37", count: 40, descKo: "Unified bootstrap. ONE HookSystem 보장", descEn: "Unified bootstrap. ONE HookSystem guaranteed" },
  { ver: "v0.42", count: 46, descKo: "+4 운영 이벤트. SHUTDOWN, CONFIG_RELOADED, MCP 연결 추적", descEn: "+4 operational events. SHUTDOWN, CONFIG_RELOADED, MCP connection tracking" },
  { ver: "v0.45", count: 48, descKo: "+2 관측 이벤트. SessionMetrics, LLM resilience 지원", descEn: "+2 observability events. SessionMetrics, LLM resilience support" },
  { ver: "v0.48", count: 55, descKo: "+6 hook interceptor. block/modify chain", descEn: "+6 interceptor pattern. block/modify chain" },
  { ver: "v0.65", count: 58, descKo: "+3 prompt + lifecycle. PROMPT_ASSEMBLED 추가", descEn: "+3 prompt + lifecycle. PROMPT_ASSEMBLED added" },
];

/* ── Design decisions data ── */
const decisions = [
  { title: "Sync, not Async", color: "#818CF8",
    ko: "도구 실행은 asyncio.gather로 병렬화하지만, Hook은 동기 체인을 유지합니다. P50→P80→P85 순서가 깨지면 RunLog 없이 Snapshot이 먼저 실행되는 문제가 발생하기 때문입니다. 관측 핸들러는 ~ms 단위라 전체 레이턴시에 영향이 미미합니다.",
    en: "Tool execution uses asyncio.gather for parallelism, but Hooks maintain a sync chain. If P50→P80→P85 ordering breaks, Snapshot could execute before RunLog. Observer handlers run in ~ms, so latency impact is negligible." },
  { title: "Prune, then Restore", color: "#E87080",
    ko: "v0.35.1에서 핸들러 0개인 6 이벤트를 제거했습니다(46→40). v0.42에서 운영 모니터링 필요로 4종을 재추가(SHUTDOWN_STARTED, CONFIG_RELOADED, MCP_SERVER_CONNECTED/FAILED)하여 46으로 복원. v0.45에서 LLM resilience 관측을 위해 2종 추가(48). 필요할 때만 존재시키는 원칙을 검증했습니다.",
    en: "In v0.35.1, removed 6 events with zero handlers (46→40). In v0.42, re-added 4 operational events (SHUTDOWN_STARTED, CONFIG_RELOADED, MCP_SERVER_CONNECTED/FAILED), restoring to 46. In v0.45, added 2 for LLM resilience observability (48). Validated the principle: events exist only when needed." },
  { title: "Unified Wiring", color: "#34D399",
    ko: "v0.35.0 이전에는 serve/scheduler에서 HookSystem이 미연결되어, serve에서 발화한 이벤트를 REPL 핸들러가 수신하지 못했습니다. GeodeRuntime이 단일 HookSystem을 소유하도록 전환하여 전 모드 이벤트 전파를 보장합니다.",
    en: "Before v0.35.0, HookSystem was not wired in serve/scheduler. Events fired in serve couldn't be received by REPL handlers. Switching to a single HookSystem owned by GeodeRuntime guarantees event propagation across all modes." },
  { title: "Priority Bands", color: "#F5C542",
    ko: "P40-50 인프라(RunLog, StuckDetect), P60-85 도메인(Journal, Snapshot, MemoryWriteBack), P200 알림(Notification). 숫자가 낮을수록 먼저 실행됩니다. P200은 의도적으로 큰 간격을 두어 인프라/도메인 핸들러 완료 후 알림을 보장합니다.",
    en: "P40-50 infra (RunLog, StuckDetect), P60-85 domain (Journal, Snapshot, MemoryWriteBack), P200 notifications. Lower = executes first. P200's large gap ensures notifications fire only after all infra/domain handlers complete." },
];

/* Priority to delay ms mapping */
function priorityToDelay(p: number) {
  if (p <= 50) return 200;
  if (p <= 60) return 350;
  if (p <= 70) return 500;
  if (p <= 80) return 600;
  if (p <= 85) return 650;
  return 1100;
}

/* ── Main export ── */
export function HooksSection() {
  const locale = useLocale();
  const [selected, setSelected] = useState(0);
  const [ripplePhase, setRipplePhase] = useState(-1);
  const [showBoomerang, setShowBoomerang] = useState(false);
  const [hoveredHandler, setHoveredHandler] = useState<number | null>(null);
  const [hoveredVersion, setHoveredVersion] = useState<number | null>(null);
  const [showDecisions, setShowDecisions] = useState(true);
  const [replayRot, setReplayRot] = useState(0);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const ev = events[selected];

  /* Clear all timers */
  const clearTimers = () => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  };

  /* Run ripple animation */
  const runRipple = () => {
    clearTimers();
    setRipplePhase(-1);
    setShowBoomerang(false);
    const sorted = ev.priorities.map((p, i) => ({ p, i })).sort((a, b) => a.p - b.p);
    sorted.forEach((item, seqIdx) => {
      const delay = priorityToDelay(item.p);
      const tid = setTimeout(() => setRipplePhase(seqIdx), delay);
      timersRef.current.push(tid);
    });
    if (ev.isBoomerang) {
      const tid = setTimeout(() => setShowBoomerang(true), priorityToDelay(ev.priorities[0]) + 400);
      timersRef.current.push(tid);
    }
  };

  /* On event change or mount, fire ripple */
  useEffect(() => { runRipple(); return clearTimers; }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps

  /* Waterfall lane layout */
  const svgW = 600, svgH = 220;
  const dotCx = 30, dotCy = 110, railY = 110, colW = 70, colH = 140;
  const sorted = ev.priorities.map((p, i) => ({ p, i, name: ev.handlers[i], color: ev.handlerColors[i] })).sort((a, b) => a.p - b.p);
  const startX = 80;
  const maxGap = 80;
  const colPositions = sorted.map((item, idx) => {
    if (idx === 0) return startX;
    const gap = Math.min((item.p - sorted[idx - 1].p) * 0.6, maxGap);
    return startX + sorted.slice(0, idx).reduce((acc, _, j) => {
      const g = Math.min((sorted[j + 1]?.p - sorted[j].p) * 0.6, maxGap);
      return acc + colW + (g < 8 ? 8 : g);
    }, 0);
  });
  const particleCx = ripplePhase >= 0 && ripplePhase < sorted.length
    ? colPositions[ripplePhase] + colW / 2
    : dotCx;

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(78,205,196,0.015)_0%,transparent_60%)] pointer-events-none" />
      <div className="relative z-10 max-w-5xl mx-auto">

        {/* 1. Header */}
        <SectionHeader
          variant="quote"
          labelColor="#4ECDC4"
          title={t(locale, "이벤트 기반 리플 패턴", "Event-Driven Ripple Pattern")}
          description={t(locale,
            "비결정적 LLM 시스템은 모든 경로를 테스트할 수 없습니다. 초기에는 노드 간 직접 콜백으로 관측했지만, 26개 파일에 의존성이 퍼지며 순환 참조가 발생했습니다. Hook 이벤트 버스로 전환하여 발화 측은 누가 듣는지 모르고, 핸들러는 누가 쏘는지 모르는 완전 분리를 달성했습니다. v0.10(26) → v0.31(42, 반응) → v0.35(40, orphan 정리) → v0.37(통합) → v0.42(46, 운영) → v0.45(48, 관측)로 성숙했습니다.",
            "Non-deterministic LLM systems cannot test every path. Initially we observed via direct callbacks between nodes, but dependencies spread across 26 files, creating circular references. Switching to a Hook event bus achieved full decoupling: emitters don't know who listens, handlers don't know who fires. Matured from v0.10 (26) → v0.31 (42, react) → v0.35 (40, orphan cleanup) → v0.37 (unified) → v0.42 (46, operational) → v0.45 (48, observability)."
          )}
        />

        {/* 2. Overview: Sources → HookSystem → Handlers */}
        <ScrollReveal delay={0.05}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-10">
            <svg viewBox="0 0 780 240" className="w-full min-w-[600px]" style={{ maxHeight: 270 }}>
              {/* Column labels */}
              <text x={80} y={16} textAnchor="middle" fill="white" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>
                {t(locale, "이벤트 소스", "Event Sources")}
              </text>
              <text x={350} y={16} textAnchor="middle" fill="white" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>
                HookSystem
              </text>
              <text x={640} y={16} textAnchor="middle" fill="white" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>
                {t(locale, "핸들러 체인", "Handler Chain")}
              </text>

              {/* Event source categories (left) */}
              {[
                { label: "Pipeline", count: 3, color: "#E87080", y: 30 },
                { label: "Node", count: 4, color: "#F4B8C8", y: 60 },
                { label: "Analysis", count: 3, color: "#818CF8", y: 90 },
                { label: "Automation", count: 6, color: "#F5C542", y: 120 },
                { label: "SubAgent", count: 3, color: "#C084FC", y: 150 },
                { label: "Context+LLM", count: 6, color: "#60A5FA", y: 180 },
                { label: "Tool+HITL", count: 6, color: "#4ECDC4", y: 210 },
              ].map((s) => (
                <g key={s.label}>
                  <rect x={10} y={s.y} width={140} height={24} rx={5} fill="#0C1220" stroke={s.color} strokeWidth={0.6} strokeOpacity={0.3} />
                  <text x={24} y={s.y + 16} fill={s.color} fillOpacity={0.7} fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>{s.label}</text>
                  <text x={136} y={s.y + 16} textAnchor="end" fill={s.color} fillOpacity={0.35} fontSize={7} fontFamily="ui-monospace, monospace">{s.count}</text>
                  <path d={`M150,${s.y + 12} C200,${s.y + 12} 250,120 290,120`} stroke={s.color} strokeOpacity={0.12} strokeWidth={0.8} fill="none" />
                </g>
              ))}

              {/* HookSystem hub (center) */}
              <circle cx={350} cy={120} r={0} fill="none" stroke="#4ECDC4" strokeWidth={0.6} strokeOpacity={0}>
                <animate attributeName="r" values="0;55" dur="3s" repeatCount="indefinite" />
                <animate attributeName="stroke-opacity" values="0.1;0" dur="3s" repeatCount="indefinite" />
              </circle>
              <rect x={300} y={88} width={100} height={64} rx={12} fill="#0C1220" stroke="#4ECDC4" strokeWidth={1} strokeOpacity={0.35} />
              <text x={350} y={112} textAnchor="middle" fill="#4ECDC4" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>HookSystem</text>
              <text x={350} y={128} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.4} fontSize={7} fontFamily="ui-monospace, monospace">58 events</text>
              <text x={350} y={142} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.3} fontSize={7} fontFamily="ui-monospace, monospace">priority-sorted</text>

              {/* Handler chain (right, sorted by priority) */}
              {[
                { label: "P40", name: "StuckDetect", color: "#60A5FA", y: 30 },
                { label: "P50", name: "RunLog (ALL)", color: "#60A5FA", y: 55 },
                { label: "P60", name: "Journal", color: "#34D399", y: 80 },
                { label: "P65", name: "ApprovalTracker", color: "#4ECDC4", y: 105 },
                { label: "P70", name: "DriftTrigger", color: "#4ECDC4", y: 130 },
                { label: "P80", name: "Snapshot", color: "#4ECDC4", y: 155 },
                { label: "P85", name: "MemoryWriteBack", color: "#818CF8", y: 180 },
                { label: "P200", name: "Notification", color: "#F5C542", y: 215 },
              ].map((h, i) => (
                <g key={h.label}>
                  <path d={`M400,120 C440,120 480,${h.y + 12} 540,${h.y + 12}`} stroke={h.color} strokeOpacity={0.12} strokeWidth={0.8} fill="none" />
                  <rect x={540} y={h.y} width={150} height={22} rx={5} fill="#0C1220" stroke={h.color} strokeWidth={0.5} strokeOpacity={0.25} />
                  <text x={556} y={h.y + 15} fill={h.color} fillOpacity={0.5} fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={700}>{h.label}</text>
                  <text x={596} y={h.y + 15} fill="white" fillOpacity={0.45} fontSize={8} fontFamily="ui-monospace, monospace">{h.name}</text>
                  {/* Priority gap indicator for P200 */}
                  {i === 6 && <line x1={615} y1={h.y + 22 + 4} x2={615} y2={215 - 2} stroke="white" strokeOpacity={0.06} strokeWidth={1} strokeDasharray="2 4" />}
                </g>
              ))}

              {/* Legend */}
              <text x={615} y={236} textAnchor="middle" fill="white" fillOpacity={0.15} fontSize={7} fontFamily="ui-monospace, monospace">
                {t(locale, "낮은 P = 먼저 실행", "Lower P = executes first")}
              </text>
            </svg>
          </div>
        </ScrollReveal>

        {/* 4. Main Area: Event Selector + Waterfall Lane */}
        <ScrollReveal delay={0.1}>
          <div className="flex flex-col md:flex-row gap-4 mb-10">
            {/* Left: Event Selector */}
            <div className="flex md:flex-col gap-2 md:w-[200px] overflow-x-auto md:overflow-x-visible pb-2 md:pb-0 shrink-0">
              {events.map((e, i) => (
                <motion.button
                  key={e.id}
                  onClick={() => setSelected(i)}
                  className="whitespace-nowrap rounded-lg border px-3 py-2 text-left text-xs font-mono font-bold transition-colors shrink-0"
                  style={{
                    borderColor: selected === i ? `${e.color}60` : "rgba(255,255,255,0.06)",
                    background: selected === i ? `${e.color}12` : "transparent",
                    color: selected === i ? e.color : "rgba(255,255,255,0.4)",
                  }}
                  animate={selected === i ? { scale: [1, 1.03, 1] } : { scale: 1 }}
                  transition={selected === i ? { repeat: Infinity, duration: 2.5, ease: "easeInOut" } : {}}
                >
                  {e.label}
                </motion.button>
              ))}
            </div>

            {/* Right: Waterfall Lane */}
            <div className="flex-1 min-w-0">
              <div className="relative">
                {/* Replay button */}
                <button
                  className="absolute top-2 right-2 z-10 w-7 h-7 rounded-full border border-white/10 flex items-center justify-center text-white/30 hover:text-white/60 hover:border-white/20 transition-colors"
                  onClick={() => { setReplayRot(r => r + 360); runRipple(); }}
                >
                  <motion.svg animate={{ rotate: replayRot }} transition={{ duration: 0.4 }} width={14} height={14} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5}>
                    <path d="M2 8a6 6 0 0 1 10.5-4M14 8a6 6 0 0 1-10.5 4" />
                    <path d="M12.5 1v3h-3M3.5 15v-3h3" />
                  </motion.svg>
                </button>

                {/* Event description */}
                <p className="text-xs text-[#A0B4D4] mb-3 font-mono">{t(locale, ev.descKo, ev.descEn)}</p>

                <svg viewBox={`0 0 ${svgW} ${svgH}`} className="w-full rounded-xl" style={{ background: "#0C1220" }}>
                  {/* Rail line */}
                  <line x1={dotCx} y1={railY} x2={svgW - 20} y2={railY} stroke="white" strokeOpacity={0.06} strokeWidth={1} />

                  {/* Event dot (pulsing) */}
                  <circle cx={dotCx} cy={dotCy} r={12} fill={ev.color} fillOpacity={0.15} stroke={ev.color} strokeWidth={1.2} strokeOpacity={0.5}>
                    <animate attributeName="r" values="10;14;10" dur="2s" repeatCount="indefinite" />
                    <animate attributeName="stroke-opacity" values="0.5;0.8;0.5" dur="2s" repeatCount="indefinite" />
                  </circle>
                  <circle cx={dotCx} cy={dotCy} r={5} fill={ev.color} fillOpacity={0.8} />

                  {/* Handler columns */}
                  {sorted.map((item, idx) => {
                    const cx = colPositions[idx];
                    const isActive = ripplePhase >= idx;
                    const colTop = railY - colH / 2;
                    return (
                      <g
                        key={item.name}
                        onMouseEnter={() => setHoveredHandler(idx)}
                        onMouseLeave={() => setHoveredHandler(null)}
                        style={{ cursor: "pointer" }}
                      >
                        {/* Background column */}
                        <rect x={cx} y={colTop} width={colW} height={colH} rx={6} fill="white" fillOpacity={0.03} stroke="white" strokeOpacity={0.06} strokeWidth={0.5} />
                        {/* Fill-up animation */}
                        <motion.rect
                          x={cx}
                          y={colTop}
                          width={colW}
                          rx={6}
                          fill={item.color}
                          fillOpacity={0.2}
                          initial={{ height: 0 }}
                          animate={{ height: isActive ? colH : 0 }}
                          transition={{ duration: 0.15, ease: "easeOut" }}
                        />
                        {/* Glow on activation */}
                        <AnimatePresence>
                          {isActive && ripplePhase === idx && (
                            <motion.rect
                              x={cx - 2}
                              y={colTop - 2}
                              width={colW + 4}
                              height={colH + 4}
                              rx={8}
                              fill="none"
                              stroke={item.color}
                              strokeWidth={1.5}
                              initial={{ opacity: 0.8 }}
                              animate={{ opacity: 0 }}
                              exit={{ opacity: 0 }}
                              transition={{ duration: 0.6 }}
                            />
                          )}
                        </AnimatePresence>
                        {/* Name label (top) */}
                        <text x={cx + colW / 2} y={colTop - 6} textAnchor="middle" fill={item.color} fontSize={9} fontFamily="ui-monospace,monospace" fontWeight={600} fillOpacity={isActive ? 1 : 0.4}>{item.name}</text>
                        {/* Priority badge (bottom) */}
                        <text x={cx + colW / 2} y={colTop + colH + 14} textAnchor="middle" fill="white" fontSize={8} fontFamily="ui-monospace,monospace" fillOpacity={0.3}>P{item.p}</text>
                      </g>
                    );
                  })}

                  {/* Traveling particle */}
                  <motion.circle
                    cy={railY}
                    r={4}
                    fill={ev.color}
                    animate={{ cx: particleCx }}
                    transition={{ duration: 0.2, ease: "easeOut" }}
                  >
                    <animate attributeName="opacity" values="1;0.6;1" dur="0.5s" repeatCount="indefinite" />
                  </motion.circle>

                  {/* Boomerang return path for CONTEXT_OVERFLOW */}
                  {ev.isBoomerang && showBoomerang && (
                    <g>
                      <motion.path
                        d={`M ${colPositions[0] + colW / 2} ${railY + colH / 2 + 8} Q ${(colPositions[0] + colW / 2 + dotCx) / 2} ${railY + colH / 2 + 30} ${dotCx} ${dotCy + 14}`}
                        fill="none"
                        stroke="#F5C542"
                        strokeWidth={1.2}
                        strokeDasharray="5 3"
                        initial={{ pathLength: 0, opacity: 0 }}
                        animate={{ pathLength: 1, opacity: 0.7 }}
                        transition={{ duration: 0.5 }}
                      />
                      <motion.text
                        x={(colPositions[0] + colW / 2 + dotCx) / 2}
                        y={railY + colH / 2 + 36}
                        textAnchor="middle"
                        fill="#F5C542"
                        fontSize={8}
                        fontFamily="ui-monospace,monospace"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 0.8 }}
                        transition={{ delay: 0.3, duration: 0.4 }}
                      >
                        trigger_with_result()
                      </motion.text>
                    </g>
                  )}
                </svg>

                {/* Handler hover tooltip */}
                <AnimatePresence>
                  {hoveredHandler !== null && sorted[hoveredHandler] && (
                    <motion.div
                      initial={{ opacity: 0, y: -4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.15 }}
                      className="mt-2 px-3 py-2 rounded-lg border border-white/[0.08] bg-[#0A0F1A] text-xs font-mono"
                    >
                      <span style={{ color: sorted[hoveredHandler].color }} className="font-bold">{sorted[hoveredHandler].name}</span>
                      <span className="text-white/30 ml-2">P{sorted[hoveredHandler].p}</span>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </div>
        </ScrollReveal>

        {/* 4. Version Timeline */}
        <ScrollReveal delay={0.15}>
          <div className="flex justify-center mb-10">
            <svg viewBox="0 0 520 70" className="w-full max-w-[500px]">
              {versions.map((v, i) => {
                const x = 40 + i * 140;
                const nextX = i < versions.length - 1 ? 40 + (i + 1) * 140 : null;
                return (
                  <g key={v.ver} onMouseEnter={() => setHoveredVersion(i)} onMouseLeave={() => setHoveredVersion(null)} style={{ cursor: "pointer" }}>
                    {/* Connecting arc */}
                    {nextX && (
                      <path d={`M ${x + 8} 30 Q ${(x + nextX) / 2} 18 ${nextX - 8} 30`} fill="none" stroke="white" strokeOpacity={0.08} strokeWidth={1} />
                    )}
                    {/* Dot */}
                    <circle cx={x} cy={30} r={6} fill={hoveredVersion === i ? "#4ECDC4" : "#1E293B"} stroke="#4ECDC4" strokeWidth={1} strokeOpacity={hoveredVersion === i ? 0.8 : 0.3} />
                    {/* Version label */}
                    <text x={x} y={14} textAnchor="middle" fill="white" fillOpacity={0.5} fontSize={9} fontFamily="ui-monospace,monospace" fontWeight={600}>{v.ver}</text>
                    {/* Count */}
                    <text x={x} y={50} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={8} fontFamily="ui-monospace,monospace">({v.count})</text>
                  </g>
                );
              })}
            </svg>
          </div>
          {/* Version hover annotation */}
          <AnimatePresence>
            {hoveredVersion !== null && versions[hoveredVersion] && (
              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-center text-xs text-[#A0B4D4] font-mono -mt-6 mb-6"
              >
                {t(locale, versions[hoveredVersion].descKo, versions[hoveredVersion].descEn)}
              </motion.p>
            )}
          </AnimatePresence>
        </ScrollReveal>

        {/* 5. Design Decisions (collapsible) */}
        <ScrollReveal delay={0.2}>
          <button
            onClick={() => setShowDecisions(!showDecisions)}
            className="text-xs font-mono font-bold text-white/40 hover:text-white/60 border border-white/[0.06] rounded-lg px-4 py-2 mb-4 transition-colors"
          >
            {showDecisions ? "▾" : "▸"} {t(locale, "설계 결정과 트레이드오프", "Design Decisions & Trade-offs")}
          </button>
          <AnimatePresence>
            {showDecisions && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {decisions.map((d) => (
                    <div key={d.title} className="rounded-lg border px-4 py-3" style={{ borderColor: `${d.color}25`, background: `${d.color}06` }}>
                      <p className="text-xs font-bold mb-1" style={{ color: d.color }}>{d.title}</p>
                      <p className="text-[11px] text-[#A0B4D4] leading-relaxed">{t(locale, d.ko, d.en)}</p>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </ScrollReveal>
      </div>
    </section>
  );
}
