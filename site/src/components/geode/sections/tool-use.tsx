"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ScrollReveal } from "../scroll-reveal";
import { TabBar } from "../ui/tab-bar";
import { useLocale, t } from "../locale-context";

/* ── 5-Route Dispatch ── */
const routes = [
  { id: "bash",   label: "Bash",  count: "38 safe prefixes", color: "#E87080", descKo: "PolicyChain 3-layer 방어. safe prefix(cat, ls, git...)는 자동 실행, 위험 패턴(rm -rf /, sudo)은 차단, 나머지는 HITL 승인.", descEn: "PolicyChain 3-layer defense. Safe prefixes (cat, ls, git...) auto-execute, dangerous patterns (rm -rf /, sudo) blocked, rest requires HITL approval." },
  { id: "native", label: "Tool",  count: "43 native",        color: "#4ECDC4", descKo: "43개 고유 도구 클래스. 12개 카테고리(Analysis, Memory, Planning 등). 초기 52에서 중복/불용을 지속 정리. ToolExecutor가 handler dict에서 디스패치.", descEn: "43 unique tool classes. 12 categories (Analysis, Memory, Planning, etc.). Continuously trimmed from initial 52. ToolExecutor dispatches from handler dict." },
  { id: "mcp",    label: "MCP",   count: "44 catalog",       color: "#818CF8", descKo: "MCPServerManager auto-discovery. Anthropic format 자동 정규화. steam/arxiv/linkedin은 사전 승인, 나머지는 서버별 1회 승인. install_mcp_server로 NL 설치.", descEn: "MCPServerManager auto-discovery. Auto-normalizes to Anthropic format. steam/arxiv/linkedin pre-approved, rest requires one-time per-server approval. NL install via install_mcp_server." },
  { id: "skill",  label: "Skill", count: "3-tier disclosure", color: "#C084FC", descKo: "Progressive Disclosure: T1 메타데이터(system prompt) → T2 본문(lazy load) → T3 context:fork(격리 서브에이전트). 4 scope 우선순위.", descEn: "Progressive Disclosure: T1 metadata (system prompt) → T2 body (lazy load) → T3 context:fork (isolated sub-agent). 4-scope priority." },
  { id: "dag",    label: "DAG",   count: "13-node pipeline",  color: "#F5C542", descKo: "analyze_ip 호출 시 LangGraph StateGraph 13노드 파이프라인 실행. Router → Analyst×4(Send API) → Evaluator×3 → Scoring → Synthesizer.", descEn: "On analyze_ip call, runs LangGraph StateGraph 13-node pipeline. Router → Analyst×4 (Send API) → Evaluator×3 → Scoring → Synthesizer." },
];

/* ── 5-Tier Safety ── */
const tiers = [
  { tier: "T0", name: "SAFE",      count: 13, color: "#34D399", gateKo: "없음", gateEn: "None",              execKo: "asyncio.gather 즉시 병렬", execEn: "Immediate parallel via asyncio.gather", examples: "list_ips, search_ips, memory_search, web_fetch" },
  { tier: "T1", name: "STANDARD",  count: 25, color: "#60A5FA", gateKo: "없음", gateEn: "None",              execKo: "자동 실행. 서브에이전트 위임 가능", execEn: "Auto-execute. Can delegate to sub-agent", examples: "schedule_job, delegate_task, create_plan" },
  { tier: "T2", name: "WRITE",     count: 10, color: "#F5C542", gateKo: "HITL 승인", gateEn: "HITL approval",    execKo: "영속 상태 변경. 명시적 확인 필요", execEn: "Persistent state change. Explicit confirmation required", examples: "memory_save, set_api_key, profile_update" },
  { tier: "T3", name: "EXPENSIVE", count: 3,  color: "#F4B8C8", gateKo: "비용 확인", gateEn: "Cost confirm",    execKo: "실행 전 비용 표시. Always 가능", execEn: "Shows cost before execution. 'Always' option available", examples: "analyze_ip($1.50), batch($5.00), compare($3.00)" },
  { tier: "T4", name: "DANGEROUS", count: 1,  color: "#E87080", gateKo: "패턴+HITL", gateEn: "Pattern+HITL",    execKo: "safe prefix만 자동. 나머지 항상 승인", execEn: "Only safe prefixes auto-run. Rest always requires approval", examples: "run_bash" },
];

