import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Meta-harness catalog — GEODE Docs" };

/**
 * Meta-harness catalog. Single-sourced row data rendered into both locales.
 *
 * Every row is code-verified: the mechanism class/function exists at the
 * listed path, and the control surface is the actual knob (config key, env,
 * hook event, gate threshold, CLI flag). No unverified entries
 * (CLAUDE.md CANNOT: no catalog padding).
 */

type Row = {
  name: string; // mechanism, language-neutral
  ko: string; // what divergence it bounds (KO)
  en: string; // what divergence it bounds (EN)
  control: string; // control surface, code-ish neutral
  path: string; // repo-relative code path
};

const CONTEXT_ROWS: Row[] = [
  {
    name: "ContextWindowManager",
    ko: "컨텍스트 총량이 임계선을 넘으면 emergency prune과 recovery를 발화",
    en: "Fires emergency prune and recovery when total context crosses the critical band",
    control: "CONTEXT_CRITICAL / CONTEXT_OVERFLOW_ACTION hooks",
    path: "core/agent/context_manager.py",
  },
  {
    name: "Context budget policy",
    ko: "모델 window에서 토큰 상한, warning, critical 밴드를 유도하는 단일 SoT",
    en: "Single SoT deriving token ceilings and warning/critical bands from the model window",
    control: "ceiling 200k, warn 50/70/80%, crit 90%, output reserve 20k",
    path: "core/orchestration/context_budget.py",
  },
  {
    name: "Message prune policy",
    ko: "first-user, bridge, 최근 N개만 유지해 히스토리를 예산 안에 고정",
    en: "Keeps first-user, bridge, and recent-N messages to hold history under budget",
    control: "activation at 30 msgs, keep-recent 5/8, floor 3",
    path: "core/orchestration/context_budget.py",
  },
  {
    name: "Deferred tool loading",
    ko: "도구가 임계 초과면 스키마를 검색 도구 뒤로 지연시켜 컨텍스트 범람 차단",
    en: "Above the threshold, defers tool schemas behind a search tool so definitions do not flood context",
    control: "TOOL_DEFER_THRESHOLD=16, always-loaded set",
    path: "core/llm/tool_defer.py",
  },
  {
    name: "Cache breakpoint policy",
    ko: "trailing cache_control breakpoint 수를 제한해 캐시 적중과 호출 오버헤드를 교환",
    en: "Bounds trailing cache_control breakpoints, trading cache hits against per-call overhead",
    control: "cache-policy.json messages_breakpoints, 0..3",
    path: "core/llm/cache_policy.py",
  },
  {
    name: "System-reminder injection",
    ko: "말미 고정 주입이 prefix-stable이라 프롬프트 캐시 키를 깨지 않음",
    en: "Tail-anchored reminder injection is prefix-stable, so it never re-keys the prompt cache",
    control: "cache contract pinned by tests",
    path: "core/agent/system_injection.py",
  },
  {
    name: "System prompt modes",
    ko: "persona 주입과 audit strip으로 모델이 수렴할 identity를 제어",
    en: "Persona injection and the audit strip control which identity the model converges toward",
    control: "GEODE_PERSONA=off, GEODE_AUDIT_UNRESTRICTED=1",
    path: "core/agent/system_prompt.py",
  },
  {
    name: "ToolResultOffloadStore",
    ko: "대형 tool result를 디스크로 이관하고 컨텍스트에는 ref만 남김",
    en: "Moves oversized tool results to disk, leaving only a reference in context",
    control: "threshold 5000 tokens, TOOL_RESULT_OFFLOADED hook",
    path: "core/orchestration/tool_offload.py",
  },
  {
    name: "Result token guard",
    ko: "tool result 단건에 모델 파생 토큰 상한을 적용해 절단",
    en: "Applies a model-derived per-result token cap and truncates before the result enters context",
    control: "max_tool_result_tokens setting",
    path: "core/agent/tool_executor/result_token_guard.py",
  },
  {
    name: "compact_conversation",
    ko: "server-side compaction이 없는 프로바이더용 4단계 클라이언트 압축",
    en: "Four-phase client-side compaction for providers without server-side compaction",
    control: "keep_recent arg, Anthropic no-op (server-side)",
    path: "core/orchestration/compaction.py",
  },
  {
    name: "SessionManager",
    ko: "메시지 상태를 checkpoint로 저장, 복원해 긴 실행을 유한 지점에서 재개",
    en: "Persists and rehydrates message state so long runs resume from a bounded checkpoint",
    control: "geode_checkpoints.db, cleanup 72h",
    path: "core/memory/session_manager.py",
  },
  {
    name: "EpisodicStore",
    ko: "회전 캡이 있는 episodic 메모리 tier, 무한 성장 없이 recall 공급",
    en: "Rolling episodic memory tier with a rotation cap, feeding recall without unbounded growth",
    control: "JSONL rotation cap",
    path: "core/memory/episodic.py",
  },
  {
    name: "DreamingService",
    ko: "세션을 배경에서 압축 artifact로 통합",
    en: "Background synthesis that consolidates a session into a compact artifact",
    control: "dream artifact via SessionManager",
    path: "core/memory/dreaming.py",
  },
];

