# GEODE — 범용 자율 실행 에이전트

## Project Overview

LangGraph 기반 범용 자율 실행 에이전트. 리서치, 분석, 자동화, 스케줄링을 자율적으로 수행합니다.

- **Version**: 0.30.0
- **Python**: >= 3.12
- **Package Manager**: uv
- **Entry Point**: `geode.cli:app` (Typer)
- **Modules**: 195
- **Tests**: 3249+
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

6-Layer Architecture.

```
L0: CLI & AGENT      — Typer CLI, AgenticLoop, SubAgentManager, Batch
L1: INFRASTRUCTURE   — Ports (Protocol), ClaudeAdapter, OpenAIAdapter, MCP Adapters
L2: MEMORY           — Organization > Project > Session + User Profile (4-Tier + Hybrid L1/L2)
L3: ORCHESTRATION    — HookSystem(36), TaskGraph DAG, PlanMode, CoalescingQueue, LaneQueue
L4: EXTENSIBILITY    — ToolRegistry(47), PolicyChain, Skills, MCP Catalog(44), Reports
L5: DOMAIN PLUGINS   — DomainPort Protocol, GameIPDomain, LangGraph StateGraph
```

### Sub-Agent System

서브에이전트는 부모의 tools/MCP/skills/memory를 상속받아 독립 컨텍스트에서 병렬 실행.
`SubAgentManager` → `CoalescingQueue`(250ms dedup) → `TaskGraph`(DAG) → `IsolatedRunner`(MAX_CONCURRENT=5).
제어: max_depth=2, max_total=15, timeout=120s, auto_approve=True(STANDARD만), max_rounds=10, max_tokens=8192.

**메모리 격리 규칙:**
- 서브에이전트는 부모 메모리 스냅샷을 읽기 전용으로 상속
- 서브에이전트 쓰기는 task_id 스코프 버퍼에 기록 (공유 메모리 직접 수정 금지)
- 부모는 태스크 완료 후 summary만 병합 — 두 에이전트가 동시에 공유 메모리에 쓰지 않음

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

## SOT (Source of Truth)

| Document | Path | Content |
|----------|------|---------|
| Layer Plan | `docs/architecture/layer-implementation-plan.md` | 6-layer roadmap |
| Orchestration | `docs/architecture/orchestration-tools-hooks-plans.md` | L3/L4 설계 |
| CLAUDE.md | `CLAUDE.md` | Architecture overview + conventions (이 파일) |

## Project Structure

코드는 `core/` 하위에 6-Layer로 구성. `find core/ -name "*.py" | wc -l`로 모듈 수 확인.
주요 진입점: `core/cli/agentic_loop.py`(AgenticLoop), `core/graph.py`(StateGraph), `core/runtime.py`(DI wiring).

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
- Berserk: **S** (81.2) — conversion_failure
- Cowboy Bebop: **A** (68.4) — undermarketed
- Ghost in the Shell: **B** (51.7) — discovery_failure

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

## LLM Models (verified 2026-03-24)

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

모든 자유 텍스트 입력은 AgenticLoop로 직행한다. Claude가 47개 도구 정의를 직접 보고 tool_use로 자율 선택한다.

- `/command` -> commands.py 슬래시 커맨드 디스패치
- 자유 텍스트 -> AgenticLoop.run() (while tool_use 루프)

도구 정의는 `core/tools/definitions.json` (47개)에 통합 관리된다.

**도구 권한 수준** (PolicyChain 6-layer 관통):
- **STANDARD**: 읽기·분석 도구 — Sub-Agent auto_approve 대상
- **WRITE**: 상태 변경 도구 (memory_save, profile_update, manage_rule) — 승인 필요
- **DANGEROUS**: 시스템 접근 도구 (run_bash, delegate_task) — 항상 HITL 승인 필수

### Claude Code-style UI (agentic_ui.py)

```
▸ analyze_ip(ip_name="Berserk")        # tool call
✓ analyze_ip → S · 81.2               # tool result
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

> **설계 원칙**: CANNOT(가드레일)이 CAN(자유도)보다 먼저 온다. 제약이 품질을 담보한다. (Karpathy P1, OpenClaw Policy Chain, Codex Sandbox)

### CANNOT — 절대 금지 규칙

어떤 단계에서든 위반할 수 없다. 위반 시 즉시 중단하고 수정한다.

| 영역 | 규칙 | 근거 |
|------|------|------|
| **Git** | worktree 없이 코드 작업 금지 | 격리 실행 (OpenClaw Session) |
| | main/develop 직접 push 금지 — PR → CI → merge | 래칫 (P4) |
| | 타 세션 worktree 삭제 금지 (`.owner` 불일치) | 소유권 보호 |
| | worktree 내 `git checkout` 전환 금지 | 격리 유지 |
| | `docs/progress.md` feature/develop에서 수정 금지 | main 단일 진실 |
| | 원격 미동기화 상태에서 브랜치 생성 금지 | 충돌 방지 |
| **계획** | 소크라틱 게이트 없이 구현 착수 금지 (버그·문서 제외) | 과잉 구현 방지 |
| **품질** | lint/type/test 실패 상태 커밋 금지 | 래칫 (P4) |
| | 수치에 자리표시자(XXXX) 금지 — 실측값만 | 진실 보장 |
| | `# type: ignore` 남발 금지 — 타입 에러는 수정 | 정확성 |
| | live 테스트(`-m live`) 무단 실행 금지 | 비용 제어 (P3) |
| **문서** | 코드 커밋에서 CHANGELOG 누락 금지 | 추적 가능성 |
| | main에 `[Unreleased]` 잔류 금지 | 릴리스 규율 |
| | 버전 4곳 불일치 금지 | 단일 진실 |
| **PR** | HEREDOC 없이 PR body 금지 | 형식 일관성 |
| | Why 근거 없이 PR 금지 | 의사결정 기록 |
| | CI 가드레일 미통과 PR 머지 금지 | 래칫 (P4) |

