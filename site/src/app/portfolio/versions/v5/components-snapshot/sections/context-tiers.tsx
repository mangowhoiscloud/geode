"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";

/* ── 3-Tier structure with data flow ── */
const tiers = [
  {
    id: "global",
    label: "~/.geode/",
    color: "#818CF8",
    scope: "Global",
    desc: "사용자 전역 데이터. 프로젝트에 독립적인 자격증명, 모델 레지스트리, 사용량 추적. 모든 프로젝트가 공유하는 단일 진실 소스.",
    dirs: [
      { name: "vault/", purpose: "API 키, 자격증명. 프로젝트 간 공유", color: "#E87080" },
      { name: "models/", purpose: "모델 레지스트리. 버전 관리 + 프로모션 이력", color: "#C084FC" },
      { name: "identity/", purpose: "사용자 프로필. 선호 설정, 언어, 타임존", color: "#F4B8C8" },
      { name: "runs/", purpose: "전체 실행 이력. 크로스 프로젝트 통계", color: "#60A5FA" },
      { name: "usage/", purpose: "API 사용량. per-model 토큰/비용 추적", color: "#F5C542" },
      { name: "mcp/", purpose: "MCP 서버 설정. 글로벌 기본 서버 목록", color: "#4ECDC4" },
      { name: "config.toml", purpose: "글로벌 기본값. cascade 베이스 레이어", color: "#818CF8" },
    ],
    dataFlow: "읽기 전용 참조 — 프로젝트별 오버라이드 가능",
  },
  {
    id: "project",
    label: "~/.geode/projects/{id}/",
    color: "#4ECDC4",
    scope: "Per-Project",
    desc: "프로젝트별 세션 데이터. 경로를 Claude Code 패턴으로 인코딩(/→-)하여 프로젝트 간 완전 격리. 기존 .geode/ 경로에서 자동 fallback으로 backward-compat 유지.",
    dirs: [
      { name: "journal/", purpose: "세션 이벤트 로그. JSONL, 시간순 append-only", color: "#34D399" },
      { name: "sessions/", purpose: "턴 히스토리. 멀티턴 대화 컨텍스트 복원용", color: "#60A5FA" },
      { name: "snapshots/", purpose: "드리프트/디버그 캡처. 재현 가능한 상태 저장", color: "#F5C542" },
    ],
    dataFlow: "쓰기 대상 — 파이프라인/루프 실행 결과가 여기에 축적",
  },
  {
    id: "workspace",
    label: "{workspace}/.geode/",
    color: "#F5C542",
    scope: "Workspace",
    desc: "프로젝트 로컬 데이터. 코드 저장소와 함께 버전 관리. 프로젝트의 메모리, 규칙, 스킬을 담아 에이전트 행동을 프로젝트 맥락에 맞게 조율.",
    dirs: [
      { name: "memory/", purpose: "프로젝트 메모리. 규칙, 인사이트, 패턴 학습", color: "#F4B8C8" },
      { name: "rules/", purpose: "커스텀 자동화 규칙. 도메인 특화 제약", color: "#E87080" },
      { name: "skills/", purpose: "프로젝트 전용 스킬. YAML frontmatter + trigger", color: "#818CF8" },
      { name: "reports/", purpose: "분석 리포트. IP 평가 결과 아카이브", color: "#C084FC" },
      { name: "MEMORY.md", purpose: "메모리 인덱스. 에이전트가 매 세션 로드", color: "#4ECDC4" },
      { name: "LEARNING.md", purpose: "학습 로그. 교정 이력, 실수 패턴 기록", color: "#34D399" },
      { name: "config.toml", purpose: "프로젝트 오버라이드. cascade 최상위 레이어", color: "#F5C542" },
    ],
    dataFlow: "읽기 + 쓰기. 에이전트가 학습하며 축적",
  },
];

