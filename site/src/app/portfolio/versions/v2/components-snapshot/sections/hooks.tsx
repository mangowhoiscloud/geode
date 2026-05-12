"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";

/* ── Maturity Levels ── */
const levels = [
  {
    id: "L1", name: "OBSERVE", color: "#60A5FA",
    desc: "기록만, 상태 변경 없음",
    handlers: [
      { name: "TaskGraphBridge", priority: "P30", events: "NODE_ENTER/EXIT/ERROR" },
      { name: "StuckDetector", priority: "P40", events: "PIPELINE_START/END/ERROR" },
      { name: "RunLog", priority: "P50", events: "ALL 45 events → JSONL" },
      { name: "LLM Lifecycle", priority: "P55", events: "LLM_CALL_START/END" },
      { name: "JournalHook", priority: "P60", events: "END/ERROR → runs.jsonl" },
      { name: "TableLoggers ×5", priority: "P90", events: "Automation events" },
    ],
    status: "complete",
  },
  {
    id: "L2", name: "REACT", color: "#4ECDC4",
    desc: "이벤트에 자동 반응, 상태 변경",
    handlers: [
      { name: "drift_pipeline_trigger", priority: "P70", events: "DRIFT → 재분석 트리거" },
      { name: "drift_auto_snapshot", priority: "P80", events: "DRIFT → 상태 캡처" },
      { name: "pipeline_end_snapshot", priority: "P80", events: "PIPELINE_END → 스냅샷" },
      { name: "turn_auto_memory", priority: "P85", events: "TURN_COMPLETE → 인사이트 저장" },
      { name: "memory_write_back", priority: "P85", events: "PIPELINE_END → MEMORY.md" },
    ],
    status: "frontier",
  },
  {
    id: "L3", name: "DECIDE", color: "#F5C542",
    desc: "Hook이 행동 방향을 결정",
    handlers: [
      { name: "context_action", priority: "P50", events: "CONTEXT_CRITICAL → 압축 전략 위임" },
      { name: "session_start", priority: "—", events: "SESSION_START → 동적 프롬프트 보강" },
    ],
    status: "partial",
  },
  {
    id: "L4", name: "AUTONOMY", color: "#C084FC",
    desc: "패턴에서 규칙을 자율 학습",
    handlers: [
      { name: "tool-approval", priority: "—", events: "HITL 승인 이력 → 자동 승인 룰 학습" },
      { name: "model-switched", priority: "—", events: "전환 사유 기록 → 자동 전환 정책" },
      { name: "filesystem-plugin", priority: "—", events: ".geode/hooks/ 자동 발견 + 등록" },
    ],
    status: "planned",
  },
];

/* ── Coverage Matrix (45 events × 4 levels) ── */
const coverageRows = [
  { group: "Pipeline", count: 3, L1: "5 handlers", L2: "2 handlers", L3: "—", L4: "—" },
  { group: "Node", count: 4, L1: "2 handlers", L2: "—", L3: "—", L4: "—" },
  { group: "Analysis", count: 3, L1: "RunLog", L2: "—", L3: "—", L4: "—" },
  { group: "Verification", count: 2, L1: "RunLog", L2: "—", L3: "—", L4: "—" },
  { group: "Automation", count: 5, L1: "6 handlers", L2: "2 handlers", L3: "—", L4: "—" },
  { group: "Turn", count: 1, L1: "RunLog", L2: "AutoMemory", L3: "—", L4: "—" },
  { group: "SubAgent", count: 3, L1: "2 handlers", L2: "—", L3: "—", L4: "—" },
  { group: "Context", count: 3, L1: "RunLog", L2: "—", L3: "○ planned", L4: "—" },
  { group: "Gateway", count: 2, L1: "—", L2: "—", L3: "—", L4: "—" },
  { group: "MCP", count: 2, L1: "RunLog", L2: "—", L3: "—", L4: "—" },
  { group: "Tool Recovery", count: 3, L1: "RunLog", L2: "—", L3: "—", L4: "—" },
  { group: "Memory", count: 4, L1: "—", L2: "—", L3: "—", L4: "—" },
  { group: "Prompt", count: 2, L1: "RunLog", L2: "—", L3: "—", L4: "—" },
  { group: "LLM", count: 2, L1: "Lifecycle", L2: "—", L3: "—", L4: "—" },
  { group: "Tool Approval", count: 3, L1: "Tracker", L2: "—", L3: "—", L4: "○ planned" },
  { group: "Session", count: 2, L1: "Logger", L2: "—", L3: "—", L4: "—" },
];

/* ── Event sources for architecture SVG ── */
const eventSources = [
  { label: "StateGraph", sub: "NODE_*", color: "#4ECDC4", y: 30 },
  { label: "AgenticLoop", sub: "TURN_*", color: "#F4B8C8", y: 75 },
  { label: "PromptAsm", sub: "PROMPT_*", color: "#818CF8", y: 120 },
  { label: "Automation", sub: "DRIFT/TRIGGER", color: "#F5C542", y: 165 },
  { label: "SubAgent", sub: "SUBAGENT_*", color: "#C084FC", y: 210 },
  { label: "Gateway", sub: "GATEWAY_*", color: "#60A5FA", y: 255 },
];

