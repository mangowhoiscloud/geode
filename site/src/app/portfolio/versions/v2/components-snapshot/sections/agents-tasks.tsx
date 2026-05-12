"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";

/* ── SubAgent System ── */
const subAgentSpecs = [
  { label: "Max Concurrent", value: "5", color: "#4ECDC4" },
  { label: "Max Depth", value: "2", color: "#818CF8" },
  { label: "Max Total", value: "15", color: "#C084FC" },
  { label: "Timeout", value: "120s", color: "#F5C542" },
  { label: "Max Rounds", value: "10", color: "#34D399" },
  { label: "Max Tokens", value: "8192", color: "#60A5FA" },
];

/* ── Task DAG nodes ── */
const taskNodes = [
  { id: "router", label: "Router", color: "#4ECDC4", col: 0 },
  { id: "signals", label: "Signals", color: "#F5C542", col: 1 },
  { id: "analyst_gm", label: "Game\nMech", color: "#818CF8", col: 2, row: 0 },
  { id: "analyst_pe", label: "Player\nExp", color: "#818CF8", col: 2, row: 1 },
  { id: "analyst_gp", label: "Growth", color: "#818CF8", col: 2, row: 2 },
  { id: "analyst_d", label: "Discovery", color: "#818CF8", col: 2, row: 3 },
  { id: "evaluators", label: "Evaluators", color: "#C084FC", col: 3 },
  { id: "scoring", label: "Scoring\n+PSM", color: "#F5C542", col: 4 },
  { id: "verify", label: "Verify\n+Cross", color: "#34D399", col: 5 },
  { id: "synthesis", label: "Synthesis\n+Report", color: "#F4B8C8", col: 6 },
];

/* ── PlanMode lifecycle ── */
const planStates = ["DRAFT", "PRESENTED", "APPROVED", "EXECUTING", "COMPLETED"];

/* ── Tabs ── */
type Tab = "subagent" | "taskgraph" | "planmode";

