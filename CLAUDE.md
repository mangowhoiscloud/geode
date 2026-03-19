# GEODE — 범용 자율 실행 에이전트

## Project Overview

LangGraph 기반 범용 자율 실행 에이전트. 리서치, 분석, 자동화, 스케줄링을 자율적으로 수행합니다.

- **Version**: 0.21.0
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Point**: `geode.cli:app` (Typer)
- **Modules**: 178
- **Tests**: 2930+
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

### Recent Features (v0.15.0 -- v0.21.0)

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
| v0.21.0 | Model Policy | `.geode/model-policy.toml` — allowlist/denylist 기반 모델 거버넌스 |
| v0.21.0 | Routing Config | `.geode/routing.toml` — 노드별 LLM 모델 라우팅 (비용 최적화) |
| v0.21.0 | SessionManager + SQLite | 세션 메타 인덱스 (WAL), `/resume` 커맨드 + REPL 시작 탐지 |
| v0.21.0 | AgentMemoryStore | 서브에이전트별 task_id 격리 메모리 (파일 스코프 + 24h TTL) |
| v0.21.0 | Context Compaction | WARNING(80%) Haiku 요약 압축, CRITICAL(95%) prune fallback |

## SOT (Source of Truth)

| Document | Path | Content |
|----------|------|---------|
| Architecture v6 | `docs/architecture-v6.md` | Full spec (335KB) |
| LangGraph Flow | `docs/langgraph-flow.md` | StateGraph topology |
| Layer Plan | `docs/architecture/layer-implementation-plan.md` | 6-layer roadmap |

## Project Structure

```
core/
├── cli/                 # CLI + Agentic Loop + Sub-Agent
│   ├── agentic_loop.py  # while(tool_use) multi-round + Token Guard + multi-provider
│   ├── agentic_response.py # AgenticResponse — provider-agnostic response normalization
│   ├── sub_agent.py     # SubAgentManager + SubAgentResult + ErrorCategory
│   ├── tool_executor.py # Tool dispatch + HITL + delegate_task + write fallback
│   ├── session_checkpoint.py # C3 Session checkpoint — save/restore/resume
│   ├── system_prompt.py # System prompt builder for AgenticLoop
│   ├── ip_names.py      # IP name registry (canonical names from fixtures)
│   ├── conversation.py  # Multi-turn sliding-window (max 200 turns, server-side clear_tool_uses)
│   ├── batch.py         # Batch analysis (ThreadPoolExecutor)
│   ├── commands.py      # Slash command dispatch (20 commands)
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
│   ├── project_journal.py # C2 Journal — .geode/journal/ append-only execution record
│   ├── journal_hooks.py # Hook handlers for auto-recording to Journal
│   ├── session.py       # Session tier — in-memory with TTL
│   ├── hybrid_session.py # L1(Redis) → L2(PostgreSQL) hybrid store
│   ├── session_key.py   # Hierarchical key builder (ip:name:phase)
│   ├── session_manager.py # SessionManager — SQLite session index (WAL)
│   ├── agent_memory.py  # AgentMemoryStore — sub-agent isolated memory (TTL)
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
│   ├── context_compactor.py # Context Compaction — LLM summary (Haiku, WARNING 80%)
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

## LLM Models (verified 2026-03-19)

| Provider | Model | Input $/M | Output $/M | Context | 용도 |
|----------|-------|-----------|------------|---------|------|
| **Anthropic** | `claude-opus-4-6` | $5.00 | $25.00 | 1M | Primary (Pipeline + Agentic) |
| Anthropic | `claude-sonnet-4-6` | $3.00 | $15.00 | 1M | Fallback |
| Anthropic | `claude-haiku-4-5-20251001` | $1.00 | $5.00 | 200K | Budget |
| **OpenAI** | `gpt-5.4` | $2.50 | $15.00 | 1M | Cross-LLM Secondary (default) |
| OpenAI | `gpt-5.2` | $1.75 | $14.00 | 128K | Fallback 1 |
| OpenAI | `gpt-4.1` | $2.00 | $8.00 | 1M | Fallback 2 |
| OpenAI | `gpt-4.1-mini` | $0.40 | $1.60 | 1M | Budget |
| **ZhipuAI** | `glm-5` | $0.72 | $2.30 | 80K | GLM Primary |
| ZhipuAI | `glm-5-turbo` | $0.96 | $3.20 | 200K | GLM Agent |
| ZhipuAI | `glm-4.7-flash` | Free | Free | 200K | GLM Budget |

- **Fallback chain** (Anthropic): `claude-opus-4-6` → `claude-sonnet-4-6`
- **Fallback chain** (OpenAI): `gpt-5.4` → `gpt-5.2` → `gpt-4.1`
- **Fallback chain** (GLM): `glm-5` → `glm-5-turbo` → `glm-4.7-flash`
- **Cache pricing** (Anthropic): creation = input × 1.25, read = input × 0.1
- **Deprecated** (removed): gpt-4o, gpt-4o-mini, o3-mini, claude-haiku-3-5

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

> **설계 원칙** (Karpathy P1): "무엇을 할 수 없는가"를 먼저 정의한다. 행동 목록이 아닌 가드레일이 품질을 담보한다.

### CANNOT — 절대 금지 규칙

이 규칙은 어떤 단계에서든 위반할 수 없다. 위반 시 즉시 중단하고 수정한다.

**Git/Branch:**
- worktree 없이 코드 작업 시작 금지 — 모든 작업은 `git worktree add` 로 시작
- main/develop에 직접 push 금지 — 반드시 PR → CI → merge
- 타 세션의 worktree 삭제 금지 — `.owner` task_id 불일치 시 절대 제거하지 않음
- worktree 내 `git checkout` 브랜치 전환 금지
- `docs/progress.md`를 feature/develop 브랜치에서 수정 금지 — main에서만
- 원격/로컬 브랜치 동기화 미확인 상태에서 feature 브랜치 생성 금지 — `git fetch origin` 후 main·develop 양쪽 HEAD 일치 확인 필수

**워크플로우:**
- Plan 없이 구현 착수 금지 — 반드시 EnterPlanMode 진입 → 계획 승인 → ExitPlanMode 경유 (단순 버그 수정·문서 수정 제외)
- 칸반(progress.md) 필수 컬럼 빈칸 기재 금지 — 모든 필수 컬럼에 값 기입, "—" 허용하되 빈칸 금지

**코드 품질:**
- lint/type/test 실패 상태에서 커밋 금지
- 테스트 수치에 자리표시자(XXXX) 사용 금지 — 반드시 실제 실행 결과
- `# type: ignore` 남발 금지 — 타입 에러는 수정이 원칙
- live 테스트(`-m live`) 무단 실행 금지 — 비용 발생 (메모리 `feedback_test_cost` 참조)

