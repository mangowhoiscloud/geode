# GEODE 작업 리포트 — 2026-03-10

**브랜치**: `refactor/folder-restructuring`
**릴리스**: v0.6.1 (PATCH — 내부 리팩터링, 신규 사용자 기능 없음)
**테스트**: 1,879 passed (115 modules)

---

## 1. 커밋 요약

총 8개 커밋, 5개 카테고리.

| 커밋 | 메시지 | 유형 | 변경 파일 |
|------|--------|------|-----------|
| `cc23154` | feat(cli): agentic loop + HITL bash + sub-agent | Feature | 13 |
| `caff544` | refactor(prompts): extract prompt templates to .md | Refactor | 10 |
| `dd7213c` | refactor: centralize tool definitions, prompts, templates | Refactor | 17 |
| `877c948` | refactor: externalize domain data to YAML/JSON + constants | Refactor | 20 |
| `78b7f98` | refactor: remove legacy src/geode/ + fix test imports | Refactor | 411 |
| `c9f9114` | chore: add pre-commit hooks + fix fixture EOF | Chore | 204 |
| `a32354e` | chore: bump v0.7.0 (superseded) | Chore | 4 |
| `a0d652b` | chore: correct version to 0.6.1 | Chore | 4 |

---

## 2. 주요 작업 상세

### 2-1. Agentic Loop + HITL Bash + Sub-Agent (`cc23154`)

0.6.0의 single-shot NL Router를 `while(tool_use)` 루프로 전환.

| 모듈 | 파일 | 라인 | 설명 |
|------|------|------|------|
| AgenticLoop | `core/cli/agentic_loop.py` | 248 | multi-round 실행 (max 10 rounds), 토큰 추적 |
| ToolExecutor | `core/cli/tool_executor.py` | 135 | 17 handler, SAFE/STANDARD/DANGEROUS 분류, HITL gate |
| ConversationContext | `core/cli/conversation.py` | 91 | sliding-window 20 turns, API 호환 trim |
| BashTool | `core/cli/bash_tool.py` | 142 | 9 blocked patterns, 30s timeout, stdout 10K cap |
| SubAgentManager | `core/cli/sub_agent.py` | 181 | IsolatedRunner 기반, MAX_CONCURRENT=5 |

**CLI 통합** (`core/cli/__init__.py` 1501-1550):
```
사용자 입력
├─ `/` 슬래시 커맨드 → _handle_command() (기존 유지)
├─ 자유 텍스트 + API 키 → AgenticLoop.run() (신규)
└─ 자유 텍스트 + 오프라인 → _handle_natural_language() (fallback)
```

**Tool 안전 분류**:
- SAFE (7): `list_ips`, `search_ips`, `show_help`, `check_status`, `switch_model`, `memory_search`, `manage_rule`
- DANGEROUS (1): `run_bash` → `[Y/n]` 승인 프롬프트
- STANDARD: 나머지 (analyze, compare, report 등)

### 2-2. Prompt Template 외부화 (`caff544`, `dd7213c`)

Python 문자열 → `.md` 템플릿 파일 분리 (content/code separation).

| 템플릿 | 용도 |
|--------|------|
| `analyst.md` | 분석가 시스템 프롬프트 |
| `evaluator.md` | 평가기 프롬프트 |
| `synthesizer.md` | 합성기 프롬프트 |
| `biasbuster.md` | 편향 감지 프롬프트 |
| `commentary.md` | 해설 프롬프트 |
| `router.md` | NL 라우터 + agentic suffix |
| `cross_llm.md` | Cross-LLM 검증 프롬프트 |
| `tool_augmented.md` | 도구 증강 접미사 |

**로더**: `core/llm/prompts/__init__.py` — `load_prompt()` API, `=== SECTION ===` 구분자, backward-compatible re-export.