### CAN — 허용된 자유도

CANNOT에 없는 것은 자유롭게 할 수 있다. 특히:

| 자유도 | 설명 |
|--------|------|
| 단순 버그·문서 수정 | Plan 생략, worktree에서 바로 구현 |
| 플랜에 없는 개선 발견 시 | 현재 작업 완료 후 다음 이터레이션에서 처리 |
| 테스트 선별 실행 | 변경 범위에 해당하는 테스트만 먼저 실행, 최종은 전체 |
| 커밋 메시지 언어 | 한글/영어 자유 (일관성만 유지) |
| 도구 선택 | 동일 결과면 더 빠른 도구 자유 선택 |

### 장애 시나리오 (Failure Modes)

| 시나리오 | 감지 | 조치 |
|----------|------|------|
| 네트워크 다운 | `git fetch` 실패 | 작업 중단, 사용자에게 보고 |
| `.owner` 파일 부재 | worktree stat 실패 | 실행 거부 — 격리 위반 |
| CI 30분+ 타임아웃 | `gh pr checks` 미응답 | 잡 취소, 테스트 진단 후 에스컬레이션 |
| 메모리 파일 부패 | `tier=?`, `score=0.00` 등 파싱 에러 | 해당 레코드 삭제 후 재실행 |
| Confidence 미달 (5회 반복) | loopback max 5 도달, confidence < 0.7 | 사용자에게 에스컬레이션 — 자율 override 금지 |
| LLM 프로바이더 전체 장애 | 3사 fallback chain 소진 | Degraded Response(is_degraded=True + 기본값) — 파이프라인 중단 없음 |
| MCP 서버 스폰 실패 | subprocess 타임아웃 | 해당 MCP 없이 계속 (Graceful Degradation) |

### ContextVar 스레드 전파 (Gateway)

`geode serve`의 Gateway 폴러는 데몬 스레드에서 실행됨. 데몬 스레드는 부모의 contextvars를 상속하지 않음.
해결: `boot.propagate_to_thread()`를 각 Gateway 핸들러 진입 시 호출하여 domain/gateway/hooks를 재주입.
이 호출이 없으면 `get_domain()` → None → AgenticLoop 크래시.

### 워크플로우 단계

```
0. Board + Worktree → 1. GAP Audit → 2. Plan + Socratic Gate → 3. Implement+Test → 4. E2E Verify → 5. Docs-Sync → 6. PR → 7. Board
```

#### 0. Board + Worktree Alloc

```bash
# 1) Progress Board에 Backlog → In Progress 기록 (main에서)
# docs/progress.md에 작업 항목 추가/이동

# 2) Worktree 할당
git fetch origin
# main·develop 동기화 확인 (불일치 시 pull)
git worktree add .claude/worktrees/<작업명> -b feature/<브랜치명> develop
echo "session=$(date -Iseconds) task_id=<작업명>" > .claude/worktrees/<작업명>/.owner
```

Progress Board 기록 후 Worktree 할당. 완료 후: `git push` → `git worktree remove`

#### 1. GAP Audit (신규)

> 구현 전에 "정말 필요한가?"를 코드 실측으로 확인한다. 이미 구현된 것을 다시 만들지 않는다.

**프로세스**:
1. 플랜 문서(`docs/plans/`)의 TO-BE 항목을 나열
2. 각 항목에 대해 `grep`/`Explore`로 **코드에 이미 존재하는지** 실측
3. 3단 분류:

| 분류 | 판정 기준 | 액션 |
|------|----------|------|
| **구현 완료** | 코드에 존재 + 테스트 통과 | 플랜에서 제거, `_done/` 이동 |
| **부분 구현** | 코드 존재하나 통합/테스트 미완 | 남은 부분만 구현 |
| **미구현** | 코드에 없음 | 구현 대상 |

**산출물**: GAP 분류 테이블 (플랜 항목별 구현/부분/미구현)

#### 2. Plan + Socratic Gate

> 단순 버그·문서 수정은 생략 가능. 그 외 구현은 소크라틱 게이트 필수.

