"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";
import { SectionHeader } from "../ui/section-header";
import { TabBar } from "../ui/tab-bar";
import { useLocale, t } from "../locale-context";

/* ── Channel types ── */
type Channel = "slack" | "webhook" | "mcp";

const channels: {
  id: Channel;
  label: string;
  color: string;
  descKo: string;
  descEn: string;
  flow: { step: string; detailKo: string; detailEn: string }[];
  tagsKo: string[];
  tagsEn: string[];
}[] = [
  {
    id: "slack",
    label: "Slack Gateway",
    color: "#4ECDC4",
    descKo: "Slack 채널에서 @geode 멘션으로 분석을 요청합니다. ChannelBinding 규칙에 따라 자동 응답하고, 쓰레드별로 멀티턴 대화를 유지합니다.",
    descEn: "Request analysis by @geode mention in a Slack channel. Auto-responds per ChannelBinding rules and maintains multi-turn conversations per thread.",
    flow: [
      { step: "SlackPoller", detailKo: "MCP로 채널 히스토리 폴링 (poll_interval=3s)", detailEn: "Polls channel history via MCP (poll_interval=3s)" },
      { step: "ChannelManager", detailKo: "바인딩 매칭 → 세션 키 생성 → LaneQueue", detailEn: "Binding match → session key creation → LaneQueue" },
      { step: "AgenticLoop", detailKo: "hitl_level=0, time_budget_s=300", detailEn: "hitl_level=0, time_budget_s=300" },
      { step: "SlackNotificationAdapter", detailKo: "결과를 쓰레드에 응답", detailEn: "Replies result to thread" },
    ],
    tagsKo: ["ChannelBinding", "멀티턴 세션", "LaneQueue 동시성 제어", "binding hot-reload"],
    tagsEn: ["ChannelBinding", "Multi-turn session", "LaneQueue concurrency", "binding hot-reload"],
  },
  {
    id: "webhook",
    label: "Webhook",
    color: "#F5C542",
    descKo: "HTTP POST :8765 엔드포인트로 외부 시스템(CI/CD, 모니터링)에서 파이프라인을 트리거합니다. JSON payload로 IP 이름과 분석 옵션을 전달합니다.",
    descEn: "External systems (CI/CD, monitoring) trigger the pipeline via HTTP POST :8765. Pass IP name and analysis options as JSON payload.",
    flow: [
      { step: "WebhookHandler", detailKo: "BaseHTTPRequestHandler.do_POST()", detailEn: "BaseHTTPRequestHandler.do_POST()" },
      { step: "Payload Parse", detailKo: "ip_name, options, callback_url 추출", detailEn: "Extract ip_name, options, callback_url" },
      { step: "ChannelManager", detailKo: "webhook 채널로 라우팅 → 세션 생성", detailEn: "Route to webhook channel → create session" },
      { step: "AgenticLoop", detailKo: "분석 실행 → callback_url에 결과 POST", detailEn: "Run analysis → POST result to callback_url" },
    ],
    tagsKo: ["HTTP POST :8765", "JSON Payload", "Callback URL", "CI/CD 연동"],
    tagsEn: ["HTTP POST :8765", "JSON Payload", "Callback URL", "CI/CD integration"],
  },
  {
    id: "mcp",
    label: "MCP Server",
    color: "#818CF8",
    descKo: "FastMCP 기반 6개 도구를 외부에 노출합니다. Claude Code, Cursor 등 MCP 클라이언트가 직접 파이프라인에 접근합니다.",
    descEn: "Exposes 6 tools externally via FastMCP. MCP clients such as Claude Code and Cursor access the pipeline directly.",
    flow: [
      { step: "analyze_ip", detailKo: "전체 파이프라인 실행 (full_pipeline)", detailEn: "Full pipeline execution (full_pipeline)" },
      { step: "quick_score", detailKo: "스코어링만 실행 (dry-run)", detailEn: "Scoring only (dry-run)" },
      { step: "get_ip_signals", detailKo: "커뮤니티 시그널 조회", detailEn: "Query community signals" },
      { step: "query_memory", detailKo: "프로젝트 메모리 검색", detailEn: "Search project memory" },
      { step: "list_fixtures", detailKo: "분석 가능 IP 목록 반환", detailEn: "Return list of analyzable IPs" },
      { step: "get_health", detailKo: "파이프라인 + 프로바이더 상태 체크", detailEn: "Pipeline + provider health check" },
    ],
    tagsKo: ["FastMCP", "6 Tools", "2 Resources", "config.toml 단일 진실 소스"],
    tagsEn: ["FastMCP", "6 Tools", "2 Resources", "config.toml single source of truth"],
  },
];