**도구 정의 중앙화**:
- `core/tools/definitions.json` — 19개 tool definition (name, description, input_schema)
- `core/tools/tool_schemas.json` — 10개 parameter schema
- `core/extensibility/templates/` — report HTML + 2 Markdown 템플릿

### 2-3. Domain Data YAML 분리 (`877c948`)

하드코딩된 도메인 데이터를 YAML/JSON으로 외부화.

| 파일 | 내용 |
|------|------|
| `core/config/evaluator_axes.yaml` | 20 axes + Korean rubric anchors, analyst_specific 4종 |
| `core/config/cause_actions.yaml` | 6 cause→action 매핑, 설명, IP narrative hooks |
| `core/tools/mcp_tools.json` | MCP 서버 tool 설명 6종 |

**상수 Settings 이관**:
- `router_model`, `default_secondary_model` → `pydantic-settings` (환경변수 오버라이드 가능)
- `agreement_threshold` (0.67), `primary_analysts`, `secondary_analysts`
- `VALID_AXES_MAP` — YAML에서 파생 (SSOT, state.py 25줄 중복 제거)
- `EVALUATOR_TYPES` — `EVALUATOR_AXES.keys()`에서 파생

### 2-4. 패키지 구조 변경 (`78b7f98`)

`src/geode/` → `core/` 마이그레이션 완료.

- 315개 레거시 파일 삭제 (`src/geode/` 전체)
- 85개 테스트 파일 import 경로 수정 (`geode.xxx` → `core.xxx`)
- Bandit `# nosec B404/B602` 적용 (`bash_tool.py` subprocess)
- CLI 진입점 불변: `geode = "core.cli:app"` (pyproject.toml)

### 2-5. Pre-commit Hooks (`c9f9114`)

`.pre-commit-config.yaml` 신규 생성 — CI 파이프라인을 로컬에서 재현.

| Hook | 소스 | 설명 |
|------|------|------|
| ruff lint | astral-sh/ruff-pre-commit v0.15.2 | `--fix --exit-non-zero-on-fix` |
| ruff format | 동일 | 포맷 검증 |
| mypy | local (`uv run`) | strict mode, project venv 활용 |
| bandit | local (`uv run`) | `-r core/ -c pyproject.toml` |
| trailing-whitespace | pre-commit-hooks v5.0.0 | markdown linebreak 허용 |
| end-of-file-fixer | 동일 | EOF 개행 보장 |
| check-yaml/json/toml | 동일 | 구문 검증 |
| check-added-large-files | 동일 | 500KB 제한 |
| check-merge-conflict | 동일 | conflict marker 감지 |
| debug-statements | 동일 | print/breakpoint 감지 |

### 2-6. 버전 판정 (`a32354e` → `a0d652b`)

SemVer 조사 후 0.7.0 → 0.6.1로 수정.

**판정 근거**: 0.6.0 이후 변경사항에 새로운 user-facing 기능 없음 (Agentic Loop 등은 0.6.0에 이미 포함). 전부 internal refactoring + infrastructure → PATCH.

`geode-changelog` skill에 SemVer Decision Tree 추가:
```
변경사항 발생
 ├─ 기존 public API 호환성 깨짐? → MAJOR
 ├─ 새로운 user-facing 기능? → MINOR
 └─ 그 외 (리팩터, CI, 버그 수정) → PATCH
```

---

## 3. PR 현황

| PR | 방향 | 제목 | 상태 |
|---|---|---|---|
| #6 | branch → develop | refactor: restructure project folders | Merged |
| #8 | branch → develop | fix imports + pre-commit hooks | Merged |
| #9 | develop → main | v0.6.1 릴리스 | Open |
| #10 | branch → develop | v0.6.1 content/code separation | Merged |

**머지 체인**: #6 → #8 → #10 (develop) → #9 (main, 대기 중)

---

## 4. 테스트 현황