/* ── Tool Categories ── */
const categories = [
  { name: "Analysis",     count: 8, color: "#4ECDC4" },
  { name: "External",     count: 7, color: "#F5C542" },
  { name: "Planning",     count: 6, color: "#818CF8" },
  { name: "Discovery",    count: 5, color: "#60A5FA" },
  { name: "Memory",       count: 5, color: "#F4B8C8" },
  { name: "Model",        count: 5, color: "#C084FC" },
  { name: "Task",         count: 5, color: "#34D399" },
  { name: "Profile",      count: 4, color: "#E87080" },
  { name: "Calendar",     count: 3, color: "#F5C542" },
  { name: "Scheduling",   count: 2, color: "#818CF8" },
  { name: "Notification", count: 1, color: "#60A5FA" },
  { name: "Data",         count: 1, color: "#4ECDC4" },
];

/* ── Deferred Loading ── */
const deferredSpec = {
  threshold: 10,
  alwaysLoaded: ["list_ips", "search_ips", "analyze_ip", "memory_search", "show_help", "general_web_search"],
  saving: "~85%",
  categories: ["analysis", "data", "signals", "memory", "output", "mcp", "other"],
};

type Tab = "routes" | "safety" | "deferred" | "inventory";

export function ToolUseSection() {
  const locale = useLocale();
  const [activeTab, setActiveTab] = useState<Tab>("routes");
  const [activeRoute, setActiveRoute] = useState(0);

  return (
    <section className="relative py-28 sm:py-32 px-4 sm:px-6">
      <div className="relative z-10 max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#4ECDC4]/60 uppercase tracking-[0.25em] mb-3">
            Tool Orchestration
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-3">
            Dispatch, Search, Safety
          </h2>
          <p className="text-sm sm:text-base text-[#A0B4D4] max-w-xl mb-8 leading-relaxed">
            {t(locale,
              "LLM이 도구를 선택하면 ToolExecutor가 5개 경로(Bash, Native, MCP, Skill, DAG)로 디스패치합니다. 43+ 도구 전체 스키마를 매 턴 전송하면 2-3K 토큰을 소모하므로, tool_search로 지연 로딩하여 85% 절감합니다. 5-Tier 안전 분류(T0 SAFE는 병렬, T4 DANGEROUS는 패턴+HITL)가 실행 전략을 결정합니다.",
              "When the LLM selects a tool, ToolExecutor dispatches across 5 routes (Bash, Native, MCP, Skill, DAG). Sending full schemas for 43+ tools every turn costs 2-3K tokens, so deferred loading via tool_search saves 85%. 5-Tier safety classification (T0 SAFE = parallel, T4 DANGEROUS = pattern+HITL) determines execution strategy."
            )}
          </p>
        </ScrollReveal>

        {/* ── Dispatch Flow SVG ── */}
        <ScrollReveal delay={0.05}>
          <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-8">
            <svg viewBox="0 0 800 200" className="w-full min-w-[640px]" style={{ maxHeight: 230 }}>
              {/* LLM box */}
              <rect x={15} y={65} width={90} height={70} rx={10}
                fill="#0C1220" stroke="#818CF8" strokeWidth={1.2} strokeOpacity={0.5} />
              <text x={60} y={90} textAnchor="middle" fill="#818CF8"
                fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>LLM</text>
              <text x={60} y={107} textAnchor="middle" fill="#818CF8" fillOpacity={0.4}
                fontSize={8} fontFamily="ui-monospace, monospace">tool_use block</text>
              <text x={60} y={122} textAnchor="middle" fill="#818CF8" fillOpacity={0.3}
                fontSize={7} fontFamily="ui-monospace, monospace">name + input</text>

              {/* Arrow → ToolExecutor */}
              <path d="M105,100 C120,100 130,100 145,100" stroke="white" strokeOpacity={0.2} strokeWidth={1} fill="none" />

              {/* ToolExecutor */}
              <rect x={145} y={55} width={120} height={90} rx={10}
                fill="#0C1220" stroke="#F4B8C8" strokeWidth={1} strokeOpacity={0.45} />
              <text x={205} y={80} textAnchor="middle" fill="#F4B8C8"
                fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>ToolExecutor</text>
              <text x={205} y={96} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.45}
                fontSize={7} fontFamily="ui-monospace, monospace">PolicyChain</text>
              <text x={205} y={110} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.35}
                fontSize={7} fontFamily="ui-monospace, monospace">Safety Gate</text>
              <text x={205} y={124} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.25}
                fontSize={7} fontFamily="ui-monospace, monospace">HITL Approval</text>

              {/* 5 route branches */}
              {routes.map((r, i) => {
                const y = 18 + i * 38;
                return (
                  <g key={r.id}>
                    <path d={`M265,100 C290,100 300,${y + 14} 320,${y + 14}`}
                      stroke={r.color} strokeOpacity={0.3} strokeWidth={1} fill="none" />
                    <rect x={320} y={y} width={90} height={28} rx={7}
                      fill="#0A0F1A" stroke={r.color} strokeWidth={0.8} strokeOpacity={activeRoute === i ? 0.6 : 0.3}
                      style={{ cursor: "pointer", transition: "stroke-opacity 0.3s" }}
                      onMouseEnter={() => setActiveRoute(i)} />
                    <text x={365} y={y + 17} textAnchor="middle" fill={r.color}
                      fillOpacity={activeRoute === i ? 1 : 0.6}
                      fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>{r.label}</text>
                  </g>
                );
              })}

              {/* Converge arrows → Result */}
              {routes.map((r, i) => {
                const y = 18 + i * 38;
                return (
                  <path key={`arr-${r.id}`} d={`M410,${y + 14} C430,${y + 14} 440,100 460,100`}
                    stroke={r.color} strokeOpacity={0.2} strokeWidth={0.8} fill="none" />
                );
              })}

              {/* Result box */}
              <rect x={460} y={65} width={110} height={70} rx={10}
                fill="#0C1220" stroke="#34D399" strokeWidth={1} strokeOpacity={0.4} />
              <text x={515} y={90} textAnchor="middle" fill="#34D399"
                fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>tool_result</text>
              <text x={515} y={107} textAnchor="middle" fill="#34D399" fillOpacity={0.4}
                fontSize={7} fontFamily="ui-monospace, monospace">JSON serialize</text>
              <text x={515} y={122} textAnchor="middle" fill="#34D399" fillOpacity={0.3}
                fontSize={7} fontFamily="ui-monospace, monospace">token guard</text>

              {/* Arrow → back to LLM */}
              <path d="M570,100 C590,100 600,100 620,100" stroke="white" strokeOpacity={0.2} strokeWidth={1} fill="none" />

              {/* Continue box */}
              <rect x={620} y={70} width={100} height={60} rx={10}
                fill="#0C1220" stroke="#818CF8" strokeWidth={0.8} strokeOpacity={0.35} />
              <text x={670} y={93} textAnchor="middle" fill="#818CF8"
                fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>LLM</text>
              <text x={670} y={110} textAnchor="middle" fill="#818CF8" fillOpacity={0.4}
                fontSize={7} fontFamily="ui-monospace, monospace">continue loop</text>

              {/* Loopback arrow */}
              <path d="M670,130 C670,170 60,170 60,135" fill="none"
                stroke="#4ECDC4" strokeOpacity={0.15} strokeWidth={1} strokeDasharray="4 3" />
              <text x={370} y={185} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.3}
                fontSize={7} fontFamily="ui-monospace, monospace">while(tool_use) → next round</text>

              {/* Top label */}
              <text x={400} y={10} textAnchor="middle" fill="white" fillOpacity={0.2}
                fontSize={8} fontFamily="ui-monospace, monospace" letterSpacing="0.1em">
                LLM → EXECUTOR → 5 ROUTES → RESULT → LLM (LOOP)
              </text>
            </svg>
          </div>
        </ScrollReveal>

        {/* ── Tab bar ── */}
        <ScrollReveal delay={0.08}>
          <TabBar
            variant="underline"
            tabs={[
              { id: "routes", label: "5-Route Dispatch", color: "#4ECDC4" },
              { id: "deferred", label: "Deferred Loading", color: "#F5C542" },
              { id: "safety", label: "5-Tier Safety", color: "#E87080" },
              { id: "inventory", label: "Inventory", color: "#818CF8" },
            ]}
            activeId={activeTab}
            onSelect={(id) => setActiveTab(id as Tab)}
          />
        </ScrollReveal>

        <ScrollReveal delay={0.1}>
          <div className="min-h-[420px]">
          <AnimatePresence mode="wait">
          {/* ── 5-Route Dispatch ── */}
          {activeTab === "routes" && (
            <motion.div key="routes" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <div className="space-y-2">
              {routes.map((r, i) => (
                <div key={r.id}
                  className="flex items-start gap-4 px-4 py-3 rounded-lg border transition-all duration-200"
                  style={{
                    borderColor: activeRoute === i ? `${r.color}20` : "rgba(255,255,255,0.04)",
                    background: activeRoute === i ? `${r.color}05` : `${r.color}02`,
                  }}
                  onMouseEnter={() => setActiveRoute(i)}
                >
                  <div className="shrink-0 w-16 text-center">
                    <div className="text-sm font-mono font-bold" style={{ color: r.color }}>{r.label}</div>
                    <div className="text-[9px] font-mono text-white/25 mt-0.5">{r.count}</div>
                  </div>
                  <p className="text-sm text-[#A0B4D4] leading-relaxed">{locale === "en" ? r.descEn : r.descKo}</p>
                </div>
              ))}
            </div>
            </motion.div>
          )}

          {/* ── Deferred Loading ── */}
          {activeTab === "deferred" && (
            <motion.div key="deferred" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <div>
              {/* How it works SVG */}
              <div className="overflow-x-auto -mx-4 px-4 pb-2 mb-6">
                <svg viewBox="0 0 760 140" className="w-full min-w-[560px]" style={{ maxHeight: 160 }}>
                  {/* All tools */}
                  <rect x={15} y={30} width={120} height={80} rx={10}
                    fill="#0C1220" stroke="#818CF8" strokeWidth={0.8} strokeOpacity={0.35} />
                  <text x={75} y={55} textAnchor="middle" fill="#818CF8"
                    fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>43 + MCP</text>
                  <text x={75} y={72} textAnchor="middle" fill="#818CF8" fillOpacity={0.4}
                    fontSize={8} fontFamily="ui-monospace, monospace">combined &gt; 10</text>
                  <text x={75} y={88} textAnchor="middle" fill="#818CF8" fillOpacity={0.3}
                    fontSize={7} fontFamily="ui-monospace, monospace">defer 활성화</text>

                  <path d="M135,70 C155,70 165,40 185,40" stroke="#34D399" strokeOpacity={0.3} strokeWidth={1} fill="none" />
                  <path d="M135,70 C155,70 165,100 185,100" stroke="#F5C542" strokeOpacity={0.3} strokeWidth={1} fill="none" />

                  {/* Always loaded */}
                  <rect x={185} y={18} width={140} height={45} rx={8}
                    fill="#0C1220" stroke="#34D399" strokeWidth={1} strokeOpacity={0.45} />
                  <text x={255} y={37} textAnchor="middle" fill="#34D399"
                    fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>Always Loaded (6)</text>
                  <text x={255} y={52} textAnchor="middle" fill="#34D399" fillOpacity={0.4}
                    fontSize={7} fontFamily="ui-monospace, monospace">core tools, 즉시 호출 가능</text>

                  {/* Deferred */}
                  <rect x={185} y={78} width={140} height={45} rx={8}
                    fill="#0C1220" stroke="#F5C542" strokeWidth={0.8} strokeOpacity={0.35} />
                  <text x={255} y={97} textAnchor="middle" fill="#F5C542"
                    fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={700}>Deferred (나머지)</text>
                  <text x={255} y={112} textAnchor="middle" fill="#F5C542" fillOpacity={0.4}
                    fontSize={7} fontFamily="ui-monospace, monospace">이름만 노출, 스키마 지연</text>

                  {/* tool_search */}
                  <path d="M325,100 C345,100 355,70 375,70" stroke="white" strokeOpacity={0.2} strokeWidth={1} fill="none" />
                  <rect x={375} y={45} width={130} height={50} rx={10}
                    fill="#0C1220" stroke="#C084FC" strokeWidth={1} strokeOpacity={0.45} />
                  <text x={440} y={65} textAnchor="middle" fill="#C084FC"
                    fontSize={10} fontFamily="ui-monospace, monospace" fontWeight={700}>tool_search</text>
                  <text x={440} y={82} textAnchor="middle" fill="#C084FC" fillOpacity={0.4}
                    fontSize={7} fontFamily="ui-monospace, monospace">query → 관련 도구 로딩</text>

                  {/* Result */}
                  <path d="M505,70 C525,70 535,70 555,70" stroke="white" strokeOpacity={0.2} strokeWidth={1} fill="none" />
                  <rect x={555} y={45} width={130} height={50} rx={10}
                    fill="#0C1220" stroke="#4ECDC4" strokeWidth={0.8} strokeOpacity={0.35} />
                  <text x={620} y={65} textAnchor="middle" fill="#4ECDC4"
                    fontSize={9} fontFamily="ui-monospace, monospace" fontWeight={600}>Schema Loaded</text>
                  <text x={620} y={82} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.4}
                    fontSize={7} fontFamily="ui-monospace, monospace">이후 턴에서도 유지</text>

                  <text x={380} y={15} textAnchor="middle" fill="white" fillOpacity={0.2}
                    fontSize={8} fontFamily="ui-monospace, monospace" letterSpacing="0.08em">
                    SPLIT → CORE ALWAYS / REST DEFERRED → SEARCH → LOAD
                  </text>
                </svg>
              </div>

              {/* Always loaded tools */}
              <div className="rounded-xl border border-white/[0.04] px-5 py-4 mb-4" style={{ background: "#34D39904" }}>
                <div className="flex items-center gap-3 mb-3">
                  <span className="text-sm font-mono font-bold text-[#34D399]">Always Loaded</span>
                  <span className="text-[10px] font-mono text-white/30">{deferredSpec.alwaysLoaded.length} core tools</span>
                </div>
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {deferredSpec.alwaysLoaded.map((tool) => (
                    <span key={tool} className="px-2 py-0.5 rounded text-[11px] font-mono text-[#34D399]/70 bg-[#34D399]/08 border border-[#34D399]/12">{tool}</span>
                  ))}
                </div>
                <p className="text-xs text-[#9BB0CC]">
                  {t(locale,
                    "가장 빈번하게 사용되는 core 도구. defer 활성화 여부와 관계없이 항상 전체 스키마가 로딩됩니다.",
                    "Most frequently used core tools. Full schema always loaded regardless of defer activation."
                  )}
                </p>
              </div>

              {/* Deferred mechanism */}
              <div className="rounded-xl border border-white/[0.04] px-5 py-4 mb-4" style={{ background: "#F5C54204" }}>
                <div className="flex items-center gap-3 mb-3">
                  <span className="text-sm font-mono font-bold text-[#F5C542]">Deferred Mechanism</span>
                  <span className="text-[10px] font-mono text-white/30">threshold={deferredSpec.threshold}</span>
                </div>
                <div className="space-y-2 text-xs text-[#A0B4D4]">
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 text-[10px] font-mono font-bold text-[#F5C542]">1</span>
                    <span>{t(locale,
                      `native(43) + MCP 합산이 ${deferredSpec.threshold}개를 초과하면 deferred 모드 활성화`,
                      `Deferred mode activates when native(43) + MCP combined exceeds ${deferredSpec.threshold}`
                    )}</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 text-[10px] font-mono font-bold text-[#F5C542]">2</span>
                    <span>{locale === "ko"
                      ? <>나머지 도구는 <code className="text-[#C084FC]/60">defer_loading: true</code> 마킹. 이름만 LLM에 전달</>
                      : <>Remaining tools marked <code className="text-[#C084FC]/60">defer_loading: true</code>. Only names sent to LLM</>
                    }</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 text-[10px] font-mono font-bold text-[#F5C542]">3</span>
                    <span>{locale === "ko"
                      ? <>LLM이 <code className="text-[#C084FC]/60">tool_search(query=&quot;...&quot;)</code>로 필요한 도구 검색</>
                      : <>LLM searches for needed tools via <code className="text-[#C084FC]/60">tool_search(query=&quot;...&quot;)</code></>
                    }</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="shrink-0 text-[10px] font-mono font-bold text-[#F5C542]">4</span>
                    <span>{t(locale,
                      "매칭된 도구의 전체 스키마가 로딩되어 이후 턴에서도 유지",
                      "Full schema of matched tools is loaded and persists in subsequent turns"
                    )}</span>
                  </div>
                </div>
              </div>

              {/* Context saving + categories */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="rounded-lg border border-white/[0.04] px-4 py-3">
                  <div className="text-2xl font-bold text-[#4ECDC4]">{deferredSpec.saving}</div>
                  <div className="text-[10px] font-mono text-white/30">{t(locale, "Context Token 절감", "Context Token Savings")}</div>
                  <div className="text-[9px] font-mono text-white/15 mt-1">{t(locale, "전체 스키마 대신 이름만 전달", "Only names sent instead of full schema")}</div>
                </div>
                <div className="rounded-lg border border-white/[0.04] px-4 py-3">
                  <div className="text-sm font-mono font-bold text-[#C084FC] mb-1">Search Categories</div>
                  <div className="flex flex-wrap gap-1">
                    {deferredSpec.categories.map((c) => (
                      <span key={c} className="px-1.5 py-px rounded text-[9px] font-mono text-[#C084FC]/50 bg-[#C084FC]/06">{c}</span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
            </motion.div>
          )}

          {/* ── 5-Tier Safety ── */}
          {activeTab === "safety" && (
            <motion.div key="safety" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <div>
              {/* Tier spectrum bar */}
              <div className="flex gap-1 mb-6 rounded-lg overflow-hidden">
                {tiers.map((ti) => (
                  <div key={ti.tier} className="flex-1 py-2 text-center" style={{ background: `${ti.color}12` }}>
                    <div className="text-[10px] font-mono font-bold" style={{ color: ti.color }}>{ti.tier}</div>
                    <div className="text-[9px] font-mono text-white/30">{ti.count}</div>
                  </div>
                ))}
              </div>

              <div className="space-y-2">
                {tiers.map((ti) => (
                  <div key={ti.tier} className="rounded-lg border border-white/[0.04] px-4 py-3" style={{ background: `${ti.color}03` }}>
                    <div className="flex items-center gap-3 mb-1.5">
                      <span className="text-sm font-mono font-bold" style={{ color: ti.color }}>{ti.tier} {ti.name}</span>
                      <span className="text-[10px] font-mono text-white/30">{ti.count} tools</span>
                      <span className="ml-auto px-2 py-0.5 rounded text-[10px] font-mono"
                        style={{ color: ti.color, background: `${ti.color}10` }}>{locale === "en" ? ti.gateEn : ti.gateKo}</span>
                    </div>
                    <p className="text-xs text-[#A0B4D4] mb-1">{locale === "en" ? ti.execEn : ti.execKo}</p>
                    <code className="text-[10px] font-mono text-white/20">{ti.examples}</code>
                  </div>
                ))}
              </div>

              {/* Approval mechanism */}
              <div className="mt-4 rounded-lg border border-white/[0.04] px-4 py-3">
                <div className="text-xs font-semibold text-white/50 mb-2">Session-Level Always Approval</div>
                <p className="text-xs text-[#9BB0CC]">
                  {locale === "ko"
                    ? <>승인 프롬프트에서 <code className="text-[#4ECDC4]/50">A</code>(Always) 응답 시 해당 카테고리(bash, write, cost, mcp:서버명) 전체가 세션 내 자동 승인.</>
                    : <>Responding <code className="text-[#4ECDC4]/50">A</code> (Always) at the approval prompt auto-approves the entire category (bash, write, cost, mcp:server) for the session.</>
                  }
                </p>
              </div>
            </div>
            </motion.div>
          )}

          {/* ── 47 Tools Inventory ── */}
          {activeTab === "inventory" && (
            <motion.div key="inventory" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
            <div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 mb-4">
                {categories.map((c) => (
                  <div key={c.name} className="rounded-lg border border-white/[0.04] px-3 py-2.5 text-center"
                    style={{ background: `${c.color}04` }}>
                    <div className="text-lg font-bold" style={{ color: c.color }}>{c.count}</div>
                    <div className="text-[10px] font-mono text-white/40">{c.name}</div>
                  </div>
                ))}
              </div>

              {/* MCP + total summary */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="rounded-lg border border-white/[0.04] px-4 py-3" style={{ background: "#4ECDC404" }}>
                  <div className="text-2xl font-bold text-[#4ECDC4]">43</div>
                  <div className="text-[10px] font-mono text-white/30">Native Tools</div>
                  <div className="text-[9px] font-mono text-white/15 mt-1">12 categories</div>
                </div>
                <div className="rounded-lg border border-white/[0.04] px-4 py-3" style={{ background: "#818CF804" }}>
                  <div className="text-2xl font-bold text-[#818CF8]">44</div>
                  <div className="text-[10px] font-mono text-white/30">MCP Servers</div>
                  <div className="text-[9px] font-mono text-white/15 mt-1">3 auto-approved</div>
                </div>
                <div className="rounded-lg border border-white/[0.04] px-4 py-3" style={{ background: "#C084FC04" }}>
                  <div className="text-2xl font-bold text-[#C084FC]">91+</div>
                  <div className="text-[10px] font-mono text-white/30">Total Toolset</div>
                  <div className="text-[9px] font-mono text-white/15 mt-1">native + MCP + skills</div>
                </div>
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
