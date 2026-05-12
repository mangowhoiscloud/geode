"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";

/* ── Schedule Types ── */
const scheduleTypes = [
  { id: "AT", color: "#E87080", desc: "일회성. 지정 시각에 한 번 실행 후 자동 삭제" },
  { id: "EVERY", color: "#4ECDC4", desc: "고정 간격. Anchor 기반 drift 방지" },
  { id: "CRON", color: "#818CF8", desc: "5-field cron. 분/시/일/월/요일" },
];

/* ── Trigger Types (F1-F4) ── */
const triggerTypes = [
  { id: "F1", name: "MANUAL", color: "#60A5FA", desc: "사용자가 직접 실행", dispatch: "fire_manual()" },
  { id: "F2", name: "SCHEDULED", color: "#818CF8", desc: "Cron 시간 기반", dispatch: "check_scheduled()" },
  { id: "F3", name: "EVENT", color: "#4ECDC4", desc: "HookEvent 반응 (DRIFT → 재분석)", dispatch: "make_event_handler()" },
  { id: "F4", name: "WEBHOOK", color: "#F5C542", desc: "외부 HTTP POST", dispatch: "handle_webhook()" },
];

/* ── Predefined Automations ── */
const predefined = [
  { name: "Weekly Discovery Scan", cron: "0 9 * * 1", type: "CRON", color: "#4ECDC4" },
  { name: "Calibration Drift Scan", cron: "0 6 * * *", type: "CRON", color: "#818CF8" },
  { name: "Outcome Tracker", cron: "0 0 1 * *", type: "CRON", color: "#C084FC" },
  { name: "Pending Analysis Worker", cron: "*/30 * * * *", type: "CRON", color: "#34D399" },
  { name: "Auto-Generate Report", cron: "event:pipeline_complete", type: "EVENT", color: "#F5C542" },
  { name: "Anomaly Detector", cron: "event:pipeline_complete", type: "EVENT", color: "#E87080" },
];

/* ── Drift → Trigger flow ── */
const driftFlow = [
  { step: "CUSUM Detector", detail: "4 metrics 모니터링 (Spearman, α, precision, tier)", color: "#E87080" },
  { step: "DRIFT_DETECTED", detail: "임계치 초과 → HookEvent 발화", color: "#F5C542" },
  { step: "P70 DriftTrigger", detail: "EVENT trigger → 재분석 파이프라인", color: "#4ECDC4" },
  { step: "P80 DriftSnapshot", detail: "SnapshotManager → 상태 캡처", color: "#818CF8" },
  { step: "P90 DriftLogger", detail: "구조화 로깅", color: "#60A5FA" },
];

type Tab = "scheduler" | "triggers" | "predefined";