export function AgentsTasksSection() {
  const [activeTab, setActiveTab] = useState<Tab>("subagent");

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#C084FC]/60 uppercase tracking-[0.25em] mb-3">
            Orchestration
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-3">
            SubAgent · TaskGraph · PlanMode
          </h2>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-8 leading-relaxed">
            병렬 에이전트 위임(SubAgent), 의존성 기반 작업 DAG(TaskGraph),
            실행 전 계획 승인(PlanMode) — 세 시스템이 연동하여 복잡한 작업을 분할·병렬·검증합니다.
          </p>
        </ScrollReveal>

        {/* ── Tab bar ── */}
        <ScrollReveal delay={0.05}>
          <div className="flex gap-2 mb-8 flex-wrap">
            {([
              { id: "subagent" as Tab, label: "SubAgent", sub: "병렬 위임", color: "#4ECDC4" },
              { id: "taskgraph" as Tab, label: "TaskGraph", sub: "DAG 추적", color: "#818CF8" },
              { id: "planmode" as Tab, label: "PlanMode", sub: "계획 → 실행", color: "#F5C542" },
            ]).map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className="px-4 py-2 rounded-lg text-xs font-mono font-bold transition-all duration-300"
                style={{
                  color: activeTab === t.id ? t.color : "#5A6A8A",
                  background: activeTab === t.id ? `${t.color}08` : "transparent",
                  border: `1px solid ${activeTab === t.id ? `${t.color}20` : "rgba(255,255,255,0.04)"}`,
                }}
              >
                {t.label}
                <span className="ml-2 text-[10px] opacity-50">{t.sub}</span>
              </button>
            ))}
          </div>
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          {/* ── SubAgent Tab ── */}
          {activeTab === "subagent" && (
            <div>
              {/* Spawn → Execute → Announce flow diagram */}
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 760 200" className="w-full min-w-[580px]" style={{ maxHeight: 230 }}>
                  {/* Parent agent */}
                  <rect x={20} y={70} width={120} height={60} rx={10} fill="#0A0F1A" stroke="#F4B8C8" strokeWidth={1} strokeOpacity={0.3} />
                  <text x={80} y={93} textAnchor="middle" fill="#F4B8C8" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>Parent</text>
                  <text x={80} y={110} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.4} fontSize={9} fontFamily="ui-monospace, monospace">AgenticLoop</text>

                  {/* Spawn arrows → 3 children */}
                  <text x={170} y={80} fill="#4ECDC4" fillOpacity={0.3} fontSize={9} fontFamily="ui-monospace, monospace">delegate()</text>
                  {[40, 100, 160].map((y, i) => (
                    <g key={`spawn-${i}`}>
                      <path d={`M 140,100 C 180,100 190,${y} 230,${y}`} fill="none" stroke="#4ECDC4" strokeOpacity={0.15} strokeWidth={1} strokeDasharray="4 3" className="animate-flow" />
                    </g>
                  ))}

                  {/* Sub agents (3 parallel) */}
                  {[
                    { y: 30, label: "Sub-A", task: "analyze" },
                    { y: 90, label: "Sub-B", task: "search" },
                    { y: 150, label: "Sub-C", task: "compare" },
                  ].map((sa) => (
                    <g key={sa.label}>
                      <rect x={230} y={sa.y} width={100} height={44} rx={8} fill="#0A0F1A" stroke="#4ECDC4" strokeWidth={0.8} strokeOpacity={0.2} />
                      <text x={280} y={sa.y + 18} textAnchor="middle" fill="#4ECDC4" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>{sa.label}</text>
                      <text x={280} y={sa.y + 32} textAnchor="middle" fill="#5A6A8A" fontSize={8} fontFamily="ui-monospace, monospace">{sa.task}</text>
                    </g>
                  ))}

                  {/* IsolatedRunner box */}
                  <rect x={220} y={15} width={120} height={190} rx={12} fill="none" stroke="#4ECDC4" strokeOpacity={0.12} strokeWidth={1} strokeDasharray="6 4" />
                  <text x={280} y={10} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.30} fontSize={8} fontFamily="ui-monospace, monospace">IsolatedRunner (threads)</text>

                  {/* Execute arrows → Results */}
                  {[40, 100, 160].map((y, i) => (
                    <g key={`exec-${i}`}>
                      <line x1={330} y1={y + 10} x2={395} y2={y + 10} stroke="#34D399" strokeOpacity={0.12} strokeWidth={1} />
                      <text x={362} y={y + 3} fill="#34D399" fillOpacity={0.30} fontSize={7}>✓</text>
                    </g>
                  ))}

                  {/* SubAgentResult boxes */}
                  {[
                    { y: 30, status: "ok", score: "82.2 S" },
                    { y: 90, status: "ok", score: "12 results" },
                    { y: 150, status: "ok", score: "3 matches" },
                  ].map((r, i) => (
                    <g key={`result-${i}`}>
                      <rect x={395} y={r.y} width={90} height={44} rx={8} fill="#0A0F1A" stroke="#34D399" strokeWidth={0.6} strokeOpacity={0.2} />
                      <text x={440} y={r.y + 18} textAnchor="middle" fill="#34D399" fillOpacity={0.7} fontSize={9} fontFamily="ui-monospace, monospace">{r.status}</text>
                      <text x={440} y={r.y + 32} textAnchor="middle" fill="#5A6A8A" fontSize={8} fontFamily="ui-monospace, monospace">{r.score}</text>
                    </g>
                  ))}

                  {/* Announce arrows → queue */}
                  <text x={520} y={65} fill="#F5C542" fillOpacity={0.3} fontSize={9} fontFamily="ui-monospace, monospace">announce</text>
                  {[40, 100, 160].map((y, i) => (
                    <path key={`ann-${i}`} d={`M 485,${y + 10} C 530,${y + 10} 540,100 570,100`} fill="none" stroke="#F5C542" strokeOpacity={0.12} strokeWidth={1} strokeDasharray="3 3" className="animate-flow" />
                  ))}

                  {/* Announce queue */}
                  <rect x={570} y={75} width={80} height={50} rx={8} fill="#0A0F1A" stroke="#F5C542" strokeWidth={0.8} strokeOpacity={0.25} />
                  <text x={610} y={95} textAnchor="middle" fill="#F5C542" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Queue</text>
                  <text x={610} y={110} textAnchor="middle" fill="#F5C542" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">announce_queue</text>

                  {/* Drain arrow back to parent */}
                  <path d="M 650,100 C 680,100 700,100 720,100 C 740,100 740,140 720,150 L 140,150 L 140,120" fill="none" stroke="#F4B8C8" strokeOpacity={0.18} strokeWidth={1} strokeDasharray="4 4" className="animate-flow" />
                  <text x={700} y={88} fill="#F4B8C8" fillOpacity={0.25} fontSize={8} fontFamily="ui-monospace, monospace">drain</text>
                  <text x={180} y={162} fill="#F4B8C8" fillOpacity={0.30} fontSize={8} fontFamily="ui-monospace, monospace">→ 대화 컨텍스트 주입</text>
                </svg>
              </div>

              {/* Spec numbers */}
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 sm:gap-3 mb-6">
                {subAgentSpecs.map((s) => (
                  <div key={s.label} className="text-center px-2 py-3 rounded-xl border border-white/[0.04]" style={{ background: `${s.color}04` }}>
                    <div className="text-lg sm:text-xl font-bold" style={{ color: s.color }}>{s.value}</div>
                    <div className="text-[10px] sm:text-xs text-[#7A8CA8] font-mono mt-1">{s.label}</div>
                  </div>
                ))}
              </div>

              {/* Inheritance detail */}
              <div className="flex flex-wrap gap-1.5">
                {["Full Inheritance", "Deny List (7 tools)", "Read-Only Memory", "Token Guard (P2-A)", "Spawn+Announce"].map((t) => (
                  <span key={t} className="px-2 py-0.5 rounded text-[11px] font-mono text-[#4ECDC4]/70 bg-[#4ECDC4]/06 border border-[#4ECDC4]/12">{t}</span>
                ))}
              </div>
            </div>
          )}

          {/* ── TaskGraph Tab — Two separate visualizations ── */}
          {activeTab === "taskgraph" && (
            <div className="space-y-8">
              {/* 1. Pipeline DAG (Game IP Value Inference) */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#818CF8]/10 text-[#818CF8]/80 border border-[#818CF8]/15">PIPELINE</span>
                  <span className="text-sm font-semibold text-white/80">TaskGraph — Game IP 가치추론</span>
                </div>
                <div className="overflow-x-auto -mx-4 px-4 pb-2">
                  <svg viewBox="0 0 740 200" className="w-full min-w-[600px]" style={{ maxHeight: 230 }}>
                    <g stroke="white" strokeOpacity={0.14} strokeWidth={1} fill="none">
                      <line x1={70} y1={100} x2={145} y2={100} />
                      {[40, 80, 120, 160].map((y) => (
                        <path key={y} d={`M170,100 C200,100 210,${y} 250,${y}`} />
                      ))}
                      {[40, 80, 120, 160].map((y) => (
                        <path key={`e${y}`} d={`M310,${y} C340,${y} 350,100 380,100`} />
                      ))}
                      <line x1={440} y1={100} x2={495} y2={100} />
                      <line x1={560} y1={100} x2={615} y2={100} />
                    </g>
                    {[
                      { x: 50, y: 100, label: "Router", color: "#4ECDC4" },
                      { x: 155, y: 100, label: "Signals", color: "#F5C542" },
                    ].map((n) => (
                      <g key={n.label}>
                        <circle cx={n.x} cy={n.y} r={18} fill="#0A0F1A" stroke={n.color} strokeWidth={0.8} strokeOpacity={0.3} />
                        <text x={n.x} y={n.y + 1} textAnchor="middle" dominantBaseline="central" fill={n.color} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>{n.label}</text>
                      </g>
                    ))}
                    {["Mech", "Exp", "Growth", "Disc"].map((l, i) => (
                      <g key={l}>
                        <circle cx={280} cy={40 + i * 40} r={16} fill="#0A0F1A" stroke="#818CF8" strokeWidth={0.6} strokeOpacity={0.25} />
                        <text x={280} y={41 + i * 40} textAnchor="middle" dominantBaseline="central" fill="#818CF8" fillOpacity={0.7} fontSize={8} fontFamily="ui-monospace, monospace">{l}</text>
                      </g>
                    ))}
                    {[
                      { x: 410, y: 100, label: "Eval ×3", color: "#C084FC" },
                      { x: 530, y: 100, label: "Score", color: "#F5C542" },
                      { x: 650, y: 100, label: "Verify", color: "#34D399" },
                    ].map((n) => (
                      <g key={n.label}>
                        <circle cx={n.x} cy={n.y} r={18} fill="#0A0F1A" stroke={n.color} strokeWidth={0.8} strokeOpacity={0.3} />
                        <text x={n.x} y={n.y + 1} textAnchor="middle" dominantBaseline="central" fill={n.color} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>{n.label}</text>
                      </g>
                    ))}
                    <text x={280} y={12} textAnchor="middle" fill="#818CF8" fillOpacity={0.25} fontSize={9} fontFamily="ui-monospace, monospace">fan-out ×4</text>
                    <text x={410} y={12} textAnchor="middle" fill="#C084FC" fillOpacity={0.25} fontSize={9} fontFamily="ui-monospace, monospace">fan-in</text>
                  </svg>
                </div>
                <p className="text-sm text-[#8B9CC0] leading-relaxed mt-2">
                  TaskGraphHookBridge가 LangGraph NODE_ENTER/EXIT/ERROR를 수신하여 ~13개 Task 상태를 자동 갱신합니다. 실패 시 하류 Task를 자동 SKIP합니다.
                </p>
              </div>

              {/* 2. Agentic Loop Task System */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#4ECDC4]/10 text-[#4ECDC4]/80 border border-[#4ECDC4]/15">AGENTIC</span>
                  <span className="text-sm font-semibold text-white/80">TaskGraph — Agentic Loop Task System</span>
                </div>
                <div className="overflow-x-auto -mx-4 px-4 pb-2">
                  <svg viewBox="0 0 700 180" className="w-full min-w-[540px]" style={{ maxHeight: 210 }}>
                    {/* User request */}
                    <rect x={20} y={60} width={110} height={50} rx={10} fill="#0A0F1A" stroke="#F4B8C8" strokeWidth={0.8} strokeOpacity={0.25} />
                    <text x={75} y={80} textAnchor="middle" fill="#F4B8C8" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>User Request</text>
                    <text x={75} y={95} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">복합 요청</text>

                    {/* Arrow */}
                    <line x1={130} y1={85} x2={180} y2={85} stroke="white" strokeOpacity={0.14} strokeWidth={1} />

                    {/* GoalDecomposer */}
                    <rect x={180} y={55} width={130} height={60} rx={10} fill="#0A0F1A" stroke="#818CF8" strokeWidth={1} strokeOpacity={0.3} />
                    <text x={245} y={78} textAnchor="middle" fill="#818CF8" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>GoalDecomposer</text>
                    <text x={245} y={95} textAnchor="middle" fill="#818CF8" fillOpacity={0.35} fontSize={8} fontFamily="ui-monospace, monospace">분해 → sub-goals</text>

                    {/* Fan-out to tasks */}
                    {[35, 85, 135].map((y, i) => (
                      <g key={`task-${i}`}>
                        <path d={`M310,85 C340,85 350,${y} 380,${y}`} fill="none" stroke="#4ECDC4" strokeOpacity={0.18} strokeWidth={1} />
                        <rect x={380} y={y - 18} width={100} height={36} rx={8} fill="#0A0F1A" stroke="#4ECDC4" strokeWidth={0.6} strokeOpacity={0.2} />
                        <text x={430} y={y - 2} textAnchor="middle" fill="#4ECDC4" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>
                          {["Task A", "Task B", "Task C"][i]}
                        </text>
                        <text x={430} y={y + 12} textAnchor="middle" fill="#5A6A8A" fontSize={8} fontFamily="ui-monospace, monospace">
                          {["RUNNING", "READY", "PENDING"][i]}
                        </text>
                      </g>
                    ))}

                    {/* CLI /tasks */}
                    <rect x={530} y={55} width={80} height={60} rx={10} fill="#0A0F1A" stroke="#F5C542" strokeWidth={0.7} strokeOpacity={0.2} />
                    <text x={570} y={78} textAnchor="middle" fill="#F5C542" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>/tasks</text>
                    <text x={570} y={95} textAnchor="middle" fill="#F5C542" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">CLI 조회</text>

                    {/* Connection */}
                    {[35, 85, 135].map((y, i) => (
                      <line key={`conn-${i}`} x1={480} y1={y} x2={530} y2={85} stroke="#F5C542" strokeOpacity={0.12} strokeWidth={1} />
                    ))}

                    {/* ContextVar label */}
                    <text x={430} y={168} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.30} fontSize={9} fontFamily="ui-monospace, monospace">
                      세션별 ContextVar — 독립 TaskGraph
                    </text>

                    {/* Dependency arrows between tasks */}
                    <path d="M430,53 L430,67" stroke="white" strokeOpacity={0.12} strokeWidth={1} strokeDasharray="2 3" />
                    <path d="M430,103 L430,117" stroke="white" strokeOpacity={0.12} strokeWidth={1} strokeDasharray="2 3" />
                  </svg>
                </div>
                <p className="text-sm text-[#8B9CC0] leading-relaxed mt-2">
                  GoalDecomposer가 복합 요청을 sub-goal로 분해하고, 세션별 ContextVar에 독립 TaskGraph를 생성합니다. CLI /tasks로 실시간 상태를 조회할 수 있습니다.
                </p>
              </div>
            </div>
          )}

          {/* ── PlanMode Tab ── */}
          {activeTab === "planmode" && (
            <div>
              {/* PlanMode lifecycle SVG */}
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 760 200" className="w-full min-w-[560px]" style={{ maxHeight: 230 }}>
                  {/* Planner (route selection) */}
                  <rect x={20} y={60} width={100} height={60} rx={10} fill="#0A0F1A" stroke="#60A5FA" strokeWidth={1} strokeOpacity={0.3} />
                  <text x={70} y={83} textAnchor="middle" fill="#60A5FA" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>Planner</text>
                  <text x={70} y={100} textAnchor="middle" fill="#60A5FA" fillOpacity={0.35} fontSize={8} fontFamily="ui-monospace, monospace">route 선택</text>

                  <line x1={120} y1={90} x2={160} y2={90} stroke="white" strokeOpacity={0.14} strokeWidth={1} />

                  {/* Plan lifecycle states */}
                  {[
                    { label: "DRAFT", x: 190, color: "#5A6A8A" },
                    { label: "PRESENT", x: 290, color: "#818CF8" },
                    { label: "APPROVE", x: 390, color: "#F5C542" },
                    { label: "EXECUTE", x: 490, color: "#4ECDC4" },
                    { label: "COMPLETE", x: 590, color: "#34D399" },
                  ].map((s, i) => (
                    <g key={s.label}>
                      <rect x={s.x - 40} y={65} width={80} height={50} rx={8} fill="#0A0F1A" stroke={s.color} strokeWidth={0.8} strokeOpacity={0.25} />
                      <text x={s.x} y={85} textAnchor="middle" fill={s.color} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>{s.label}</text>
                      <text x={s.x} y={100} textAnchor="middle" fill={s.color} fillOpacity={0.3} fontSize={7} fontFamily="ui-monospace, monospace">
                        {["생성", "리뷰", "HITL 승인", "실행 중", "완료"][i]}
                      </text>
                      {i < 4 && (
                        <line x1={s.x + 40} y1={90} x2={[290, 390, 490, 590][i] - 40} y2={90} stroke="white" strokeOpacity={0.14} strokeWidth={1} />
                      )}
                    </g>
                  ))}

                  {/* REJECTED fork */}
                  <path d="M390,115 L390,150 L190,150 L190,115" fill="none" stroke="#E87080" strokeOpacity={0.18} strokeWidth={1} strokeDasharray="4 4" />
                  <text x={290} y={163} textAnchor="middle" fill="#E87080" fillOpacity={0.2} fontSize={8} fontFamily="ui-monospace, monospace">REJECTED → DRAFT로 복귀</text>

                  {/* Templates */}
                  <rect x={640} y={30} width={100} height={42} rx={8} fill="#0A0F1A" stroke="#F5C542" strokeWidth={0.6} strokeOpacity={0.2} />
                  <text x={690} y={48} textAnchor="middle" fill="#F5C542" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>full_pipeline</text>
                  <text x={690} y={62} textAnchor="middle" fill="#5A6A8A" fontSize={8} fontFamily="ui-monospace, monospace">10 steps · $1.50</text>

                  <rect x={640} y={80} width={100} height={42} rx={8} fill="#0A0F1A" stroke="#818CF8" strokeWidth={0.6} strokeOpacity={0.2} />
                  <text x={690} y={98} textAnchor="middle" fill="#818CF8" fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>prospect</text>
                  <text x={690} y={112} textAnchor="middle" fill="#5A6A8A" fontSize={8} fontFamily="ui-monospace, monospace">6 steps · $0.80</text>

                  {/* Connection to templates */}
                  <line x1={630} y1={90} x2={640} y2={51} stroke="#F5C542" strokeOpacity={0.14} strokeWidth={1} />
                  <line x1={630} y1={90} x2={640} y2={101} stroke="#818CF8" strokeOpacity={0.14} strokeWidth={1} />

                  {/* Top label */}
                  <text x={400} y={25} textAnchor="middle" fill="white" fillOpacity={0.18} fontSize={9} fontFamily="ui-monospace, monospace" letterSpacing="0.1em">
                    PLANNER → DRAFT → PRESENT → APPROVE(HITL) → EXECUTE → COMPLETE
                  </text>
                </svg>
              </div>

              <p className="text-sm text-[#8B9CC0] leading-relaxed">
                Planner가 요청을 6개 Route(FULL_PIPELINE, PROSPECT, PARTIAL_RERUN 등)로 분류하고,
                PlanMode가 DRAFT → PRESENTED → APPROVED(HITL) → EXECUTING → COMPLETED 생애주기를 관리합니다.
                REJECTED되면 DRAFT로 복귀합니다.
              </p>
            </div>
          )}
        </ScrollReveal>
      </div>
    </section>
  );
}
