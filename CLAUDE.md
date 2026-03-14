# GEODE — 게임화 IP 도메인 자율 실행 하네스

## Project Overview

저평가 IP를 데이터 기반으로 발굴하는 LangGraph Agent CLI.

- **Version**: 0.10.1
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Point**: `geode.cli:app` (Typer)
- **Modules**: 131
- **Tests**: 2168+
- **CHANGELOG**: `CHANGELOG.md` (Keep a Changelog + SemVer)

## Quick Start

```bash
# Install
uv sync

# Dry-run (no LLM, fixture only)
uv run geode analyze "Cowboy Bebop" --dry-run

# Full run (requires API keys in .env)
uv run geode analyze "Cowboy Bebop"

# Verbose
uv run geode analyze "Cowboy Bebop" --verbose

# Interactive REPL
uv run geode
```

## Architecture

6-Layer Architecture based on `architecture-v6.md` SOT.

```
L6: EXTENSIBILITY   — Custom Agents, Plugins, Reports
L5: AUTOMATION       — Triggers, Dispatch, Snapshot, CUSUM Drift, Predefined(10)
L4: ORCHESTRATION    — Planner, Plan Mode, Task System, Hooks(19), Bootstrap
L3: AGENTIC CORE     — StateGraph, Analysts×4, Evaluators×3, Feedback Loop(5-Phase)
L2: MEMORY           — Organization > Project > Session (3-Tier + Hybrid L1/L2)
L1: FOUNDATION       — MonoLake, LLM Clients, APIs, Skills, DI (Port/Adapter)
```

### Pipeline (LangGraph StateGraph)

```
START → router → signals → analyst×4 (Send API)
     → evaluator×3 → scoring → verification
     → [confidence ≥ 0.7?] → synthesizer → END
                            → gather (loopback to signals, max 5 iter)
```

### Key Design Decisions

- **Send API Clean Context**: Analysts receive state WITHOUT `analyses` to prevent anchoring
- **Decision Tree**: Cause classification is code-based, NOT LLM
- **D-axis Exclusion**: D excluded from recovery_potential (PSM covers same dimension)
- **graph.stream()**: Step-by-step progress tracking (not invoke)
- **Typed Evaluator Output**: Per-evaluator Pydantic models enforce required axes in structured output
- **Confidence Multiplier**: `final = base × (0.7 + 0.3 × confidence/100)`
- **Port/Adapter DI**: All infra accessed via Protocol ports + contextvars injection

## SOT (Source of Truth)

| Document | Path | Content |
|----------|------|---------|
| Architecture v6 | `docs/architecture-v6.md` | Full spec (335KB) |
| LangGraph Flow | `docs/langgraph-flow.md` | StateGraph topology |
| Layer Plan | `docs/layer-implementation-plan.md` | 6-layer roadmap |

## Project Structure

```
core/
├── cli/                 # Typer CLI + NL router + search
├── config.py            # Pydantic Settings (.env)
├── state.py             # GeodeState TypedDict + Pydantic models
├── graph.py             # StateGraph build + compile
├── runtime.py           # GeodeRuntime — DI wiring + graph execution
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
│   └── commentary.py       # LLM commentary generation
├── memory/
│   ├── organization.py  # Org tier — fixture-based, read-only
│   ├── project.py       # Project tier — .claude/MEMORY.md, rules, insights
│   ├── session.py       # Session tier — in-memory with TTL
│   ├── hybrid_session.py # L1(Redis) → L2(PostgreSQL) hybrid store
│   ├── session_key.py   # Hierarchical key builder (ip:name:phase)
│   └── context.py       # 3-tier context assembler
├── orchestration/
│   ├── hooks.py         # HookSystem (23 events)
│   ├── bootstrap.py     # Node bootstrap (pre-execution context injection)
│   ├── planner.py       # Planner (multi-step plan generation)
│   ├── plan_mode.py     # Plan mode state machine
│   ├── task_system.py   # Task tracking + dependency management
│   ├── task_bridge.py   # Task ↔ pipeline bridge
│   ├── coalescing.py    # Duplicate request coalescing
│   ├── lane_queue.py    # Priority lane queue
│   ├── hook_discovery.py # Auto-discovery of hook handlers
│   ├── hot_reload.py    # Hot reload support
│   ├── isolated_execution.py # Sandboxed execution
│   ├── run_log.py       # Run audit log
│   └── stuck_detection.py # Stuck pipeline detection
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
│   └── rights_risk.py   # IP rights risk assessment
├── infrastructure/
│   ├── ports/           # Protocol interfaces (LLM, Memory, Auth, Hook, Tool, etc.)
│   └── adapters/llm/    # Claude + OpenAI adapters
├── tools/               # LLM-callable tools (memory, signal, analysis, output, data)
├── auth/                # API key rotation, cooldown, profiles
├── extensibility/       # Custom agents, plugins, report generators
├── fixtures/            # JSON test data (3 IPs) + data generator
└── ui/
    ├── console.py       # Rich Console singleton (width=120, GEODE theme)
    ├── agentic_ui.py    # Claude Code-style renderer (▸/✓/✗/✢/● markers)
    ├── panels.py        # Rich Panel builders
    ├── streaming.py     # Streaming output handler
    └── status.py        # Status bar + spinner
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

## Scoring Formula (§13.8.1)

```
Final = (0.25×PSM + 0.20×Quality + 0.18×Recovery + 0.12×Growth + 0.20×Momentum + 0.05×Dev)
        × (0.7 + 0.3 × Confidence/100)

