"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { SectionHeader } from "../ui/section-header";
import { TabBar } from "../ui/tab-bar";
import { useLocale, t } from "../locale-context";

type Phase = "as-is" | "to-be";
type Tab = "evolution" | "sessionlane";

const ease = [0.22, 1, 0.36, 1] as const;
const posTx = { duration: 0.6, ease };
const fadeTx = { duration: 0.3 };

/* 11 red dot positions */
const dots = [
  { x: 200, y: 55 }, { x: 310, y: 42 }, { x: 420, y: 78 },
  { x: 260, y: 130 }, { x: 155, y: 95 }, { x: 480, y: 55 },
  { x: 350, y: 200 }, { x: 520, y: 160 }, { x: 175, y: 210 },
  { x: 600, y: 100 }, { x: 440, y: 245 },
];

const cards = [
  { color: "#E87080", headKo: "11건 → 0건", headEn: "11 → 0 defects", bodyKo: "globals race, semaphore leak, zombie thread, 이중 publish 등 전수 해소", bodyEn: "globals race, semaphore leak, zombie thread, double publish all resolved" },
  { color: "#4ECDC4", headKo: "3 bootstrap → 1 Runtime", headEn: "3 bootstrap → 1 Runtime", bodyKo: "GeodeRuntime.create_session(mode). ONE Hook, ONE MCP, ONE Skills", bodyEn: "GeodeRuntime.create_session(mode). ONE Hook, ONE MCP, ONE Skills" },
  { color: "#F5C542", headKo: "4-lane → acquire_all()", headEn: "4-lane → acquire_all()", bodyKo: "SessionLane(per-key) + Lane(global, max=8). 단일 코드 패스", bodyEn: "SessionLane(per-key) + Lane(global, max=8). Single code path" },
];

/* SessionLane deep dive data */
const openclawFixes = [
  { issue: "Unbounded growth", issueEn: "Unbounded growth", fix: "max_sessions=256 soft cap", color: "#E87080" },
  { issue: "Idle 미정리", issueEn: "No idle cleanup", fix: "300s idle eviction + held 보호", color: "#F5C542" },
];

const usagePatterns = [
  { name: "Gateway (Slack)", nameEn: "Gateway (Slack)", key: "gateway:slack:C12345:U789:thread_A", descKo: "같은 쓰레드 = serial, 다른 쓰레드 = parallel", descEn: "Same thread = serial, different threads = parallel", color: "#4ECDC4" },
  { name: "Scheduler", nameEn: "Scheduler", key: "scheduler:weekly_scan", descKo: "non-blocking try_acquire. 실패 시 rollback", descEn: "Non-blocking try_acquire. Rollback on failure", color: "#F5C542" },
  { name: "SubAgent", nameEn: "SubAgent", key: "ip:berserk:pipeline:subagent:reddit", descKo: "유니크 key → 항상 즉시 획득. global Lane이 병렬 제어", descEn: "Unique key = always immediate acquire. global Lane controls parallelism", color: "#C084FC" },
];

