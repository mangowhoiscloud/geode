# GEODE — 범용 자율 실행 에이전트

## Project Overview

LangGraph 기반 범용 자율 실행 에이전트. 리서치, 분석, 자동화, 스케줄링을 자율적으로 수행합니다.

- **Version**: 0.19.1
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Point**: `geode.cli:app` (Typer)
- **Modules**: 167
- **Tests**: 2688+
- **CHANGELOG**: `CHANGELOG.md` (Keep a Changelog + SemVer)

## Quick Start

```bash
# Install
uv sync

# Interactive REPL (primary interface)
uv run geode

# Natural language CLI
uv run geode "summarize the latest AI research trends"
uv run geode "compare React vs Vue for a new project"
uv run geode "schedule daily standup reminder at 9am"

# Game IP Domain Plugin (dry-run, no LLM)
uv run geode analyze "Cowboy Bebop" --dry-run

# Game IP Domain Plugin (full run, requires API keys)
uv run geode analyze "Cowboy Bebop" --verbose
```

## Architecture

6-Layer Architecture based on `architecture-v6.md` SOT.

```
L0: CLI & AGENT      — Typer CLI, AgenticLoop, SubAgentManager, Batch
L1: INFRASTRUCTURE   — Ports (Protocol), ClaudeAdapter, OpenAIAdapter, MCP Adapters
L2: MEMORY           — Organization > Project > Session + User Profile (4-Tier + Hybrid L1/L2)
L3: ORCHESTRATION    — HookSystem(36), TaskGraph DAG, PlanMode, CoalescingQueue, LaneQueue
L4: EXTENSIBILITY    — ToolRegistry(46), PolicyChain, Skills, MCP Catalog(42), Reports
L5: DOMAIN PLUGINS   — DomainPort Protocol, GameIPDomain, LangGraph StateGraph
```

### Sub-Agent System

서브에이전트는 부모 AgenticLoop의 전체 역량(tools, MCP, skills, memory)을 상속받아 독립 컨텍스트에서 병렬 실행.

```
Parent AgenticLoop → delegate_task → SubAgentManager
  → CoalescingQueue (250ms dedup) → TaskGraph (DAG)
  → IsolatedRunner (MAX_CONCURRENT=5) → Worker×N
  → SubAgentResult (summary 보존) → Token Guard (default: unlimited) → parent
```

| 구성 요소 | 설명 |
|----------|------|
| **SubAgentManager** | 병렬 위임 오케스트레이터. `action_handlers`/`mcp_manager`/`skill_registry` 자식 전달. 재귀 depth 제어 |
| **SubTask** | 입력 스펙 — `task_id`, `description`, `task_type` (analyze/search/compare), `args` |
| **SubAgentResult** | 표준 출력 — `status` (ok/error/timeout/partial), 필수 `summary`, `error_category`, `duration_ms`, `children_count` |
| **ErrorCategory** | `TIMEOUT`/`API_ERROR` (retryable) vs `VALIDATION`/`RESOURCE`/`DEPTH_EXCEEDED`/`UNKNOWN` (not retryable) |
| **IsolatedRunner** | 스레드 풀 격리 실행. `MAX_CONCURRENT=5`, 타임아웃 + 에러 격리 |
| **CoalescingQueue** | 250ms 윈도우 내 동일 task_id 중복 요청 병합 |
| **TaskGraph** | DAG 기반 실행 순서 결정, 순환 감지, 실패 전파 (`propagate_failure`) |
| **Token Guard** | tool_result 절단 (기본: 무제한, `GEODE_MAX_TOOL_RESULT_TOKENS`로 상한 설정 가능). `clear_tool_uses` 서버측 정리가 누적 방지 |

**제어 파라미터:**

| 항목 | 값 | 설명 |
|------|-----|------|
| `max_depth` | 2 | 재귀 위임 최대 깊이 (Root=0 → depth 2까지) |
| `max_total` | 15 | 세션당 최대 서브에이전트 수 |
| `MAX_CONCURRENT` | 5 | 동시 병렬 워커 수 |
| `timeout_s` | 120s | 개별 태스크 타임아웃 |
| `auto_approve` | True | 서브에이전트 STANDARD 도구 승인 생략 (DANGEROUS/WRITE는 항상 승인 필수) |
| `subagent_max_rounds` | 10 | 서브에이전트 AgenticLoop 라운드 제한 |
| `subagent_max_tokens` | 8192 | 서브에이전트 출력 토큰 제한 |

**Hook 이벤트**: `SUBAGENT_STARTED`, `SUBAGENT_COMPLETED`, `SUBAGENT_FAILED`

### Domain Plugin System

`DomainPort` Protocol로 도메인별 분석 파이프라인을 플러그인으로 교체 가능.

```
DomainPort (Protocol)
  ├── Identity: name, version, description
  ├── Analyst Config: get_analyst_types(), get_analyst_specific()
  ├── Evaluator Config: get_evaluator_types(), get_evaluator_axes(), get_valid_axes_map()
  ├── Scoring: get_scoring_weights(), get_tier_thresholds(), get_confidence_multiplier_params()
  ├── Classification: get_cause_values(), get_cause_to_action()
  └── Fixtures: list_fixtures(), get_fixture_path()
```