Tier: S≥80, A≥60, B≥40, C<40
```

## Cause Classification (§13.9.2)

Decision Tree on D-E-F axes:
- D≥3, E≥3 → conversion_failure
- D≥3, E<3 → undermarketed
- D≤2, E≥3 → monetization_misfit
- D≤2, E≤2, F≥3 → niche_gem
- D≤2, E≤2, F≤2 → discovery_failure

## Quality Evaluation (5-Layer)

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

## NL Router (20 Tools)

NLRouter는 Claude Opus 4.6 Tool Use로 자연어 → 도구 호출을 매핑한다. 3단계 fallback: LLM → regex → help.

| Tool | Action | 설명 |
|------|--------|------|
| `list_ips` | list | IP 목록 조회 |
| `analyze_ip` | analyze | IP 분석 실행 |
| `search_ips` | search | IP 검색 |
| `compare_ips` | compare | IP 비교 |
| `show_help` | help | 도움말 |
| `generate_report` | report | 리포트 생성 |
| `batch_analyze` | batch | 배치 분석 |
| `check_status` | status | 시스템 상태 |
| `switch_model` | model | 모델 전환 |
| `memory_search` | memory | 메모리 검색 |
| `memory_save` | memory | 메모리 저장 |
| `manage_rule` | memory | 규칙 관리 |
| `set_api_key` | key | API 키 설정 |
| `manage_auth` | auth | 인증 관리 |
| `generate_data` | generate | 데이터 생성 |
| `schedule_job` | schedule | 작업 스케줄링 |
| `trigger_event` | trigger | 이벤트 트리거 |
| `create_plan` | plan | 분석 계획 생성 |
| `approve_plan` | plan | 계획 승인/실행 |
| `delegate_task` | delegate | 서브에이전트 병렬 위임 |

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
- **Hook-driven**: 19 lifecycle events for extensibility

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

```
1. 기존 코드 탐색 (Explore agent, Grep, Read)
2. 외부 사례 조사 (Eco², OpenClaw, Claude Code 패턴 참조)
3. Gap 분석 (AS-IS → TO-BE 정리)
4. docs/plans/에 계획 문서 작성
```

### 2. Implement → Unit Verify (반복)

```
1. 코드 변경 (최소 단위)
2. uv run ruff check core/ tests/     # lint
3. uv run mypy core/                   # type check
4. uv run pytest tests/ -q             # 전체 regression
5. 실패 시 → 수정 → 2번으로
```

### 3. E2E Verify (재귀 핵심)

Mock E2E → CLI dry-run → Live E2E → LangSmith 검증 순서로 점검. 각 단계에서 오류/품질 저하 발견 시 **2번으로 즉시 복귀**.

```
3a. Mock E2E: uv run pytest tests/test_agentic_loop.py tests/test_e2e.py tests/test_e2e_orchestration_live.py -v
3b. CLI dry-run: uv run geode analyze "Berserk" --dry-run  (실제 CLI 동작 확인)
3c. NL 의도→행동 점검:
    - "목록 보여줘" → list_ips 호출 확인
    - "Berserk 분석 계획 세워줘" → create_plan 호출 확인
    - "병렬로 처리해" → delegate_task 호출 확인
3d. Live E2E (API 키 필요): set -a && source .env && set +a && uv run pytest tests/test_e2e_live_llm.py -v -m live
3e. LangSmith 트레이스 확인: smith.langchain.com → geode 프로젝트
    - AgenticLoop 트레이스 존재
    - tool call 성공률 확인
    - 비용(cost_usd) 확인
