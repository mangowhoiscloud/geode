# SubAgent 병렬 실행 — GAP 분석에서 Live E2E 검증까지

> Date: 2026-03-12 | Author: geode-team | Tags: sub-agent, parallel-execution, e2e, gap-analysis, hooks

## 목차

1. 도입: 왜 서브에이전트가 동작하지 않았는가
2. GAP 분석: 6개의 단절 지점
3. Phase 1-4 구현: 연결, 라우팅, 배치, 훅
4. Live E2E 검증: 7개 시나리오 실행 기록
5. G7 해결: OpenClaw 세션 키 격리로 SQLite 손상 제거
6. 마무리

---

## 1. 도입: 왜 서브에이전트가 동작하지 않았는가

GEODE의 SubAgent 시스템은 약 1,500줄의 코드로 구현되어 있었습니다. `SubAgentManager`, `IsolatedRunner`, `TaskGraph`, `CoalescingQueue` — 구성 요소들은 모두 존재했습니다. 그런데 실제로 `delegate_task` 도구를 호출하면 아무 일도 일어나지 않았습니다.

문제의 본질은 **연결(wiring)의 부재**였습니다. CLI 레이어에서 `ToolExecutor`를 생성할 때 `sub_agent_manager`를 전달하지 않고, 전달할 `SubAgentManager` 인스턴스를 만들어주는 팩토리 함수도 존재하지 않았습니다. 인프라는 완성되었으나 전선이 연결되지 않은 상태 — 이 글은 그 단절을 식별하고, 수복하고, 실제 LLM을 통해 검증한 과정의 기록입니다.

---

## 2. GAP 분석: 6개의 단절 지점

코드베이스 탐색을 통해 다음 6개의 GAP을 식별했습니다.

| GAP | 심각도 | 문제 | 해결 방향 |
|-----|--------|------|-----------|
| **G1: CLI 미연결** | CRITICAL | `ToolExecutor` 생성 시 `sub_agent_manager` 미전달 | `_build_sub_agent_manager()` 팩토리 |
| **G2: task_handler 미구현** | CRITICAL | 실제 파이프라인 실행 핸들러 없음 | `make_pipeline_handler()` 구현 |
| **G3: AgentDefinition 단절** | HIGH | 에이전트 정의가 실행과 분리 | `_resolve_agent()` + AgentRegistry 주입 |
| **G4: 단일 태스크 스키마** | MEDIUM | delegate_task가 1건만 수용 | `tasks` 배열 필드 + 배치 실행 |
| **G5: 진행 콜백 없음** | LOW | 병렬 실행 중 진행 표시 없음 | `on_progress` 콜백 |
| **G6: 훅 시맨틱 오용** | LOW | `NODE_ENTER/EXIT`를 서브에이전트에 재사용 | `SUBAGENT_*` 전용 이벤트 |

> G1과 G2가 CRITICAL인 이유는 명확합니다. 이 두 가지가 빠지면 나머지 4개가 모두 구현되어 있어도 delegate_task는 `"SubAgentManager not configured"` 에러만 반환합니다. **인프라의 완성도와 시스템의 동작 여부는 별개**라는 교훈입니다.

---

## 3. Phase 1-4 구현: 연결, 라우팅, 배치, 훅

### 3.1 Phase 1 — Critical Wiring (G1 + G2)

핵심은 두 가지: 파이프라인 함수를 서브에이전트로 연결하는 핸들러와, 그 핸들러를 CLI에 주입하는 팩토리.

```python
# core/cli/sub_agent.py
def make_pipeline_handler(
    *,
    run_analysis_fn: Callable[..., dict[str, Any] | None],
    search_fn: Callable[..., dict[str, Any]] | None = None,
    compare_fn: Callable[..., dict[str, Any]] | None = None,
) -> Callable[..., dict[str, Any]]:
    """task_type을 실제 파이프라인 함수로 라우팅합니다."""

    def handler(
        task_type: str,
        args: dict[str, Any],
        *,
        agent_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if task_type == "analyze":
            ip_name = args.get("ip_name", "")
            result = run_analysis_fn(ip_name, dry_run=args.get("dry_run", True))
            if result is None:
                return {"error": f"Analysis failed for '{ip_name}'"}
            return _extract_analysis_summary(result, ip_name)
        # ... search, compare 라우팅
    return handler
```