- **ContextVar 주입**: `set_domain()` / `get_domain()` — `contextvars` 기반 DI
- **Domain Loader**: `load_domain_adapter(name)` — 동적 임포트 + 레지스트리
- **기본 도메인**: `game_ip` → `core.domains.game_ip.adapter:GameIPDomain`
- **확장 방법**: `register_domain(name, adapter_path)` 후 `DomainPort` Protocol 구현

### Game IP Pipeline (Domain Plugin)

```
START → router → signals → analyst×4 (Send API)
     → evaluator×3 → scoring → verification
     → [confidence ≥ 0.7?] → synthesizer → END
                            → gather (loopback to signals, max 5 iter)
```

### Key Design Decisions

- **Port/Adapter DI**: All infra accessed via Protocol ports + contextvars injection
- **Sub-Agent Inheritance**: 자식은 부모의 tools/MCP/skills/memory 전체 상속 (P2-B)
- **Token Guard**: SubAgentResult의 `summary` 필드 필수 보존으로 컨텍스트 폭발 방지
- **Domain Plugin**: 파이프라인은 DomainPort 구현체로 교체 가능 (게임 IP는 플러그인)
- **Send API Clean Context**: Analysts receive state WITHOUT `analyses` to prevent anchoring
- **Decision Tree**: Cause classification is code-based, NOT LLM
- **graph.stream()**: Step-by-step progress tracking (not invoke)
- **Typed Evaluator Output**: Per-evaluator Pydantic models enforce required axes in structured output
- **Confidence Multiplier**: `final = base × (0.7 + 0.3 × confidence/100)`

### Recent Features (v0.15.0 -- v0.19.0)

| Version | Feature | Description |
|---------|---------|-------------|
| v0.15.0 | Tier 0.5 User Profile | `~/.geode/user_profile/` + `.geode/user_profile/` -- 프로필/선호/학습 패턴 영속 저장 |
| v0.16.0 | Config Cascade (TOML) | 4-level 우선순위: CLI > env > project TOML > global TOML > default |
| v0.16.0 | `geode init` | `.geode/` 디렉토리 구조 + 템플릿 config.toml + .gitignore 자동 생성 |
| v0.16.0 | Run History Context | ContextAssembler에 최근 실행 이력 3건 자동 주입 (Karpathy P6) |
| v0.17.0 | Cost Tracker / UsageStore | `~/.geode/usage/YYYY-MM.jsonl`에 LLM 비용 영속 저장 |
| v0.17.0 | Agent Reflection | `PIPELINE_END` Hook으로 `learned.md` 자동 패턴 추출 (Karpathy P4 Ratchet) |
| v0.17.0 | Cache Expiry 24h+hash | ResultCache 24h TTL + SHA-256 content hash 검증 |
| v0.17.0 | `geode history` | 실행 이력 + 모델별 비용 요약 조회 서브커맨드 |
| v0.19.0 | Messaging Integration | Slack/Discord/Telegram 아웃바운드 알림 + 인바운드 Gateway (OpenClaw 패턴) |
| v0.19.0 | Calendar Integration | Google Calendar + Apple Calendar (CalDAV) 양방향 동기화 |
| v0.19.0 | Notification Hook Plugin | PIPELINE_END/ERROR → 외부 채널 자동 알림 (YAML auto-discovery) |

## SOT (Source of Truth)

| Document | Path | Content |
|----------|------|---------|
| Architecture v6 | `docs/architecture-v6.md` | Full spec (335KB) |
| LangGraph Flow | `docs/langgraph-flow.md` | StateGraph topology |
| Layer Plan | `docs/layer-implementation-plan.md` | 6-layer roadmap |

## Project Structure