export function AutomationSection() {
  const [activeTab, setActiveTab] = useState<Tab>("scheduler");

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#F5C542]/60 uppercase tracking-[0.25em] mb-3">
            Automation
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-3">
            Scheduler · Triggers · Drift
          </h2>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-8 leading-relaxed">
            시간 기반 스케줄(AT/EVERY/CRON), 이벤트 기반 트리거(F1-F4), 드리프트 감지 자동 재분석 —
            세 축이 연동하여 파이프라인을 자율적으로 운용합니다.
          </p>
        </ScrollReveal>

        {/* Tab bar */}
        <ScrollReveal delay={0.05}>
          <div className="flex gap-2 mb-8 flex-wrap">
            {([
              { id: "scheduler" as Tab, label: "SchedulerService", sub: "AT / EVERY / CRON", color: "#818CF8" },
              { id: "triggers" as Tab, label: "TriggerManager", sub: "F1-F4", color: "#4ECDC4" },
              { id: "predefined" as Tab, label: "Predefined", sub: "10 Templates", color: "#F5C542" },
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

        {/* ── Architecture SVG: Scheduler ↔ Trigger ↔ Hook ── */}
        <ScrollReveal delay={0.08}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-8">
            <svg viewBox="0 0 760 180" className="w-full min-w-[560px]" style={{ maxHeight: 210 }}>
              {/* SchedulerService */}
              <rect x={20} y={50} width={140} height={70} rx={10} fill="#0A0F1A" stroke="#818CF8" strokeWidth={1} strokeOpacity={0.3} />
              <text x={90} y={75} textAnchor="middle" fill="#818CF8" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>Scheduler</text>
              <text x={90} y={93} textAnchor="middle" fill="#818CF8" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">AT · EVERY · CRON</text>
              <text x={90} y={108} textAnchor="middle" fill="#5A6A8A" fontSize={8} fontFamily="ui-monospace, monospace">~/.geode/scheduler/</text>

              {/* Arrow: Scheduler → action_queue */}
              <line x1={160} y1={85} x2={220} y2={85} stroke="#818CF8" strokeOpacity={0.12} strokeWidth={1} />
              <text x={190} y={78} textAnchor="middle" fill="#818CF8" fillOpacity={0.2} fontSize={8} fontFamily="ui-monospace, monospace">enqueue</text>

              {/* action_queue */}
              <rect x={220} y={60} width={100} height={50} rx={8} fill="#0A0F1A" stroke="#F5C542" strokeWidth={0.8} strokeOpacity={0.25} />
              <text x={270} y={82} textAnchor="middle" fill="#F5C542" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>action_queue</text>
              <text x={270} y={97} textAnchor="middle" fill="#F5C542" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">prompt text</text>

              {/* Arrow: queue → AgenticLoop */}
              <line x1={320} y1={85} x2={380} y2={85} stroke="#F5C542" strokeOpacity={0.12} strokeWidth={1} />

              {/* AgenticLoop */}
              <rect x={380} y={50} width={120} height={70} rx={10} fill="#0A0F1A" stroke="#4ECDC4" strokeWidth={1} strokeOpacity={0.3} />
              <text x={440} y={75} textAnchor="middle" fill="#4ECDC4" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>AgenticLoop</text>
              <text x={440} y={93} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">실행 + 검증</text>

              {/* Arrow: Loop → HookSystem */}
              <line x1={500} y1={85} x2={560} y2={85} stroke="#4ECDC4" strokeOpacity={0.12} strokeWidth={1} />
              <text x={530} y={78} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.2} fontSize={8} fontFamily="ui-monospace, monospace">emit</text>

              {/* HookSystem */}
              <rect x={560} y={50} width={100} height={70} rx={10} fill="#0A0F1A" stroke="#E87080" strokeWidth={1} strokeOpacity={0.3} />
              <text x={610} y={75} textAnchor="middle" fill="#E87080" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>HookSystem</text>
              <text x={610} y={93} textAnchor="middle" fill="#E87080" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">TRIGGER_FIRED</text>

              {/* Feedback: Hook → TriggerManager → Scheduler */}
              <path d="M610,120 L610,150 L90,150 L90,120" fill="none" stroke="#C084FC" strokeOpacity={0.14} strokeWidth={1} strokeDasharray="4 4" className="animate-flow" />
              <text x={350} y={145} textAnchor="middle" fill="#C084FC" fillOpacity={0.30} fontSize={8} fontFamily="ui-monospace, monospace">DRIFT_DETECTED → EVENT trigger → 재분석 파이프라인</text>

              {/* TriggerManager label on feedback */}
              <rect x={300} y={130} width={100} height={24} rx={6} fill="#0A0F1A" stroke="#C084FC" strokeWidth={0.6} strokeOpacity={0.15} />
              <text x={350} y={146} textAnchor="middle" fill="#C084FC" fillOpacity={0.5} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>TriggerManager</text>

              {/* Top label */}
              <text x={380} y={30} textAnchor="middle" fill="white" fillOpacity={0.18} fontSize={9} fontFamily="ui-monospace, monospace" letterSpacing="0.1em">SCHEDULER → QUEUE → LOOP → HOOK → TRIGGER (FEEDBACK)</text>
            </svg>
          </div>
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          {/* ── SchedulerService ── */}
          {activeTab === "scheduler" && (
            <div>
              {/* Schedule types */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
                {scheduleTypes.map((s) => (
                  <div key={s.id} className="rounded-xl border border-white/[0.04] px-5 py-4" style={{ background: `${s.color}04` }}>
                    <div className="text-lg font-mono font-bold mb-1" style={{ color: s.color }}>{s.id}</div>
                    <div className="text-sm text-[#8B9CC0]">{s.desc}</div>
                  </div>
                ))}
              </div>

              {/* Features */}
              <div className="rounded-xl border border-white/[0.04] px-5 py-4 space-y-3">
                <div className="text-sm font-semibold text-white/80">NL Schedule Parser</div>
                <p className="text-sm text-[#8B9CC0] leading-relaxed">
                  자연어로 스케줄을 정의합니다. <code className="text-[#818CF8]/60">&quot;every 5 minutes during 09:00-22:00&quot;</code> →
                  EVERY(300s) + ActiveHours(09:00–22:00). LLM 호출 없이 순수 규칙 기반으로 파싱합니다.
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {["Active Hours (TZ)", "Anchor Drift 방지", "JSONL 로그", "자동 Prune (2MB)"].map((t) => (
                    <span key={t} className="px-2 py-0.5 rounded text-[11px] font-mono text-[#818CF8]/70 bg-[#818CF8]/06 border border-[#818CF8]/12">{t}</span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ── TriggerManager ── */}
          {activeTab === "triggers" && (
            <div>
              {/* F1-F4 grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
                {triggerTypes.map((t) => (
                  <div key={t.id} className="rounded-xl border border-white/[0.04] px-4 py-3" style={{ background: `${t.color}04` }}>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-mono font-bold" style={{ color: t.color }}>{t.id}</span>
                      <span className="text-xs font-semibold text-white/70">{t.name}</span>
                    </div>
                    <div className="text-xs text-[#5A6A8A] mb-2">{t.desc}</div>
                    <code className="text-[10px] font-mono text-white/20">{t.dispatch}</code>
                  </div>
                ))}
              </div>

              {/* Drift → Trigger chain */}
              <div className="rounded-xl border border-white/[0.04] px-5 py-4">
                <div className="text-sm font-semibold text-white/80 mb-3">Drift → Trigger → Reanalysis</div>
                <div className="space-y-2">
                  {driftFlow.map((d, i) => (
                    <div key={d.step} className="flex items-center gap-3">
                      <span className="shrink-0 w-6 h-6 rounded flex items-center justify-center text-[10px] font-mono font-bold" style={{ color: d.color, background: `${d.color}10` }}>
                        {i + 1}
                      </span>
                      <span className="text-sm font-medium text-white/70 w-[140px] sm:w-[160px] shrink-0">{d.step}</span>
                      <span className="text-sm text-[#5A6A8A]">{d.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ── Predefined Templates ── */}
          {activeTab === "predefined" && (
            <div className="space-y-2">
              {predefined.map((p) => (
                <div key={p.name} className="flex items-center gap-4 px-4 py-3 rounded-lg border border-white/[0.04]" style={{ background: `${p.color}03` }}>
                  <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold" style={{ color: p.color, background: `${p.color}12` }}>
                    {p.type}
                  </span>
                  <span className="text-sm font-medium text-white/80 flex-1">{p.name}</span>
                  <code className="text-xs font-mono text-[#5A6A8A] hidden sm:block">{p.cron}</code>
                </div>
              ))}
              <p className="text-xs text-[#5A6A8A] font-mono mt-3">
                CLI: /schedule create &quot;every 5m during 09:00-22:00&quot; · /schedule enable · /schedule run
              </p>
            </div>
          )}
        </ScrollReveal>
      </div>
    </section>
  );
}