const handlerChain = [
  { label: "P30", name: "TaskBridge", color: "#60A5FA", y: 30 },
  { label: "P40", name: "StuckDetect", color: "#60A5FA", y: 65 },
  { label: "P50", name: "RunLog", color: "#60A5FA", y: 100 },
  { label: "P60", name: "Journal", color: "#60A5FA", y: 135 },
  { label: "P70", name: "DriftTrigger", color: "#4ECDC4", y: 170 },
  { label: "P80", name: "Snapshot", color: "#4ECDC4", y: 205 },
  { label: "P85", name: "AutoMemory", color: "#4ECDC4", y: 240 },
  { label: "P90", name: "TableLog", color: "#60A5FA", y: 275 },
];

const statusLabel: Record<string, { text: string; color: string }> = {
  complete: { text: "COMPLETE", color: "#34D399" },
  frontier: { text: "FRONTIER", color: "#4ECDC4" },
  partial: { text: "PARTIAL", color: "#F5C542" },
  planned: { text: "PLANNED", color: "#C084FC" },
};

/* ── Hook Architecture SVG ── */
function HookArchitectureDiagram() {
  const W = 780;
  const H = 310;
  const SRC_X = 80;
  const HUB_X = 340;
  const CHAIN_X = 600;

  return (
    <div className="w-full overflow-x-auto -mx-4 px-4 pb-2 mb-10">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[600px]" style={{ maxHeight: 350 }}>
        {/* Column labels */}
        <text x={SRC_X} y={16} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>Event Sources</text>
        <text x={HUB_X} y={16} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>HookSystem</text>
        <text x={CHAIN_X} y={16} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>Handler Chain</text>

        {/* Event source boxes */}
        {eventSources.map((s) => (
          <g key={s.label}>
            <rect x={SRC_X - 55} y={s.y} width={110} height={36} rx={8} fill="#0A0F1A" stroke={s.color} strokeWidth={0.7} strokeOpacity={0.2} />
            <text x={SRC_X} y={s.y + 15} textAnchor="middle" fill={s.color} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>{s.label}</text>
            <text x={SRC_X} y={s.y + 28} textAnchor="middle" fill={s.color} fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">{s.sub}</text>
            {/* Arrow to hub */}
            <line x1={SRC_X + 55} y1={s.y + 18} x2={HUB_X - 60} y2={H / 2} stroke={s.color} strokeOpacity={0.14} strokeWidth={1} />
          </g>
        ))}

        {/* HookSystem hub */}
        <rect x={HUB_X - 55} y={H / 2 - 35} width={110} height={70} rx={12} fill="#0A0F1A" stroke="#4ECDC4" strokeWidth={1.2} strokeOpacity={0.25} />
        <text x={HUB_X} y={H / 2 - 10} textAnchor="middle" fill="#4ECDC4" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>HookSystem</text>
        <text x={HUB_X} y={H / 2 + 6} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">register()</text>
        <text x={HUB_X} y={H / 2 + 20} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">trigger()</text>

        {/* Hub to handler chain arrows */}
        {handlerChain.map((h) => (
          <line key={h.label} x1={HUB_X + 55} y1={H / 2} x2={CHAIN_X - 70} y2={h.y + 14} stroke={h.color} strokeOpacity={0.12} strokeWidth={1} />
        ))}

        {/* Handler chain (priority sorted) */}
        {handlerChain.map((h, i) => (
          <g key={h.label}>
            <rect x={CHAIN_X - 65} y={h.y} width={130} height={28} rx={6} fill="#0A0F1A" stroke={h.color} strokeWidth={0.6} strokeOpacity={0.15} />
            <text x={CHAIN_X - 48} y={h.y + 18} fill={h.color} fillOpacity={0.5} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>{h.label}</text>
            <text x={CHAIN_X + 10} y={h.y + 18} fill="white" fillOpacity={0.5} fontSize={9} fontFamily="ui-monospace, monospace">{h.name}</text>
            {/* Maturity indicator */}
            <circle cx={CHAIN_X + 58} cy={h.y + 14} r={3} fill={h.color} fillOpacity={0.3} />
            {/* Chain connector */}
            {i < handlerChain.length - 1 && (
              <line x1={CHAIN_X} y1={h.y + 28} x2={CHAIN_X} y2={handlerChain[i + 1].y} stroke="white" strokeOpacity={0.04} strokeWidth={1} strokeDasharray="2 3" />
            )}
          </g>
        ))}

        {/* L1/L2 boundary label */}
        <line x1={CHAIN_X - 70} y1={153} x2={CHAIN_X + 68} y2={153} stroke="#4ECDC4" strokeOpacity={0.18} strokeWidth={1} strokeDasharray="4 4" />
        <text x={CHAIN_X + 72} y={157} fill="#4ECDC4" fillOpacity={0.25} fontSize={8} fontFamily="ui-monospace, monospace">L2 ↑</text>
        <text x={CHAIN_X + 72} y={145} fill="#60A5FA" fillOpacity={0.25} fontSize={8} fontFamily="ui-monospace, monospace">L1 ↓</text>
      </svg>
    </div>
  );
}