> `agent_context` 키워드 인자를 선택적으로 받는 이유가 있습니다. 기존 테스트 핸들러들은 `(task_type, args)` 시그니처만 가지고 있어서, 새 핸들러와 레거시 핸들러가 공존해야 합니다. `_execute_subtask`에서 `TypeError` fallback으로 하위 호환성을 보장합니다.

```python
# core/cli/__init__.py
def _build_sub_agent_manager(verbose: bool = False) -> Any:
    handler = make_pipeline_handler(
        run_analysis_fn=lambda ip_name, dry_run=force_dry, **_kw:
            _run_analysis(ip_name, dry_run=dry_run, verbose=verbose),
        search_fn=lambda query="", **_kw: {
            "results": [{"name": r.ip_name, "score": r.score}
                        for r in _get_search_engine().search(query)]
        },
    )
    runner = IsolatedRunner()
    registry = AgentRegistry()
    registry.load_defaults()
    return SubAgentManager(
        runner, handler, timeout_s=300.0, agent_registry=registry
    )
```

> 이 팩토리가 CLI의 두 곳(초기 생성 + verbose 변경 시 재생성)에서 호출되어 `ToolExecutor(sub_agent_manager=sub_mgr)`로 연결됩니다. G1의 "전선 연결"이 완성되는 지점입니다.

### 3.2 Phase 2 — Agent-Aware Execution (G3)

```python
# core/cli/sub_agent.py
_TYPE_AGENT_MAP: dict[str, str] = {
    "analyze": "game_analyst",
    "search": "market_researcher",
    "compare": "game_analyst",
}

def _resolve_agent(self, task: SubTask) -> dict[str, Any] | None:
    """우선순위: task.agent(명시) > _TYPE_AGENT_MAP(타입 기반) > None"""
    agent_name = task.agent or _TYPE_AGENT_MAP.get(task.task_type)
    if agent_name is None:
        return None
    agent_def = self._agent_registry.get(agent_name)
    return {
        "agent_name": agent_def.name,
        "role": agent_def.role,
        "system_prompt": agent_def.system_prompt,
        "tools": agent_def.tools,
        "model": agent_def.model,
    }
```

> `_TYPE_AGENT_MAP`은 의도적으로 코드 상수로 관리합니다. YAML이나 JSON 외부 설정으로 빼면 유연하지만, 현재 3개 타입에 2개 에이전트만 매핑되는 규모에서는 코드 내 가시성이 더 중요합니다.

### 3.3 Phase 3 — Batch Schema & UX (G4 + G5)

```json
{
  "name": "delegate_task",
  "input_schema": {
    "properties": {
      "task_description": {"type": "string"},
      "task_type": {"enum": ["analyze", "search", "compare"]},
      "args": {"type": "object"},
      "tasks": {
        "type": "array",
        "items": {
          "properties": {
            "task_description": {"type": "string"},
            "task_type": {"enum": ["analyze", "search", "compare"]},
            "args": {"type": "object"}
          }
        }
      }
    },
    "required": []
  }
}
```

> `required: []`로 설정한 이유: 단건 모드(`task_description + task_type + args`)와 배치 모드(`tasks` 배열)가 공존합니다. LLM이 상황에 따라 자유롭게 선택할 수 있도록 필수 필드를 비웁니다. `_execute_delegate`에서 `tasks`가 없으면 단건 필드로 fallback합니다.

### 3.4 Phase 4 — Hook 시맨틱 정리 (G6)

```python
# core/orchestration/hooks.py
class HookEvent(Enum):
    # ... 기존 23개 이벤트 ...

    # SubAgent lifecycle (신규)
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_COMPLETED = "subagent_completed"
    SUBAGENT_FAILED = "subagent_failed"
```

> 파이프라인 노드의 `NODE_ENTER/EXIT/ERROR`와 서브에이전트의 생명주기를 동일 이벤트로 공유하면 이벤트 소비자가 출처를 구분할 수 없습니다. 전용 이벤트 3개를 추가하여 Hook 구독자가 `if event == SUBAGENT_COMPLETED`로 명확히 필터링할 수 있게 했습니다. 이벤트 총 수는 23 → 26개.

---

## 4. Live E2E 검증: 7개 시나리오 실행 기록

모든 테스트는 `tests/test_e2e_live_llm.py::TestSubAgentLive`에 구현되어 있으며, 실제 Anthropic API(`claude-opus-4-6`)를 사용합니다.

### 4.1 테스트 결과 요약

