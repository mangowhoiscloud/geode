# P1: SubAgent Manager & Parallel Execution 보강 플랜

> **Status**: Implemented (Phase 1-4 + G7 complete), All GAPs Resolved
> **Priority**: P1 (핵심 기능 미동작 → 해결)
> **작성일**: 2026-03-12

---

## 1. 발견된 GAP 요약

SubAgent 시스템은 5개 파일(~1,500 LOC)에 구현되어 있었으나, **CLI 레이어에서 실제 연결(wiring)이 누락**되어 `delegate_task` 도구가 런타임에서 동작하지 않는 상태였음.

### GAP 목록

| GAP | 심각도 | 설명 | 해결 |
|-----|--------|------|------|
| **G1: CLI 미연결** | CRITICAL | `ToolExecutor` 생성 시 `sub_agent_manager` 미전달 | `_build_sub_agent_manager()` 팩토리 + wiring |
| **G2: task_handler 미구현** | CRITICAL | 실제 파이프라인 실행 핸들러 없음 | `make_pipeline_handler()` 구현 |
| **G3: AgentDefinition 분리** | HIGH | L6 에이전트 정의가 실행 레이어와 단절 | `_resolve_agent()` + AgentRegistry 주입 |
| **G4: 단일 태스크 스키마** | MEDIUM | delegate_task 도구가 1건만 수용 | `tasks` 배열 필드 + 배치 _execute_delegate |
| **G5: 진행 콜백 없음** | LOW | 병렬 실행 중 진행 표시 없음 | `on_progress` 콜백 파라미터 |
| **G6: 훅 시맨틱 오용** | LOW | NODE_ENTER/EXIT를 서브에이전트에 재사용 | SUBAGENT_* 전용 훅 이벤트 |

---

## 2. 구현 내역

### Phase 1: Critical Wiring (G1 + G2) — 완료

**`core/cli/sub_agent.py`**:
- `make_pipeline_handler()` 팩토리 함수 — analyze/search/compare 라우팅
- `_extract_analysis_summary()` 헬퍼
- handler signature에 `agent_context` kwarg + TypeError fallback

**`core/cli/__init__.py`**:
- `_build_sub_agent_manager()` 팩토리 함수
- 2곳에서 `ToolExecutor(sub_agent_manager=sub_mgr)` 연결

### Phase 2: Agent-Aware Execution (G3) — 완료

**`core/cli/sub_agent.py`**:
- `SubAgentManager.__init__`에 `agent_registry: AgentRegistry | None` 파라미터
- `_resolve_agent(task)` — task.agent > _TYPE_AGENT_MAP > None
- `SubTask` dataclass에 `agent: str | None` 필드

### Phase 3: Batch Schema & UX (G4 + G5) — 완료

**`core/tools/definitions.json`**:
- delegate_task에 `tasks` 배열 필드 추가, `bash` 제거, `required: []`

**`core/cli/tool_executor.py`**:
- `_execute_delegate()` 배치 지원: 단건 flat / 다건 `{results, total, succeeded}`

**`core/cli/sub_agent.py`**:
- `delegate()`에 `on_progress` 콜백

### Phase 4: Hook 시맨틱 정리 (G6) — 완료

**`core/orchestration/hooks.py`**:
- `SUBAGENT_STARTED`, `SUBAGENT_COMPLETED`, `SUBAGENT_FAILED` (26 events)

---

## 3. 테스트 결과

| 카테고리 | 수 | 결과 |
|---------|-----|------|
| Mock 테스트 | 2008 | All pass |
| Live E2E (§6) | 7 | 7/7 pass |

### Live E2E 시나리오

| # | 시나리오 | 결과 | 소요 |
|---|---------|------|------|
| E1 | delegate 단건 NL | PASS | 18.66s |
| E2 | delegate 배치 NL | PASS | 21.38s |
| E3 | SubAgent wiring | PASS | <1s |
| E4 | SUBAGENT_* 훅 | PASS | <1s |
| E5 | AgentRegistry | PASS | <1s |
| E6 | analyze_ip 비회귀 | PASS | 86.76s |
| E7 | _execute_delegate | PASS | 7.81s |

---

## 4. 변경 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `core/cli/sub_agent.py` | make_pipeline_handler, _resolve_agent, on_progress, agent field, SUBAGENT_* hooks |
| `core/cli/__init__.py` | _build_sub_agent_manager() + ToolExecutor wiring (2곳) |
| `core/cli/tool_executor.py` | _execute_delegate 배치 지원 |
| `core/tools/definitions.json` | delegate_task tasks 배열 스키마 |
| `core/orchestration/hooks.py` | SUBAGENT_STARTED/COMPLETED/FAILED 이벤트 |
| `tests/test_agentic_loop.py` | Hook 이벤트 갱신 + auto_approve |
| `tests/test_e2e_orchestration_live.py` | Hook 이벤트 갱신 |
| `tests/test_e2e_live_llm.py` | TestSubAgentLive 7개 시나리오 |
| `tests/test_bootstrap.py` | HookEvent 수 23 → 26 |
| `tests/test_hooks.py` | HookEvent 수 23 → 26 |
| `core/memory/session_key.py` | build_subagent_session_key, build_subagent_thread_config, parse 5-part |
| `core/runtime.py` | is_subagent 플래그 + MemorySaver 조건 분기 |

---

### Phase 5: OpenClaw 세션 키 격리 (G7) — 완료

**`core/memory/session_key.py`**:
- `build_subagent_session_key()` — `ip:X:Y:subagent:Z` 형식
- `build_subagent_thread_config()` — LangGraph config + LangSmith metadata
- `parse_session_key()` 5-part 서브에이전트 키 지원

**`core/cli/sub_agent.py`**:
- `_subagent_context` 스레드 로컬 + `get_subagent_context()`
- `SubagentRunRecord` 부모-자식 추적 dataclass
- `_execute_subtask()`에서 스레드 로컬 설정/정리

**`core/runtime.py`**:
- `is_subagent: bool` 플래그
- `compile_graph()` 내 MemorySaver 조건 분기

**`core/cli/__init__.py`**:
- `_run_analysis()`에서 `get_subagent_context()` → `runtime.is_subagent = True`

---

## 5. 추가 발견 GAP (전수 해결)

| GAP | 심각도 | 설명 | 상태 |
|-----|--------|------|------|
| G7 | MEDIUM | SQLite 체크포인터가 병렬 스레드에서 손상 | **해결** — OpenClaw 세션 키 격리 + MemorySaver |
| G8 | LOW | IsolatedRunner.PostToMain은 범용 PIPELINE_END 유지 | **해결** — 설계 결정 (SubAgent 훅은 Manager에서만 발행) |