3f. 품질 판정:
    - tool 실행 결과에 error 없음
    - 올바른 모드(dry-run vs live) 확인
    - UI 출력 형식 (▸/✓/✗/✢) 정상
```

**재귀 판정 기준:**

| 발견 | 조치 |
|------|------|
| 테스트 실패 | → 2번(코드 수정) |
| CLI 오류/crash | → 2번(코드 수정) |
| NL 의도 불일치 | → nl_router 패턴/매핑 수정 → 2번 |
| LangSmith 트레이스 누락 | → tracing 데코레이터 확인 → 2번 |
| 품질 저하 (score 이상) | → 해당 노드 로직 점검 → 2번 |
| 모두 통과 | → 4번 진행 |

### 4. Docs-Sync (PR 전 필수 게이트)

**코드 변경과 동일 커밋에 문서를 동기화한다.** PR 생성 전에 반드시 완료. 별도 후속 커밋으로 미루지 않는다.

#### 4a. CHANGELOG.md 동기화 (매 커밋)

**모든 코드 변경 커밋에 CHANGELOG 항목을 포함한다.** `[Unreleased]`에 누적 → 릴리스 시 버전 부여.

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

#### 4b. README.md + CLAUDE.md 수치·묘사·시각화 동기화 (매 커밋)

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
| Tool 수 | NL Router 테이블 | Features 테이블 + Tool 목록 38종 |
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
| CHANGELOG `[Unreleased]` | — | 머지된 PR body와 대조 (feature/fix PR만) |

#### 4c. 버전업 판단 (릴리스 시에만)

| 변경 규모 | 버전 | 예시 |
|----------|------|------|
| 호환 깨짐 (API/State 변경) | MAJOR (x.0.0) | GeodeState 필드 삭제, CLI 명령어 변경 |
| 새 기능 추가 | MINOR (0.x.0) | 새 tool, 새 노드, 새 검증 레이어 |
| 버그 수정/개선 | PATCH (0.0.x) | 직렬화 수정, 트레이싱 추가 |
| 문서/리팩터만 | 버전업 안 함 | README 수정, 내부 리팩터 |

```
릴리스 절차:
1. [Unreleased] → [x.y.z] — YYYY-MM-DD 로 변환
2. CLAUDE.md Version 필드 업데이트
3. pyproject.toml version 필드 업데이트
4. Version History 테이블에 행 추가
5. 비교 링크 업데이트 ([Unreleased] compare URL)
6. 동일 커밋에 CHANGELOG.md + CLAUDE.md + pyproject.toml 포함
```

#### 4d. Skill / E2E 문서 (해당 시)

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
| 본문 | `## 요약` → `## 변경 사항` (핵심/부수 분리, 각 변경의 **왜?** 포함) → `## 영향 범위` → `## 설계 판단` (해당 시) → `## 테스트` (실제 수치) → `## 검증 체크리스트` |
| Assignee | `--assignee mangowhoiscloud` (항상) |
| Base | feature → `develop`, develop → `main` |

### E2E 업데이트 규칙 (필수)

**기능 변경 시 반드시 아래 파일을 함께 업데이트:**

| 변경 유형 | 갱신 대상 |
|----------|----------|
| 새 tool 추가 | `definitions.json` + `_build_tool_handlers()` + `test_e2e_live_llm.py` + E2E 시나리오 문서 |
| 파이프라인 노드 변경 | `graph.py` + `test_e2e_orchestration_live.py` + `test_e2e_live_llm.py` (§5) |
| LLM 어댑터 변경 | `client.py` + `test_e2e_live_llm.py` (§4 LangSmith) |
| Offline 패턴 추가 | `nl_router.py` regex + `test_e2e_live_llm.py` (§C5) |

### 품질 게이트

| 게이트 | 명령어 | 기준 |
|--------|--------|------|
| Lint | `uv run ruff check core/ tests/` | 0 errors |
| Type | `uv run mypy core/` | 0 errors |
| Mock | `uv run pytest tests/ -q` | 2000+ pass |
| Live | `uv run pytest tests/test_e2e_live_llm.py -v -m live` | All pass, tool results valid |

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
| `tech-blog-writer` | blog, 포스팅, 블로그, tech blog | 기술 블로그 작성 가이드 |

## Linked Skills (from parent project)

| Skill | Use |
|-------|-----|
| `langgraph-pipeline` | LangGraph general patterns |
| `clean-architecture` | Port/Adapter, dependency rules |
| `prompt-engineering` | Prompt design best practices |
| `ip-evaluation` | IP evaluation methodology |
| `mermaid-diagrams` | Architecture diagram styling |