| # | 시나리오 | user_query | 검증 항목 | 결과 | 소요 시간 |
|---|---------|------------|----------|------|-----------|
| E1 | delegate 단건 NL 의도 | "Berserk를 서브에이전트로 분석해줘" | delegate_task 호출, 결과 반환 | **PASS** | 18.66s |
| E2 | delegate 배치 NL 의도 | "Berserk이랑 Cowboy Bebop 동시에 분석해줘. 서브에이전트 병렬로 돌려." | tasks 배열 생성, 다건 결과 | **PASS** | 21.38s |
| E3 | SubAgent wiring | (프로그래밍 검증) | `executor._sub_agent_manager is sub_mgr` | **PASS** | <1s |
| E4 | SUBAGENT_* 훅 발행 | (프로그래밍 검증) | STARTED/COMPLETED 이벤트 발행 | **PASS** | <1s |
| E5 | AgentRegistry 연결 | (프로그래밍 검증) | `_resolve_agent`가 game_analyst 반환 | **PASS** | <1s |
| E6 | 기존 분석 비회귀 | "Berserk 분석해줘" | analyze_ip 호출, tier=S | **PASS** | 86.76s |
| E7 | _execute_delegate 직접 | (프로그래밍 검증) | flat result 반환, tier 유효 | **PASS** | 7.81s |

### 4.2 E1 상세: delegate_task 단건 NL 의도

**입력**: `"Berserk를 서브에이전트로 분석해줘"`

**LLM 응답**: Claude Opus는 "서브에이전트" 키워드를 인식하고 `delegate_task` 도구를 선택했습니다.

```
▸ delegate_task(
    task_description="Berserk IP 분석",
    task_type="analyze",
    args={"ip_name": "Berserk"}
  )
```

**실행 흐름**:
1. `ToolExecutor._execute_delegate()` → `SubTask` 생성
2. `SubAgentManager.delegate([task])` → `IsolatedRunner.run_async()`
3. `_execute_subtask(task)` → `make_pipeline_handler`의 analyze 분기
4. `_run_analysis("Berserk", dry_run=True)` → 전체 파이프라인 실행
5. `_extract_analysis_summary()` → `{"tier": "S", "final_score": 81.5}`

**판정**: delegate_task → 파이프라인 → 결과 반환 경로가 완전히 동작함. G1+G2 해결 확인.

### 4.3 E2 상세: delegate_task 배치 NL 의도

**입력**: `"Berserk이랑 Cowboy Bebop 동시에 분석해줘. 서브에이전트 병렬로 돌려."`

**LLM 응답**: Claude Opus는 `tasks` 배열을 사용한 배치 모드를 선택했습니다.

```
▸ delegate_task(tasks=[
    {task_description: "Berserk IP 분석", task_type: "analyze", args: {ip_name: "Berserk"}},
    {task_description: "Cowboy Bebop IP 분석", task_type: "analyze", args: {ip_name: "Cowboy Bebop"}}
  ])
```

**실행 결과**:
- Berserk: S tier, 81.5pts — 정상 완료
- Cowboy Bebop: SQLite `database disk image is malformed` — 파이프라인 에러

**판정**: 배치 스키마(G4)가 LLM에 의해 올바르게 사용됨. 병렬 실행(`IsolatedRunner.run_async`) 동작 확인. Cowboy Bebop의 SQLite 에러는 LangGraph 체크포인터의 기존 이슈(G7, 후술).

### 4.4 E6 상세: 비회귀 확인

**입력**: `"Berserk 분석해줘"` (서브에이전트 언급 없음)

**LLM 응답**: `analyze_ip(ip_name="Berserk")` — 기존 직접 분석 경로 선택.

**판정**: "서브에이전트"를 언급하지 않으면 기존 `analyze_ip` 도구가 호출됩니다. delegate_task 추가가 기존 라우팅에 영향을 주지 않음을 확인. 86.76s는 실제 LLM 호출(Claude Opus) 비용.

---

## 5. G7 해결: OpenClaw 세션 키 격리로 SQLite 손상 제거

### 5.1 문제 발견

Phase 1-4 구현 직후 Live E2E E2(배치 테스트)에서 문제가 발생했습니다. Berserk는 S tier로 정상 완료되었으나, Cowboy Bebop이 `database disk image is malformed` 에러와 함께 실패했습니다.

원인은 명확했습니다. `IsolatedRunner`가 daemon 스레드에서 파이프라인을 실행하는데, 두 스레드가 **동일한 SQLite 체크포인터 파일**에 동시 쓰기를 시도하면서 파일이 손상된 것입니다. LangGraph의 `SqliteSaver`는 단일 스레드를 전제로 설계되어 있어, 병렬 서브에이전트 시나리오에서는 필연적으로 충돌합니다.

