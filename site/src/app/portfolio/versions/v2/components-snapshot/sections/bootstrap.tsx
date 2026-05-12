"use client";

import { ScrollReveal } from "../scroll-reveal";

const steps = [
  { id: 1, name: "Hooks", detail: "HookSystem + 17 handlers (P30→P200)", color: "#4ECDC4" },
  { id: 2, name: "Session", detail: "InMemory / Hybrid SessionStore", color: "#60A5FA" },
  { id: 3, name: "Memory", detail: "ProjectMemory + MonoLake + UserProfile + Journal + Vault", color: "#F4B8C8" },
  { id: 4, name: "ConfigWatch", detail: ".env hot-reload + constraint validation", color: "#F5C542" },
  { id: 5, name: "TaskGraph", detail: "create_geode_task_graph() + HookBridge", color: "#818CF8" },
  { id: 6, name: "Prompt", detail: "SkillRegistry discover + PromptAssembler", color: "#C084FC" },
  { id: 7, name: "Graph", detail: "StateGraph compile + checkpoint setup", color: "#34D399" },
];

export function BootstrapSection() {
  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#34D399]/60 uppercase tracking-[0.25em] mb-3">
            Bootstrap
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-3">
            초기화 시퀀스
          </h2>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-8 leading-relaxed">
            7단계 순차 초기화. 각 단계가 이전 단계의 결과를 의존성으로 받아 조립됩니다.
            한 단계라도 실패하면 graceful degradation으로 선택적 부팅합니다.
          </p>
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
            <svg viewBox="0 0 780 120" className="w-full min-w-[600px]" style={{ maxHeight: 140 }}>
              {steps.map((s, i) => {
                const x = 30 + i * 108;
                return (
                  <g key={s.id}>
                    <rect x={x} y={25} width={90} height={55} rx={10} fill="#0A0F1A" stroke={s.color} strokeWidth={0.8} strokeOpacity={0.25} />
                    <text x={x + 45} y={47} textAnchor="middle" fill={s.color} fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>{s.name}</text>
                    <text x={x + 45} y={63} textAnchor="middle" fill={s.color} fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">Step {s.id}</text>
                    {i < steps.length - 1 && (
                      <line x1={x + 90} y1={52} x2={x + 108} y2={52} stroke="white" strokeOpacity={0.14} strokeWidth={1} />
                    )}
                  </g>
                );
              })}
              <text x={390} y={105} textAnchor="middle" fill="white" fillOpacity={0.18} fontSize={9} fontFamily="ui-monospace, monospace" letterSpacing="0.1em">
                HOOKS → SESSION → MEMORY → CONFIG → TASK → PROMPT → GRAPH
              </text>
            </svg>
          </div>

          <div className="space-y-2">
            {steps.map((s) => (
              <div key={s.id} className="flex items-center gap-4 px-4 py-2.5 rounded-lg border border-white/[0.04]" style={{ background: `${s.color}03` }}>
                <span className="shrink-0 w-7 text-center text-[11px] font-mono font-bold" style={{ color: s.color }}>{s.id}</span>
                <span className="text-sm font-medium text-white/80 w-[100px] shrink-0">{s.name}</span>
                <span className="text-sm text-[#7A8CA8]">{s.detail}</span>
              </div>
            ))}
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