const EXECUTE_ROWS: Row[] = [
  {
    name: "AgenticLoop",
    ko: "perceive, plan, act, observe inner 루프. round, time, cost 가드가 폭주를 절단",
    en: "The perceive-plan-act-observe inner loop; round, time, and cost guards cut runaway iteration",
    control: "max_rounds (default 0=unlimited), time_budget_s, cost_budget",
    path: "core/agent/loop/agent_loop.py",
  },
  {
    name: "Plan + Dynamic Replan",
    ko: "명시적 Plan 객체를 세션에 유지하고 verify FAIL, cadence, low-confidence 세 트리거로 planner LLM을 재발화",
    en: "Keeps an explicit Plan object per session and re-fires the planner LLM on three triggers: verify FAIL, cadence, low confidence",
    control: "replan_interval, REPLAN_LOW_CONFIDENCE=0.4",
    path: "core/agent/plan.py",
  },
  {
    name: "Reflection node",
    ko: "도구 라운드마다 record_reflection 구조화 호출 1회로 CognitiveState의 가설과 confidence를 갱신",
    en: "One structured record_reflection call per tool round updates the CognitiveState hypotheses and confidence",
    control: "cognitive_reflection_enabled, max_tokens 512",
    path: "core/agent/loop/_reflection.py",
  },
  {
    name: "CognitiveState + store",
    ko: "hypotheses, confidence, subgoals 믿음 상태를 SQLite에 지속화. 세션 재개의 DB-first 소스",
    en: "Persists the hypotheses, confidence, and subgoals belief state to SQLite; the DB-first source for session resume",
    control: "snapshot + append-only event stream",
    path: "core/memory/cognitive_state_store.py",
  },
  {
    name: "ConvergenceDetector",
    ko: "동일 도구 에러 3연속 또는 무진전 성공 반복에서 루프를 종료",
    en: "Ends the loop on three identical tool errors or repeated no-progress successes",
    control: "REPEATED_SUCCESS_THRESHOLD=5",
    path: "core/agent/convergence.py",
  },
  {
    name: "TimeBudget",
    ko: "세션 wall-clock 예산. 만료 전 임계에서 handoff를 먼저 발화",
    en: "Session wall-clock budget; fires a handoff at the threshold before hard expiry",
    control: "budget_seconds, handoff threshold, HANDOFF_TRIGGERED hook",
    path: "core/agent/budget.py",
  },
  {
    name: "Cost budget guard",
    ko: "세션 USD 상한. 80%에서 경고, 초과 시 루프 정지",
    en: "Session USD ceiling; warns at 80 percent and halts the loop on breach",
    control: "cost.limit_usd config, COST_LIMIT_EXCEEDED hook",
    path: "core/agent/loop/agent_loop.py",
  },
  {
    name: "Lane / LaneQueue",
    ko: "세마포어로 세션 간 동시 실행을 제한",
    en: "Semaphore-bounded concurrency across sessions",
    control: "max concurrent 50, max sessions 256",
    path: "core/orchestration/lane_queue.py",
  },
  {
    name: "Audit lane",
    ko: "Petri 감사 서브프로세스를 직렬화해 cron과 수동 감사의 충돌, 이중 지출 차단",
    en: "Serializes Petri audit subprocesses so cron and manual audits never collide or double-spend",
    control: "max_concurrent 1, 15-min timeout",
    path: "core/orchestration/audit_lane.py",
  },
  {
    name: "SubAgentManager + roles",
    ko: "서브에이전트의 도구 표면과 재귀 위임을 role allowlist로 제한",
    en: "Bounds sub-agent tool surface and recursive delegation via role allowlists",
    control: "SUBAGENT_ROLES, role_denied_tools",
    path: "core/agent/sub_agent.py",
  },
  {
    name: "Candidate sampling",
    ko: "같은 작업 best-of-N 팬아웃과 judge 선택. N 상한으로 비용 제한",
    en: "Best-of-N fan-out with judge selection; a hard cap on N bounds cost",
    control: "hard cap N=4, diversity lens per index",
    path: "core/agent/candidate_sampling.py",
  },
  {
    name: "ToolExecutor denylist",
    ko: "safety gate와 handler 조회 이전에 도구를 거부하는 headless denylist",
    en: "Headless denylist that refuses a tool before the safety gate or handler lookup",
    control: "denied_tools frozenset (ctor)",
    path: "core/agent/tool_executor/executor.py",
  },
  {
    name: "Safety classification",
    ko: "도구별 위험 분류. DANGEROUS 도구는 HITL 승인 필수",
    en: "Per-tool risk classification; DANGEROUS tools require HITL approval",
    control: "DANGEROUS_TOOLS set, GEODE_DANGEROUSLY_SKIP_PERMISSIONS",
    path: "core/agent/safety.py",
  },
  {
    name: "Computer-use HITL",
    ko: "화면 제어 도구는 명시적 사용자 거부 경로가 있는 게이트를 통과",
    en: "Screen-control tools pass a gate with an explicit user deny path",
    control: "600s tool deadline, denied result contract",
    path: "core/agent/tool_executor/executor.py",
  },
  {
    name: "Approval FSM",
    ko: "HITL 승인 상태기계. 3-strike 자동 거부, 모든 전이를 기록",
    en: "HITL approval state machine; three-strike auto-deny, every transition recorded",
    control: "legal-transition table, APPROVAL_TRANSITION hook",
    path: "core/agent/approval_fsm.py",
  },
  {
    name: "Hook interceptor",
    ko: "interceptor 모드 훅이 도구, LLM 호출을 실행 중에 차단하거나 수정",
    en: "Interceptor-mode hooks block or modify tool and LLM execution mid-flight",
    control: "handler returns block:true, per-handler timeout_s",
    path: "core/hooks/system.py",
  },
  {
    name: "PlanMode",
    ko: "다단계 작업의 plan, approve, execute 게이트",
    en: "Plan, approve, execute gate for multi-step work",
    control: "MANUAL (default) vs AUTO execution mode",
    path: "core/orchestration/plan_mode.py",
  },
  {
    name: "SchedulerService",
    ko: "lock과 jitter로 반복 작업의 동시 발화를 억제",
    en: "Bounds recurring-job execution with a lock and jitter",
    control: "enable_jitter, max_jitter_ms, SchedulerLock",
    path: "core/scheduler/service.py",
  },
  {
    name: "Model switching",
    ko: "/model 전환 시 drift-health 체크와 캐시 안전 breadcrumb 주입",
    en: "Model switch runs a drift-health check and injects a cache-safe breadcrumb",
    control: "/model command, MODEL_SWITCHED hook",
    path: "core/agent/loop/_model_switching.py",
  },
];

