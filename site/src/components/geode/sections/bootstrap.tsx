"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { useLocale, t } from "../locale-context";

const steps = [
  { id: 1, name: "Hooks", detailKo: "HookSystem 58 events (P30→P200)", detailEn: "HookSystem 58 events (P30→P200)", subKo: "전 모듈이 의존하는 이벤트 버스. 가장 먼저 기동되어 이후 단계의 발화를 수신할 준비를 마친다", subEn: "Event bus that every module depends on. Brought up first so all subsequent stages can fire into a wired bus", color: "#4ECDC4" },
  { id: 2, name: "Session", detailKo: "InMemory / Hybrid SessionStore", detailEn: "InMemory / Hybrid SessionStore", subKo: "SessionMode(REPL/IPC/DAEMON)에 따라 스토어 분기", subEn: "Store branches by SessionMode (REPL/IPC/DAEMON)", color: "#60A5FA" },
  { id: 3, name: "Memory", detailKo: "ProjectMemory + MonoLake + UserProfile + Journal", detailEn: "ProjectMemory + MonoLake + UserProfile + Journal", subKo: "5-Tier 메모리 계층 마운트. Session 스토어에 의존", subEn: "Mount 5-tier memory hierarchy. Depends on session store", color: "#F4B8C8" },
  { id: 4, name: "Config", detailKo: ".env hot-reload + constraint validation", detailEn: ".env hot-reload + constraint validation", subKo: "ConfigWatcher 시작. Hook으로 CONFIG_RELOADED 발화", subEn: "Start ConfigWatcher. Fires CONFIG_RELOADED via Hook", color: "#F5C542" },
  { id: 5, name: "TaskGraph", detailKo: "create_geode_task_graph() + HookBridge", detailEn: "create_geode_task_graph() + HookBridge", subKo: "Hook 이벤트와 Task 상태를 브릿지 연결", subEn: "Bridge Hook events to Task state transitions", color: "#818CF8" },
  { id: 6, name: "Prompt", detailKo: "SkillRegistry discover + PromptAssembler", detailEn: "SkillRegistry discover + PromptAssembler", subKo: "41 스캐폴드 스킬을 5계층 디렉토리에서 디스커버하고 시스템 프롬프트를 조립한다. 결과는 frozen=True 의 AssembledPrompt", subEn: "Discover 41 scaffold skills across 5-tier directories and assemble the system prompt. Result is a frozen AssembledPrompt", color: "#C084FC" },
  { id: 7, name: "Graph", detailKo: "StateGraph compile + checkpoint setup", detailEn: "StateGraph compile + checkpoint setup", subKo: "LangGraph 파이프라인 컴파일. 부트스트랩 완료", subEn: "Compile LangGraph pipeline. Bootstrap complete", color: "#34D399" },
];

const ease = [0.22, 1, 0.36, 1] as const;

