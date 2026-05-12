"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";

/* ── Gateway modes ── */
type Mode = "slack" | "serve" | "mcp";

const modes = [
  {
    id: "slack" as Mode,
    label: "Slack Gateway",
    color: "#4ECDC4",
    desc: "Slack 채널에서 @geode 멘션으로 분석을 요청합니다. ChannelBinding 규칙에 따라 자동 응답하고, 쓰레드별로 멀티턴 대화를 유지합니다.",
    flow: [
      { step: "Slack 메시지", detail: "@geode Berserk 분석해줘" },
      { step: "SlackPoller", detail: "MCP로 채널 히스토리 폴링" },
      { step: "ChannelManager", detail: "바인딩 매칭 → 세션 키 생성" },
      { step: "AgenticLoop", detail: "hitl_level=0, max_rounds=30" },
      { step: "응답", detail: "SlackNotificationAdapter → 채널" },
    ],
    tags: ["ChannelBinding", "멀티턴 세션", "LaneQueue 동시성 제어"],
  },
  {
    id: "serve" as Mode,
    label: "Headless Serve",
    color: "#818CF8",
    desc: "geode serve --poll 3.0 명령으로 REPL 없이 데몬 모드로 실행합니다. Slack/Discord/Telegram 폴러와 Webhook을 동시에 가동합니다.",
    flow: [
      { step: "bootstrap", detail: "domain, memory, MCP, skills 초기화" },
      { step: "gateway 빌드", detail: "MCP startup + 바인딩 로드" },
      { step: "폴러 시작", detail: "Slack/Discord/Telegram 병렬 쓰레드" },
      { step: "webhook", detail: "HTTP POST :8765 (선택)" },
      { step: "signal", detail: "SIGINT/SIGTERM → graceful shutdown" },
    ],
    tags: ["데몬 모드", "multi-poller", "Webhook :8765"],
  },
  {
    id: "mcp" as Mode,
    label: "MCP Server",
    color: "#F5C542",
    desc: "FastMCP 기반 6개 도구를 외부에 노출합니다. Gateway와 CLI 모두 이 MCP 서버를 통해 파이프라인에 접근합니다.",
    flow: [
      { step: "analyze_ip", detail: "전체 파이프라인 실행" },
      { step: "quick_score", detail: "스코어링만 (dry-run)" },
      { step: "get_ip_signals", detail: "커뮤니티 시그널 조회" },
      { step: "query_memory", detail: "프로젝트 메모리 검색" },
      { step: "list_fixtures", detail: "분석 가능 IP 목록" },
      { step: "get_health", detail: "파이프라인 + 프로바이더 상태" },
    ],
    tags: ["FastMCP", "6 Tools", "2 Resources"],
  },
];