**문서:**
- 코드 변경 커밋에서 CHANGELOG 누락 금지
- main에 `[Unreleased]` 항목 잔류 금지 — 머지 시 반드시 버전 부여
- 버전 번호 4곳(CHANGELOG, CLAUDE.md, README.md, pyproject.toml) 불일치 금지

**PR:**
- PR body에 인라인 `--body "..."` 사용 금지 — HEREDOC 필수
- PR body에서 변경 파일의 Why 근거 누락 금지

### 워크플로우 단계

각 단계에서 실패 시 이전 단계로 돌아간다.

```
0. Worktree Alloc → 1. Research → 2. Implement+Test → 3. Verify → 4. Docs-Sync → 5. PR → 6. Board
```

#### 0. Worktree

```bash
# 0-a. 원격 fetch
git fetch origin

# 0-b. main 동기화 확인
LOCAL_MAIN=$(git rev-parse main)
REMOTE_MAIN=$(git rev-parse origin/main)
[ "$LOCAL_MAIN" != "$REMOTE_MAIN" ] && echo "STOP: local main ≠ origin/main" && git checkout main && git pull origin main

# 0-c. develop 동기화 확인
LOCAL_DEV=$(git rev-parse develop)
REMOTE_DEV=$(git rev-parse origin/develop)
[ "$LOCAL_DEV" != "$REMOTE_DEV" ] && echo "STOP: local develop ≠ origin/develop" && git checkout develop && git pull origin develop

# 0-d. worktree 생성 (develop 기반)
git worktree add .claude/worktrees/<작업명> -b feature/<브랜치명> develop
echo "session=$(date -Iseconds) task_id=<작업명>" > .claude/worktrees/<작업명>/.owner
```

완료 후: `git push origin feature/<브랜치명>` → 소유권 검증 → `git worktree remove`

#### 1. Plan (필수)

> 단순 버그 수정·문서만 수정은 Plan 생략 가능. 그 외 모든 구현 작업은 Plan 필수.

1. `EnterPlanMode` 진입
2. Explore Agent로 AS-IS 탐색 + 프론티어 리서치 (해당 시, `frontier-harness-research` 스킬 참조)
3. Plan Agent로 설계 → 플랜 파일 작성 (`docs/plans/`)
4. `ExitPlanMode`로 사용자 승인 요청
5. 승인 후 `TaskCreate`로 작업 항목 등록 — 칸반 In Progress와 1:1 매핑
6. 구현 착수 (Step 2)

#### 2. Implement → Unit Verify (반복)

코드 변경 → `uv run ruff check` → `uv run mypy core/` → `uv run pytest tests/ -q` → 실패 시 수정 반복.

#### 3. E2E Verify + 검증팀 (병렬)

`geode-e2e` 스킬 참조. Mock E2E → CLI dry-run → Live E2E(선택) → 검증팀 4인 페르소나 리뷰 병렬 실행. `verification-team` 스킬 참조.

#### 4. Docs-Sync

`geode-changelog` 스킬 참조.

**Pre-write** (PR 전): CHANGELOG `[Unreleased]` 항목 추가 + ABOUT 4곳 동기화 + 수치 갱신.
**Post-verify** (머지 후): 실측값 재대조, 불일치 시 fix 커밋.

| 검증 포인트 | 동기화 대상 |
|------------|-----------|
| 버전 | CHANGELOG, CLAUDE.md, README.md, pyproject.toml |
| 수치 | Tests, Modules, Tools, HookEvents, MCP — CLAUDE.md + README.md |
| 시각화 | README.md Mermaid → 코드 상수와 대조 |

**버전업 판단**: 새 기능 = MINOR, 버그 수정 = PATCH, 문서만 = 버전업 안 함.

#### 5. PR & Merge

`geode-gitflow` 스킬 참조. feature → develop → main. 한글 HEREDOC PR. CI 실패 시 수정 루프.

**변경 연쇄 규칙:**

| 변경 | 함께 갱신 |
|------|----------|
| 새 tool | `definitions.json` + `_build_tool_handlers()` + E2E 테스트 |
| 파이프라인 노드 | `graph.py` + E2E 테스트 |
| LLM 어댑터 | `client.py` + E2E 테스트 |

#### 6. Progress Board

main에서만 `docs/progress.md` 갱신. 3-Checkpoint: Alloc(Step 0) → Free(머지 후) → Session-start(교차 검증). Backlog → In Progress → Done 순서 준수.

### 품질 게이트

| 게이트 | 명령어 | 기준 |
|--------|--------|------|
| Lint | `uv run ruff check core/ tests/` | 0 errors |
| Type | `uv run mypy core/` | 0 errors |
| Test | `uv run pytest tests/ -q` | 2000+ pass |

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