### 5.2 설계 결정: Claude Code vs OpenClaw

서브에이전트 메모리 격리에는 두 가지 접근법이 있습니다.

| 관점 | Claude Code (Stateless) | OpenClaw (Spawn+Announce) |
|------|------------------------|--------------------------|
| 메모리 | 서브에이전트에 공유 상태 없음 | 부모가 `childSessionKey` 발급, 독립 네임스페이스 |
| 체크포인터 | 불필요 (결과만 반환) | 자식별 MemorySaver (in-memory) |
| 추적성 | 결과 메시지로만 판단 | `SubagentRunRecord`로 부모-자식 관계 추적 |
| 적합 시나리오 | 단순 조회, 독립 태스크 | 파이프라인 실행, 상태 복원 필요 |

> GEODE의 서브에이전트는 전체 LangGraph 파이프라인을 실행합니다. 파이프라인 노드 간 상태 전이를 체크포인트로 기록해야 하므로, 체크포인터 자체를 제거할 수는 없습니다. 대신 **스레드별 독립 MemorySaver**를 할당하는 OpenClaw 방식이 적합합니다.

### 5.3 구현: 3개 파일, 최소 변경

**`core/memory/session_key.py`** — 서브에이전트 전용 세션 키 빌더:

```python
# core/memory/session_key.py
def build_subagent_session_key(
    ip_name: str, task_id: str, phase: str = "pipeline"
) -> str:
    """ip:{normalized_name}:{phase}:subagent:{normalized_task_id}"""
    normalized_name = _normalize_name(ip_name)
    normalized_task_id = _normalize_name(task_id)
    return f"ip:{normalized_name}:{phase}:subagent:{normalized_task_id}"

def build_subagent_thread_config(
    ip_name: str, task_id: str, phase: str = "pipeline"
) -> dict[str, Any]:
    thread_id = build_subagent_session_key(ip_name, task_id, phase)
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": f"geode:subagent:{ip_name}:{task_id}",
        "tags": [f"ip:{ip_name}", f"phase:{phase}", "subagent"],
        "metadata": {"ip_name": ip_name, "task_id": task_id, "is_subagent": True},
    }
```

> 기존 `build_session_key()`의 3-part 형식(`ip:X:Y`)에 `subagent:Z`를 확장하여 5-part 형식으로 만들었습니다. `parse_session_key()`도 5-part 키를 인식하도록 갱신했습니다.

**`core/cli/sub_agent.py`** — 스레드 로컬 컨텍스트 + SubagentRunRecord:

```python
# core/cli/sub_agent.py
_subagent_context = threading.local()

def get_subagent_context() -> tuple[bool, str]:
    """Return (is_subagent, child_session_key) from thread-local."""
    is_sub = getattr(_subagent_context, "is_subagent", False)
    key = getattr(_subagent_context, "child_session_key", "")
    return is_sub, key

@dataclass
class SubagentRunRecord:
    """Track parent-child relationship (OpenClaw Spawn pattern)."""
    run_id: str
    task_id: str
    child_session_key: str
    parent_session_key: str
    task_type: str
    started_at: float = 0.0
    completed_at: float = 0.0
    outcome: str = "pending"
```

> `_execute_subtask()` 진입 시 스레드 로컬에 `is_subagent=True`와 `child_session_key`를 설정하고, `finally` 블록에서 정리합니다. 이 값은 `_run_analysis()` → `GeodeRuntime`까지 전파되어 체크포인터 선택에 영향을 줍니다.

**`core/runtime.py`** — 서브에이전트 시 MemorySaver 강제:

```python
# core/runtime.py (compile_graph 내부)
if self.is_subagent:
    # Force MemorySaver for subagents (thread-safe, no SQLite contention)
    checkpoint_db = None  # MemorySaver fallback in compile_graph()
```

> `compile_graph()`에서 `checkpoint_db=None`이면 `MemorySaver`(in-memory)로 fallback합니다. 서브에이전트는 결과만 부모에게 반환하면 되므로, 영구 체크포인트가 불필요합니다. 이 한 줄 분기로 SQLite 경합이 완전히 제거됩니다.

### 5.4 검증 결과

G7 수정 후 E2 배치 테스트를 재실행한 결과:

