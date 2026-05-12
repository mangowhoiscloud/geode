"use client";

import { useState } from "react";
import { ScrollReveal } from "../scroll-reveal";
import { SectionHeader } from "../ui/section-header";
import { useLocale, t } from "../locale-context";

/* ── Role badge colors ── */
const roleMeta: Record<string, { label: string; bg: string }> = {
  credential: { label: "credential", bg: "#E8708018" },
  config:     { label: "config",     bg: "#818CF818" },
  registry:   { label: "registry",   bg: "#C084FC18" },
  profile:    { label: "profile",    bg: "#F4B8C818" },
  log:        { label: "log",        bg: "#60A5FA18" },
  audit:      { label: "audit",      bg: "#34D39918" },
  cache:      { label: "cache",      bg: "#F5C54218" },
  state:      { label: "state",      bg: "#4ECDC418" },
  memory:     { label: "memory",     bg: "#F4B8C818" },
  rule:       { label: "rule",       bg: "#E8708018" },
  skill:      { label: "skill",      bg: "#818CF818" },
  report:     { label: "report",     bg: "#C084FC18" },
  index:      { label: "index",      bg: "#4ECDC418" },
};

/* ── 3-Tier structure with data flow ── */
const tiers = [
  {
    id: "global",
    label: "~/.geode/",
    color: "#818CF8",
    scope: "Global",
    desc: "사용자 전역 데이터. 프로젝트에 독립적인 자격증명, 모델 레지스트리, 사용량 추적. 모든 프로젝트가 공유하는 단일 진실 소스.",
    descEn: "User-wide data. Project-independent credentials, model registry, and usage tracking. A single source of truth shared by all projects.",
    dirs: [
      { name: ".env",               role: "credential", purpose: "API 키, 환경 변수. dotenv 로딩, vault/와 분리된 런타임 시크릿", purposeEn: "API keys, env vars. dotenv loading, runtime secrets separate from vault/", color: "#E87080" },
      { name: "vault/",             role: "credential", purpose: "아티팩트 저장소. profile/research/applications 자동 분류", purposeEn: "Artifact store. Auto-classified into profile/research/applications", color: "#E87080" },
      { name: "config.toml",        role: "config",     purpose: "글로벌 기본값. cascade 베이스 레이어 (우선순위 4/4)", purposeEn: "Global defaults. Cascade base layer (priority 4/4)", color: "#818CF8" },
      { name: "identity/",          role: "profile",    purpose: "사용자 신원. 언어, 타임존", purposeEn: "User identity. Language, timezone", color: "#F4B8C8" },
      { name: "user_profile/",      role: "profile",    purpose: "profile.md + career.toml + preferences.json + learned.md (100건 rotate)", purposeEn: "profile.md + career.toml + preferences.json + learned.md (100-entry rotate)", color: "#F4B8C8" },
      { name: "models/",            role: "registry",   purpose: "모델 레지스트리. 버전 관리 + 프로모션 이력", purposeEn: "Model registry. Version management + promotion history", color: "#C084FC" },
      { name: "mcp/",               role: "registry",   purpose: "MCP 서버 설정. 45 catalog auto-discovery", purposeEn: "MCP server config. 45 catalog auto-discovery", color: "#4ECDC4" },
      { name: "runs/",              role: "log",        purpose: "RunLog JSONL. {session_key}.jsonl, 2MB/2000줄 auto-prune", purposeEn: "RunLog JSONL. {session_key}.jsonl, 2MB/2000-line auto-prune", color: "#60A5FA" },
      { name: "usage/",             role: "log",        purpose: "API 사용량. per-model 토큰/비용 추적", purposeEn: "API usage. Per-model token/cost tracking", color: "#F5C542" },
      { name: "journal/transcripts/", role: "audit",    purpose: "세션 트랜스크립트. {slug}/{sid}.jsonl, 30일 TTL, 5MB 상한", purposeEn: "Session transcripts. {slug}/{sid}.jsonl, 30-day TTL, 5MB cap", color: "#34D399" },
      { name: "scheduler/",         role: "state",      purpose: "jobs.json + logs/{job_id}.jsonl. 잡 정의와 실행 이력", purposeEn: "jobs.json + logs/{job_id}.jsonl. Job definitions and execution history", color: "#34D399" },
      { name: "workers/",           role: "state",      purpose: "IsolatedRunner 실행 레코드. MAX_CONCURRENT=5", purposeEn: "IsolatedRunner execution records. MAX_CONCURRENT=5", color: "#60A5FA" },
    ],
    dataFlow: "읽기 전용 참조. 프로젝트별 오버라이드 가능",
    dataFlowEn: "Read-only reference. Per-project override supported",
  },
  {
    id: "project",
    label: "~/.geode/projects/{id}/",
    color: "#4ECDC4",
    scope: "Per-Project",
    desc: "프로젝트별 세션 데이터. 경로를 Claude Code 패턴으로 인코딩(/→-)하여 프로젝트 간 완전 격리. v0.33.0에서 session, snapshot, journal, result_cache를 workspace에서 이관. 기존 경로 자동 fallback으로 backward-compat 유지.",
    descEn: "Per-project session data. Path encoded with Claude Code pattern (/ → -) for full inter-project isolation. Migrated session, snapshot, journal, result_cache from workspace in v0.33.0. Auto fallback from old paths for backward-compat.",
    dirs: [
      { name: "journal/",       role: "log",   purpose: "runs/costs/errors.jsonl + learned.md. append-only, Hook settlement 대상", purposeEn: "runs/costs/errors.jsonl + learned.md. Append-only, Hook settlement target", color: "#34D399" },
      { name: "sessions/",      role: "state", purpose: "체크포인트 JSON(state/messages/tools) + sessions.db SQLite WAL. 20msg trim, 72h cleanup", purposeEn: "Checkpoint JSON (state/messages/tools) + sessions.db SQLite WAL. 20-msg trim, 72h cleanup", color: "#60A5FA" },
      { name: "snapshots/",     role: "state", purpose: "snap-{uuid}.json. point-in-time 캡처, max 30 recent + weekly 보존", purposeEn: "snap-{uuid}.json. Point-in-time capture, max 30 recent + weekly retention", color: "#F5C542" },
      { name: "result_cache/",  role: "cache", purpose: "IP별 분석 결과. LRU 8건, TTL 24h, content hash 검증", purposeEn: "Per-IP analysis results. LRU 8 entries, TTL 24h, content hash verification", color: "#C084FC" },
    ],
    dataFlow: "쓰기 대상. 파이프라인/루프 실행 결과가 여기에 축적",
    dataFlowEn: "Write target. Pipeline/loop execution results accumulate here",
  },
  {
    id: "workspace",
    label: "{workspace}/.geode/",
    color: "#F5C542",
    scope: "Workspace",
    desc: "프로젝트 로컬 데이터. 코드 저장소와 함께 버전 관리. 프로젝트의 메모리, 규칙, 스킬을 담아 에이전트 행동을 프로젝트 맥락에 맞게 조율. 세션 데이터는 v0.33.0에서 Per-Project로 이관.",
    descEn: "Project-local data. Version-controlled alongside the code repository. Contains project memory, rules, and skills to align agent behavior with project context. Session data migrated to Per-Project in v0.33.0.",
    dirs: [
      { name: "memory/",     role: "memory",     purpose: "PROJECT.md (200줄 context 로드) + 인사이트, 패턴 학습", purposeEn: "PROJECT.md (200-line context load) + insights, pattern learning", color: "#F4B8C8" },
      { name: "rules/",      role: "rule",       purpose: "도메인 규칙. YAML frontmatter glob 매칭 (anime-ip, dark-fantasy 등)", purposeEn: "Domain rules. YAML frontmatter glob matching (anime-ip, dark-fantasy, etc.)", color: "#E87080" },
      { name: "skills/",     role: "skill",      purpose: "프로젝트 전용 스킬. YAML frontmatter + trigger 패턴", purposeEn: "Project-specific skills. YAML frontmatter + trigger patterns", color: "#818CF8" },
      { name: "reports/",    role: "report",     purpose: "생성된 분석 리포트. IP 평가 결과 아카이브", purposeEn: "Generated analysis reports. IP evaluation result archive", color: "#C084FC" },
      { name: "vault/",      role: "credential", purpose: "프로젝트 로컬 아티팩트. global vault override", purposeEn: "Project-local artifacts. Global vault override", color: "#E87080" },
      { name: "MEMORY.md",   role: "index",      purpose: "메모리 인덱스. 에이전트가 매 세션 로드하는 진입점", purposeEn: "Memory index. Entry point loaded by the agent each session", color: "#4ECDC4" },
      { name: "LEARNING.md", role: "memory",     purpose: "학습 로그. 교정 이력, 실수 패턴, 자동 축적", purposeEn: "Learning log. Correction history, error patterns, auto-accumulated", color: "#34D399" },
      { name: "config.toml", role: "config",     purpose: "프로젝트 오버라이드. cascade 최상위 레이어 (우선순위 3/4)", purposeEn: "Project override. Cascade top layer (priority 3/4)", color: "#F5C542" },
    ],
    dataFlow: "읽기 + 쓰기. 에이전트가 학습하며 축적",
    dataFlowEn: "Read + Write. Agent learns and accumulates",
  },
];