const VERIFY_ROWS: Row[] = [
  {
    name: "VerifyMode",
    ko: "턴 단위 rubric 검증. 회복 가능한 miss는 재시도로 수렴",
    en: "Per-turn rubric verification; recoverable misses converge through retries",
    control: "GEODE_VERIFY_MODE (off / rule_based / llm_judge)",
    path: "core/agent/verify.py",
  },
  {
    name: "compute_fitness",
    ko: "per-dim 감사 점수를 stability 가중으로 단일 fitness 스칼라에 집계",
    en: "Aggregates per-dim audit scores into one fitness scalar with stability weighting",
    control: "critical_margin 0.5, MC margin 1000 samples",
    path: "core/self_improving/fitness.py",
  },
  {
    name: "AXIS_TIERS + critical floors",
    ko: "차원을 tier로 분류. critical 5개 dim은 후퇴 시 무조건 거부",
    en: "Tiers every dimension; the five critical dims strict-reject on any regression",
    control: "CRITICAL_DIMS, tier weights",
    path: "core/self_improving/fitness.py",
  },
  {
    name: "Promotion margin gate",
    ko: "gain 대 stderr margin으로 승격 판정. critical veto가 항상 선행",
    en: "Promotion decided by a gain-versus-stderr margin; the critical veto always runs first",
    control: "fitness_margin_floor, hard-contract veto",
    path: "core/self_improving/gate.py",
  },
  {
    name: "Promote-policy control arm",
    ko: "gate, random, never 3-arm으로 이득을 무변이 바닥과 대조 측정",
    en: "Three-arm gate/random/never policy measures gains against a no-mutation floor",
    control: "--promote-policy, --promote-policy-seed",
    path: "core/self_improving/gate.py",
  },
  {
    name: "Rollback condition",
    ko: "자유 서술 롤백 조건을 파싱해 veto 신호로 평가",
    en: "Parses free-text rollback conditions and evaluates them as a veto signal",
    control: "regression-pattern grammar",
    path: "core/self_improving/loop/observe/rollback_condition.py",
  },
  {
    name: "Statistical power",
    ko: "목표 효과 검출에 필요한 표본 수를 산출해 노이즈발 승격을 억제",
    en: "Computes the samples needed to detect a target effect, bounding noise-driven promotes",
    control: "--replicate M, alpha/power defaults",
    path: "core/self_improving/loop/observe/statistical_power.py",
  },
  {
    name: "Petri adversarial audit",
    ko: "적대 감사가 per-dim 안전 점수를 생산. 루프의 측정 계층",
    en: "The adversarial audit produces the per-dim safety scores; the loop's measurement layer",
    control: "geode audit CLI, petri role config",
    path: "core/self_improving/measure.py",
  },
  {
    name: "Champion chain",
    ko: "champion baseline을 변이, 감사 후 승격 또는 되돌림. (1+1) 체인",
    en: "Mutates a champion baseline, audits, then promotes or reverts; an honest (1+1) chain",
    control: "baseline.json vs tracked baseline_archive.jsonl",
    path: "core/self_improving/campaign.py",
  },
  {
    name: "Seed survivor selection",
    ko: "seed 생성 루프의 생존자를 감사 seed 풀로 교체하는 cross-loop handoff",
    en: "Cross-loop handoff swaps seed-generation survivors into the audit seed pool",
    control: "AUTORESEARCH_SEED_SELECT, seed_limit",
    path: "core/self_improving/train.py",
  },
  {
    name: "Judge selection",
    ko: "cross-LLM judge가 N개 후보 출력을 하나로 수렴. 실패는 관측 가능",
    en: "A cross-LLM judge converges N candidate outputs to one; failures stay observable",
    control: "select_candidate judge tool",
    path: "core/agent/candidate_sampling.py",
  },
];