export function ConcurrencySection() {
  const locale = useLocale();
  const [tab, setTab] = useState<Tab>("evolution");
  const [phase, setPhase] = useState<Phase>("as-is");
  const isToBe = phase === "to-be";

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <SectionHeader
          variant="quote"
          labelColor="#818CF8"
          title="Concurrency"
          description={t(locale,
            "REPL + serve 이원화에서 serve 단일 데몬으로. 11건 구조적 결함을 전수 해소하며 도달한 최종 아키텍처.",
            "From dual REPL + serve to a single serve daemon. The final architecture reached after resolving all 11 structural defects."
          )}
        />

        {/* Tab bar */}
        <ScrollReveal delay={0.03}>
          <TabBar
            variant="underline"
            tabs={[
              { id: "evolution", label: t(locale, "REPL + serve → 단일 Daemon", "REPL + serve → Unified Daemon"), color: "#E87080" },
              { id: "sessionlane", label: "SessionLane Deep Dive", color: "#818CF8" },
            ]}
            activeId={tab}
            onSelect={(id) => setTab(id as Tab)}
          />
        </ScrollReveal>

        {/* ══════════ EVOLUTION TAB ══════════ */}
        {tab === "evolution" && (
          <>
            <ScrollReveal delay={0.05}>
              <div className="flex justify-center mb-8">
                <div className="inline-flex rounded-full bg-[#0A0F1A] border border-white/[0.06] p-1">
                  {(["as-is", "to-be"] as Phase[]).map((p) => (
                    <button key={p} onClick={() => setPhase(p)}
                      className="relative px-5 py-1.5 rounded-full text-xs font-mono font-bold uppercase tracking-wider transition-colors duration-200"
                      style={{ color: phase === p ? "#fff" : "#7A8CA8", background: phase === p ? (p === "as-is" ? "rgba(232,112,128,0.25)" : "rgba(78,205,196,0.25)") : "transparent" }}>
                      {p === "as-is" ? "AS-IS" : "TO-BE"}
                    </button>
                  ))}
                </div>
              </div>

              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 750 280" className="w-full min-w-[640px]" style={{ maxHeight: 320 }}>
                  <defs>
                    <radialGradient id="glow-as" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="#E87080" stopOpacity={0.06} /><stop offset="100%" stopColor="#E87080" stopOpacity={0} /></radialGradient>
                    <radialGradient id="glow-to" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="#4ECDC4" stopOpacity={0.06} /><stop offset="100%" stopColor="#4ECDC4" stopOpacity={0} /></radialGradient>
                  </defs>
                  <motion.rect x={0} y={0} width={750} height={280} rx={16} animate={{ fill: isToBe ? "url(#glow-to)" : "url(#glow-as)" }} transition={fadeTx} />

                  {/* Entry boxes */}
                  {[
                    { asLabel: "REPL", toLabel: "CLI (IPC)", color: "#4ECDC4", y: 30 },
                    { asLabel: "serve", toLabel: "Daemon", color: "#818CF8", y: 110 },
                    { asLabel: "Scheduler", toLabel: "Scheduler", color: "#F5C542", y: 190 },
                  ].map((e, i) => (
                    <g key={i}>
                      <rect x={30} y={e.y} width={110} height={44} rx={8} fill="#0A0F1A" stroke={e.color} strokeWidth={0.8} strokeOpacity={0.5} />
                      <AnimatePresence mode="wait">
                        <motion.text key={isToBe ? e.toLabel : e.asLabel} x={85} y={e.y + 27} textAnchor="middle" fill={e.color} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}
                          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={fadeTx}>
                          {isToBe ? e.toLabel : e.asLabel}
                        </motion.text>
                      </AnimatePresence>
                    </g>
                  ))}

                  {/* AS-IS: separate queues */}
                  {[{ label: "bootstrap_1", y: 30, color: "#F4B8C8" }, { label: "bootstrap_2", y: 110, color: "#F4B8C8" }, { label: "action_queue", y: 190, color: "#F5C542" }].map((q, i) => (
                    <motion.g key={`asq-${i}`} animate={{ opacity: isToBe ? 0 : 1, x: isToBe ? 80 : 0, y: isToBe ? (110 - q.y) * 0.3 : 0 }} transition={posTx}>
                      <rect x={280} y={q.y} width={130} height={44} rx={8} fill="#0C1220" stroke={q.color} strokeWidth={0.8} strokeOpacity={0.4} />
                      <text x={345} y={q.y + 27} textAnchor="middle" fill={q.color} fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>{q.label}</text>
                    </motion.g>
                  ))}

                  {/* AS-IS: arrows */}
                  {[30, 110, 190].map((y, i) => (
                    <motion.path key={`as-arr-${i}`} d={`M140,${y + 22} L280,${y + 22}`} stroke={["#F4B8C8", "#F4B8C8", "#F5C542"][i]} strokeWidth={[0.8, 1.2, 1.5][i]} strokeOpacity={[0.3, 0.45, 0.6][i]} fill="none" animate={{ opacity: isToBe ? 0 : 1 }} transition={fadeTx} />
                  ))}

                  {/* AS-IS: CoalescingQueue ghost */}
                  <motion.g animate={{ opacity: isToBe ? 0 : 0.3, filter: isToBe ? "blur(4px)" : "blur(0px)" }} transition={fadeTx}>
                    <rect x={480} y={20} width={150} height={36} rx={8} fill="none" stroke="#5A6A8A" strokeWidth={1} strokeDasharray="4 3" />
                    <text x={555} y={35} textAnchor="middle" fill="#5A6A8A" fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>CoalescingQueue</text>
                    <text x={555} y={48} textAnchor="middle" fill="#5A6A8A" fontSize={7} fontFamily="ui-monospace, monospace">250ms, 0 triggers</text>
                  </motion.g>

                  {/* 11 red dots */}
                  {dots.map((d, i) => (
                    <motion.circle key={`dot-${i}`} r={3} fill="#E87080"
                      animate={{ cx: isToBe ? 375 : d.x, cy: isToBe ? 140 : d.y, scale: isToBe ? 0 : 1, opacity: isToBe ? 0 : 0.85 }}
                      transition={{ ...posTx, delay: isToBe ? i * 0.03 : (10 - i) * 0.03 }}>
                      {!isToBe && <animate attributeName="cx" values={`${d.x - 2};${d.x + 2};${d.x - 2}`} dur={`${1.5 + i * 0.2}s`} repeatCount="indefinite" />}
                    </motion.circle>
                  ))}

                  {/* TO-BE: converging arrows */}
                  {[52, 132, 212].map((y, i) => (
                    <motion.path key={`to-arr-${i}`} d={`M140,${y} L290,132`} stroke="#4ECDC4" strokeWidth={1.5} fill="none"
                      animate={{ opacity: isToBe ? 1 : 0, strokeDashoffset: isToBe ? 0 : 200 }} strokeDasharray={200} transition={{ ...posTx, delay: isToBe ? 0.3 : 0 }} />
                  ))}

                  {/* TO-BE: SessionLane → Lane → AgenticLoop */}
                  <motion.g animate={{ opacity: isToBe ? 1 : 0, x: isToBe ? 0 : -30 }} transition={posTx}>
                    <rect x={290} y={100} width={140} height={64} rx={10} fill="#0C1220" stroke="#818CF8" strokeWidth={1.2} strokeOpacity={0.6} />
                    <text x={360} y={122} textAnchor="middle" fill="#818CF8" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>SessionLane</text>
                    <text x={360} y={138} textAnchor="middle" fill="#818CF8" fillOpacity={0.5} fontSize={8} fontFamily="ui-monospace, monospace">per-key Sem(1)</text>
                    <text x={360} y={152} textAnchor="middle" fill="#818CF8" fillOpacity={0.35} fontSize={7} fontFamily="ui-monospace, monospace">max=256</text>
                  </motion.g>
                  <motion.g animate={{ opacity: isToBe ? 1 : 0, x: isToBe ? 0 : -20 }} transition={{ ...posTx, delay: isToBe ? 0.1 : 0 }}>
                    <rect x={460} y={108} width={110} height={48} rx={10} fill="#0C1220" stroke="#F5C542" strokeWidth={1.2} strokeOpacity={0.6} />
                    <text x={515} y={128} textAnchor="middle" fill="#F5C542" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>Lane</text>
                    <text x={515} y={144} textAnchor="middle" fill="#F5C542" fillOpacity={0.5} fontSize={8} fontFamily="ui-monospace, monospace">global, max=8</text>
                  </motion.g>
                  <motion.g animate={{ opacity: isToBe ? 1 : 0, x: isToBe ? 0 : -10 }} transition={{ ...posTx, delay: isToBe ? 0.2 : 0 }}>
                    <rect x={600} y={108} width={120} height={48} rx={10} fill="#0C1220" stroke="#4ECDC4" strokeWidth={1.2} strokeOpacity={0.6} />
                    <text x={660} y={128} textAnchor="middle" fill="#4ECDC4" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>AgenticLoop</text>
                    <text x={660} y={144} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.5} fontSize={8} fontFamily="ui-monospace, monospace">while(tool_use)</text>
                  </motion.g>
                  <motion.path d="M430,132 L460,132" stroke="#4ECDC4" strokeWidth={1.5} fill="none" animate={{ opacity: isToBe ? 1 : 0 }} transition={fadeTx} />
                  <motion.path d="M570,132 L600,132" stroke="#4ECDC4" strokeWidth={1.5} fill="none" animate={{ opacity: isToBe ? 1 : 0 }} transition={fadeTx} />
                </svg>
              </div>
            </ScrollReveal>

            {/* Defect counter */}
            <ScrollReveal delay={0.1}>
              <div className="flex justify-center items-center gap-3 mb-10">
                <AnimatePresence mode="wait">
                  <motion.span key={isToBe ? "zero" : "eleven"} className="text-5xl font-mono font-black" style={{ color: isToBe ? "#34D399" : "#E87080" }}
                    initial={{ opacity: 0, scale: 1.4, filter: "blur(8px)" }} animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }} exit={{ opacity: 0, scale: 0.6, filter: "blur(8px)" }} transition={{ duration: 0.35 }}>
                    {isToBe ? "0" : "11"}
                  </motion.span>
                </AnimatePresence>
                <span className="text-sm font-mono text-white/40">{isToBe ? t(locale, "전수 해소", "all resolved") : t(locale, "구조적 결함", "structural defects")}</span>
              </div>
            </ScrollReveal>

            {/* Trade-off cards */}
            <ScrollReveal delay={0.15}>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {cards.map((c) => (
                  <div key={c.headEn} className="rounded-xl border px-5 py-5" style={{ borderColor: `${c.color}15`, background: `linear-gradient(160deg, ${c.color}06, transparent 70%)` }}>
                    <p className="text-base font-mono font-bold mb-2" style={{ color: c.color }}>{locale === "en" ? c.headEn : c.headKo}</p>
                    <p className="text-xs text-[#9BB0CC] leading-relaxed">{locale === "en" ? c.bodyEn : c.bodyKo}</p>
                  </div>
                ))}
              </div>
            </ScrollReveal>
          </>
        )}

        {/* ══════════ SESSIONLANE DEEP DIVE TAB ══════════ */}
        {tab === "sessionlane" && (
          <>
            {/* AS-IS / TO-BE toggle for SessionLane */}
            <ScrollReveal delay={0.05}>
              <div className="flex justify-center mb-6">
                <div className="inline-flex rounded-full bg-[#0A0F1A] border border-white/[0.06] p-1">
                  {(["as-is", "to-be"] as Phase[]).map((p) => (
                    <button key={`sl-${p}`} onClick={() => setPhase(p)}
                      className="relative px-5 py-1.5 rounded-full text-xs font-mono font-bold uppercase tracking-wider transition-colors duration-200"
                      style={{ color: phase === p ? "#fff" : "#7A8CA8", background: phase === p ? (p === "as-is" ? "rgba(232,112,128,0.25)" : "rgba(78,205,196,0.25)") : "transparent" }}>
                      {p === "as-is" ? t(locale, "Single Sem: 전역 직렬화", "Single Sem: Global Serialization") : t(locale, "Per-Key Sem: 키별 병렬화", "Per-Key Sem: Per-Key Parallelism")}
                    </button>
                  ))}
                </div>
              </div>

              {/* Single large animated SVG */}
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-8">
                <svg viewBox="0 0 700 260" className="w-full min-w-[560px]" style={{ maxHeight: 300 }}>
                  <defs>
                    <radialGradient id="sl-glow-as" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="#E87080" stopOpacity={0.04} /><stop offset="100%" stopColor="#E87080" stopOpacity={0} /></radialGradient>
                    <radialGradient id="sl-glow-to" cx="50%" cy="50%" r="50%"><stop offset="0%" stopColor="#4ECDC4" stopOpacity={0.04} /><stop offset="100%" stopColor="#4ECDC4" stopOpacity={0} /></radialGradient>
                  </defs>

                  <motion.rect x={0} y={0} width={700} height={260} rx={14}
                    animate={{ fill: isToBe ? "url(#sl-glow-to)" : "url(#sl-glow-as)" }} transition={fadeTx} />

                  {/* Title */}
                  <AnimatePresence mode="wait">
                    <motion.text key={isToBe ? "sl-title-to" : "sl-title-as"}
                      x={350} y={28} textAnchor="middle"
                      fill={isToBe ? "#4ECDC4" : "#E87080"} fontSize={14} fontFamily="ui-monospace, monospace" fontWeight={800}
                      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={fadeTx}>
                      {isToBe ? "SessionLane: Dict[str, Semaphore(1)]" : "Lane: Single Semaphore(1)"}
                    </motion.text>
                  </AnimatePresence>

                  {/* 3 threads/sessions */}
                  {[
                    { label: "Thread A", key: "key_A", y: 60 },
                    { label: "Thread B", key: "key_B", y: 120 },
                    { label: "Thread C", key: "key_C", y: 180 },
                  ].map((th, i) => {
                    const color = isToBe ? "#4ECDC4" : "#E87080";
                    const isBlocked = !isToBe && i > 0;
                    return (
                      <g key={th.label}>
                        {/* Thread box */}
                        <rect x={30} y={th.y} width={120} height={42} rx={8}
                          fill="#0A0F1A" stroke={color} strokeWidth={0.8} strokeOpacity={isBlocked ? 0.2 : 0.5} />
                        <text x={90} y={th.y + 18} textAnchor="middle" fill={color} fillOpacity={isBlocked ? 0.3 : 0.8}
                          fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>{th.label}</text>
                        <text x={90} y={th.y + 33} textAnchor="middle" fill={color} fillOpacity={isBlocked ? 0.2 : 0.5}
                          fontSize={7} fontFamily="ui-monospace, monospace">{th.key}</text>

                        {/* Arrow to semaphore */}
                        <motion.path
                          d={isToBe
                            ? `M150,${th.y + 21} L280,${th.y + 21}`  /* each thread → own semaphore */
                            : `M150,${th.y + 21} L280,131`            /* all threads → single semaphore */
                          }
                          stroke={color} strokeWidth={1} strokeOpacity={isBlocked ? 0.15 : 0.4} fill="none"
                          animate={{ d: isToBe ? `M150,${th.y + 21} L280,${th.y + 21}` : `M150,${th.y + 21} L280,131` }}
                          transition={posTx}
                        />

                        {/* Semaphore box (per-key in TO-BE, single in AS-IS) */}
                        <motion.rect
                          rx={7} fill={isToBe ? `${color}08` : (i === 0 ? `${color}08` : "transparent")}
                          stroke={color} strokeWidth={isBlocked ? 0.4 : 0.8} strokeOpacity={isBlocked ? 0.15 : 0.4}
                          animate={{
                            x: 280, width: 140,
                            y: isToBe ? th.y : 110,
                            height: isToBe ? 42 : 42,
                            opacity: isToBe ? 1 : (i === 0 ? 1 : 0),
                          }}
                          transition={posTx}
                        />
                        {isToBe && (
                          <motion.text x={350} y={th.y + 18} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.7}
                            fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}
                            initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ ...fadeTx, delay: 0.3 }}>
                            sem_{th.key.split("_")[1]}
                          </motion.text>
                        )}

                        {/* Status label */}
                        <motion.text x={480} y={isToBe ? th.y + 25 : (i === 0 ? 135 : 135 + i * 16)}
                          textAnchor="middle"
                          fill={isToBe ? "#34D399" : (i === 0 ? "#34D399" : "#E87080")}
                          fillOpacity={0.7} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}
                          animate={{ y: isToBe ? th.y + 25 : (i === 0 ? 125 : 125 + i * 18) }}
                          transition={posTx}>
                          {isToBe ? "acquired (parallel)" : (i === 0 ? "acquired" : "BLOCKED")}
                        </motion.text>
                      </g>
                    );
                  })}

                  {/* AS-IS: single semaphore label */}
                  <motion.text x={350} y={128} textAnchor="middle" fill="#E87080" fillOpacity={0.7}
                    fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}
                    animate={{ opacity: isToBe ? 0 : 1 }} transition={fadeTx}>
                    Sem(1)
                  </motion.text>
                  <motion.text x={350} y={145} textAnchor="middle" fill="#E87080" fillOpacity={0.35}
                    fontSize={8} fontFamily="ui-monospace, monospace"
                    animate={{ opacity: isToBe ? 0 : 1 }} transition={fadeTx}>
                    global serialization
                  </motion.text>

                  {/* Bottom summary */}
                  <AnimatePresence mode="wait">
                    <motion.text key={isToBe ? "sl-sum-to" : "sl-sum-as"}
                      x={350} y={245} textAnchor="middle"
                      fill={isToBe ? "#4ECDC4" : "#E87080"} fillOpacity={0.4}
                      fontSize={9} fontFamily="ui-monospace, monospace"
                      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={fadeTx}>
                      {isToBe ? "Same key = serial, Different key = parallel. max_sessions=256, idle cleanup 300s" : "All keys share one semaphore. B waits for A. C waits for B. Global bottleneck."}
                    </motion.text>
                  </AnimatePresence>
                </svg>
              </div>
            </ScrollReveal>

            {/* OpenClaw defects → GEODE fixes */}
            <ScrollReveal delay={0.08}>
              <div className="rounded-xl border border-white/[0.04] px-5 py-4 mb-6">
                <div className="text-sm font-semibold text-white/70 mb-3">{t(locale, "OpenClaw 결함 → GEODE 수정", "OpenClaw Defects → GEODE Fixes")}</div>
                <div className="space-y-2">
                  {openclawFixes.map((f) => (
                    <div key={f.fix} className="flex items-center gap-4 px-3 py-2.5 rounded-lg border border-white/[0.04]" style={{ background: `${f.color}03` }}>
                      <span className="shrink-0 w-2 h-2 rounded-full" style={{ background: f.color }} />
                      <span className="text-sm text-white/60 w-[140px] shrink-0">{locale === "en" ? f.issueEn : f.issue}</span>
                      <span className="text-xs text-white/25 mx-1">→</span>
                      <code className="text-xs font-mono text-[#34D399]/70">{f.fix}</code>
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {["_SessionEntry(__slots__)", "held flag (eviction 보호)", "Lock scope: dict만 보호", "max_sessions=256 soft cap"].map((tag) => (
                    <span key={tag} className="px-2 py-0.5 rounded text-[9px] font-mono text-[#818CF8]/50 bg-[#818CF8]/06 border border-[#818CF8]/10">{tag}</span>
                  ))}
                </div>
              </div>
            </ScrollReveal>

            {/* Usage patterns (compact single-line) */}
            <ScrollReveal delay={0.1}>
              <div className="space-y-1.5 mb-6">
                {usagePatterns.map((p) => (
                  <div key={p.key} className="flex items-center gap-3 px-4 py-2 rounded-lg border border-white/[0.04]" style={{ background: `${p.color}03` }}>
                    <span className="shrink-0 text-xs font-mono font-bold w-[90px]" style={{ color: p.color }}>{locale === "en" ? p.nameEn : p.name}</span>
                    <code className="shrink-0 text-[9px] font-mono text-white/20 w-[280px] hidden sm:block truncate">{p.key}</code>
                    <span className="text-xs text-[#9BB0CC] flex-1">{locale === "en" ? p.descEn : p.descKo}</span>
                  </div>
                ))}
              </div>
            </ScrollReveal>

            {/* Design invariants */}
            <ScrollReveal delay={0.12}>
              <div className="rounded-lg border border-white/[0.04] px-4 py-3">
                <div className="text-xs font-semibold text-white/50 mb-2">{t(locale, "설계 불변식", "Design Invariants")}</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-[#9BB0CC]">
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-[#4ECDC4]/50 mt-1" />
                    <span>{t(locale, "같은 key = serial, 다른 key = parallel", "Same key = serial, different key = parallel")}</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-[#F5C542]/50 mt-1" />
                    <span>{t(locale, "Lock은 dict 보호만. sem.acquire()는 Lock 밖에서", "Lock protects dict only. sem.acquire() outside lock")}</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-[#E87080]/50 mt-1" />
                    <span>{t(locale, "held=True 엔트리는 절대 eviction 안 함", "held=True entries never evicted")}</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-[#818CF8]/50 mt-1" />
                    <span>{t(locale, "Duck typing: Lane과 동일 API (acquire, try_acquire, manual_release)", "Duck typing: Same API as Lane (acquire, try_acquire, manual_release)")}</span>
                  </div>
                </div>
              </div>
            </ScrollReveal>
          </>
        )}
      </div>
    </section>
  );
}
