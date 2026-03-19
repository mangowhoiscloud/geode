# P2: Sub-Agent Orchestration Hardening

**Status**: COMPLETE (P2-A/B/C done, P2-D RLM deferred)
**Created**: 2026-03-15
**Updated**: 2026-03-19 (G1-G8,G10 해소, G3 on_progress 완료, G9 보류)
**Priority**: P2
**Depends**: P1-subagent-parallel-execution (completed)

---

## 0. 핵심 방향: 서브에이전트 = 부모와 동일한 AgenticLoop

> 서브에이전트는 "축소된 미니 에이전트"가 아니라, 부모 AgenticLoop의 모든 요소(도구, 메모리, MCP, 스킬, HITL)를 **그대로 상속**받는 완전한 에이전트여야 한다.
> 재귀 서브에이전트 호출 시 각 레벨이 독립 context window를 가지므로, 유효 컨텍스트는 이론적으로 무한해진다 (MIT RLM, arXiv:2512.24601 실증).

### AS-IS vs TO-BE

```
AS-IS (현재):
  AgenticLoop (full) → delegate_task → task_handler(analyze/search/compare)
                                         ↑ 단순 함수 호출, 도구 없음, 재귀 불가

TO-BE (목표):
  AgenticLoop (depth=0) → delegate_task
    → AgenticLoop (depth=1, 부모 전체 상속)
        ├─ 동일 action_handlers (38+ tools)
        ├─ 동일 MCP manager (4 active servers)
        ├─ 동일 skill_registry
        ├─ 동일 Memory ContextVars
        ├─ 자체 ConversationContext (독립 context window)
        ├─ 자체 ToolExecutor (HITL 포함)
        ├─ depth < MAX_DEPTH → delegate_task 포함 (재귀 가능)
        └─ depth >= MAX_DEPTH → delegate_task 제외 (재귀 차단)
```

---

## 1. 현황 (AS-IS)

### 재귀 차단 5개 포인트

| 차단 포인트 | 위치 | 설명 |
|------------|------|------|
| **ToolExecutor 미주입** | `sub_agent.py:354` | `_execute_subtask()`는 `task_handler`만 호출 |
| **delegate_task 미노출** | `tool_executor.py:126` | 메인 AgenticLoop에서만 등록 |
| **AgenticLoop 미생성** | `sub_agent.py:438` | `make_pipeline_handler()`는 단순 라우터 |
| **ContextVar 미상속** | `sub_agent.py:365` | 자식 스레드에 Memory/Hook 미전파 |
| **MAX_DEPTH 미정의** | `config.py` | 재귀 깊이 설정 없음 |

### Gap 10건

| # | Gap | Phase | 심각도 |
|---|-----|-------|--------|
| G1 | max_tokens 8192 부족 | P2-A | HIGH |
| G2 | 결과 형태 불일치 (단건 vs 배치) | P2-A | MED |
| G3 | on_progress 미와이어링 | P2-C | MED |
| G4 | tool_result 무제한 (context 폭발) | P2-A | HIGH |
| G5 | 에러 분류 부재 | P2-A | MED |
| G6 | HookSystem 동기 호출 | 보류 | LOW |
| G7 | 결과 표준화 부재 | P2-A | HIGH |
| G8 | 재귀 depth 미지원 | P2-B | HIGH |
| G9 | 코드 매개 재귀(RLM) 미지원 | P2-D | HIGH |
| G10 | 컨텍스트 압축 없음 | P2-B | MED |

---

## 2. 설계 (4 Phase)

### Phase 1: 기반 구축 (P2-A) — SubAgentResult + Token Guard + Config

결과 표준화, 에러 분류, 토큰 가드, 설정 추가. Phase 2의 선제 조건.

#### 2.1 SubAgentResult

```python
@dataclass
class SubAgentResult:
    task_id: str
    task_type: str
    status: Literal["ok", "error", "timeout", "partial"]
    depth: int = 0
    summary: str = ""          # 항상 존재 (LLM 결과 요약)
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    token_usage: dict[str, int] | None = None
    children_count: int = 0
    error_category: str | None = None
    error_message: str | None = None
    retryable: bool = False
```