export function ContextTiersSection() {
  const [activeTier, setActiveTier] = useState(0);
  const tier = tiers[activeTier];

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#F5C542]/60 uppercase tracking-[0.25em] mb-3">
            Context Hierarchy
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-2">
            3-Tier 경로 분리
          </h2>
          <p className="text-lg text-white/40 font-semibold mb-4">
            Global · Per-Project · Workspace
          </p>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-10 leading-relaxed">
            Claude Code의 <code className="text-[#818CF8]/70">~/.claude/</code> 패턴을 참조하여
            사용자 데이터와 프로젝트 데이터를 3계층으로 분리.
            config.toml은 Global → Project cascade 로딩으로 동작하며,
            기존 경로에서 자동 fallback으로 backward-compat을 유지합니다.
          </p>
        </ScrollReveal>

        {/* ── Data flow SVG ── */}
        <ScrollReveal delay={0.1}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-8">
            <svg viewBox="0 0 800 240" className="w-full min-w-[600px]" style={{ maxHeight: 270 }}>
              {/* 3 tier boxes */}
              {tiers.map((t, i) => {
                const x = 30 + i * 260;
                const isActive = activeTier === i;
                return (
                  <g key={t.id} style={{ cursor: "pointer" }} onClick={() => setActiveTier(i)}>
                    <rect x={x} y={20} width={230} height={150} rx={14}
                      fill={`${t.color}${isActive ? "0A" : "04"}`}
                      stroke={t.color}
                      strokeWidth={isActive ? 1.5 : 0.6}
                      strokeOpacity={isActive ? 0.5 : 0.12}
                      style={{ transition: "all 0.3s" }}
                    />
                    {/* Scope badge */}
                    <rect x={x + 10} y={30} width={60} height={20} rx={4}
                      fill={t.color} fillOpacity={isActive ? 0.15 : 0.06}
                    />
                    <text x={x + 40} y={44} textAnchor="middle" fill={t.color}
                      fillOpacity={isActive ? 0.8 : 0.4}
                      fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}
                    >
                      {t.scope}
                    </text>
                    {/* Path */}
                    <text x={x + 115} y={75} textAnchor="middle" fill={t.color}
                      fillOpacity={isActive ? 0.8 : 0.35}
                      fontSize={12} fontFamily="ui-monospace, monospace" fontWeight={700}
                    >
                      {t.label.length > 20 ? t.label.slice(0, 18) + "…" : t.label}
                    </text>
                    {/* Dir count */}
                    <text x={x + 115} y={100} textAnchor="middle" fill={t.color}
                      fillOpacity={isActive ? 0.5 : 0.2}
                      fontSize={10} fontFamily="ui-monospace, monospace"
                    >
                      {t.dirs.length} entries
                    </text>
                    {/* Data flow */}
                    <text x={x + 115} y={155} textAnchor="middle" fill={t.color}
                      fillOpacity={isActive ? 0.4 : 0.15}
                      fontSize={8} fontFamily="ui-monospace, monospace"
                    >
                      {t.dataFlow.slice(0, 30)}
                    </text>
                  </g>
                );
              })}

              {/* Cascade arrows */}
              <g>
                <line x1={260} y1={95} x2={290} y2={95} stroke="white" strokeOpacity={0.15} strokeWidth={1.5} />
                <text x={275} y={85} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={12}>→</text>
                <line x1={520} y1={95} x2={550} y2={95} stroke="white" strokeOpacity={0.15} strokeWidth={1.5} />
                <text x={535} y={85} textAnchor="middle" fill="white" fillOpacity={0.25} fontSize={12}>→</text>
              </g>

              {/* Cascade label */}
              <rect x={250} y={190} width={300} height={28} rx={6} fill="#0A0F1A" stroke="white" strokeOpacity={0.06} strokeWidth={1} />
              <text x={400} y={208} textAnchor="middle" fill="white" fillOpacity={0.3} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>
                config.toml cascade: Global → Project override
              </text>

              {/* Backward compat label */}
              <text x={400} y={235} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.2} fontSize={9} fontFamily="ui-monospace, monospace">
                기존 .geode/ 경로 → 자동 fallback (backward-compat)
              </text>
            </svg>
          </div>
        </ScrollReveal>

        {/* ── Active tier detail ── */}
        <ScrollReveal delay={0.15}>
          <div
            className="rounded-xl border px-6 py-5 transition-all duration-300 mb-6"
            style={{
              borderColor: `${tier.color}20`,
              background: `linear-gradient(135deg, ${tier.color}06, transparent 60%)`,
            }}
          >
            <div className="flex items-center gap-3 mb-2">
              <span
                className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase"
                style={{ color: tier.color, background: `${tier.color}15` }}
              >
                {tier.scope}
              </span>
              <code className="text-sm font-mono font-bold" style={{ color: tier.color }}>
                {tier.label}
              </code>
            </div>
            <p className="text-sm text-[#8B9CC0] leading-relaxed mb-4">
              {tier.desc}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {tier.dirs.map((d) => (
                <div key={d.name} className="flex items-start gap-3 px-3 py-2.5 rounded-lg border border-white/[0.04]"
                  style={{ background: `${d.color}03` }}
                >
                  <div
                    className="shrink-0 w-1.5 h-full min-h-[32px] rounded-full mt-0.5"
                    style={{ background: d.color, opacity: 0.3 }}
                  />
                  <div>
                    <code className="text-xs font-mono font-semibold text-white/70">{d.name}</code>
                    <div className="text-xs text-[#8B9CC0] leading-relaxed mt-0.5">{d.purpose}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </ScrollReveal>

        {/* Project ID encoding */}
        <ScrollReveal delay={0.2}>
          <div className="rounded-lg border border-white/[0.06] px-5 py-3.5 font-mono text-sm">
            <span className="text-[#7A8CA8]">Project ID 인코딩: </span>
            <span className="text-white/60">/Users/mango/workspace/geode</span>
            <span className="text-white/25 mx-2">→</span>
            <span style={{ color: "#4ECDC4" }}>-Users-mango-workspace-geode</span>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