export function GatewaySection() {
  const [activeMode, setActiveMode] = useState<Mode>("slack");
  const mode = modes.find((m) => m.id === activeMode)!;

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#4ECDC4]/60 uppercase tracking-[0.25em] mb-3">
            Gateway
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-3">
            Headless Execution
          </h2>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-8 leading-relaxed">
            CLI 없이도 Slack 멘션, HTTP Webhook, MCP 호출로 GEODE 파이프라인을 실행합니다.
            <code className="text-[#818CF8]/70 ml-1">geode serve</code> 한 번이면 데몬 모드로 상시 대기합니다.
          </p>
        </ScrollReveal>

        {/* ── Mode selector ── */}
        <ScrollReveal delay={0.05}>
          <div className="flex gap-2 mb-8 flex-wrap">
            {modes.map((m) => (
              <button
                key={m.id}
                onClick={() => setActiveMode(m.id)}
                className="px-4 py-2 rounded-lg text-xs font-mono font-bold transition-all duration-300"
                style={{
                  color: activeMode === m.id ? m.color : "#5A6A8A",
                  background: activeMode === m.id ? `${m.color}08` : "transparent",
                  border: `1px solid ${activeMode === m.id ? `${m.color}20` : "rgba(255,255,255,0.04)"}`,
                }}
              >
                {m.label}
              </button>
            ))}
          </div>
        </ScrollReveal>

        {/* ── Gateway Architecture SVG ── */}
        <ScrollReveal delay={0.08}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-8">
            <svg viewBox="0 0 760 170" className="w-full min-w-[560px]" style={{ maxHeight: 200 }}>
              {[
                { label: "Slack", y: 30, color: "#4ECDC4" },
                { label: "Webhook", y: 80, color: "#F5C542" },
                { label: "MCP", y: 130, color: "#818CF8" },
              ].map((s) => (
                <g key={s.label}>
                  <rect x={20} y={s.y} width={80} height={36} rx={8} fill="#0A0F1A" stroke={s.color} strokeWidth={0.8} strokeOpacity={0.25} />
                  <text x={60} y={s.y + 22} textAnchor="middle" fill={s.color} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>{s.label}</text>
                  <line x1={100} y1={s.y + 18} x2={160} y2={85} stroke={s.color} strokeOpacity={0.18} strokeWidth={1} />
                </g>
              ))}
              <rect x={160} y={55} width={120} height={60} rx={10} fill="#0A0F1A" stroke="#F4B8C8" strokeWidth={1} strokeOpacity={0.3} />
              <text x={220} y={78} textAnchor="middle" fill="#F4B8C8" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>ChannelMgr</text>
              <text x={220} y={95} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.35} fontSize={8} fontFamily="ui-monospace, monospace">binding match</text>
              <line x1={280} y1={85} x2={330} y2={85} stroke="white" strokeOpacity={0.14} strokeWidth={1} />
              <rect x={330} y={55} width={100} height={60} rx={10} fill="#0A0F1A" stroke="#C084FC" strokeWidth={0.8} strokeOpacity={0.25} />
              <text x={380} y={78} textAnchor="middle" fill="#C084FC" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>SessionStore</text>
              <text x={380} y={95} textAnchor="middle" fill="#C084FC" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">멀티턴</text>
              <line x1={430} y1={85} x2={480} y2={85} stroke="white" strokeOpacity={0.14} strokeWidth={1} />
              <rect x={480} y={50} width={120} height={70} rx={10} fill="#0A0F1A" stroke="#4ECDC4" strokeWidth={1} strokeOpacity={0.3} />
              <text x={540} y={78} textAnchor="middle" fill="#4ECDC4" fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={700}>AgenticLoop</text>
              <text x={540} y={95} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">hitl=0, 30 rounds</text>
              <line x1={600} y1={85} x2={650} y2={85} stroke="white" strokeOpacity={0.14} strokeWidth={1} />
              <rect x={650} y={60} width={90} height={50} rx={10} fill="#0A0F1A" stroke="#34D399" strokeWidth={0.8} strokeOpacity={0.25} />
              <text x={695} y={82} textAnchor="middle" fill="#34D399" fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>Response</text>
              <text x={695} y={97} textAnchor="middle" fill="#34D399" fillOpacity={0.3} fontSize={8} fontFamily="ui-monospace, monospace">→ channel</text>
              <text x={380} y={22} textAnchor="middle" fill="white" fillOpacity={0.28} fontSize={9} fontFamily="ui-monospace, monospace" letterSpacing="0.1em">INBOUND → ROUTE → SESSION → LOOP → RESPOND</text>
            </svg>
          </div>
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          <div
            className="rounded-xl border px-5 sm:px-6 py-5 transition-all duration-300 mb-8"
            style={{
              borderColor: `${mode.color}20`,
              background: `linear-gradient(135deg, ${mode.color}06, transparent 60%)`,
            }}
          >
            <p className="text-sm text-[#8B9CC0] leading-relaxed mb-5">
              {mode.desc}
            </p>

            {/* Flow steps */}
            <div className="space-y-2 mb-4">
              {mode.flow.map((f, i) => (
                <div key={f.step} className="flex items-center gap-3">
                  <span
                    className="shrink-0 w-6 h-6 rounded flex items-center justify-center text-[10px] font-mono font-bold"
                    style={{ color: mode.color, background: `${mode.color}10` }}
                  >
                    {i + 1}
                  </span>
                  <span className="text-sm font-medium text-white/70 w-[120px] sm:w-[140px] shrink-0">{f.step}</span>
                  <span className="text-sm text-[#7A8CA8]">{f.detail}</span>
                </div>
              ))}
            </div>

            {/* Tags */}
            <div className="flex flex-wrap gap-1.5">
              {mode.tags.map((t) => (
                <span
                  key={t}
                  className="px-2 py-0.5 rounded text-[11px] font-mono"
                  style={{ color: `${mode.color}80`, background: `${mode.color}08`, border: `1px solid ${mode.color}15` }}
                >
                  {t}
                </span>
              ))}
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