const OBSERVE_ROWS: Row[] = [
  {
    name: "HookSystem",
    ko: "65개 이벤트의 중앙 계측 버스. observe, feedback, interceptor 3채널",
    en: "Central instrumentation bus of 65 events with observe, feedback, and interceptor channels",
    control: "trigger / trigger_with_result / trigger_interceptor",
    path: "core/hooks/system.py",
  },
  {
    name: "Event persistence spec",
    ko: "이벤트별 보존 클래스와 SQL, transcript 지속 여부를 선언하는 카탈로그",
    en: "Catalog declaring each event's retention class and SQL/transcript persistence",
    control: "4 retention classes (high-volume/standard/audit/transient)",
    path: "core/hooks/catalog.py",
  },
  {
    name: "HookEventStore",
    ko: "row, age, payload 캡이 있는 SQLite 이벤트 보존",
    en: "Bounded SQLite event persistence with row, age, and payload caps",
    control: "7/30/180d retention, max 100k rows, 8KB payload",
    path: "core/observability/event_store.py",
  },
  {
    name: "HookPersistenceSink",
    ko: "각 dispatch를 spec에 따라 SQL과 transcript로 라우팅",
    en: "Routes each dispatch to SQL and the transcript mirror per the catalog spec",
    control: "persist_sql / mirror_transcript flags",
    path: "core/observability/hook_persistence.py",
  },
  {
    name: "SessionTranscript",
    ko: "세션 이벤트의 append-only JSONL 감사 추적",
    en: "Append-only JSONL audit trail of every session event",
    control: "transcript dir, per-event truncation",
    path: "core/observability/transcript.py",
  },
  {
    name: "SessionMetrics",
    ko: "토큰, 캐시, thinking, 비용, 도구 호출, 시간 예산의 누적 ledger",
    en: "Cumulative ledger of tokens, cache, thinking, cost, tool calls, and time budget",
    control: "ContextVar-scoped, estimated_cost_usd",
    path: "core/observability/session_metrics.py",
  },
  {
    name: "JobRunLog",
    ko: "스케줄 job별 실행 이력. 크기와 행 수로 자동 prune",
    en: "Per-scheduler-job run history, auto-pruned by size and row count",
    control: "get_runs(limit), size/row prune",
    path: "core/observability/run_log.py",
  },
  {
    name: "UsageStore",
    ko: "일, 월 롤링 사용량 ledger. geode history의 데이터 소스",
    en: "Daily and monthly rolling usage ledger backing geode history",
    control: "~/.geode/usage/*.jsonl, eval-id dedup",
    path: "core/llm/usage_store.py",
  },
  {
    name: "Token tracker",
    ko: "호출당 로컬 비용 계산과 cache-hit-rate 집계",
    en: "Per-call local cost calculation and cache-hit-rate accounting",
    control: "per-provider cost tables",
    path: "core/llm/token_tracker.py",
  },
  {
    name: "OAuth usage windows",
    ko: "5시간, 7일 quota 버킷을 추적해 rate-limit 전에 backoff",
    en: "Tracks the 5-hour and 7-day quota buckets to back off before the rate limit",
    control: "quota-aware backoff windows",
    path: "core/llm/oauth_usage.py",
  },
  {
    name: "OTel export",
    ko: "런타임 이벤트의 선택적 OpenTelemetry span, metric 내보내기",
    en: "Optional OpenTelemetry span and metric export of runtime events",
    control: "env/config gated exporter",
    path: "core/observability/otel_export.py",
  },
  {
    name: "ActivityRegistry",
    ko: "지금 실행 중인 도구를 보여주는 라이브 activity 레지스트리",
    en: "Live registry of the currently running tool for the TUI",
    control: "updated per tool execution",
    path: "core/observability/activity_registry.py",
  },
];

