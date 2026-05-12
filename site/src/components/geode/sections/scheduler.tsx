"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { SectionHeader } from "../ui/section-header";
import { TabBar } from "../ui/tab-bar";
import { useLocale, t } from "../locale-context";

/* ── Schedule Kinds ── */
const kinds = [
  { id: "AT",    color: "#E87080", label: "AT",    descKo: "일회성 실행. 지정 시각에 한 번 실행 후 자동 삭제.", descEn: "One-shot execution. Runs once at the specified time, then auto-deletes." },
  { id: "EVERY", color: "#4ECDC4", label: "EVERY", descKo: "고정 간격. Anchor 기반 drift 방지. 실행 지연이 다음 주기에 누적되지 않음.", descEn: "Fixed interval. Anchor-based drift prevention. Execution delay does not accumulate into the next cycle." },
  { id: "CRON",  color: "#818CF8", label: "CRON",  descKo: "5-field cron 표현식. 분/시/일/월/요일. timezone-aware.", descEn: "5-field cron expression. min/hr/day/month/weekday. Timezone-aware." },
];

/* ── Lifecycle steps ── */
const lifecycle = [
  { step: "add_job()",         detailKo: "AT/EVERY/CRON + Active Hours + action 등록. jobs.json 영속화", detailEn: "Register AT/EVERY/CRON + Active Hours + action. Persist to jobs.json", color: "#818CF8" },
  { step: "_loop(interval_s)", detailKo: "백그라운드 데몬 쓰레드. check_due_jobs() 주기 호출", detailEn: "Background daemon thread. Periodic check_due_jobs() calls", color: "#60A5FA" },
  { step: "check_due_jobs()",  detailKo: "Active Hours(TZ) 검증 → 듀 잡 필터 → next_run 갱신", detailEn: "Verify Active Hours(TZ) → filter due jobs → update next_run", color: "#4ECDC4" },
  { step: "action_queue",      detailKo: "(job_id, action, isolated) 엔큐. serve 메인 루프가 드레인", detailEn: "Enqueue (job_id, action, isolated). Drained by serve main loop", color: "#F5C542" },
  { step: "IsolatedRunner",    detailKo: "격리 모드. 데몬 쓰레드 실행, MAX_CONCURRENT=5, 크래시 격리", detailEn: "Isolated mode. Daemon thread execution, MAX_CONCURRENT=5, crash isolation", color: "#C084FC" },
  { step: "AgenticLoop.run()", detailKo: "공유 모드. 메인 세션 블로킹 실행. hitl_level 상속", detailEn: "Shared mode. Main session blocking execution. Inherits hitl_level", color: "#4ECDC4" },
];

/* ── Predefined templates ── */
const templates = [
  { name: "Weekly Discovery Scan",  schedule: "0 9 * * 1",              kind: "CRON",  color: "#4ECDC4" },
  { name: "Calibration Drift Scan", schedule: "0 6 * * *",              kind: "CRON",  color: "#818CF8" },
  { name: "Outcome Tracker",        schedule: "0 0 1 * *",              kind: "CRON",  color: "#C084FC" },
  { name: "Pending Analysis Worker", schedule: "*/30 * * * *",           kind: "CRON",  color: "#34D399" },
  { name: "Auto-Generate Report",   schedule: "event:pipeline_complete", kind: "EVENT", color: "#F5C542" },
  { name: "Anomaly Detector",       schedule: "event:pipeline_complete", kind: "EVENT", color: "#E87080" },
];

type Tab = "lifecycle" | "templates" | "nl-parser";

