"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { SectionHeader } from "../ui/section-header";
import { useLocale, t } from "../locale-context";

type Mode = "ipc" | "daemon" | "scheduler";

const modes: Record<Mode, {
  label: string; sub: string; color: string;
  descKo: string; descEn: string;
  detailsKo: string[]; detailsEn: string[];
  source: string; poller: string;
}> = {
  ipc: {
    label: "CLI (IPC)", sub: "SessionMode.IPC", color: "#4ECDC4",
    descKo: "thin CLI가 Unix socket(~/.geode/cli.sock)으로 serve에 접속. serve가 미실행이면 자동 시작(pidfile lock, TOCTOU 방지). line-delimited JSON 프로토콜. hitl=0, WRITE 허용, DANGEROUS 차단.",
    descEn: "thin CLI connects to serve via Unix socket (~/.geode/cli.sock). Auto-starts serve if not running (pidfile lock, TOCTOU prevention). Line-delimited JSON protocol. hitl=0, WRITE allowed, DANGEROUS blocked.",
    detailsKo: ["IPCClient + CLIPoller", "auto-start serve", "chmod 0o600 보안"],
    detailsEn: ["IPCClient + CLIPoller", "auto-start serve", "chmod 0o600 security"],
    source: "Terminal", poller: "CLIPoller",
  },
  daemon: {
    label: "Daemon", sub: "SessionMode.DAEMON", color: "#818CF8",
    descKo: "Slack/Discord/Telegram 폴러가 외부 메시지를 수신. config.toml [gateway] pollers에서 동적 등록(_POLLER_REGISTRY). hitl=0, quiet 모드, DANGEROUS 차단.",
    descEn: "Slack/Discord/Telegram pollers receive external messages. Dynamically registered via config.toml [gateway] pollers (_POLLER_REGISTRY). hitl=0, quiet mode, DANGEROUS blocked.",
    detailsKo: ["Config-driven pollers", "ChannelBinding 라우팅", "SessionLane 동시성"],
    detailsEn: ["Config-driven pollers", "ChannelBinding routing", "SessionLane concurrency"],
    source: "Slack / Discord", poller: "Gateway",
  },
  scheduler: {
    label: "Scheduler", sub: "SessionMode.SCHEDULER", color: "#F5C542",
    descKo: "serve 내부에서 SchedulerService가 AT/EVERY/CRON 잡을 실행. hitl=0, quiet, 300s 시간 제한. fcntl.flock으로 jobs.json 동시 접근 방지. stuck job 10분 탐지.",
    descEn: "SchedulerService runs AT/EVERY/CRON jobs inside serve. hitl=0, quiet, 300s time cap. fcntl.flock prevents concurrent jobs.json access. Stuck job detection at 10 min.",
    detailsKo: ["serve 내장 데몬", "300s time cap", "fcntl.flock 잡 잠금"],
    detailsEn: ["Built-in serve daemon", "300s time cap", "fcntl.flock job locking"],
    source: "Cron / AT / EVERY", poller: "Scheduler",
  },
};

const modeOrder: Mode[] = ["ipc", "daemon", "scheduler"];
const fadeTx = { duration: 0.3 };
const ease = [0.22, 1, 0.36, 1] as const;