| 카테고리 | 테스트 수 | 파일 |
|----------|-----------|------|
| ToolExecutor | 7 | test_agentic_loop.py |
| AgenticLoop | 6 | test_agentic_loop.py |
| SubAgentManager | 4 | test_agentic_loop.py |
| BashTool 검증 | 11 (parametrized) | test_bash_tool.py |
| BashTool 실행 | 10 | test_bash_tool.py |
| ConversationContext | 8 | test_conversation.py |
| Tool definitions | 3 | test_agentic_loop.py |
| **신규 합계** | **49** | |
| **전체** | **1,879** | 115 modules |

---

## 5. Plan 대비 구현 현황

### 구현 완료 (100%)

| Plan 항목 | 파일 | 상태 |
|-----------|------|------|
| AgenticLoop while(tool_use) | `agentic_loop.py` | Done |
| ToolExecutor + HITL gate | `tool_executor.py` | Done |
| ConversationContext | `conversation.py` | Done |
| BashTool + 9 patterns | `bash_tool.py` | Done |
| SubAgentManager | `sub_agent.py` | Done |
| CLI 통합 (3-path routing) | `__init__.py` | Done |
| Tool definitions JSON | `definitions.json` | Done |
| System prompt + AGENTIC_SUFFIX | `router.md` | Done |
| 테스트 (agentic, bash, conversation) | `tests/test_*.py` | Done |
| Backward compat (slash commands) | `_handle_command()` | Done |
| Offline fallback | `_handle_natural_language()` | Done |

### 미구현 / 미완성 (Plan 외 추가 작업 필요)

| 항목 | 설명 | 우선순위 |
|------|------|----------|
| **SubAgent 실전 테스트** | `delegate_task` tool이 REPL에서 LLM에 의해 실제 호출되는 E2E 시나리오 미검증. 단위 테스트만 존재. | Medium |
| **AgenticLoop E2E** | 실제 API 키로 multi-intent / multi-turn 동작 검증 필요 (현재 mock 기반 테스트만) | Medium |
| **TaskGraph 연동** | Plan에 "의존성 추적 (A 완료 후 B 실행)" 언급되었으나, SubAgentManager가 TaskGraph를 직접 사용하지 않음. 단순 병렬 실행만 구현. | Low |
| **HookSystem 이벤트 발행** | Plan에 "TASK_STARTED, TASK_COMPLETED 이벤트 발행" 언급되었으나, SubAgentManager에서 Hook 호출 미구현. | Low |
| **CoalescingQueue 연동** | Plan에 "중복 요청 병합" 언급되었으나, 미연결. | Low |

---

## 6. 파일 변경 통계

| 카테고리 | 생성 | 수정 | 삭제 |
|----------|------|------|------|
| core/cli/ (agentic) | 5 | 1 | 0 |
| core/llm/prompts/ | 9 | 1 | 0 |
| core/config/ | 2 | 1 | 0 |
| core/tools/ | 3 | 2 | 0 |
| core/extensibility/templates/ | 3 | 1 | 0 |
| src/geode/ (삭제) | 0 | 0 | 315 |
| tests/ | 3 | 85 | 0 |
| fixtures/ (EOF fix) | 0 | 201 | 0 |
| infra (.pre-commit, pyproject) | 1 | 2 | 0 |
| docs/skills | 0 | 1 | 0 |
| **합계** | **26** | **295** | **315** |

---

## 7. CI/CD 현황

| Job | 상태 |
|-----|------|
| Lint & Format (ruff) | Pass |
| Type Check (mypy strict) | Pass |
| Test (Python 3.12) | Pass |
| Test (Python 3.13) | Pass |
| Security Scan (bandit) | Pass |
| Gate (all checks) | Pass |

**CI 수정 이력**:
1. `--cov=geode` → `--cov=core` (coverage 타겟)
2. 85 test files import 경로 수정
3. `# nosec B404/B602` (bash_tool.py subprocess)
4. 201 fixture JSON EOF 개행
