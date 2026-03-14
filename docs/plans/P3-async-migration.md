# P3: Async Migration — threading → asyncio

**Status**: DRAFT
**Created**: 2026-03-15
**Priority**: P3
**Depends**: P2-subagent-orchestration-hardening (completed)

---

## 0. 핵심 판단

> GEODE는 코드베이스 전체가 threading 기반 동기 실행이다. 프론티어 에이전트 시스템(Claude Code, Codex, LangGraph)은 2026년 기준으로 **asyncio-first**가 표준이다. 특히 LangGraph의 `.astream()`은 50 동시 요청에서 sync 대비 **37x 성능 향상**을 보였다.

### 전환 근거

| 근거 | 설명 |
|------|------|
| **I/O-bound 워크로드** | LLM API 호출, HTTP fetch, MCP RPC — 전부 I/O 대기. asyncio의 최적 영역 |
| **LangGraph 네이티브** | `.astream()` / `.ainvoke()` 이미 제공. 현재 `.stream()` 사용은 성능 손해 |
| **Anthropic SDK** | `AsyncAnthropic` + `httpx.AsyncClient` drop-in 대체 가능 |
| **ContextVar 자동 전파** | asyncio에서는 `create_task()` 시 부모 context 자동 복사 → P2-B의 수동 전파 불필요 |
| **서브에이전트 병렬성** | async 전환 시 `asyncio.gather()` 로 동시 실행 → 현재 polling 제거 |
| **Python 3.14** | free-threading production-ready (2026.03). CPU-bound 부분도 혜택 |

### 전환하지 않을 경우의 리스크

| 리스크 | 영향 |
|--------|------|
| `_wait_for_result()` polling | 0.05s→1s sleep 루프. CPU idle이지만 스레드 점유 |
| HookSystem 동기 호출 | 느린 리스너가 `delegate()` 전체 차단 |
| 순차 tool 실행 | 병렬 가능한 tool call이 순차 실행 |
| LangGraph sync 모드 | `.stream()` → `.astream()` 전환만으로 37x 개선 가능한데 미사용 |

---

## 1. 프론티어 비교