```
▸ delegate_task(tasks=[{Berserk}, {Cowboy Bebop}])
Berserk: S | 81.2 pts | conversion_failure — SUCCESS
Cowboy Bebop: A | 68.4 pts | undermarketed — SUCCESS
✓ delegate_task → ok
1 passed in 14.78s
```

Cowboy Bebop의 `database disk image is malformed` 에러가 완전히 사라졌습니다. 두 IP 모두 독립된 MemorySaver로 파이프라인을 실행하므로, 스레드 간 SQLite 경합이 원천적으로 발생하지 않습니다.

### 5.5 G8: IsolatedRunner 시맨틱 유지 (설계 결정)

| GAP | 심각도 | 설명 | 결정 |
|-----|--------|------|------|
| **G8** | LOW | `IsolatedRunner._post_to_main()`은 범용 시설이므로 `PIPELINE_END` 유지 | SubAgent 훅은 `SubAgentManager._emit_hook()`에서만 발행 |

> 초기에 `IsolatedRunner`의 `PIPELINE_END`를 `SUBAGENT_COMPLETED`로 변경했다가, `TestPostToMain` 실패로 롤백했습니다. `IsolatedRunner`는 서브에이전트 전용이 아닌 범용 격리 실행기이므로, SUBAGENT 시맨틱을 주입하면 안 됩니다. 올바른 설계는 **Manager 레이어에서 별도 발행**입니다.

---

## 6. 마무리

### 핵심 정리

| 항목 | 값 |
|------|-----|
| 식별된 GAP | 8개 (G1-G8), 전수 해결 |
| 구현 Phase | 4개 (Critical Wiring → Agent-Aware → Batch → Hooks) + G7 OpenClaw 격리 |
| 변경 파일 | 13개 (코드 8 + 테스트 5) |
| HookEvent 수 | 23 → 26 (SUBAGENT_STARTED/COMPLETED/FAILED) |
| 테스트 결과 | 2008 mock + 7 live E2E = 전수 통과 |
| Live E2E 소요 | E1: 18.66s, E2: 14.78s (G7 수정 후), E6: 86.76s |

### 변경 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `core/cli/sub_agent.py` | `make_pipeline_handler`, `_resolve_agent`, `on_progress`, `agent` 필드, `SUBAGENT_*` 훅, `_subagent_context` 스레드 로컬, `SubagentRunRecord` |
| `core/cli/__init__.py` | `_build_sub_agent_manager()` + ToolExecutor wiring (2곳), `get_subagent_context()` 연동 |
| `core/cli/tool_executor.py` | `_execute_delegate` 배치 지원 |
| `core/tools/definitions.json` | delegate_task `tasks` 배열 스키마, `bash` 타입 제거 |
| `core/orchestration/hooks.py` | `SUBAGENT_STARTED/COMPLETED/FAILED` 이벤트 |
| `core/memory/session_key.py` | `build_subagent_session_key()`, `build_subagent_thread_config()`, `parse_session_key()` 5-part 지원 |
| `core/runtime.py` | `is_subagent` 플래그 + MemorySaver 조건 분기 |
| `tests/test_agentic_loop.py` | Hook 이벤트 → SUBAGENT_* 반영, `auto_approve`, `TestSubAgentSessionIsolation` |
| `tests/test_e2e_orchestration_live.py` | Hook 이벤트 → SUBAGENT_* 반영, `TestSubAgentSessionIsolationE2E` |
| `tests/test_e2e_live_llm.py` | `TestSubAgentLive` 7개 시나리오, `_make_loop` 4-tuple |
| `tests/test_bootstrap.py` | HookEvent 수 23 → 26 |
| `tests/test_hooks.py` | HookEvent 수 23 → 26 |

### 체크리스트

- [x] G1: CLI `_build_sub_agent_manager()` 팩토리 + ToolExecutor wiring
- [x] G2: `make_pipeline_handler()` — analyze/search/compare 라우팅
- [x] G3: `_resolve_agent()` + `AgentRegistry` 주입
- [x] G4: `tasks` 배열 스키마 + `_execute_delegate` 배치 지원
- [x] G5: `on_progress` 콜백 파라미터
- [x] G6: `SUBAGENT_STARTED/COMPLETED/FAILED` 전용 훅
- [x] G7: OpenClaw 세션 키 격리 + MemorySaver (SQLite 경합 제거)
- [x] G8: IsolatedRunner 시맨틱 유지 (설계 결정으로 해결)
- [x] Mock 테스트 2008 pass
- [x] Live E2E 7/7 pass (E1-E7)