```
core/
├── cli/                 # CLI + Agentic Loop + Sub-Agent
│   ├── agentic_loop.py  # while(tool_use) multi-round + Token Guard + multi-provider
│   ├── agentic_response.py # AgenticResponse — provider-agnostic response normalization
│   ├── sub_agent.py     # SubAgentManager + SubAgentResult + ErrorCategory
│   ├── tool_executor.py # Tool dispatch + HITL + delegate_task + write fallback
│   ├── system_prompt.py # System prompt builder for AgenticLoop
│   ├── ip_names.py      # IP name registry (canonical names from fixtures)
│   ├── conversation.py  # Multi-turn sliding-window (max 200 turns, server-side clear_tool_uses)
│   ├── batch.py         # Batch analysis (ThreadPoolExecutor)
│   ├── commands.py      # Slash command dispatch (17 commands)
│   ├── repl.py          # REPL 메인 루프 (prompt_toolkit 기반)
│   ├── tool_handlers.py # 10개 논리 그룹 tool handler 디스패처
│   ├── result_cache.py  # ResultCache (24h TTL + SHA-256 content hash)
│   ├── error_recovery.py # ErrorRecoveryStrategy (retry → alternative → fallback → escalate)
│   └── search.py        # IP search engine (synonym expansion)
├── config.py            # Pydantic Settings (.env)
├── state.py             # GeodeState TypedDict + Pydantic models
├── graph.py             # StateGraph build + compile
├── runtime.py           # GeodeRuntime — DI wiring + graph execution
├── domains/             # Domain plugin adapters
│   ├── loader.py        # load_domain_adapter(), register_domain()
│   └── game_ip/         # GameIPDomain — DomainPort 구현
├── nodes/
│   ├── router.py        # 6-mode routing + fixture loading + memory assembly
│   ├── signals.py       # External signals fixture
│   ├── analysts.py      # 4 Analysts (Send API, Clean Context)
│   ├── evaluators.py    # 3+1 Evaluators (14-axis rubric, typed output models)
│   ├── scoring.py       # PSM Engine + 6-weighted composite + Tier
│   └── synthesizer.py   # Decision Tree + Narrative
├── llm/
│   ├── client.py        # Anthropic Claude wrapper (retry, circuit breaker, failover)
│   ├── prompts.py       # All prompt templates (versioned SHA-256)
│   ├── prompt_assembler.py  # ADR-007 prompt assembly
│   ├── skill_registry.py   # Skill definition + registry
│   ├── usage_store.py     # UsageStore — ~/.geode/usage/ LLM 비용 영속 저장
│   └── commentary.py       # LLM commentary generation
├── memory/
│   ├── organization.py  # Org tier — fixture-based, read-only
│   ├── project.py       # Project tier — .claude/MEMORY.md, rules, insights
│   ├── session.py       # Session tier — in-memory with TTL
│   ├── hybrid_session.py # L1(Redis) → L2(PostgreSQL) hybrid store
│   ├── session_key.py   # Hierarchical key builder (ip:name:phase)
│   └── context.py       # 4-tier context assembler
├── orchestration/
│   ├── hooks.py         # HookSystem (36 events + async atrigger)
│   ├── context_monitor.py # Context Overflow Detection (Karpathy P6 Context Budget)
│   ├── bootstrap.py     # Node bootstrap (pre-execution context injection)
│   ├── goal_decomposer.py # GoalDecomposer (compound request → sub-goal DAG)
│   ├── planner.py       # Planner (multi-step plan generation)
│   ├── plan_mode.py     # Plan mode state machine
│   ├── task_system.py   # TaskGraph DAG (dependency, cycle detection)
│   ├── task_bridge.py   # Task ↔ pipeline bridge
│   ├── coalescing.py    # CoalescingQueue (250ms dedup window)
│   ├── lane_queue.py    # Priority lane queue
│   ├── hook_discovery.py # Auto-discovery of hook handlers
│   ├── hot_reload.py    # Hot reload support
│   ├── isolated_execution.py # IsolatedRunner (MAX_CONCURRENT=5, thread pool)
│   ├── agent_reflection.py # Agent Reflection — PIPELINE_END 학습 패턴 추출
│   ├── run_log.py       # Run audit log
│   ├── stuck_detection.py # Stuck pipeline detection
│   ├── calendar_bridge.py # CalendarSchedulerBridge (scheduler ↔ calendar sync)
│   └── plugins/
│       └── notification_hook/ # YAML plugin: 이벤트 → 알림 자동 전송
├── gateway/               # Inbound messaging (OpenClaw Gateway pattern)
│   ├── models.py          # InboundMessage, ChannelBinding
│   ├── channel_manager.py # Binding-based routing + Lane Queue
│   └── pollers/           # Slack/Discord/Telegram daemon pollers
├── automation/
│   ├── triggers.py      # TriggerManager + unified dispatch
│   ├── predefined.py    # 10 predefined automation templates (§12.4)
│   ├── drift.py         # CUSUM drift detection
│   ├── snapshot.py      # Pipeline snapshot capture
│   ├── feedback_loop.py # 5-Phase RLHF cycle (incl. RLAIF)
│   ├── scheduler.py     # Cron-based scheduler
│   ├── nl_scheduler.py  # Natural language schedule parsing
│   ├── outcome_tracking.py # Outcome tracking + correlation
│   ├── correlation.py   # Statistical correlation analysis
│   ├── model_registry.py # Model version registry
│   ├── expert_panel.py  # Expert panel management
│   └── trigger_endpoint.py # HTTP trigger endpoint
├── verification/
│   ├── guardrails.py    # G1-G4 checks (schema, range, grounding, consistency)
│   ├── biasbuster.py    # 6 bias types (REAE framework)
│   ├── cross_llm.py     # Cross-LLM agreement + Krippendorff's α
│   ├── stats.py         # Statistical utilities (Krippendorff's α, shared)
│   └── rights_risk.py   # IP rights risk assessment
├── infrastructure/
│   ├── ports/           # Protocol interfaces (LLM, Memory, Auth, Hook, Tool, Domain, Notification, Calendar, Gateway)
│   └── adapters/
│       ├── llm/         # ClaudeAdapter, OpenAIAdapter
│       └── mcp/         # MCP adapters (9) + Composite adapters (3) + catalog (42 entries)
├── tools/               # Tool Protocol + Registry + Policy + definitions.json (46 tools)
├── auth/                # API key rotation, cooldown, profiles
├── extensibility/       # Report generation + Skills + AgentRegistry (3 defaults)
├── fixtures/            # JSON test data (3 core IPs + 201 Steam)
└── ui/
    ├── console.py       # Rich Console singleton (dynamic width 80-160, GEODE theme)
    ├── agentic_ui.py    # Claude Code-style renderer (▸/✓/✗/✢/● markers)
    ├── panels.py        # Rich Panel builders
    └── status.py        # TextSpinner + GeodeStatus (non-invasive, no raw mode)
```