**소크라틱 5문 — 각 플랜 항목에 대해:**

| # | 질문 | 실패 시 |
|---|------|--------|
| Q1 | **코드에 이미 있는가?** (`grep`/`Explore` 실측) | → 제거 |
| Q2 | **이걸 안 하면 무엇이 깨지는가?** (실제 장애 시나리오) | 답 없으면 → 제거 |
| Q3 | **효과를 어떻게 측정하는가?** (테스트, 메트릭, dry-run) | 측정 불가 → 보류 |
| Q4 | **가장 단순한 구현은?** (P10 Simplicity Selection) | 최소 변경만 채택 |
| Q5 | **프론티어 3종 이상에서 동일 패턴인가?** (Claude Code, Codex CLI, OpenClaw, autoresearch) | 1종만 → 필요성 재검증 |

**프로세스**:
1. GAP Audit 결과에서 "미구현" 항목만 추출
2. 소크라틱 5문 적용 → 통과 항목만 구현 대상
3. 프론티어 리서치 (`frontier-harness-research` 스킬)
4. 플랜 문서 작성 (`docs/plans/`) → 사용자 승인
5. `TaskCreate`로 작업 등록

#### 3. Implement → Unit Verify (반복)

코드 변경 → 품질 게이트 3종 반복. 실패 시 수정.

```bash
uv run ruff check core/ tests/      # Lint: 0 errors
uv run mypy core/                    # Type: 0 errors
uv run pytest tests/ -m "not live"   # Test: 3219+ pass
```

#### 4. E2E Verify

`geode-e2e` 스킬 참조.

```bash
uv run geode analyze "Cowboy Bebop" --dry-run  # A (68.4) 변동 없음 확인
```

검증팀 4인 페르소나 리뷰: `verification-team` 스킬 참조 (대규모 변경 시).

#### 5. Docs-Sync

`geode-changelog` 스킬 참조.

**Pre-write**: CHANGELOG `[Unreleased]` + ABOUT 4곳 동기화 + 수치 실측 갱신.
**Post-verify**: 실측값 재대조, 불일치 시 fix.

| 동기화 대상 | 검증 |
|-----------|------|
| 버전 4곳 | CHANGELOG, CLAUDE.md, README.md, pyproject.toml |
| 수치 | Tests, Modules, Commands — 실측값 |

**버전업**: 새 기능 = MINOR, 버그 = PATCH, 문서만 = 안 함.

#### 6. PR & Merge

`geode-gitflow` 스킬 참조. feature → develop → main. HEREDOC PR. CI 5/5 필수.

| 변경 | 연쇄 갱신 |
|------|----------|
| 새 tool | `definitions.json` + handlers + E2E |
| 파이프라인 노드 | `graph.py` + E2E |
| LLM 어댑터 | `client.py` + E2E |

#### 7. Progress Board

main에서만 `docs/progress.md` 갱신. Backlog → In Progress → Done.

### 품질 게이트

| 게이트 | 명령어 | 기준 |
|--------|--------|------|
| Lint | `uv run ruff check core/ tests/` | 0 errors |
| Type | `uv run mypy core/` | 0 errors |
| Test | `uv run pytest tests/ -m "not live"` | 3219+ pass |
| E2E | `uv run geode analyze "Cowboy Bebop" --dry-run` | A (68.4) |

## Custom Skills (Scaffold)

Scaffold가 GEODE 개발 시 사용하는 skills (`.geode/skills/`). GEODE 런타임의 `core/skills/` SkillRegistry와는 별개.

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
| `explore-reason-act` | explore, 탐색, reason, root cause, read before write | 코드 수정 전 탐색-추론-실행 3단계 (REODE 역수입) |
| `anti-deception-checklist` | deception, 가짜, fake success, regression | 가짜 성공 방지 검증 체크리스트 (REODE 역수입) |
| `code-review-quality` | quality, 품질, SOLID, dead code, resource leak | Python 코드 품질 6-렌즈 리뷰 (REODE 역수입) |
| `dependency-review` | dependency, import, 의존성, 레이어, circular, lazy | 6-Layer 의존성 건전성 리뷰 (REODE 역수입) |
| `kent-beck-review` | kent beck, simple design, simplify, god object, SRP | Simple Design 4규칙 코드 리뷰 (REODE 역수입) |
| `codebase-audit` | audit, 감사, dead code, refactor, god object, 중복 | 코드 감사 + 리팩토링 워크플로우 (v0.24.0 실증) |
| `geode-serve` | serve, gateway, slack, 바인딩, binding, 폴러, config.toml | Slack Gateway 운영 + 디버깅 가이드 |

## Linked Skills (from parent project)

| Skill | Use |
|-------|-----|
| `langgraph-pipeline` | LangGraph general patterns |
| `clean-architecture` | Port/Adapter, dependency rules |
| `prompt-engineering` | Prompt design best practices |
| `ip-evaluation` | IP evaluation methodology |
| `mermaid-diagrams` | Architecture diagram styling |