const SCAFFOLD_ROWS: Row[] = [
  {
    name: "CLAUDE.md",
    ko: "제작 룰북. CANNOT 35룰(8영역)이 incident 인용과 함께 게이트 우회, SoT 드리프트, over-engineering을 차단",
    en: "The build rulebook: 35 CANNOT rules across 8 areas, each citing its originating incident, blocking gate bypass, SoT drift, and over-engineering",
    control: "CANNOT/CAN tables, wiring invariants",
    path: "CLAUDE.md",
  },
  {
    name: "AGENTS.md",
    ko: "코드 루트 내비게이션 맵과 Codex operating loop. 구조를 모른 채 수정하는 실패를 차단",
    en: "Code-root navigation map plus the Codex operating loop; prevents edits made blind to the module structure",
    control: "module map, non-negotiables",
    path: "AGENTS.md",
  },
  {
    name: "GEODE.md",
    ko: "런타임 identity와 RUNTIME CANNOT. 개발용 CANNOT의 실행 시점 대응물",
    en: "Runtime identity and RUNTIME CANNOT, the execution-time counterpart of the dev-time CANNOT",
    control: "Tier-0 injection, GEODE_PERSONA opt-out",
    path: "GEODE.md",
  },
  {
    name: "Workflow 0-8 + Socratic Gate",
    ko: "GAP audit과 5질문 게이트가 이미 있는 것의 재구축, 불필요 구현을 사전 차단",
    en: "GAP audit plus the five-question gate blocks rebuilding what exists and building what is not needed",
    control: "Socratic Q1-Q5, GAP 3-way classify",
    path: "CLAUDE.md, docs/workflow.md",
  },
  {
    name: "Scaffold skills",
    ko: "gitflow, workflow, anti-deception, verification-team 등 절차 스킬의 progressive disclosure",
    en: "Progressive-disclosure procedure skills: gitflow, workflow, anti-deception, verification-team, and more",
    control: "skill triggers per session",
    path: "docs/scaffold-skills.md",
  },
  {
    name: "Local quality gates",
    ko: "lint, format, type, imports, test, CLI smoke 6종. 파이프로 감싼 게이트는 금지",
    en: "Six gates: lint, format, type, imports, test, CLI smoke; piping a gate command is forbidden",
    control: "exit codes asserted bare",
    path: "CLAUDE.md (Quality Gates)",
  },
  {
    name: "CI ratchet suite",
    ko: "legacy import, repo hygiene, slop growth, llms 버전, petri bundle, hero layout 커스텀 ratchet이 침묵 퇴행을 차단",
    en: "Custom ratchets for legacy imports, repo hygiene, slop growth, llms version, petri bundle, and hero layout block silent regressions",
    control: "scripts/check_*.py wired into ci.yml",
    path: ".github/workflows/ci.yml",
  },
  {
    name: "Prompt integrity pins",
    ko: "runtime 프롬프트 변경은 같은 커밋에서 해시 pin 갱신을 강제. 의도치 않은 drift는 빌드 실패",
    en: "Changing a runtime prompt forces a hash-pin update in the same commit; unintended drift fails the build",
    control: "_PINNED_HASHES (4 pins), verify_prompt_integrity",
    path: "core/llm/prompts/__init__.py",
  },
  {
    name: "Test-count floor",
    ko: "테스트 수 하한 ratchet. 테스트 삭제로 만드는 가짜 green을 차단",
    en: "A minimum-test-count ratchet blocks fake green produced by deleting tests",
    control: "pytest count floor in CI",
    path: ".github/workflows/ci.yml",
  },
  {
    name: "Worktree isolation + .owner",
    ko: "작업 단위마다 worktree 격리. 타 세션 소유물 보호, orphan은 hygiene ratchet이 검출",
    en: "Every work unit runs in an isolated worktree; ownership is protected and orphans are caught by the hygiene ratchet",
    control: ".owner convention, check_repo_hygiene.py",
    path: ".claude/worktrees/",
  },
  {
    name: "Merge flow",
    ko: "feature는 develop에 squash, develop은 main에 pass-through. 매 사이클 main에서 develop로 선동기화",
    en: "Features squash into develop, develop passes through to main, with a main-to-develop pre-sync every cycle",
    control: "CI 5/5 required, PR template",
    path: "CLAUDE.md (PR & Merge)",
  },
  {
    name: "Version SoT fan-out",
    ko: "버전 스탬프 5위치와 파생 파일 재생성. stale 스냅숏은 CI ratchet이 차단",
    en: "Version stamps across five locations plus derived-file regeneration; stale snapshots are blocked by a CI ratchet",
    control: "sync-stats.mjs, check_llms_version.py",
    path: "site/scripts/sync-stats.mjs",
  },
  {
    name: "Cross-LLM verification",
    ko: "PR마다 Codex MCP 교차 검증을 병행. 로컬 게이트 단독 종결 금지",
    en: "Every PR runs a parallel Codex MCP cross-verification; local gates alone never close a change",
    control: "top-tier reviewer model pinned",
    path: "docs/workflow.md",
  },
];

const TERMINATION_REASONS = [
  "max_rounds",
  "time_budget_expired",
  "session_time_budget_handoff",
  "session_time_budget_expired",
  "input_blocked",
  "billing_error",
  "user_cancelled",
  "model_action_required",
  "actionable_partial",
  "context_exhausted",
  "tool_use_yield",
  "cost_budget_exceeded",
  "user_clarification_needed",
  "model_refusal",
  "convergence_detected",
  "repeated_success_no_progress",
];