export function ContextTiersSection() {
  const locale = useLocale();
  const [activeTier, setActiveTier] = useState(0);
  const tier = tiers[activeTier];

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <SectionHeader
          variant="quote"
          labelColor="#F5C542"
          title="Context Hierarchy"
          subtitle={t(locale, "3-Tier 경로 + 4.5-Tier 런타임 메모리 + 200K Ceiling", "3-Tier Paths + 4.5-Tier Runtime Memory + 200K Ceiling")}
          description={t(locale,
            "Claude Code의 ~/.claude/ 패턴을 참조하여 사용자 데이터와 프로젝트 데이터를 3계층으로 분리합니다. 1M 컨텍스트 모델에서도 ABSOLUTE_TOKEN_CEILING(200K)을 적용하고, 80% 도달 시 2-stage 압축(요약 → compact)으로 세션을 보존합니다. v0.45에서 User Preferences(Tier 0.5)를 추가하여 preferences.json이 시스템 프롬프트에 자동 주입됩니다.",
            "User and project data separated into 3 tiers, following Claude Code's ~/.claude/ pattern. Even on 1M context models, ABSOLUTE_TOKEN_CEILING (200K) is enforced. At 80%, 2-stage compression (summarize → compact) preserves sessions. v0.45 added User Preferences (Tier 0.5), auto-injecting preferences.json into the system prompt."
          )}
        />

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
                      fill={`${t.color}${isActive ? "0C" : "06"}`}
                      stroke={t.color}
                      strokeWidth={isActive ? 1.5 : 0.8}
                      strokeOpacity={isActive ? 0.7 : 0.3}
                      style={{ transition: "all 0.3s" }}
                    />
                    {/* Scope badge */}
                    <rect x={x + 10} y={30} width={65} height={22} rx={5}
                      fill={t.color} fillOpacity={isActive ? 0.2 : 0.08}
                    />
                    <text x={x + 42} y={45} textAnchor="middle" fill={t.color}
                      fillOpacity={isActive ? 0.9 : 0.5}
                      fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}
                    >
                      {t.scope}
                    </text>
                    {/* Path */}
                    <text x={x + 115} y={78} textAnchor="middle" fill={t.color}
                      fillOpacity={isActive ? 0.95 : 0.55}
                      fontSize={13} fontFamily="ui-monospace, monospace" fontWeight={700}
                    >
                      {t.label.length > 22 ? t.label.slice(0, 20) + "…" : t.label}
                    </text>
                    {/* Dir count */}
                    <text x={x + 115} y={100} textAnchor="middle" fill={t.color}
                      fillOpacity={isActive ? 0.7 : 0.4}
                      fontSize={10} fontFamily="ui-monospace, monospace"
                    >
                      {t.dirs.length} entries
                    </text>
                    {/* Data flow */}
                    <text x={x + 115} y={155} textAnchor="middle" fill={t.color}
                      fillOpacity={isActive ? 0.6 : 0.35}
                      fontSize={9} fontFamily="ui-monospace, monospace"
                    >
                      {locale === "en" ? t.dataFlowEn : t.dataFlow}
                    </text>
                  </g>
                );
              })}

              {/* Cascade arrows */}
              <g>
                <path d="M260,95 C270,90 280,90 290,95" stroke="white" strokeOpacity={0.25} strokeWidth={1.5} fill="none" />
                <text x={275} y={83} textAnchor="middle" fill="white" fillOpacity={0.4} fontSize={14}>→</text>
                <path d="M520,95 C530,90 540,90 550,95" stroke="white" strokeOpacity={0.25} strokeWidth={1.5} fill="none" />
                <text x={535} y={83} textAnchor="middle" fill="white" fillOpacity={0.4} fontSize={14}>→</text>
              </g>

              {/* Cascade label */}
              <rect x={230} y={188} width={340} height={30} rx={8} fill="#0C1220" stroke="white" strokeOpacity={0.1} strokeWidth={1} />
              <text x={400} y={208} textAnchor="middle" fill="white" fillOpacity={0.45} fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={600}>
                config.toml cascade: Global → Project override
              </text>

              {/* Backward compat label */}
              <text x={400} y={235} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.35} fontSize={9} fontFamily="ui-monospace, monospace">
                {locale === "en" ? "Legacy .geode/ paths → auto fallback (backward-compat)" : "기존 .geode/ 경로 → 자동 fallback (backward-compat)"}
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
            <p className="text-sm text-[#A0B4D4] leading-relaxed mb-4">
              {locale === "en" ? tier.descEn : tier.desc}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {tier.dirs.map((d) => {
                const meta = roleMeta[d.role];
                return (
                  <div key={d.name} className="flex items-start gap-3 px-3 py-2.5 rounded-lg border border-white/[0.04]"
                    style={{ background: `${d.color}03` }}
                  >
                    <div
                      className="shrink-0 w-1.5 h-full min-h-[32px] rounded-full mt-0.5"
                      style={{ background: d.color, opacity: 0.3 }}
                    />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <code className="text-xs font-mono font-semibold text-white/70">{d.name}</code>
                        {meta && (
                          <span
                            className="shrink-0 px-1.5 py-px rounded text-[9px] font-mono font-bold uppercase"
                            style={{ color: d.color, background: meta.bg, opacity: 0.8 }}
                          >
                            {meta.label}
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-[#A0B4D4] leading-relaxed mt-0.5">{locale === "en" ? d.purposeEn : d.purpose}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </ScrollReveal>

        {/* Runtime Memory Hierarchy (5-Tier) */}
        <ScrollReveal delay={0.2}>
          <div className="rounded-xl border border-white/[0.04] px-5 py-4 mb-6">
            <div className="text-sm font-semibold text-white/70 mb-3">Runtime Memory Hierarchy (5-Tier)</div>
            <div className="space-y-1.5">
              {[
                { tier: "T0", name: "Identity", desc: "GEODE.md. 에이전트 미션, 핵심 원칙, 실행 모델 (Karpathy P7)", descEn: "GEODE.md. Agent mission, core principles, execution model (Karpathy P7)", color: "#F4B8C8" },
                { tier: "T0.5", name: "User Profile", desc: "FileBasedUserProfile. 역할, 전문성, 자동 학습 패턴, 선호 설정", descEn: "FileBasedUserProfile. Role, expertise, auto-learned patterns, preferences", color: "#E87080" },
                { tier: "T1", name: "Organization", desc: "MonoLake fixture JSON. IP 메타데이터, 시그널, PSM 공변량, 기대 결과", descEn: "MonoLake fixture JSON. IP metadata, signals, PSM covariates, expected results", color: "#818CF8" },
                { tier: "T2", name: "Project", desc: "ProjectMemory. PROJECT.md(200줄) + .geode/rules/*.md 글로브 매칭", descEn: "ProjectMemory. PROJECT.md (200 lines) + .geode/rules/*.md glob matching", color: "#4ECDC4" },
                { tier: "T3", name: "Session", desc: "InMemorySessionStore. TTL 3600s, 체크포인트 save/load, 세션 간 격리", descEn: "InMemorySessionStore. TTL 3600s, checkpoint save/load, inter-session isolation", color: "#F5C542" },
              ].map((m) => (
                <div key={m.tier} className="flex items-center gap-3 px-3 py-2 rounded-lg border border-white/[0.03]" style={{ background: `${m.color}03` }}>
                  <span className="shrink-0 w-8 text-center text-[10px] font-mono font-bold" style={{ color: m.color }}>{m.tier}</span>
                  <span className="text-sm font-medium text-white/70 w-[100px] shrink-0">{m.name}</span>
                  <span className="text-sm text-[#9BB0CC]">{locale === "en" ? m.descEn : m.desc}</span>
                </div>
              ))}
            </div>
          </div>
        </ScrollReveal>

        {/* Context Compression (Provider-aware) */}
        <ScrollReveal delay={0.25}>
          <div className="rounded-xl border border-white/[0.04] px-5 py-4 mb-6">
            <div className="text-sm font-semibold text-white/70 mb-3">Context Compression (Provider-aware)</div>
            <p className="text-xs text-[#9BB0CC] mb-4 leading-relaxed">
              {locale === "en"
                ? "ContextMonitor estimates token usage each round (4 chars/token), fires CONTEXT_WARNING (80%) / CONTEXT_CRITICAL (95%) hooks. Provider-specific strategies branch to prevent cache hit rate collapse."
                : "ContextMonitor가 매 라운드 토큰 사용률을 추정(4 chars/token)하고, CONTEXT_WARNING(80%) / CONTEXT_CRITICAL(95%) Hook을 발화. 프로바이더별 전략이 분기하여 캐시 히트율 붕괴를 방지합니다."}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Anthropic */}
              <div className="rounded-lg border border-white/[0.04] px-4 py-3" style={{ background: "#818CF804" }}>
                <div className="text-xs font-mono font-bold text-[#818CF8] mb-2">Anthropic (Claude)</div>
                <div className="space-y-1.5 text-xs text-[#A0B4D4]">
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 text-[10px] font-mono font-bold text-[#34D399]">0-95%</span>
                    <span>{locale === "en" ? "Server-side handling. clear_tool_uses + compact_20260112 auto-applied" : "서버사이드 처리. clear_tool_uses + compact_20260112 자동 적용"}</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 text-[10px] font-mono font-bold text-[#E87080]">95%+</span>
                    <span>{locale === "en" ? "Emergency prune. Keep first + bridge + recent N only (client safety net)" : "Emergency prune. first + bridge + recent N개만 보존 (클라이언트 안전망)"}</span>
                  </div>
                </div>
              </div>
              {/* Non-Anthropic */}
              <div className="rounded-lg border border-white/[0.04] px-4 py-3" style={{ background: "#F5C54204" }}>
                <div className="text-xs font-mono font-bold text-[#F5C542] mb-2">OpenAI / GLM</div>
                <div className="space-y-1.5 text-xs text-[#A0B4D4]">
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 text-[10px] font-mono font-bold text-[#F5C542]">80%+</span>
                    <span>{locale === "en" ? "LLM summary compaction. Reconstruct with summary + marker + recent 10" : "LLM 요약 compaction. 요약 + marker + recent 10개로 재구성"}</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 text-[10px] font-mono font-bold text-[#E87080]">95%+</span>
                    <span>{locale === "en" ? "Emergency prune. adaptive_prune(budget 70%) or keep_recent=5 (small models)" : "Emergency prune. adaptive_prune(budget 70%) 또는 keep_recent=5 (소형 모델)"}</span>
                  </div>
                </div>
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5 mt-3">
              {["clear_tool_uses", "compact_20260112", "summarize_tool_results (>5%)", "adaptive_prune (budget 70%)", "COMPACTION_MARKER"].map((t) => (
                <span key={t} className="px-2 py-0.5 rounded text-[10px] font-mono text-white/30 bg-white/[0.02] border border-white/[0.04]">{t}</span>
              ))}
            </div>
          </div>
        </ScrollReveal>

        {/* Project ID encoding */}
        <ScrollReveal delay={0.3}>
          <div className="rounded-lg border border-white/[0.06] px-5 py-3.5 font-mono text-sm">
            <span className="text-[#9BB0CC]">{locale === "en" ? "Project ID Encoding: " : "Project ID 인코딩: "}</span>
            <span className="text-white/60">/Users/mango/workspace/geode</span>
            <span className="text-white/25 mx-2">→</span>
            <span style={{ color: "#4ECDC4" }}>-Users-mango-workspace-geode</span>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