export function HeadlessSection() {
  const locale = useLocale();
  const [active, setActive] = useState<Channel>("slack");
  const ch = channels.find((c) => c.id === active)!;

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <SectionHeader
          variant="quote"
          labelColor="#818CF8"
          title="Daemon Mode"
          description={t(locale,
            "geode serve가 유일한 데몬. config.toml [gateway] pollers로 동적 등록. SessionLane(per-key) + Lane(global, max=8)이 동시성 제어. ONE HookSystem, ONE MCP, ONE SkillRegistry.",
            "geode serve is the single daemon. Pollers registered dynamically via config.toml [gateway]. SessionLane(per-key) + Lane(global, max=8) control concurrency. ONE HookSystem, ONE MCP, ONE SkillRegistry."
          )}
        />

        {/* ── Serve architecture SVG ── */}
        <ScrollReveal delay={0.05}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-8">
            <svg viewBox="0 0 760 180" className="w-full min-w-[560px]" style={{ maxHeight: 210 }}>
              {/* geode serve box */}
              <rect x={15} y={55} width={100} height={70} rx={10}
                fill="#0C1220" stroke="#818CF8" strokeWidth={1.2} strokeOpacity={0.5} />
              <text x={65} y={80} textAnchor="middle" fill="#818CF8"
                fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>geode serve</text>
              <text x={65} y={96} textAnchor="middle" fill="#818CF8" fillOpacity={0.4}
                fontSize={8} fontFamily="ui-monospace, monospace">--poll 3.0</text>
              <text x={65} y={112} textAnchor="middle" fill="#818CF8" fillOpacity={0.3}
                fontSize={7} fontFamily="ui-monospace, monospace">hitl_level=0</text>

              {/* Arrow → ChannelMgr */}
              <path d="M115,90 C130,90 140,90 155,90" stroke="white" strokeOpacity={0.2} strokeWidth={1} fill="none" />

              {/* ChannelManager */}
              <rect x={155} y={55} width={120} height={70} rx={10}
                fill="#0C1220" stroke="#F4B8C8" strokeWidth={1} strokeOpacity={0.4} />
              <text x={215} y={80} textAnchor="middle" fill="#F4B8C8"
                fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>ChannelMgr</text>
              <text x={215} y={96} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.4}
                fontSize={8} fontFamily="ui-monospace, monospace">binding match</text>
              <text x={215} y={112} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.3}
                fontSize={7} fontFamily="ui-monospace, monospace">LaneQueue</text>

              {/* Pollers branching out from ChannelMgr */}
              {[
                { label: "Slack", y: 15, color: "#4ECDC4" },
                { label: "Webhook", y: 75, color: "#F5C542" },
                { label: "MCP", y: 135, color: "#818CF8" },
              ].map((p) => (
                <g key={p.label}>
                  <rect x={320} y={p.y} width={80} height={30} rx={7}
                    fill="#0A0F1A" stroke={p.color} strokeWidth={0.7} strokeOpacity={0.35} />
                  <text x={360} y={p.y + 19} textAnchor="middle" fill={p.color}
                    fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>{p.label}</text>
                  <path d={`M275,90 C290,90 305,${p.y + 15} 320,${p.y + 15}`}
                    stroke={p.color} strokeOpacity={0.25} strokeWidth={1} fill="none" />
                </g>
              ))}

              {/* Arrows to SessionStore */}
              {[15, 75, 135].map((y) => (
                <path key={y} d={`M400,${y + 15} C420,${y + 15} 430,90 450,90`}
                  stroke="white" strokeOpacity={0.15} strokeWidth={0.8} fill="none" />
              ))}

              {/* SessionStore */}
              <rect x={450} y={60} width={100} height={60} rx={10}
                fill="#0C1220" stroke="#C084FC" strokeWidth={0.8} strokeOpacity={0.35} />
              <text x={500} y={83} textAnchor="middle" fill="#C084FC"
                fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>SessionStore</text>
              <text x={500} y={100} textAnchor="middle" fill="#C084FC" fillOpacity={0.4}
                fontSize={8} fontFamily="ui-monospace, monospace">멀티턴</text>

              {/* → AgenticLoop */}
              <path d="M550,90 C565,90 575,90 590,90" stroke="white" strokeOpacity={0.2} strokeWidth={1} fill="none" />

              <rect x={590} y={55} width={120} height={70} rx={10}
                fill="#0C1220" stroke="#4ECDC4" strokeWidth={1} strokeOpacity={0.45} />
              <text x={650} y={82} textAnchor="middle" fill="#4ECDC4"
                fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>AgenticLoop</text>
              <text x={650} y={100} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.4}
                fontSize={8} fontFamily="ui-monospace, monospace">time_budget_s=300</text>

              {/* Top label */}
              <text x={380} y={10} textAnchor="middle" fill="white" fillOpacity={0.2}
                fontSize={8} fontFamily="ui-monospace, monospace" letterSpacing="0.1em">
                SERVE → CHANNEL_MGR → POLLERS → SESSION → LOOP
              </text>

              {/* Signal handling */}
              <text x={65} y={145} textAnchor="middle" fill="#818CF8" fillOpacity={0.25}
                fontSize={7} fontFamily="ui-monospace, monospace">SIGINT/SIGTERM → graceful shutdown</text>
            </svg>
          </div>
        </ScrollReveal>

        {/* ── Channel selector ── */}
        <ScrollReveal delay={0.08}>
          <TabBar
            variant="pill"
            tabs={channels.map((c) => ({ id: c.id, label: c.label, color: c.color }))}
            activeId={active}
            onSelect={(id) => setActive(id as Channel)}
          />
        </ScrollReveal>

        {/* ── Channel detail ── */}
        <ScrollReveal delay={0.1}>
          <div
            className="rounded-xl border px-5 sm:px-6 py-5 transition-all duration-300"
            style={{
              borderColor: `${ch.color}20`,
              background: `linear-gradient(135deg, ${ch.color}06, transparent 60%)`,
            }}
          >
            <p className="text-sm text-[#A0B4D4] leading-relaxed mb-5">{locale === "en" ? ch.descEn : ch.descKo}</p>
            <div className="space-y-2 mb-4">
              {ch.flow.map((f, i) => (
                <div key={f.step} className="flex items-center gap-3">
                  <span className="shrink-0 w-6 h-6 rounded flex items-center justify-center text-[10px] font-mono font-bold"
                    style={{ color: ch.color, background: `${ch.color}10` }}>{i + 1}</span>
                  <span className="text-sm font-medium text-white/70 w-[140px] sm:w-[180px] shrink-0 font-mono">{f.step}</span>
                  <span className="text-sm text-[#9BB0CC]">{locale === "en" ? f.detailEn : f.detailKo}</span>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(locale === "en" ? ch.tagsEn : ch.tagsKo).map((tag) => (
                <span key={tag} className="px-2 py-0.5 rounded text-[11px] font-mono"
                  style={{ color: `${ch.color}80`, background: `${ch.color}08`, border: `1px solid ${ch.color}15` }}>{tag}</span>
              ))}
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