#### 2.2 ErrorCategory

```python
class ErrorCategory(str, Enum):
    TIMEOUT = "timeout"
    API_ERROR = "api_error"
    VALIDATION = "validation"
    RESOURCE = "resource"
    DEPTH_EXCEEDED = "depth_exceeded"
    UNKNOWN = "unknown"
```

#### 2.3 Tool Result Token Guard

```python
# agentic_loop.py — _process_tool_calls()에 삽입
MAX_TOOL_RESULT_TOKENS = 4096

def _guard_tool_result(result: dict) -> dict:
    serialized = json.dumps(result, ensure_ascii=False, default=str)
    if len(serialized) // 4 <= MAX_TOOL_RESULT_TOKENS:
        return result
    if "summary" in result:
        return {"summary": result["summary"], "_truncated": True}
    return {"_truncated": True, "preview": serialized[:16000]}
```

#### 2.4 Config 추가

```python
# core/config.py
max_subagent_depth: int = 2
max_total_subagents: int = 15
subagent_max_rounds: int = 10
subagent_max_tokens: int = 8192
default_max_tokens: int = 16384  # 메인 루프 확장
```

#### 2.5 응답 통일

```python
# tool_executor.py — _execute_delegate() 반환 형태 통일
# 단건이든 배치든 동일 구조:
{
    "tasks": [sub_result.to_dict() for sub_result in results],
    "total": len(results),
    "succeeded": sum(1 for r in results if r.status == "ok"),
    "summary": "3/5 tasks completed successfully."
}
```

**변경 파일**: `sub_agent.py`, `agentic_loop.py`, `tool_executor.py`, `config.py`

---

### Phase 2: Full AgenticLoop 상속 (P2-B) — 핵심 변경

서브에이전트가 부모와 동일한 AgenticLoop을 받도록 전환.

#### 2.6 SubAgentManager 확장

```python
class SubAgentManager:
    def __init__(
        self,
        runner: IsolatedRunner,
        task_handler: Any | None = None,        # 기존 호환 유지
        *,
        # 신규: Full AgenticLoop 상속용
        action_handlers: dict[str, Callable] | None = None,
        tool_definitions: list[dict] | None = None,
        mcp_manager: Any | None = None,
        skill_registry: Any | None = None,
        depth: int = 0,
        max_depth: int = 2,
        # 기존
        timeout_s: float = 120.0,
        hooks: HookSystem | None = None,
        ...
    ):
```

#### 2.7 _execute_subtask() — AgenticLoop 생성

```python
def _execute_subtask(self, task: SubTask) -> str:
    # 1. ContextVar 상속 (명시적)
    _propagate_context_vars()

    # 2. 독립 ConversationContext
    conversation = ConversationContext(max_turns=10)

    # 3. 자식 SubAgentManager (depth+1, depth < max_depth일 때만)
    child_sam = None
    if self._depth < self._max_depth:
        child_sam = SubAgentManager(
            runner=IsolatedRunner(max_concurrent=3),
            action_handlers=self._action_handlers,
            depth=self._depth + 1,
            max_depth=self._max_depth,
            ...
        )

    # 4. ToolExecutor (부모 handlers 상속)
    executor = ToolExecutor(
        action_handlers=self._action_handlers,
        sub_agent_manager=child_sam,
        mcp_manager=self._mcp_manager,
        auto_approve=True,  # 서브에이전트는 HITL 스킵
    )

    # 5. AgenticLoop (부모와 동일 구성)
    loop = AgenticLoop(
        conversation,
        executor,
        max_rounds=settings.subagent_max_rounds,  # 10
        max_tokens=settings.subagent_max_tokens,   # 8192
        mcp_manager=self._mcp_manager,
        skill_registry=self._skill_registry,
    )

    # 6. 실행: task description을 user input으로 전달
    result = loop.run(task.description)

    # 7. SubAgentResult로 표준화
    return SubAgentResult(
        task_id=task.task_id,
        summary=result.text[:500] if result else "",
        data={"full_response": result.text} if result else {},
        ...
    ).to_json()
```

#### 2.8 _build_sub_agent_manager() 변경 (cli/__init__.py)