export function HooksSection() {
  const [activeLevel, setActiveLevel] = useState(1);

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#4ECDC4]/60 uppercase tracking-[0.25em] mb-3">
            Hook System
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-2">
            이벤트 기반 리플 패턴
          </h2>
          <p className="text-lg sm:text-xl text-white/50 font-semibold mb-4">
            45 Events × 4 Maturity
          </p>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-10 leading-relaxed">
            6개 이벤트 소스에서 발생한 45개 이벤트가 HookSystem을 거쳐
            우선순위 순으로 정렬된 핸들러 체인을 관통합니다.
            하나의 이벤트가 L1(관측)과 L2(반응)를 동시에 지나가는 것이 리플 패턴입니다.
          </p>
        </ScrollReveal>

        {/* ── Architecture Diagram: Sources → HookSystem → Handler Chain ── */}
        <ScrollReveal delay={0.1}>
          <HookArchitectureDiagram />
        </ScrollReveal>

        {/* ── Maturity Level Selector ── */}
        <ScrollReveal delay={0.15}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
            {levels.map((lv, i) => {
              const isActive = activeLevel === i;
              const st = statusLabel[lv.status];
              return (
                <button
                  key={lv.id}
                  onClick={() => setActiveLevel(i)}
                  className="text-left px-4 py-3 rounded-xl border transition-all duration-300"
                  style={{
                    borderColor: isActive ? `${lv.color}30` : "rgba(255,255,255,0.04)",
                    background: isActive ? `${lv.color}08` : "transparent",
                  }}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-mono font-bold" style={{ color: lv.color }}>{lv.id}</span>
                    <span className="text-sm font-semibold text-white/80">{lv.name}</span>
                  </div>
                  <div className="text-xs text-[#7A8CA8] mb-2">{lv.desc}</div>
                  <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded" style={{ color: st.color, background: `${st.color}15` }}>
                    {st.text}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Handler list */}
          <div className="space-y-2 mb-6">
            {levels[activeLevel].handlers.map((h) => (
              <div key={h.name} className="flex items-center gap-4 px-4 py-2.5 rounded-lg border border-white/[0.04]" style={{ background: `${levels[activeLevel].color}03` }}>
                <span className="shrink-0 w-10 text-center text-[11px] font-mono font-bold" style={{ color: levels[activeLevel].color }}>{h.priority}</span>
                <span className="text-sm font-medium text-white/80 w-[160px] shrink-0">{h.name}</span>
                <span className="text-sm text-[#7A8CA8]">{h.events}</span>
              </div>
            ))}
          </div>
        </ScrollReveal>

        {/* ── Coverage Matrix ── */}
        <ScrollReveal delay={0.2}>
          <p className="text-sm font-mono font-bold text-[#818CF8]/60 uppercase tracking-[0.25em] mb-4">
            Coverage Matrix
          </p>
          <p className="text-sm text-[#7A8CA8] mb-5">
            45개 이벤트 × 4 성숙도 레벨. 빈 칸은 아직 핸들러가 없는 확장 가능 영역입니다.
          </p>
          <div className="overflow-x-auto -mx-4 px-4">
            <table className="w-full text-xs font-mono border-collapse min-w-[540px]">
              <thead>
                <tr>
                  <th className="text-left py-2 px-3 text-[#7A8CA8] font-semibold border-b border-white/[0.06]">이벤트 그룹</th>
                  <th className="text-center py-2 px-2 border-b border-white/[0.06]" style={{ color: "#60A5FA" }}>L1</th>
                  <th className="text-center py-2 px-2 border-b border-white/[0.06]" style={{ color: "#4ECDC4" }}>L2</th>
                  <th className="text-center py-2 px-2 border-b border-white/[0.06]" style={{ color: "#F5C542" }}>L3</th>
                  <th className="text-center py-2 px-2 border-b border-white/[0.06]" style={{ color: "#C084FC" }}>L4</th>
                </tr>
              </thead>
              <tbody>
                {coverageRows.map((r) => (
                  <tr key={r.group} className="border-b border-white/[0.03] hover:bg-white/[0.01] transition-colors">
                    <td className="py-2 px-3 text-white/60">
                      {r.group} <span className="text-white/20">({r.count})</span>
                    </td>
                    {[r.L1, r.L2, r.L3, r.L4].map((cell, ci) => {
                      const colors = ["#60A5FA", "#4ECDC4", "#F5C542", "#C084FC"];
                      const isActive = cell !== "—";
                      const isPlanned = cell.includes("planned");
                      return (
                        <td key={ci} className="text-center py-2 px-2">
                          {isActive ? (
                            <span style={{ color: isPlanned ? `${colors[ci]}60` : `${colors[ci]}90`, fontSize: 10 }}>
                              {isPlanned ? "○" : "✓"} {cell.replace("○ planned", "")}
                            </span>
                          ) : (
                            <span className="text-white/10">—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