| 차원 | Claude Code | OpenClaw | Codex | LangGraph | GEODE (현재) |
|------|-------------|----------|-------|-----------|-------------|
| **실행 모델** | asyncio | Node.js event loop | SSE + async gen | asyncio native | **threading** |
| **LLM 호출** | async | async | SSE stream | async node 지원 | **sync (blocking)** |
| **서브에이전트** | async msg | Spawn+Announce (비차단) | parallel tool calls | `asyncio.gather()` | **polling wait** |
| **Hook/Event** | async lifecycle | sync (feature req #5279) | SSE events | `astream_events()` | **sync for-loop** |
| **ContextVar** | asyncio 자동 전파 | N/A (Node.js) | N/A (TypeScript) | asyncio 자동 전파 | **수동 전파 (P2-B)** |

---

## 2. 전환 범위 분류

### Phase 1: Foundation (1-2일) — Trivial + 고 ROI

| 작업 | 파일 | 난이도 | 효과 |
|------|------|--------|------|
| `AsyncAnthropic` wrapper | `core/llm/client.py` (async variant) | Moderate | LLM 호출 비동기화 |
| `time.sleep()` → `asyncio.sleep()` | 5개 파일 (6곳) | Trivial | 이벤트 루프 블로킹 제거 |
| HookSystem `async trigger()` | `core/orchestration/hooks.py` | Trivial | 느린 리스너 비차단 |

### Phase 2: Core Loop (2-3일) — 최대 성능 개선

| 작업 | 파일 | 난이도 | 효과 |
|------|------|--------|------|
| `AgenticLoop.run()` → `async def` | `core/cli/agentic_loop.py` | Moderate | 메인 루프 비동기화 |
| `ToolExecutor.execute()` async variant | `core/cli/tool_executor.py` | Moderate | 병렬 tool 실행 기반 |
| `httpx.get()` → `httpx.AsyncClient` | `core/tools/web_tools.py` | Trivial | HTTP 비차단 |
| LangGraph `.stream()` → `.astream()` | `core/runtime.py` (1줄) | Trivial | **37x 동시 처리 개선** |

### Phase 3: Orchestration (2-3일) — 구조적 전환

| 작업 | 파일 | 난이도 | 효과 |
|------|------|--------|------|
| `IsolatedRunner` → `asyncio.TaskGroup` | `core/orchestration/isolated_execution.py` | Hard | 스레드 → 태스크 전환 |
| `SubAgentManager.delegate()` async | `core/cli/sub_agent.py` | Moderate | polling 제거 |
| `_propagate_context_vars()` 제거 | `core/cli/sub_agent.py` | Trivial | asyncio 자동 전파 활용 |
| `subprocess.run()` → `create_subprocess_shell()` | `core/cli/bash_tool.py` | Moderate | subprocess 비차단 |
| MCP StdioClient async | `core/infrastructure/adapters/mcp/stdio_client.py` | Hard | MCP 비차단 |

### Phase 4: Test + Polish (1-2일)

| 작업 | 파일 | 난이도 |
|------|------|--------|
| `pytest-asyncio` 도입 | `pyproject.toml` | Trivial |
| 핵심 경로 async 테스트 | `tests/` | Moderate |
| Mixed sync/async handler wrapping | `tool_executor.py` | Moderate |

---

## 3. 핵심 설계 결정

### 3.1 점진적 전환 vs 빅뱅

**결정: 점진적 전환 (Phase 1 → 4 순차)**

| 옵션 | 장점 | 단점 |
|------|------|------|
| **빅뱅** | 한 번에 완료, 코드 일관성 | 2168 테스트 전부 깨짐, 롤백 불가 |
| **점진적** | 각 Phase 독립 검증, 리스크 분산 | 과도기 sync/async 혼재 |

> Duolingo 사례: 인프라 코드(HTTP client)부터 시작 → feature resolver → 최상위 핸들러 순서. 이 패턴을 따름.

### 3.2 Mixed sync/async handler 전략

```python
async def execute_async(self, tool_name: str, tool_input: dict) -> dict:
    handler = self._handlers.get(tool_name)
    if asyncio.iscoroutinefunction(handler):
        return await handler(**tool_input)
    else:
        return await asyncio.to_thread(handler, **tool_input)
```

> `asyncio.to_thread()`는 Python 3.9+에서 현재 context를 자동 복사합니다. sync handler를 async 컨텍스트에서 안전하게 실행할 수 있습니다. 단, `asyncio.to_thread()` 내부에서 ContextVar을 변경해도 부모에 역전파되지 않습니다 (PEP 567 by-design).

### 3.3 IsolatedRunner 전환 경로

```
AS-IS (threading):
  threading.Thread → Semaphore(5) → thread.join(timeout) → polling

TO-BE (asyncio):
  asyncio.create_task() → Semaphore(5) → await task → 직접 반환

장점:
  - polling 제거 (_wait_for_result의 time.sleep 루프 불필요)
  - context 자동 전파 (_propagate_context_vars 불필요)
  - cancel 지원 (asyncio.Task.cancel() → CancelledError)
```

### 3.4 LangGraph 1줄 변경의 37x 효과

```python
# AS-IS (sync):
result = graph.stream(state, config=runtime.thread_config)

# TO-BE (async, 1줄):
result = graph.astream(state, config=runtime.thread_config)
```

> LangGraph 벤치마크: 50 동시 요청에서 sync ~2.5분 → async ~4초. GEODE의 배치 분석(`batch --top 5`)이 직접적으로 혜택을 받는 변경입니다.

---

## 4. 트레이드오프

| 얻는 것 | 잃는 것 |
|---------|---------|
| LLM 호출 비동기 (I/O 대기 중 다른 작업 가능) | 디버깅 복잡도 증가 (async stacktrace) |
| LangGraph 37x 동시 처리 | 전체 진입점 `async def main()` 필요 |
| ContextVar 자동 전파 → P2-B 수동 코드 제거 | `asyncio.run()` 중첩 불가 제약 |
| HookSystem 느린 리스너 비차단 | sync/async 혼재 과도기 복잡도 |
| 서브에이전트 polling 제거 | `IsolatedRunner` 전면 재작성 (Hard) |
| `asyncio.gather()` 병렬 tool 실행 | 기존 2168 테스트 일부 수정 필요 |

---

## 5. 미결 사항

- [ ] Phase 1만 먼저 구현하고 성능 측정할 것인지, Phase 1-2 한꺼번에 할 것인지
- [ ] `Typer` CLI 진입점을 `anyio.run()` 또는 `asyncio.run()` 으로 전환하는 방법
- [ ] MCP StdioClient async 전환 시 기존 프로세스 관리 호환성
- [ ] Python 3.14 free-threading 활용 범위 (CPU-bound 전처리에만 제한?)
- [ ] `pytest-asyncio` strict mode vs auto mode 결정

---

## 6. 참조

| 소스 | 핵심 내용 |
|------|----------|
| LangGraph async benchmark | 50 동시 요청: sync 2.5min → async 4s (37x) |
| Claude Code async subagents | 2026 초 배경 에이전트 비동기 메시징 추가 |
| Anthropic SDK | `AsyncAnthropic` + `httpx.AsyncClient` drop-in |
| Duolingo async migration | 인프라 → feature → handler 순서 점진적 전환 |
| Python 3.14 free-threading | production-ready, single-thread 5-10% overhead |
| PEP 567 contextvars | asyncio Task 자동 복사, to_thread 자동 복사, 역전파 없음 |
| OpenClaw single-thread bottleneck | Node.js event loop 단일 스레드 10s timeout (Issue #6508) |