export function SchedulerSection() {
  const locale = useLocale();
  const [activeTab, setActiveTab] = useState<Tab>("lifecycle");

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <SectionHeader
          variant="minimal"
          title="SchedulerService"
          description={t(locale,
            "시간 기반 자동화 엔진. AT(일회), EVERY(간격), CRON(표현식) 세 가지 스케줄로 잡을 등록하고, Active Hours와 타임존 검증을 거쳐 IsolatedRunner에서 격리 실행합니다.",
            "Time-based automation engine. Register jobs with three schedule types: AT (one-shot), EVERY (interval), CRON (expression). Validates Active Hours and timezone, then runs in IsolatedRunner."
          )}
        />

        {/* ── Schedule Kinds ── */}
        <ScrollReveal delay={0.05}>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-8">
            {kinds.map((k) => (
              <div key={k.id} className="rounded-xl border border-white/[0.04] px-5 py-4" style={{ background: `${k.color}04` }}>
                <div className="text-lg font-mono font-bold mb-1" style={{ color: k.color }}>{k.label}</div>
                <div className="text-xs text-[#A0B4D4] leading-relaxed">{locale === "en" ? k.descEn : k.descKo}</div>
              </div>
            ))}
          </div>
        </ScrollReveal>

        {/* ── Scheduler lifecycle SVG ── */}
        <ScrollReveal delay={0.08}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-8">
            <svg viewBox="0 0 800 220" className="w-full min-w-[600px]" style={{ maxHeight: 250 }}>
              {/* Main pipeline: add_job → _loop → check_due → action_queue → execution */}
              {[
                { x: 15,  label: "add_job()",     sub: "AT·EVERY·CRON", color: "#818CF8" },
                { x: 165, label: "_loop()",        sub: "daemon thread",  color: "#60A5FA" },
                { x: 315, label: "check_due()",   sub: "TZ + hours",     color: "#4ECDC4" },
                { x: 465, label: "action_queue",   sub: "enqueue",        color: "#F5C542" },
              ].map((n, i) => (
                <g key={n.label}>
                  <rect x={n.x} y={50} width={130} height={55} rx={10}
                    fill="#0C1220" stroke={n.color} strokeWidth={1} strokeOpacity={0.45} />
                  <text x={n.x + 65} y={73} textAnchor="middle" fill={n.color}
                    fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>{n.label}</text>
                  <text x={n.x + 65} y={92} textAnchor="middle" fill={n.color} fillOpacity={0.4}
                    fontSize={8} fontFamily="ui-monospace, monospace">{n.sub}</text>
                  {i < 3 && (
                    <path d={`M${n.x + 130},78 C${n.x + 140},73 ${n.x + 150},73 ${n.x + 165},78`}
                      stroke="white" strokeOpacity={0.2} strokeWidth={1} fill="none" />
                  )}
                </g>
              ))}

              {/* Fork: isolated vs main */}
              <path d="M595,65 C620,55 640,35 660,35" stroke="#C084FC" strokeOpacity={0.35} strokeWidth={1} fill="none" />
              <path d="M595,90 C620,100 640,120 660,120" stroke="#4ECDC4" strokeOpacity={0.35} strokeWidth={1} fill="none" />

              {/* IsolatedRunner (top branch) */}
              <rect x={660} y={15} width={120} height={42} rx={8}
                fill="#0C1220" stroke="#C084FC" strokeWidth={1} strokeOpacity={0.4} />
              <text x={720} y={33} textAnchor="middle" fill="#C084FC"
                fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>IsolatedRunner</text>
              <text x={720} y={48} textAnchor="middle" fill="#C084FC" fillOpacity={0.4}
                fontSize={7} fontFamily="ui-monospace, monospace">daemon thread, crash-safe</text>

              {/* AgenticLoop (bottom branch) */}
              <rect x={660} y={100} width={120} height={42} rx={8}
                fill="#0C1220" stroke="#4ECDC4" strokeWidth={1} strokeOpacity={0.4} />
              <text x={720} y={118} textAnchor="middle" fill="#4ECDC4"
                fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>AgenticLoop</text>
              <text x={720} y={133} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.4}
                fontSize={7} fontFamily="ui-monospace, monospace">main session, blocking</text>

              {/* Fork labels */}
              <rect x={604} y={19} width={64} height={16} rx={4}
                fill="#C084FC" fillOpacity={0.08} stroke="#C084FC" strokeWidth={0.5} strokeOpacity={0.25} />
              <text x={636} y={30} textAnchor="middle" fill="#C084FC" fillOpacity={0.7}
                fontSize={7} fontFamily="ui-monospace, monospace" fontWeight={600}>isolated</text>
              <rect x={604} y={129} width={64} height={16} rx={4}
                fill="#4ECDC4" fillOpacity={0.08} stroke="#4ECDC4" strokeWidth={0.5} strokeOpacity={0.25} />
              <text x={636} y={140} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.7}
                fontSize={7} fontFamily="ui-monospace, monospace" fontWeight={600}>shared</text>

              {/* Active Hours annotation */}
              <rect x={315} y={125} width={130} height={35} rx={7}
                fill="#0A0F1A" stroke="#34D399" strokeWidth={0.7} strokeOpacity={0.3} />
              <text x={380} y={140} textAnchor="middle" fill="#34D399" fillOpacity={0.6}
                fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>Active Hours</text>
              <text x={380} y={153} textAnchor="middle" fill="#34D399" fillOpacity={0.35}
                fontSize={7} fontFamily="ui-monospace, monospace">09:00-22:00 Asia/Seoul</text>
              <path d="M380,105 L380,125" stroke="#34D399" strokeOpacity={0.2} strokeWidth={0.8} strokeDasharray="3 2" />

              {/* Persistence annotation */}
              <rect x={15} y={125} width={130} height={35} rx={7}
                fill="#0A0F1A" stroke="#818CF8" strokeWidth={0.7} strokeOpacity={0.3} />
              <text x={80} y={140} textAnchor="middle" fill="#818CF8" fillOpacity={0.6}
                fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>jobs.json</text>
              <text x={80} y={153} textAnchor="middle" fill="#818CF8" fillOpacity={0.35}
                fontSize={7} fontFamily="ui-monospace, monospace">~/.geode/scheduler/</text>
              <path d="M80,105 L80,125" stroke="#818CF8" strokeOpacity={0.2} strokeWidth={0.8} strokeDasharray="3 2" />

              {/* Per-job logs annotation */}
              <rect x={660} y={160} width={120} height={35} rx={7}
                fill="#0A0F1A" stroke="#F5C542" strokeWidth={0.7} strokeOpacity={0.3} />
              <text x={720} y={175} textAnchor="middle" fill="#F5C542" fillOpacity={0.6}
                fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>logs/{"{job_id}"}.jsonl</text>
              <text x={720} y={188} textAnchor="middle" fill="#F5C542" fillOpacity={0.35}
                fontSize={7} fontFamily="ui-monospace, monospace">2MB / 2000줄 prune</text>

              {/* Top label */}
              <text x={400} y={12} textAnchor="middle" fill="white" fillOpacity={0.2}
                fontSize={8} fontFamily="ui-monospace, monospace" letterSpacing="0.1em">
                REGISTER → LOOP → CHECK → ENQUEUE → EXECUTE (isolated / blocking)
              </text>
            </svg>
          </div>
        </ScrollReveal>

        {/* ── Tab bar ── */}
        <ScrollReveal delay={0.1}>
          <TabBar
            variant="underline"
            tabs={[
              { id: "lifecycle", label: "Lifecycle", color: "#818CF8" },
              { id: "templates", label: "Predefined Templates", color: "#F5C542" },
              { id: "nl-parser", label: "NL Parser", color: "#4ECDC4" },
            ]}
            activeId={activeTab}
            onSelect={(id) => setActiveTab(id as Tab)}
          />
        </ScrollReveal>

        <ScrollReveal delay={0.12}>
          <div className="min-h-[320px]">
          <AnimatePresence mode="wait">
          {/* ── Lifecycle ── */}
          {activeTab === "lifecycle" && (
            <motion.div key="lifecycle" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <div className="space-y-2">
              {lifecycle.map((l, i) => (
                <div key={l.step} className="flex items-center gap-3 px-4 py-3 rounded-lg border border-white/[0.04]"
                  style={{ background: `${l.color}03` }}>
                  <span className="shrink-0 w-6 h-6 rounded flex items-center justify-center text-[10px] font-mono font-bold"
                    style={{ color: l.color, background: `${l.color}10` }}>{i + 1}</span>
                  <span className="text-sm font-medium text-white/70 w-[140px] sm:w-[160px] shrink-0 font-mono">{l.step}</span>
                  <span className="text-sm text-[#9BB0CC]">{locale === "en" ? l.detailEn : l.detailKo}</span>
                </div>
              ))}
            </div>
            </motion.div>
          )}

          {/* ── Templates ── */}
          {activeTab === "templates" && (
            <motion.div key="templates" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <div>
              <div className="space-y-2 mb-4">
                {templates.map((t) => (
                  <div key={t.name} className="flex items-center gap-4 px-4 py-3 rounded-lg border border-white/[0.04]"
                    style={{ background: `${t.color}03` }}>
                    <span className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold"
                      style={{ color: t.color, background: `${t.color}12` }}>{t.kind}</span>
                    <span className="text-sm font-medium text-white/80 flex-1">{t.name}</span>
                    <code className="text-xs font-mono text-[#9BB0CC] hidden sm:block">{t.schedule}</code>
                  </div>
                ))}
              </div>
              <p className="text-xs text-[#9BB0CC] font-mono">
                CLI: /schedule create &quot;every 5m during 09:00-22:00&quot; · /schedule enable · /schedule run
              </p>
            </div>
            </motion.div>
          )}

          {/* ── NL Parser ── */}
          {activeTab === "nl-parser" && (
            <motion.div key="nl-parser" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <div className="rounded-xl border border-white/[0.04] px-5 py-4 space-y-4">
              <p className="text-sm text-[#A0B4D4] leading-relaxed">
                {locale === "ko" ? (
                  <>LLM이 <code className="text-[#4ECDC4]/60">schedule_job</code> tool_use로 자동 호출하면, 내부 <code className="text-[#818CF8]/60">NLScheduleParser</code>가 순수 규칙 기반(regex)으로 AT/EVERY/CRON + Active Hours 조합으로 변환합니다. 슬래시 명령 <code className="text-white/30">/schedule create</code>도 동일 경로.</>
                ) : (
                  <>When the LLM auto-invokes <code className="text-[#4ECDC4]/60">schedule_job</code> via tool_use, the internal <code className="text-[#818CF8]/60">NLScheduleParser</code> converts it to AT/EVERY/CRON + Active Hours using pure rule-based regex. The slash command <code className="text-white/30">/schedule create</code> follows the same path.</>
                )}
              </p>
              <div className="space-y-2">
                {[
                  { input: '"every 5 minutes during 09:00-22:00"', output: "EVERY(300s) + ActiveHours(09:00-22:00)" },
                  { input: '"weekdays at 09:00"', output: 'CRON("0 9 * * 1-5")' },
                  { input: '"in 30 minutes"', output: "AT(now + 1800s)" },
                  { input: '"every monday 10am KST"', output: 'CRON("0 10 * * 1") TZ=Asia/Seoul' },
                ].map((e) => (
                  <div key={e.input} className="flex items-center gap-3 px-3 py-2 rounded-lg border border-white/[0.03]" style={{ background: "#4ECDC403" }}>
                    <code className="text-xs font-mono text-[#4ECDC4]/70 flex-1">{e.input}</code>
                    <span className="text-white/20 text-xs">→</span>
                    <code className="text-xs font-mono text-white/50 flex-1 text-right">{e.output}</code>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(locale === "en"
                  ? ["Anchor Drift prevention", "Auto Prune (2MB)", "JSONL execution log", "midnight wrap-around"]
                  : ["Anchor Drift 방지", "자동 Prune (2MB)", "JSONL 실행 로그", "midnight wrap-around"]
                ).map((tag) => (
                  <span key={tag} className="px-2 py-0.5 rounded text-[10px] font-mono text-[#4ECDC4]/60 bg-[#4ECDC4]/06 border border-[#4ECDC4]/10">{tag}</span>
                ))}
              </div>
            </div>
            </motion.div>
          )}
          </AnimatePresence>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