function AxisTable({
  rows,
  lang,
  headers,
}: {
  rows: Row[];
  lang: "ko" | "en";
  headers?: [string, string, string, string];
}) {
  const h =
    headers ??
    (lang === "ko"
      ? (["메커니즘", "묶는 발산", "제어 지점", "위치"] as const)
      : (["Mechanism", "Bounds", "Control surface", "Path"] as const));
  return (
    <table>
      <thead>
        <tr>
          {h.map((x) => (
            <th key={x}>{x}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <td>
              <strong>{r.name}</strong>
            </td>
            <td>{lang === "ko" ? r.ko : r.en}</td>
            <td>{r.control}</td>
            <td>
              <code>{r.path}</code>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TerminationList() {
  return (
    <ul>
      {TERMINATION_REASONS.map((t) => (
        <li key={t}>
          <code>{t}</code>
        </li>
      ))}
    </ul>
  );
}

export default function Page() {
  return (
    <DocsShell
      slug="reference/meta-harness-catalog"
      title="Meta-harness catalog"
      titleKo="메타 하네스 카탈로그"
      summary="Every mechanism that converges GEODE's stochastic runtime, on five axes: Context Control, Plan and Execute, Verify, Observe, and the Scaffold that builds GEODE itself. Each entry is code-verified with its control surface and path."
      summaryKo="GEODE의 확률적 런타임을 수렴시키는 메커니즘 전체를 다섯 축으로 정리합니다. Context Control, Plan and Execute, Verify, Observe, 그리고 GEODE 자신을 제작하는 Scaffold 축입니다. 모든 항목은 코드 검증을 거쳐 제어 지점과 경로를 담습니다."
    >
      <Bi
        ko={
          <>
            <h2>용어: harness와 scaffold</h2>
            <p>
              2026년 기준 에이전트 커뮤니티의 용어 관례는 두 층을 구분합니다.{" "}
              <strong>harness</strong>는 실행 계층입니다. 루프를 돌리고, 도구를
              실행하고, 언제 멈출지 결정합니다. <strong>scaffold</strong>는 행동
              정의 계층입니다. 프롬프트, 도구 설명, 지침 파일이 여기 속합니다.
              에이전트는 model, scaffold, harness의 합입니다 (
              <a href="https://huggingface.co/blog/agent-glossary">
                HuggingFace agent glossary
              </a>
              ,{" "}
              <a href="https://www.firecrawl.dev/blog/what-is-an-agent-harness">
                Firecrawl
              </a>
              ).
            </p>
            <p>GEODE가 메타 하네스인 이유는 세 겹의 관계 때문입니다.</p>
            <ul>
              <li>
                <strong>제작</strong>. GEODE의 코드는 다른 하네스(Claude Code,
                Codex CLI)가 <code>CLAUDE.md</code>와 <code>AGENTS.md</code>라는
                scaffold를 읽으며 생산합니다. 아래 Scaffold 축이 이 제작
                하네스의 카탈로그입니다.
              </li>
              <li>
                <strong>실행</strong>. GEODE 자체가 하네스입니다. Context
                Control, Plan and Execute, Verify, Observe 네 축의 런타임
                메커니즘이 모델의 발산을 묶습니다.
              </li>
              <li>
                <strong>자기개선</strong>.{" "}
                <a href="/geode/docs/capabilities/autoresearch">
                  self-improving outer 루프
                </a>
                가 자기 자신의 runtime scaffold(시스템 프롬프트 섹션, behaviour
                kinds)를 변이하고 감사해 승격하거나 되돌립니다. 하네스가 자기
                scaffold를 다시 쓰는 구조입니다.
              </li>
            </ul>
            <h2>표 읽는 법</h2>
            <p>
              각 행은 메커니즘 하나입니다. 어떤 발산을 묶는지, 운영자가 만지는
              제어 지점이 무엇인지, 코드가 어디 있는지를 담습니다. 모든 행은
              코드에서 클래스와 제어 지점의 존재를 확인한 것만 실었습니다.
              수치(임계값, 캡, 기본값)는 소스의 상수를 그대로 옮긴 것입니다.
            </p>
          </>
        }
        en={
          <>
            <h2>Terminology: harness and scaffold</h2>
            <p>
              The agent community's 2026 convention separates two layers. The{" "}
              <strong>harness</strong> is the execution layer: it runs the loop,
              executes tools, and decides when to stop. The{" "}
              <strong>scaffold</strong> is the behavior-defining layer: prompts,
              tool descriptions, instruction files. An agent is model plus
              scaffold plus harness (
              <a href="https://huggingface.co/blog/agent-glossary">
                HuggingFace agent glossary
              </a>
              ,{" "}
              <a href="https://www.firecrawl.dev/blog/what-is-an-agent-harness">
                Firecrawl
              </a>
              ).
            </p>
            <p>GEODE is a meta-harness because of three stacked relations.</p>
            <ul>
              <li>
                <strong>Built by a harness</strong>. GEODE's code is produced by
                other harnesses (Claude Code, Codex CLI) reading the{" "}
                <code>CLAUDE.md</code> and <code>AGENTS.md</code> scaffold. The
                Scaffold axis below catalogs that build harness.
              </li>
              <li>
                <strong>Is a harness</strong>. GEODE itself is a harness: the
                four runtime axes, Context Control, Plan and Execute, Verify,
                and Observe, bound the model's divergence.
              </li>
              <li>
                <strong>Re-scaffolds itself</strong>. The{" "}
                <a href="/geode/docs/capabilities/autoresearch">
                  self-improving loop
                </a>{" "}
                mutates, audits, and promotes or reverts its own runtime
                scaffold (system-prompt sections, behaviour kinds). A harness
                rewriting its own scaffold.
              </li>
            </ul>
            <h2>How to read the tables</h2>
            <p>
              Each row is one mechanism: the divergence it bounds, the control
              surface an operator touches, and where the code lives. Only
              mechanisms whose class and control surface were verified in code
              are listed. Numbers (thresholds, caps, defaults) are copied from
              constants in the source.
            </p>
          </>
        }
      />

      <Bi
        ko={
          <>
            <h2>축 1. Context Control</h2>
            <p>
              모델 컨텍스트에 무엇이 들어가는지를 묶는 축입니다. 루프와
              가드레일이 출력의 상한을 결정한다는 원칙의 구현부입니다. 배경
              설명은{" "}
              <a href="/geode/docs/runtime/context">컨텍스트 조립</a>과{" "}
              <a href="/geode/docs/runtime/tools/protocol">도구와 툴셋</a>{" "}
              문서에 있습니다.
            </p>
            <AxisTable rows={CONTEXT_ROWS} lang="ko" />
          </>
        }
        en={
          <>
            <h2>Axis 1. Context Control</h2>
            <p>
              The axis that bounds what enters the model's context. This is the
              implementation of the principle that the loop and its guardrails
              set the ceiling on output quality. Background:{" "}
              <a href="/geode/docs/runtime/context">Context assembly</a> and{" "}
              <a href="/geode/docs/runtime/tools/protocol">
                Tools and toolsets
              </a>
              .
            </p>
            <AxisTable rows={CONTEXT_ROWS} lang="en" />
          </>
        }
      />

      <Bi
        ko={
          <>
            <h2>축 2. Plan and Execute</h2>
            <p>
              모델 출력을 통제된 행동으로 바꾸는 축입니다. 중심은{" "}
              <a href="/geode/docs/architecture/agentic-loop">AgenticLoop</a>,
              곧 inner 루프입니다. outer 루프(self-improving)가 시스템 자체를
              다듬는 동안, inner 루프는 작업 하나를 끝까지 처리합니다. 루프는
              ReAct 계열의 reason과 act 교차 패턴을 따르되, 그 위에 명시적
              cognitive 층이 얹혀 있습니다.
            </p>
            <h3>Cognitive 사이클: reflection, plan, verify, replan</h3>
            <p>
              한 라운드는 도구 실행 결과를 관측하고, reflection으로 믿음을
              갱신하고, 트리거가 서면 plan을 다시 씁니다. 네 조각이 하나의
              사이클로 묶입니다.
            </p>
            <ul>
              <li>
                <strong>Planning</strong>. 명시적 <code>Plan</code> 객체가
                세션에 붙고 replan마다 revision이 증가합니다. 다단계 작업의
                승인 게이트는 별도 메커니즘인 PlanMode가 맡습니다.
              </li>
              <li>
                <strong>Reflection (cognitive)</strong>. 도구 라운드마다{" "}
                <code>record_reflection</code> 구조화 호출 1회가
                CognitiveState를 갱신합니다. hypotheses 5개 이하, confidence
                0..1, next_action_hint가 subgoals로 들어갑니다. 전체 대화가
                아니라 상태 스냅숏과 도구 요약만 봅니다(clean-context 규율).
              </li>
              <li>
                <strong>verify 후 replan</strong>. replan은 세 트리거로
                발화합니다. verify FAIL(다음 실행의 첫 라운드), cadence(
                <code>replan_interval</code> 라운드마다), low-confidence
                (confidence 0.4 미만, edge-trigger라 회복 전 재발화가 없어
                replan 폭풍을 방지). replan 실패는 루프를 죽이지 않습니다.
              </li>
              <li>
                <strong>지속화</strong>. CognitiveStateStore가 스냅숏과 이벤트
                스트림을 SQLite에 저장하고, 세션 재개의 DB-first 소스가
                됩니다.
              </li>
            </ul>
            <p>
              기본 round 상한이 0(무제한)이라 실질적 경계는 시간과 비용
              예산입니다. 루프가 정직하게 끝나는 명명된 종료 경로는 아래 16개에
              정상 완료(도구 호출 없는 텍스트 응답)를 더한 것입니다.
            </p>
            <TerminationList />
            <AxisTable rows={EXECUTE_ROWS} lang="ko" />
          </>
        }
        en={
          <>
            <h2>Axis 2. Plan and Execute</h2>
            <p>
              The axis that turns model output into controlled action. The
              center is the{" "}
              <a href="/geode/docs/architecture/agentic-loop">AgenticLoop</a>,
              the inner loop. While the outer loop (self-improving) tunes the
              system itself, the inner loop carries one task to completion. It
              follows the ReAct family of interleaved reason-and-act, with an
              explicit cognitive layer on top.
            </p>
            <h3>The cognitive cycle: reflection, plan, verify, replan</h3>
            <p>
              A round observes tool results, updates beliefs through
              reflection, and rewrites the plan when a trigger fires. Four
              pieces form one cycle.
            </p>
            <ul>
              <li>
                <strong>Planning</strong>. An explicit <code>Plan</code> object
                is attached to the session, its revision incremented on every
                replan. The approve gate for multi-step work is a separate
                mechanism, PlanMode.
              </li>
              <li>
                <strong>Reflection (cognitive)</strong>. One structured{" "}
                <code>record_reflection</code> call per tool round updates the
                CognitiveState: up to five hypotheses, confidence in 0..1, and
                a next_action_hint pushed into subgoals. It sees only the state
                snapshot and a tool summary, not the full conversation
                (clean-context discipline).
              </li>
              <li>
                <strong>verify then replan</strong>. Replan fires on three
                triggers: verify FAIL (first round of the next run), cadence
                (every <code>replan_interval</code> rounds), and low confidence
                (below 0.4, edge-triggered so it cannot re-fire before
                confidence recovers, preventing a replan storm). A failed
                replan never kills the loop.
              </li>
              <li>
                <strong>Persistence</strong>. The CognitiveStateStore writes
                snapshots and an event stream to SQLite, the DB-first source
                for session resume.
              </li>
            </ul>
            <p>
              The default round cap is 0 (unlimited), so the effective bounds
              are the time and cost budgets. The named termination paths are
              the sixteen below plus normal completion (a text response with no
              tool calls).
            </p>
            <TerminationList />
            <AxisTable rows={EXECUTE_ROWS} lang="en" />
          </>
        }
      />

      <Bi
        ko={
          <>
            <h2>축 3. Verify</h2>
            <p>
              비결정론적 출력을 신뢰 가능한 수준으로 수렴시키는 축입니다. 턴
              단위 검증부터 self-improving 루프의 fitness 게이트, critical
              floor, 대조군까지 이어집니다. 차원 체계는{" "}
              <a href="/geode/docs/petri/judge-dimensions">Judge 차원</a>{" "}
              문서를 참고하십시오.
            </p>
            <AxisTable rows={VERIFY_ROWS} lang="ko" />
          </>
        }
        en={
          <>
            <h2>Axis 3. Verify</h2>
            <p>
              The axis that converges nondeterministic output to a trustable
              level, from per-turn verification up to the self-improving loop's
              fitness gate, critical floors, and control arm. For the dimension
              taxonomy see{" "}
              <a href="/geode/docs/petri/judge-dimensions">Judge dimensions</a>.
            </p>
            <AxisTable rows={VERIFY_ROWS} lang="en" />
          </>
        }
      />

      <Bi
        ko={
          <>
            <h2>축 4. Observe</h2>
            <p>
              실제 작동을 계측하는 축입니다. 65개 훅 이벤트 버스가 중심이고,
              모든 계측 저장소에 보존 캡이 있습니다. 운영 관점은{" "}
              <a href="/geode/docs/verification/observability">관측성</a>{" "}
              문서에 있습니다.
            </p>
            <AxisTable rows={OBSERVE_ROWS} lang="ko" />
          </>
        }
        en={
          <>
            <h2>Axis 4. Observe</h2>
            <p>
              The instrumentation axis. The 65-event hook bus is the center,
              and every store carries a retention cap. For the operator view
              see{" "}
              <a href="/geode/docs/verification/observability">Observability</a>
              .
            </p>
            <AxisTable rows={OBSERVE_ROWS} lang="en" />
          </>
        }
      />

      <Bi
        ko={
          <>
            <h2>축 5. Scaffold, 제작 하네스</h2>
            <p>
              위 네 축이 GEODE가 작업을 실행할 때의 하네스라면, 이 축은 GEODE
              자신이 만들어질 때의 하네스입니다. 코드 생성 절차(CLAUDE.md 룰북,
              Socratic Gate), 검증 절차(품질 게이트, CI ratchet, cross-LLM
              검증), 커밋과 PR flow(worktree 격리, squash merge)가 에이전트
              빌더의 발산을 묶습니다. 표의 실패 모드 상당수는 실제 사고에서
              나온 것이고, CLAUDE.md의 각 룰이 원인 사고를 인용합니다. 이
              규율의 배경은{" "}
              <a href="/geode/docs/explanation/ratchet">왜 ratchet 규율인가</a>
              와{" "}
              <a href="/geode/docs/explanation/self-hosting">
                왜 self-hosting 하네스인가
              </a>{" "}
              문서에 있습니다.
            </p>
            <AxisTable
              rows={SCAFFOLD_ROWS}
              lang="ko"
              headers={["메커니즘", "막는 실패 모드", "게이트", "위치"]}
            />
          </>
        }
        en={
          <>
            <h2>Axis 5. Scaffold, the build harness</h2>
            <p>
              The four axes above harness GEODE while it runs tasks; this axis
              harnesses GEODE while it is being built. The code-generation
              procedure (the CLAUDE.md rulebook, the Socratic Gate), the
              verification procedure (quality gates, CI ratchets, cross-LLM
              review), and the commit-and-PR flow (worktree isolation, squash
              merges) bound the divergence of the agent builders. Most failure
              modes in the table come from real incidents; each CLAUDE.md rule
              cites the one that produced it. Background:{" "}
              <a href="/geode/docs/explanation/ratchet">
                Why ratchet discipline
              </a>{" "}
              and{" "}
              <a href="/geode/docs/explanation/self-hosting">
                Why a self-hosting harness
              </a>
              .
            </p>
            <AxisTable
              rows={SCAFFOLD_ROWS}
              lang="en"
              headers={["Mechanism", "Failure mode prevented", "Gate", "Path"]}
            />
          </>
        }
      />

      <Bi
        ko={
          <>
            <h2>관련 문서</h2>
            <ul>
              <li>
                <a href="/geode/docs/concepts/two-loops">두 개의 루프</a>. 이
                카탈로그가 기대는 멘탈 모델.
              </li>
              <li>
                <a href="/geode/docs/reference/frontier-comparison">
                  프론티어 비교
                </a>
                . 각 메커니즘이 어느 frontier 시스템에서 왔는지.
              </li>
              <li>
                <a href="/geode/docs/ops/long-running">장기 실행 안전</a>.
                round, time, cost 가드의 운영 관점.
              </li>
              <li>
                <a href="/geode/docs/runtime/orchestration">
                  서브에이전트 오케스트레이션
                </a>
                . Lane과 role allowlist의 상세.
              </li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Related pages</h2>
            <ul>
              <li>
                <a href="/geode/docs/concepts/two-loops">The two loops</a>. The
                mental model this catalog builds on.
              </li>
              <li>
                <a href="/geode/docs/reference/frontier-comparison">
                  Frontier comparison
                </a>
                . Which frontier system each mechanism borrows from.
              </li>
              <li>
                <a href="/geode/docs/ops/long-running">Long-running safety</a>.
                The operator view of the round, time, and cost guards.
              </li>
              <li>
                <a href="/geode/docs/runtime/orchestration">
                  Sub-agent orchestration
                </a>
                . Lanes and role allowlists in detail.
              </li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