export function BootstrapSection() {
  const locale = useLocale();
  const [active, setActive] = useState(0);
  const [auto, setAuto] = useState(true);

  useEffect(() => {
    if (!auto) return;
    const timer = setInterval(() => {
      setActive((prev) => (prev + 1) % steps.length);
    }, 2200);
    return () => clearInterval(timer);
  }, [auto]);

  const handleClick = (i: number) => {
    setActive(i);
    setAuto(false);
  };

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[var(--ink-3)] uppercase tracking-[0.25em] mb-3">
            § 3.5 부팅 시퀀스
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-[var(--ink-1)] mb-3">
            {t(locale, "7단계로 구성된 부팅 시퀀스.", "A seven-stage boot sequence.")}
          </h2>
          <p className="text-sm sm:text-base text-[var(--ink-2)] max-w-2xl mb-8 leading-relaxed">
            {t(locale,
              "GEODE는 7단계를 순차적으로 거쳐 부팅합니다. 각 단계는 다음 단계가 필요로 하는 결과물을 생성합니다. 어느 한 단계에서 실패가 발생하면 전체 부팅이 중단되지 않고 부분 부팅으로 전환됩니다. 사용 가능한 표면만 활성화하고 나머지는 비활성화하며, geode doctor 명령으로 실패 지점을 확인할 수 있습니다.",
              "GEODE boots through 7 sequential stages. Each stage produces output that the next stage requires. If any stage fails, the boot transitions to partial boot mode rather than halting entirely — usable surfaces remain active while the rest are disabled, and the failed stage can be inspected via the geode doctor command."
            )}
          </p>
        </ScrollReveal>

        {/* Pipeline SVG */}
        <ScrollReveal delay={0.1}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
            <svg viewBox="0 0 780 130" className="w-full min-w-[600px]" style={{ maxHeight: 150 }}>
              {/* Progress track */}
              <line x1={75} y1={52} x2={745} y2={52} stroke="white" strokeOpacity={0.06} strokeWidth={2} />
              <motion.line
                x1={75} y1={52} y2={52}
                stroke="#34D399" strokeWidth={2} strokeOpacity={0.4}
                animate={{ x2: 75 + active * (670 / (steps.length - 1)) }}
                transition={{ duration: 0.6, ease }}
              />

              {steps.map((s, i) => {
                const x = 75 + i * (670 / (steps.length - 1));
                const isDone = i < active;
                const isActive = i === active;
                const isPending = i > active;

                return (
                  <g key={s.id} onClick={() => handleClick(i)} style={{ cursor: "pointer" }}>
                    {/* Pulse ring for active */}
                    {isActive && (
                      <circle cx={x} cy={52} r={22} fill="none" stroke={s.color} strokeWidth={1}>
                        <animate attributeName="r" values="18;26;18" dur="2s" repeatCount="indefinite" />
                        <animate attributeName="stroke-opacity" values="0.4;0;0.4" dur="2s" repeatCount="indefinite" />
                      </circle>
                    )}

                    {/* Node circle */}
                    <motion.circle
                      cx={x} cy={52} r={18}
                      fill={isDone ? `${s.color}15` : isActive ? `${s.color}20` : "var(--paper-2)"}
                      stroke={s.color}
                      strokeWidth={isActive ? 2 : isDone ? 1.2 : 0.6}
                      animate={{
                        strokeOpacity: isPending ? 0.15 : isActive ? 0.8 : 0.5,
                        scale: isActive ? 1.05 : 1,
                      }}
                      transition={{ duration: 0.3, ease }}
                    />

                    {/* Step number or check */}
                    <motion.text
                      x={x} y={isDone ? 56 : 48} textAnchor="middle"
                      fill={s.color}
                      fontSize={isDone ? 14 : 10}
                      fontFamily="ui-monospace, monospace"
                      fontWeight={700}
                      animate={{ fillOpacity: isPending ? 0.2 : isActive ? 1 : 0.7 }}
                      transition={{ duration: 0.3 }}
                    >
                      {isDone ? "✓" : s.id}
                    </motion.text>

                    {/* Name label */}
                    {!isDone && (
                      <motion.text
                        x={x} y={62} textAnchor="middle"
                        fill={s.color}
                        fontSize={7}
                        fontFamily="ui-monospace, monospace"
                        animate={{ fillOpacity: isPending ? 0.15 : 0.5 }}
                        transition={{ duration: 0.3 }}
                      >
                        {s.name}
                      </motion.text>
                    )}

                    {/* Top label for done/active */}
                    <motion.text
                      x={x} y={22} textAnchor="middle"
                      fill={s.color}
                      fontSize={8}
                      fontFamily="ui-monospace, monospace"
                      fontWeight={isActive ? 700 : 400}
                      animate={{ fillOpacity: isPending ? 0.1 : isActive ? 0.8 : 0.35 }}
                      transition={{ duration: 0.3 }}
                    >
                      {s.name}
                    </motion.text>
                  </g>
                );
              })}

              {/* Bottom: elapsed simulation */}
              <motion.text
                x={75 + active * (670 / (steps.length - 1))} y={95}
                textAnchor="middle" fill={steps[active].color} fillOpacity={0.5}
                fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}
                animate={{ x: 75 + active * (670 / (steps.length - 1)) }}
                transition={{ duration: 0.6, ease }}
              >
                Step {active + 1}/7
              </motion.text>

              {/* Total time */}
              <text x={390} y={120} textAnchor="middle" fill="white" fillOpacity={0.2}
                fontSize={8} fontFamily="ui-monospace, monospace">
                GeodeRuntime.create() → 70 LOC (243→70)
              </text>
            </svg>
          </div>
        </ScrollReveal>

        {/* Active step detail card */}
        <ScrollReveal delay={0.15}>
          <div className="min-h-[100px]">
            <AnimatePresence mode="wait">
              <motion.div
                key={active}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.25 }}
                className="rounded-xl border px-6 py-5 mb-6"
                style={{
                  borderColor: `${steps[active].color}20`,
                  background: `linear-gradient(160deg, ${steps[active].color}08, transparent 70%)`,
                }}
              >
                <div className="flex items-center gap-3 mb-2">
                  <span className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-mono font-black"
                    style={{ background: `${steps[active].color}15`, color: steps[active].color }}>
                    {active + 1}
                  </span>
                  <span className="text-lg font-bold text-[var(--ink-1)]">{steps[active].name}</span>
                  <span className="text-xs font-mono px-2 py-0.5 rounded-full"
                    style={{ color: steps[active].color, background: `${steps[active].color}10`, border: `1px solid ${steps[active].color}20` }}>
                    {locale === "en" ? steps[active].detailEn : steps[active].detailKo}
                  </span>
                </div>
                <p className="text-sm text-[var(--ink-2)] leading-relaxed pl-11">
                  {locale === "en" ? steps[active].subEn : steps[active].subKo}
                </p>
              </motion.div>
            </AnimatePresence>
          </div>
        </ScrollReveal>

        {/* Step summary grid */}
        <ScrollReveal delay={0.2}>
          <div className="grid grid-cols-7 gap-1.5">
            {steps.map((s, i) => {
              const isDone = i < active;
              const isActive = i === active;
              return (
                <button
                  key={s.id}
                  onClick={() => handleClick(i)}
                  className="text-center py-2.5 rounded-lg border transition-all duration-300"
                  style={{
                    borderColor: isActive ? `${s.color}30` : "rgba(255,255,255,0.04)",
                    background: isActive ? `${s.color}08` : isDone ? `${s.color}04` : "transparent",
                  }}
                >
                  <div className="text-sm font-bold font-mono" style={{ color: s.color, opacity: isActive ? 1 : isDone ? 0.6 : 0.2 }}>
                    {isDone ? "✓" : s.id}
                  </div>
                  <div className="text-[9px] font-mono mt-0.5" style={{ color: s.color, opacity: isActive ? 0.7 : 0.25 }}>
                    {s.name}
                  </div>
                </button>
              );
            })}
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