export function GatewaySection() {
  const locale = useLocale();
  const [active, setActive] = useState<Mode>("ipc");
  const m = modes[active];

  const pollers: { id: Mode; label: string; y: number; color: string }[] = [
    { id: "ipc", label: "CLIPoller", y: 105, color: "#4ECDC4" },
    { id: "daemon", label: "Gateway", y: 125, color: "#818CF8" },
    { id: "scheduler", label: "Scheduler", y: 145, color: "#F5C542" },
  ];

  const sources: { id: Mode; label: string; y: number; color: string; pathD: string }[] = [
    { id: "ipc", label: "Terminal", y: 20, color: "#4ECDC4", pathD: "M115,40 C140,40 155,40 175,40" },
    { id: "daemon", label: "Slack / Discord", y: 70, color: "#818CF8", pathD: "M115,85 C145,85 155,130 200,130" },
    { id: "scheduler", label: "Cron / AT / EVERY", y: 115, color: "#F5C542", pathD: "M115,130 C145,130 155,148 200,148" },
  ];

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <SectionHeader
          variant="side"
          label="Gateway"
          labelColor="#4ECDC4"
          title="Unified Daemon"
          description={t(locale,
            "REPL과 serve가 각각 HookSystem, Scheduler를 독자적으로 생성하여 이벤트 미수신, jobs.json 경합, 스케줄러의 터미널 침범이 발생했습니다. GeodeRuntime이 모든 상태를 단일 소유하도록 전환하고, CLI는 IPC thin client로 변경했습니다.",
            "REPL and serve each created their own HookSystem and Scheduler, causing missed events, jobs.json contention, and scheduler terminal invasion. Resolved by having GeodeRuntime own all state, with CLI becoming an IPC thin client."
          )}
        />

        {/* Mode selector */}
        <ScrollReveal delay={0.03}>
          <div className="flex justify-center mb-8">
            <div className="inline-flex rounded-full bg-[#0A0F1A] border border-white/[0.06] p-1">
              {modeOrder.map((id) => (
                <button key={id} onClick={() => setActive(id)}
                  className="relative px-5 py-1.5 rounded-full text-xs font-mono font-bold transition-colors duration-200"
                  style={{
                    color: active === id ? "#fff" : "#7A8CA8",
                    background: active === id ? `${modes[id].color}25` : "transparent",
                  }}>
                  {modes[id].label}
                </button>
              ))}
            </div>
          </div>
        </ScrollReveal>

        {/* Architecture SVG with mode highlighting */}
        <ScrollReveal delay={0.05}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-8">
            <svg viewBox="0 0 800 180" className="w-full min-w-[640px]" style={{ maxHeight: 210 }}>
              {/* Source boxes (left) */}
              {sources.map((s) => {
                const isActive = s.id === active;
                return (
                  <g key={s.id}>
                    <motion.rect x={15} y={s.y} width={100} height={35} rx={8}
                      fill="#0A0F1A" stroke={s.color}
                      animate={{ strokeWidth: isActive ? 1.5 : 0.6, strokeOpacity: isActive ? 0.6 : 0.15 }}
                      transition={fadeTx} />
                    <motion.text x={65} y={s.y + 15} textAnchor="middle" fill={s.color}
                      fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}
                      animate={{ fillOpacity: isActive ? 0.9 : 0.25 }} transition={fadeTx}>
                      {s.label}
                    </motion.text>
                    <motion.text x={65} y={s.y + 27} textAnchor="middle" fill={s.color}
                      fontSize={6.5} fontFamily="ui-monospace, monospace"
                      animate={{ fillOpacity: isActive ? 0.5 : 0.12 }} transition={fadeTx}>
                      {s.id === "ipc" ? "cli.sock" : s.id === "daemon" ? "pollers" : "jobs.json"}
                    </motion.text>
                    {/* Arrow to serve */}
                    <motion.path d={s.pathD} fill="none" stroke={s.color}
                      strokeDasharray={s.id === "ipc" ? "4 3" : "none"}
                      animate={{ strokeWidth: isActive ? 1.5 : 0.6, strokeOpacity: isActive ? 0.45 : 0.08 }}
                      transition={fadeTx} />
                  </g>
                );
              })}

              {/* geode serve (central box) */}
              <rect x={175} y={10} width={420} height={155} rx={12}
                fill="#0C1220" stroke="#F4B8C8" strokeWidth={1} strokeOpacity={0.3} />
              <text x={385} y={28} textAnchor="middle" fill="#F4B8C8"
                fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>
                geode serve (GeodeRuntime)
              </text>

              {/* SharedServices */}
              <rect x={190} y={38} width={150} height={55} rx={8}
                fill="#0A0F1A" stroke="#818CF8" strokeWidth={0.6} strokeOpacity={0.25} />
              <text x={265} y={55} textAnchor="middle" fill="#818CF8" fillOpacity={0.7}
                fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>SharedServices</text>
              <text x={265} y={70} textAnchor="middle" fill="#818CF8" fillOpacity={0.35}
                fontSize={6.5} fontFamily="ui-monospace, monospace">ONE Hook + MCP + Skills</text>
              <text x={265} y={82} textAnchor="middle" fill="#818CF8" fillOpacity={0.25}
                fontSize={6.5} fontFamily="ui-monospace, monospace">create_session(mode)</text>

              {/* SessionLane */}
              <rect x={355} y={38} width={115} height={55} rx={8}
                fill="#0A0F1A" stroke="#F5C542" strokeWidth={0.6} strokeOpacity={0.25} />
              <text x={412} y={55} textAnchor="middle" fill="#F5C542" fillOpacity={0.7}
                fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>SessionLane</text>
              <text x={412} y={70} textAnchor="middle" fill="#F5C542" fillOpacity={0.35}
                fontSize={6.5} fontFamily="ui-monospace, monospace">per-key Sem(1)</text>
              <text x={412} y={82} textAnchor="middle" fill="#F5C542" fillOpacity={0.25}
                fontSize={6.5} fontFamily="ui-monospace, monospace">Lane(global, 8)</text>

              {/* AgenticLoop */}
              <rect x={485} y={38} width={95} height={55} rx={8}
                fill="#0A0F1A" stroke="#4ECDC4" strokeWidth={0.6} strokeOpacity={0.25} />
              <text x={532} y={55} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.7}
                fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>AgenticLoop</text>
              <text x={532} y={70} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.35}
                fontSize={6.5} fontFamily="ui-monospace, monospace">while(tool_use)</text>
              <text x={532} y={82} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.25}
                fontSize={6.5} fontFamily="ui-monospace, monospace">time_budget_s</text>

              {/* 3 pollers */}
              {pollers.map((p) => {
                const isActive = p.id === active;
                return (
                  <g key={p.label}>
                    <motion.rect x={200} y={p.y} width={80} height={18} rx={5}
                      fill={isActive ? `${p.color}10` : "#0A0F1A"} stroke={p.color}
                      animate={{ strokeWidth: isActive ? 1.2 : 0.5, strokeOpacity: isActive ? 0.6 : 0.15 }}
                      transition={fadeTx} />
                    <motion.text x={240} y={p.y + 12} textAnchor="middle" fill={p.color}
                      fontSize={7} fontFamily="ui-monospace, monospace" fontWeight={600}
                      animate={{ fillOpacity: isActive ? 0.9 : 0.3 }} transition={fadeTx}>
                      {p.label}
                    </motion.text>
                    {/* Arrow poller → SessionLane */}
                    <motion.path d={`M280,${p.y + 9} L355,${p.y + 9}`} fill="none" stroke={p.color}
                      animate={{ strokeWidth: isActive ? 1.2 : 0.4, strokeOpacity: isActive ? 0.4 : 0.06 }}
                      transition={fadeTx} />
                  </g>
                );
              })}

              {/* SessionLane → AgenticLoop */}
              <path d="M470,65 L485,65" stroke="white" strokeOpacity={0.15} strokeWidth={0.8} />

              {/* Result output */}
              <motion.rect x={620} y={45} width={95} height={40} rx={8}
                fill="#0A0F1A" stroke="#34D399"
                animate={{ strokeWidth: 1, strokeOpacity: 0.3 }} transition={fadeTx} />
              <text x={667} y={62} textAnchor="middle" fill="#34D399" fillOpacity={0.6}
                fontSize={8} fontFamily="ui-monospace, monospace" fontWeight={600}>Result</text>
              <text x={667} y={76} textAnchor="middle" fill="#34D399" fillOpacity={0.3}
                fontSize={6.5} fontFamily="ui-monospace, monospace">→ channel</text>
              <path d="M580,65 L620,65" stroke="white" strokeOpacity={0.15} strokeWidth={0.8} />

              {/* Active mode indicator */}
              <AnimatePresence mode="wait">
                <motion.text
                  key={active}
                  x={400} y={175} textAnchor="middle"
                  fill={m.color} fillOpacity={0.4}
                  fontSize={8} fontFamily="ui-monospace, monospace"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                  transition={fadeTx}>
                  {m.source} → {m.poller} → acquire_all(key) → AgenticLoop → Result
                </motion.text>
              </AnimatePresence>
            </svg>
          </div>
        </ScrollReveal>

        {/* Active mode detail card */}
        <ScrollReveal delay={0.1}>
          <div className="min-h-[160px]">
            <AnimatePresence mode="wait">
              <motion.div
                key={active}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.25, ease }}
                className="rounded-xl border px-6 py-5"
                style={{
                  borderColor: `${m.color}20`,
                  background: `linear-gradient(160deg, ${m.color}08, transparent 70%)`,
                }}
              >
                <div className="flex items-center gap-3 mb-3">
                  <span className="text-lg font-mono font-bold" style={{ color: m.color }}>{m.label}</span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full"
                    style={{ color: m.color, background: `${m.color}10`, border: `1px solid ${m.color}20` }}>
                    {m.sub}
                  </span>
                </div>
                <p className="text-sm text-[#A0B4D4] leading-relaxed mb-3">
                  {locale === "en" ? m.descEn : m.descKo}
                </p>
                {/* CLI startup terminal mockup (IPC only) */}
                {active === "ipc" && (
                  <div className="rounded-lg bg-[#060B14] px-5 py-4 font-mono text-xs leading-relaxed border border-white/[0.03] mb-3 overflow-x-hidden">
                    <div className="flex items-center gap-1.5 mb-3">
                      <span className="w-2.5 h-2.5 rounded-full bg-[#FF5F57]/80" />
                      <span className="w-2.5 h-2.5 rounded-full bg-[#FEBC2E]/80" />
                      <span className="w-2.5 h-2.5 rounded-full bg-[#28C840]/80" />
                      <span className="ml-2 text-[10px] text-white/20">geode</span>
                    </div>
                    <pre className="text-white/40 whitespace-pre">{`  `}<span style={{color:"#9775c4"}}>╲╲</span><span className="text-white/80">{`( ◕ ᵕ ◕ )`}</span><span style={{color:"#9775c4"}}>╱╱</span>{`  `}<span style={{color:"#5f9ea0",fontWeight:700}}>GEODE</span>{` v0.65.0`}</pre>
                    <pre className="text-white/25 whitespace-pre">{`                       claude-opus-4-7 · autonomous execution agent`}</pre>
                    <pre className="text-white/20 whitespace-pre">{`                       /Users/mango/workspace/resume`}</pre>
                    <pre className="text-white/25 whitespace-pre mt-2">{`  `}<span className="text-white/30">harness:</span>{` GEODE`}</pre>
                    <pre className="text-white/40 whitespace-pre">{`  `}<span style={{color:"#22c55e",fontWeight:700}}>✓</span>{` LLM Analysis  `}<span style={{color:"#22c55e",fontWeight:700}}>✓</span>{` Project Memory  `}<span style={{color:"#22c55e",fontWeight:700}}>✓</span>{` User Profile`}</pre>
                    <pre className="text-white/40 whitespace-pre">{`  `}<span style={{color:"#22c55e",fontWeight:700}}>✓</span>{` Dry-Run Analysis  `}<span style={{color:"#22c55e",fontWeight:700}}>✓</span>{` IP Search`}</pre>
                    <pre className="text-white/20 whitespace-pre mt-2">{`  /help for commands  ·  type naturally`}</pre>
                    <pre className="text-white/25 whitespace-pre mt-2">{`  Connected to serve via IPC`}</pre>
                    <pre className="whitespace-pre" style={{color:"#22c55e",fontWeight:700}}>{`  Session: cli-6b55b450`}</pre>
                  </div>
                )}

                <div className="flex flex-wrap gap-2">
                  {(locale === "en" ? m.detailsEn : m.detailsKo).map((d) => (
                    <span key={d} className="inline-flex items-center gap-1.5 text-[11px] font-mono px-2 py-1 rounded-lg"
                      style={{ color: `${m.color}`, background: `${m.color}08`, border: `1px solid ${m.color}12` }}>
                      <span className="w-1 h-1 rounded-full" style={{ background: m.color, opacity: 0.6 }} />
                      {d}
                    </span>
                  ))}
                </div>
              </motion.div>
            </AnimatePresence>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