## Development

```bash
# Test
uv run python -m pytest tests/ -q

# Lint
uv run ruff check core/ tests/

# Type check
uv run mypy core/
```

### Expected Test Results

2000+ tests pass. 3 IP fixtures produce tier spread:
- Berserk: **S** (81.3) — conversion_failure
- Cowboy Bebop: **A** (68.4) — undermarketed
- Ghost in the Shell: **B** (51.6) — discovery_failure

## Domain Plugin: Game IP — Scoring & Classification

### Scoring Formula (§13.8.1)

```
Final = (0.25×PSM + 0.20×Quality + 0.18×Recovery + 0.12×Growth + 0.20×Momentum + 0.05×Dev)
        × (0.7 + 0.3 × Confidence/100)

Tier: S≥80, A≥60, B≥40, C<40
```

### Cause Classification (§13.9.2)

Decision Tree on D-E-F axes:
- D≥3, E≥3 → conversion_failure
- D≥3, E<3 → undermarketed
- D≤2, E≥3 → monetization_misfit
- D≤2, E≤2, F≥3 → niche_gem
- D≤2, E≤2, F≤2 → discovery_failure

### Quality Evaluation (5-Layer)

1. **Guardrails** G1-G4: Schema, Range, Grounding, 2σ Consistency
2. **BiasBuster**: 6 bias types (CV < 0.05 → anchoring flag)
3. **Cross-LLM**: Agreement ≥ 0.67, Krippendorff's α
4. **Confidence Gate**: ≥ 0.7 → proceed, else loopback (max 5 iter)
5. **Rights Risk**: CLEAR/NEGOTIABLE/RESTRICTED/EXPIRED/UNKNOWN

## LLM Models (2026-03)

| Provider | Model | Input $/M | Output $/M | 용도 |
|----------|-------|-----------|------------|------|
| **Anthropic** | `claude-opus-4-6` | $5.00 | $25.00 | Primary (Pipeline + Agentic) |
| Anthropic | `claude-sonnet-4-5-20250929` | $3.00 | $15.00 | Fallback |
| Anthropic | `claude-haiku-4-5-20251001` | $1.00 | $5.00 | Lightweight |
| **OpenAI** | `gpt-5.4` | $2.50 | $15.00 | Cross-LLM Secondary (default) |
| OpenAI | `gpt-5.2` | $1.75 | $14.00 | Fallback 1 |
| OpenAI | `gpt-4.1` | $3.50 | $14.00 | Fallback 2 |
| OpenAI | `gpt-4.1-mini` | $0.70 | $2.80 | Budget |
| OpenAI | `o3` | $3.50 | $14.00 | Reasoning |
| OpenAI | `o4-mini` | $2.00 | $8.00 | Reasoning (budget) |

