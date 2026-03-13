# GEODE — 게임화 IP 도메인 자율 실행 하네스

## Project Overview

저평가 IP를 데이터 기반으로 발굴하는 LangGraph Agent CLI.

- **Version**: 0.10.1
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Point**: `geode.cli:app` (Typer)
- **Modules**: 124
- **Tests**: 2125+
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
| OpenAI | `gpt-4.1` | $2.00 | $8.00 | Fallback 2 |
| OpenAI | `gpt-4.1-mini` | $0.40 | $1.60 | Budget |
| OpenAI | `o3` | $2.00 | $8.00 | Reasoning |
| OpenAI | `o4-mini` | $1.10 | $4.40 | Reasoning (budget) |

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

### 4. Document → Skill Update

```
1. docs/e2e-orchestration-scenarios.md 갱신 (시나리오 추가/변경)
2. tests/test_e2e_live_llm.py 갱신 (라이브 테스트 추가)
3. .claude/skills/geode-e2e/SKILL.md 갱신 (시나리오 매핑 테이블)
4. CLAUDE.md 갱신 (기능/테스트 수/NL 도구 수)
5. README.md 정합성 검증 (아래 §4a 참조)
6. CHANGELOG.md 버전업 판단 (아래 §4b 참조)
```

#### 4a. README.md 정합성 검증 (PR 전 필수)

PR 생성 전 README.md가 코드와 일치하는지 검증한다.

| 검증 항목 | 확인 방법 |
|----------|----------|
| 테스트 수 | `uv run pytest tests/ -q` 결과와 README 기재 수 일치 |
| 모듈 수 | `find core/ -name "*.py" \| wc -l` 결과와 일치 |
| Tool 수 | `definitions.json` 항목 수 = README tool 테이블 행 수 |
| 프로젝트 구조 | 신규 파일/디렉토리가 README 트리에 반영됨 |
| 다이어그램 | 파이프라인 노드/엣지 변경 시 아키텍처 다이어그램 갱신 |
| Tier/Score | fixture 결과(Berserk S/81.3 등)가 변경 시 README 업데이트 |

불일치 발견 시 README를 수정하고 동일 커밋에 포함한다.

#### 4b. CHANGELOG.md 버전업 절차

변경 규모에 따라 버전업 여부를 판단하고, 필요 시 아래 절차를 수행한다.

**버전업 판단 기준 (SemVer):**

| 변경 규모 | 버전 | 예시 |
|----------|------|------|
| 호환 깨짐 (API/State 변경) | MAJOR (x.0.0) | GeodeState 필드 삭제, CLI 명령어 변경 |
| 새 기능 추가 | MINOR (0.x.0) | 새 tool, 새 노드, 새 검증 레이어 |
| 버그 수정/개선 | PATCH (0.0.x) | 직렬화 수정, 트레이싱 추가 |
| 문서/리팩터만 | 버전업 안 함 | README 수정, 내부 리팩터 |

**절차:**

```
1. CHANGELOG.md [Unreleased] 섹션에 변경 사항 기록
   - Added / Changed / Fixed / Removed / Infrastructure / Architecture 카테고리 사용
   - Feature-level 단위 (커밋 단위 X)
2. 버전업 필요 시:
   a. [Unreleased] → [x.y.z] — YYYY-MM-DD 로 변환
   b. CLAUDE.md Version 필드 업데이트
   c. pyproject.toml version 필드 업데이트 (있는 경우)
   d. 하단 Version History 테이블에 행 추가
   e. 비교 링크 업데이트 ([Unreleased] compare URL)
3. 동일 커밋에 CHANGELOG.md + CLAUDE.md + pyproject.toml 포함
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