```python
def _build_sub_agent_manager(...) -> SubAgentManager:
    handlers = _build_tool_handlers(...)  # 기존 handlers dict 그대로 전달

    return SubAgentManager(
        runner=IsolatedRunner(),
        action_handlers=handlers,           # 전체 도구 상속
        mcp_manager=mcp_mgr,               # MCP 상속
        skill_registry=skill_registry,      # 스킬 상속
        depth=0,
        max_depth=settings.max_subagent_depth,
        timeout_s=300.0,
        agent_registry=registry,
    )
```

#### 2.9 ContextVar 전파

```python
def _propagate_context_vars():
    """Propagate parent ContextVars to child thread."""
    from core.tools.memory_tools import set_project_memory, set_org_memory
    from core.memory.project import ProjectMemory
    from core.memory.organization import MonoLakeOrganizationMemory

    try:
        set_project_memory(ProjectMemory())
        set_org_memory(MonoLakeOrganizationMemory())
    except Exception:
        pass  # Graceful degradation
```

**변경 파일**: `sub_agent.py`, `cli/__init__.py`

---

### Phase 3: 진행 보고 + 튜닝 (P2-C)

#### 2.10 on_progress → GeodeStatus

```python
# tool_executor.py
def _execute_delegate(self, tool_input):
    ...
    def _on_progress(result):
        # GeodeStatus 스피너 업데이트
        ...
    results = self._sub_agent_manager.delegate(tasks, on_progress=_on_progress)
```

#### 2.11 max_tokens 메인루프 확장

`DEFAULT_MAX_TOKENS = 16384` (기존 8192). 서브에이전트는 8192 유지.

**변경 파일**: `tool_executor.py`, `agentic_loop.py`

---

### Phase 4: RLM 코드 매개 재귀 (P2-D) — 향후

Phase 1-3 완비 후 코드 기반 재귀 패턴 도입. `run_bash` + `delegate_task` 조합으로 10M+ 토큰 처리.

---

## 3. 구현 순서

| Phase | 작업 | 파일 | Gap |
|-------|------|------|-----|
| **P2-A** | SubAgentResult + ErrorCategory | `sub_agent.py` | G7, G5 |
| | tool_result token guard | `agentic_loop.py` | G4 |
| | 응답 통일 (단건/배치) | `tool_executor.py` | G2 |
| | Config (depth, max_tokens) | `config.py` | G1, G8 |
| **P2-B** | SubAgentManager → Full AgenticLoop 상속 | `sub_agent.py` | G8, G10 |
| | _build_sub_agent_manager() 재설계 | `cli/__init__.py` | G8 |
| | ContextVar 명시 전파 | `sub_agent.py` | G8 |
| | make_pipeline_handler() → 기존 호환 유지 (fallback) | `sub_agent.py` | — |
| **P2-C** | on_progress → GeodeStatus | `tool_executor.py` | G3 |
| | DEFAULT_MAX_TOKENS 16384 | `agentic_loop.py` | G1 |
| **P2-D** | RLM 패턴 가이드 | docs/skill | G9 |

---

## 4. 참조

### 프론티어 벤치마크 (2026-03-15)

| 시스템 | depth | 격리 | 결과 포맷 | 비용 |
|--------|-------|------|----------|------|
| OpenClaw | 1 (flat) | Session | Text announce | 7x/agent |
| Claude Code | 1 (flat) | Git worktree | Final msg verbatim | 7x/agent |
| Codex | 1 (실험적) | OS sandbox | LLM-consolidated | 미공개 |
| RLM (MIT) | 2-3 | REPL | 코드 구조화 | 0.03% |
| **GEODE (목표)** | **2 (설정 가능)** | **Thread + ContextVar** | **SubAgentResult** | **상속 기반** |

### 학술 논문

- RLM (arXiv:2512.24601) — 10M+ 토큰, BrowseComp 91.33%
- MAS Failure (arXiv:2503.13657) — 41-86.7% 실패율, 14 failure modes
- ACON (arXiv:2510.00615) — 에이전트 컨텍스트 압축 26-54%
- Complexity Trap (arXiv:2508.21433) — 단순 마스킹 ≈ LLM 요약