- **Fallback chain** (OpenAI): `gpt-5.4` → `gpt-5.2` → `gpt-4.1`
- **Pricing source**: [OpenAI API Pricing](https://developers.openai.com/api/docs/pricing/)
- **Cache pricing** (Anthropic): creation = input × 1.25, read = input × 0.1

## Tool Routing (AgenticLoop Direct)

모든 자유 텍스트 입력은 AgenticLoop로 직행한다. Claude가 46개 도구 정의를 직접 보고 tool_use로 자율 선택한다.

- `/command` -> commands.py 슬래시 커맨드 디스패치
- 자유 텍스트 -> AgenticLoop.run() (while tool_use 루프)

도구 정의는 `core/tools/definitions.json` (46개)에 통합 관리된다.

### Claude Code-style UI (agentic_ui.py)

```
▸ analyze_ip(ip_name="Berserk")        # tool call
✓ analyze_ip → S · 81.3               # tool result
✗ analyze_ip — Not found              # error
✢ claude-opus-4-6 · ↓1.2k ↑350 · 2.1s  # token usage
● Plan: Berserk                        # plan steps
  1. Signal collection
  2. Multi-analyst evaluation
```

## Conventions

- **Structured Output**: Anthropic `messages.parse()` with typed Pydantic models
- **Legacy JSON fallback**: `call_llm_json()` with robust JSON extraction
- **Fixture vs Real**: External data = fixture, LLM calls = real Claude
- **Verbose gating**: Debug prints only with `--verbose` flag
- **Node contract**: Each node returns `dict` with only its output keys
- **Reducer fields**: `analyses` and `errors` use `Annotated[list, operator.add]`
- **Port/Adapter**: All infra via Protocol ports + contextvars DI
- **Hook-driven**: 36 lifecycle events (incl. `SUBAGENT_*`, `TOOL_RECOVERY_*`, `CONTEXT_*`) for extensibility
- **Domain Plugin**: `DomainPort` Protocol — 도메인별 pipeline 교체 가능 (`set_domain()` / `get_domain()`)

## Implementation Workflow

기능 구현 시 아래 재귀개선 루프를 따른다. 각 단계에서 실패/품질 저하 발견 시 이전 단계로 돌아간다.

### 0. Worktree 작업 공간 분할

**병렬 작업이나 독립 기능 개발 시 git worktree로 격리된 작업 공간을 생성한다.** main 저장소를 오염시키지 않고 안전하게 실험/개발 가능.

```bash
# 생성: feature 브랜치 + 격리된 디렉토리
git worktree add .claude/worktrees/<작업명> -b feature/<브랜치명>

# 작업 디렉토리로 이동 (Claude Code는 자동 인식)
cd .claude/worktrees/<작업명>

# 작업 중 원본 저장소와 독립적으로 커밋/테스트 가능
uv run pytest tests/ -q
git add -A && git commit -m "feat: ..."
```

**작업 완료 후 정리:**

```bash
# 1. 변경사항을 원본 저장소 브랜치로 푸시
git push origin feature/<브랜치명>

# 2. 원본 저장소로 돌아가기
cd /Users/mango/workspace/nexon/ai-live/geode

# 3. worktree 제거 + 브랜치 삭제 (PR merge 후)
git worktree remove .claude/worktrees/<작업명>
git branch -d feature/<브랜치명>
```

**주의사항:**
- worktree 내에서 `git checkout`으로 브랜치 전환 금지 (같은 브랜치를 두 곳에서 체크아웃 불가)
- `.claude/worktrees/`는 `.gitignore`에 포함되어 원격에 푸시되지 않음
- worktree에서 작업 중이면 원본에서 해당 브랜치 체크아웃 불가

### 1. Research → Plan

**모든 기능 구현 전에 프론티어 하네스 리서치를 수행한다.** 주제와 관련된 패턴을 4개 참조 시스템에서 탐색하고, GAP 분석 후 계획을 수립한다.

```
1a. 기존 코드 탐색 (Explore agent, Grep, Read)
    - AS-IS 구조 파악, 관련 Port/Adapter/Hook/Tool 식별

1b. 프론티어 하네스 리서치 (frontier-harness-research 스킬 참조)
    - Claude Code: 권한 모델, Hook, Memory, Skill, Context 관리 패턴
    - Codex: Sandbox 실행, TDD 루프, PR 워크플로우, 코드 리뷰 패턴
    - OpenClaw: Gateway, Session Key, Binding, Lane Queue, Plugin, Failover 패턴
    - autoresearch: 제약 기반 설계, 래칫, Context Budget, program.md 패턴
    - 각 시스템에서 주제 관련 패턴 추출 → GEODE 적용 가능성 판단

1c. Gap 분석 (AS-IS → TO-BE 정리)
    - 프론티어 대비 빠진 패턴/기능 식별
    - P0/P1/P2 우선순위 분류
    - 구현 범위 결정 (전체 적용 vs 핵심만)

1d. ▸ 검증팀 (리서치) — Step 1b~1c와 병렬 실행
    - 프론티어 GAP 탐지 에이전트: 주제 관련 4종 시스템 대비 누락 패턴 감사
    - 결과를 1c Gap 분석에 병합
    - 구현 전 GAP 사전 방지 (사후 발견 → 사전 탐지 전환)

1e. docs/plans/에 계획 문서 작성
    - 리서치 결과 요약 + 검증팀 GAP 탐지 결과 + 설계 판단 근거 포함
```

**리서치 판정 기준:**

| 발견 | 조치 |
|------|------|
| 프론티어에 동일 패턴 존재 | → 패턴 채택, 구현 방식 참조 |
| 프론티어에 유사 패턴 존재 | → 핵심만 추출, GEODE 맥락에 맞게 변형 |
| 프론티어에 패턴 없음 | → 자체 설계, 근거 문서화 |
| 과잉 엔지니어링 위험 | → Karpathy P10 (Simplicity Selection) 적용 |
| 검증팀이 GAP 발견 | → 1c에 병합, 구현 범위 재조정 |

### 2. Implement → Unit Verify (반복)

```
1. 코드 변경 (최소 단위)
2. uv run ruff check core/ tests/     # lint
3. uv run mypy core/                   # type check
4. uv run pytest tests/ -q             # 전체 regression
5. 실패 시 → 수정 → 2번으로
```

### 3. E2E Verify + 검증팀 (병렬)

Mock E2E → CLI dry-run → Live E2E → LangSmith 검증 순서로 점검. **검증팀 에이전트를 E2E와 동시 병렬 실행**하여 시간 추가 없이 품질 확보. 각 단계에서 오류/품질 저하 발견 시 **2번으로 즉시 복귀**.

```
3a. Mock E2E: uv run pytest tests/test_agentic_loop.py tests/test_e2e.py tests/test_e2e_orchestration_live.py -v
3b. CLI dry-run: uv run geode analyze "Berserk" --dry-run  (실제 CLI 동작 확인)
3c. AgenticLoop 의도→행동 점검 (tool_use 직행):
    - "목록 보여줘" → list_ips 호출 확인
    - "Berserk 분석 계획 세워줘" → create_plan 호출 확인
    - "병렬로 처리해" → delegate_task 호출 확인
    - "Slack에 알림 보내줘" → send_notification 호출 확인
    - "내일 일정 뭐 있어?" → calendar_list_events 호출 확인
3d. Live E2E (API 키 필요): set -a && source .env && set +a && uv run pytest tests/test_e2e_live_llm.py -v -m live
3e. LangSmith 트레이스 확인: smith.langchain.com → geode 프로젝트
    - AgenticLoop 트레이스 존재
    - tool call 성공률 확인
    - 비용(cost_usd) 확인

3v. ▸ 검증팀 (구현) — 3a~3e와 병렬 실행 (Explore agent 다중 투입)
    - 코드 검증: Port/Adapter 패턴 일관성, contextvars DI 정합성, 에러 핸들링
    - 와이어링 검증: runtime.py 주입 경로, repl.py 초기화/종료 순서, dead code 탐지
    - 문서 검증: 수치 동기화 (Modules, Tests, Tools, MCP, HookEvents), ABOUT 4곳 일치
    - OpenClaw 대조: 해당 기능의 OpenClaw 패턴 준수 여부 (openclaw-patterns 스킬 참조)
    - 검증팀 발견 이슈 → 즉시 2번 복귀

3f. 품질 판정 (E2E + 검증팀 결과 종합):
    - tool 실행 결과에 error 없음
    - 올바른 모드(dry-run vs live) 확인
    - UI 출력 형식 (▸/✓/✗/✢) 정상
    - 검증팀 이슈 0건 확인
```

**재귀 판정 기준:**

| 발견 | 조치 |
|------|------|
| 테스트 실패 | → 2번(코드 수정) |
| CLI 오류/crash | → 2번(코드 수정) |
| 의도→tool 불일치 | → system prompt / tool definitions 수정 → 2번 |
| LangSmith 트레이스 누락 | → tracing 데코레이터 확인 → 2번 |
| 품질 저하 (score 이상) | → 해당 노드 로직 점검 → 2번 |
| 검증팀: 패턴 불일치 | → 해당 패턴 수정 → 2번 |
| 검증팀: 와이어링 누락 | → runtime/repl 주입 추가 → 2번 |
| 검증팀: 문서 불일치 | → 4번에서 동기화 (코드 수정 불필요 시) |
| 모두 통과 + 검증팀 0건 | → 4번 진행 |

### 4. Docs-Sync (PR 전 필수 게이트)

**코드 변경과 동일 커밋에 문서를 동기화한다.** PR 생성 전에 반드시 완료. 별도 후속 커밋으로 미루지 않는다.

#### 4a. CHANGELOG.md 동기화 (매 커밋)

**모든 코드 변경 커밋에 CHANGELOG 항목을 포함한다.** `[Unreleased]`에 누적 → main 머지 시 반드시 버전 부여.

```bash
# 변경 유형 판별 → 해당 카테고리에 1줄 추가
#   Added:    새 기능, 새 모듈, 새 도구
#   Changed:  기존 동작 변경, 성능 개선, 기본값 변경
#   Fixed:    버그 수정
#   Removed:  삭제된 기능
#   Infrastructure: CI, 의존성, 빌드
#   Architecture:   구조적 결정

# 예시 — 커밋 메시지가 "fix: MCP orphan 방지" 이면:
# CHANGELOG.md [Unreleased] → Fixed 에 추가:
# - MCP orphan 프로세스 방지 — REPL 종료 시 close_all() 호출
```

**문서/리팩터만 변경 시**: CHANGELOG 항목 불필요 (Scope Rules 참조).

**[Unreleased] 잔류 금지 규칙**: develop → main PR 머지 시 `[Unreleased]` 섹션에 항목이 남아 있으면 **반드시 동일 머지 커밋 또는 직후 릴리스 커밋에서 버전을 부여**한다. main 브랜치에 `[Unreleased]` 항목이 존재하는 상태는 허용하지 않는다.

#### 4b. ABOUT 동기화 (프로젝트 정체성)

프로젝트 정체성 관련 텍스트는 아래 3곳에서 일관성을 유지한다:

| 항목 | CLAUDE.md | README.md | pyproject.toml |
|------|-----------|-----------|----------------|
| 프로젝트 이름 | `# GEODE — 범용 자율 실행 에이전트` | `# GEODE vX.Y.Z — Autonomous Research Harness` | `description = "GEODE — ..."` |
| 한줄 설명 | Project Overview 첫 문장 | 타이틀 아래 첫 문장 | `description` 필드 |
| 버전 | `Version: X.Y.Z` | 타이틀 `vX.Y.Z` + 뱃지 | `version = "X.Y.Z"` |
| Highlights | Key Design Decisions | Highlights 리스트 | — |

변경 시 3곳 동시 갱신. 특히 **버전 번호는 CHANGELOG, CLAUDE.md, README.md 타이틀, pyproject.toml 4곳 모두** 일치해야 한다.

#### 4c. README.md + CLAUDE.md 수치·묘사·시각화 동기화 (매 커밋)

```bash
# 아래 수치가 변경되면 README.md + CLAUDE.md를 같이 갱신
TESTS=$(uv run pytest tests/ -q 2>&1 | grep -oP '\d+ passed' | grep -oP '\d+')
MODULES=$(find core/ -name "*.py" | wc -l | tr -d ' ')
TOOLS=$(python3 -c "import json; print(len(json.load(open('core/tools/definitions.json'))))")

echo "Tests: $TESTS  Modules: $MODULES  Tools: $TOOLS"
# → CLAUDE.md Tests/Modules, README.md 해당 수치와 대조
```

**수치 정합성:**

| 검증 항목 | CLAUDE.md 위치 | README.md 위치 |
|----------|---------------|---------------|
| 테스트 수 | `Tests: XXXX+` | Features 테이블 마지막 행 |
| 모듈 수 | `Modules: XXX` | Features 테이블 마지막 행 |
| Tool 수 | Tool Routing 섹션 + definitions.json | Features 테이블 + Tool 목록 |
| HookSystem 이벤트 수 | Orchestration 섹션 | Sub-Agent Orchestration 테이블 |
| MCP Adapter 수 | MCP 설정 | MCP & Tool Architecture 섹션 |
| 프로젝트 구조 | Project Structure 트리 | Project Structure 트리 |
| Tier/Score | Expected Test Results | Available IPs 테이블 |

**묘사·시각화 정합성** (코드 동작이 바뀌면 README Mermaid도 갱신):

| 검증 항목 | README.md 섹션 | 확인 방법 |
|----------|---------------|----------|
| Pipeline 노드 수/이름 | Pipeline Flow (mermaid) + 테이블 | `graph.py` 노드 등록과 대조 |
| Agentic Loop 파라미터 | Agentic Loop (mermaid) + 테이블 | `DEFAULT_MAX_ROUNDS`, `WRAP_UP_HEADROOM` 등 상수 대조 |
| CLI Input 처리 흐름 | CLI Input & Terminal (mermaid) | `_read_multiline_input()`, `_build_prompt_session()` 대조 |
| BiasBuster Fast Path 조건 | BiasBuster (mermaid) + 테이블 | `verification/biasbuster.py` 임계값 대조 |
| MCP Adapter 목록 | MCP & Tool Architecture (mermaid) + 테이블 | `.claude/mcp_servers.json` 대조 |
| Sub-Agent 구성요소 | Sub-Agent Orchestration (mermaid) | `sub_agent.py` 클래스 대조 |
| External IP Fallback 단계 | External IP Signal Fallback (mermaid) | `router.py`, `signals.py` 대조 |

#### 4d. 버전업 판단 및 릴리스

**main 머지 시 `[Unreleased]` 항목이 있으면 반드시 버전을 부여한다.** `[Unreleased]` 상태로 main에 잔류하는 것은 금지.

| 변경 규모 | 버전 | 판단 기준 | 예시 |
|----------|------|----------|------|
| 호환 깨짐 | MAJOR (x.0.0) | API/State 스키마 변경, CLI 인터페이스 변경, 기존 도구 삭제 | GeodeState 필드 삭제, 명령어 rename |
| 새 기능 추가 | MINOR (0.x.0) | 새 tool/노드/검증 레이어, 새 MCP 어댑터, 새 도메인 플러그인, 새 CLI 커맨드 | `delegate_task` 도구 추가, BiasBuster 신규 bias 유형 |
| 버그 수정/UI 개선 | PATCH (0.0.x) | 기존 동작 수정, pre-commit/CI 수정, 마커/스피너 변경, 타임아웃 조정 | weekday 변환 버그, 이모지 통일, cache false positive |
| 문서/리팩터만 | 버전업 안 함 | README 수정, 내부 리팩터, 블로그 추가 | — |

**MINOR vs PATCH 판단 원칙**: "사용자가 새로운 기능을 얻는가?" → MINOR. "기존 기능이 더 잘 동작하는가?" → PATCH.

```
릴리스 절차:
1. [Unreleased] → [x.y.z] — YYYY-MM-DD 로 변환
2. CLAUDE.md Version 필드 업데이트
3. README.md 타이틀 버전 업데이트
4. pyproject.toml version 필드 업데이트
5. Version History 테이블에 행 추가
6. 비교 링크 업데이트 ([Unreleased] compare URL)
7. 동일 커밋에 CHANGELOG.md + CLAUDE.md + README.md + pyproject.toml 포함
```

#### 4e. Skill / E2E 문서 (해당 시)

```
1. docs/e2e-orchestration-scenarios.md 갱신 (시나리오 추가/변경)
2. tests/test_e2e_live_llm.py 갱신 (라이브 테스트 추가)
3. .claude/skills/ 갱신 (시나리오 매핑 테이블)
```

### 5. PR & Merge

feature → develop → main 순서로 머지한다. **직접 로컬 머지 금지** — 반드시 PR 생성 → CI 통과 → merge 순서.

```
1. feature 브랜치에서 커밋 + 푸시
2. feature → develop PR 생성 (한글, assignee: mangowhoiscloud)
3. CI 통과 대기 → 실패 시 수정 루프 (아래 참조)
4. CI 통과 → gh pr merge
5. develop → main PR 생성 (동일 형식)
6. CI 통과 → gh pr merge
```

**CI 실패 시 수정 루프:**

```
PR 생성 → CI 실행 → 실패?
  ├─ Yes → 로그 확인 (gh pr checks / gh run view)
  │        → 원인 수정 (lint/type/test/coverage)
  │        → 커밋 + 푸시 → CI 재실행 → 실패? (반복)
  └─ No  → gh pr merge --merge
```

주의사항:
- `coverage fail_under=75` 미달 시: 커버리지 부족 모듈에 테스트 추가
- `ruff` 실패 시: `uv run ruff check --fix core/ tests/` 후 포맷 확인
- `mypy` 실패 시: 타입 에러 수정, `# type: ignore` 최소화
- pre-commit stash 충돌 시: `git stash` → 커밋 → `git stash pop`

**PR 작성 규칙:** `geode-gitflow` 스킬에 상세 템플릿과 지침 정의. 핵심만 아래 기술.

| 항목 | 규칙 |
|------|------|
| 언어 | **한글** (제목 + 본문 모두) |
| 제목 | `<type>: <한글 설명>` (70자 이내) |
| 본문 | `## 요약` → `## 변경 사항` (핵심/부수/문서 분리, 각 변경의 **왜?** 포함) → `## 영향 범위` → `## 설계 판단` (해당 시) → `## Pre-PR Quality Gate` (실제 실행 결과 체크리스트, `geode-gitflow` 스킬 템플릿 준수) |
| Assignee | `--assignee mangowhoiscloud` (항상) |
| Base | feature → `develop`, develop → `main` |

### E2E 업데이트 규칙 (필수)

**기능 변경 시 반드시 아래 파일을 함께 업데이트:**

| 변경 유형 | 갱신 대상 |
|----------|----------|
| 새 tool 추가 | `definitions.json` + `_build_tool_handlers()` + `test_e2e_live_llm.py` + E2E 시나리오 문서 |
| 파이프라인 노드 변경 | `graph.py` + `test_e2e_orchestration_live.py` + `test_e2e_live_llm.py` (§5) |
| LLM 어댑터 변경 | `client.py` + `test_e2e_live_llm.py` (§4 LangSmith) |
| Tool 라우팅 변경 | `definitions.json` tool descriptions + `router.md` system prompt |

### 품질 게이트

| 게이트 | 명령어 | 기준 |
|--------|--------|------|
| Lint | `uv run ruff check core/ tests/` | 0 errors |
| Type | `uv run mypy core/` | 0 errors |
| Mock | `uv run pytest tests/ -q` | 2000+ pass |
| Live | `uv run pytest tests/test_e2e_live_llm.py -v -m live` | All pass, tool results valid |

### 6. Progress Board 갱신 (세션 종료 시)

**`docs/progress.md`를 칸반 보드로 갱신한다.** 모든 에이전트/세션이 공유하는 SOT.

```
6a. 완료 작업: In Progress/In Review → Done (날짜별 그룹)
6b. 신규 작업: Backlog에 추가 (task_id, 우선순위, plan 연결)
6c. GAP Registry: 새로 발견된 GAP 추가, 해소된 GAP → Resolved
6d. Metrics: Version, Modules, Tests, Tools 등 수치 갱신
6e. Blocked: 차단 사유 기록 (blocked_by task_id)
```

**규칙:**
- 세션 시작 시 읽기 → 현재 보드 상태 파악 → 이미 할당된 작업 회피
- 세션 종료 시 쓰기 → 변경 사항 반영
- task_id는 케밥 케이스, 고유, 변경 불가
- 담당은 GitHub 계정 (`@username`)
- plan 연결: `docs/plans/{task_id}.md`

## Custom Skills

Project-specific skills in `.claude/skills/`:

| Skill | Triggers | Content |
|-------|----------|---------|
| `geode-pipeline` | pipeline, graph, topology, send api | StateGraph patterns, node contracts |
| `geode-scoring` | score, psm, tier, rubric, formula | Scoring formulas, 14-axis rubric |
| `geode-analysis` | analyst, evaluator, clean context | Analyst/Evaluator patterns, prompts |
| `geode-verification` | guardrail, bias, cause, decision tree | G1-G4, BiasBuster, Decision Tree |
| `geode-e2e` | e2e, live test, 검증, langsmith, tracing | Live E2E 패턴, LangSmith 검증, 품질 점검 |
| `geode-gitflow` | branch, git, pr, merge, 커밋 | Gitflow 전략, PR 템플릿, CI 수정 루프 |
| `geode-changelog` | changelog, release, version, 릴리스 | CHANGELOG 관리, SemVer 버전업 |
| `karpathy-patterns` | autoresearch, agenthub, ratchet, context budget | 자율 에이전트 10대 설계 원칙 (P1-P10) |
| `openclaw-patterns` | gateway, session, binding, lane, plugin | 에이전트 시스템 설계 패턴 (OpenClaw) |
| `architecture-patterns` | clean architecture, hexagonal, DDD | Backend 아키텍처 패턴 |
| `frontier-harness-research` | 리서치, research, gap, frontier, harness, 사례 조사 | 프론티어 하네스 4종 비교 리서치 프로세스 |
| `verification-team` | 검증, 검증팀, review, verify, 점검, 리뷰 | 4인 페르소나 검증 (Beck/Karpathy/Steinberger/Cherny) |
| `tech-blog-writer` | blog, 포스팅, 블로그, tech blog | 기술 블로그 작성 가이드 |

## Linked Skills (from parent project)

| Skill | Use |
|-------|-----|
| `langgraph-pipeline` | LangGraph general patterns |
| `clean-architecture` | Port/Adapter, dependency rules |
| `prompt-engineering` | Prompt design best practices |
| `ip-evaluation` | IP evaluation methodology |
| `mermaid-diagrams` | Architecture diagram styling |
