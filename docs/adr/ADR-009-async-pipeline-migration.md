# ADR-009: 파이프라인 Async 전환 전략

> Status: **PROPOSED** | Date: 2026-03-16 | Author: geode-team

## Context

GEODE 파이프라인은 현재 **전면 sync**입니다. LangGraph 노드가 `def` (sync)이고, LLM 호출이 `Anthropic` (sync client)이며, `graph.stream()`으로 실행됩니다.

v0.12.0에서 직접 검증한 결과, LangGraph는 `async def` 노드 + `Send()` + `.astream()` + `.ainvoke()`를 **완전히 지원**합니다.

```python
# 검증 결과: Send + async 4개 병렬 → 3.9x speedup
async def async_worker(state):
    await asyncio.sleep(0.1)
    return {'values': [f'{state["_worker_type"]}_done']}

# 0.4초 순차 → 0.103초 병렬 (3.9x)
```

이전 P3 asyncio 시도(v0.11.0)가 리버트된 이유는 LangGraph 제약이 아니라 **전환 범위의 파급**이었습니다. 이 ADR은 리서치 결과를 기반으로 전환 전략을 결정합니다.

## Decision Drivers

1. **4 Analyst 병렬 실행**: 현재 Send API가 라우팅만 하고 LLM 호출은 순차 실행 (sync `call_llm_parsed`)
2. **시간 예산 (Karpathy P3)**: `asyncio.timeout()`으로 wall-clock 예산 제어 가능
3. **관측성 즉시성**: Hook 발행이 완료 즉시 (as_completed 패턴 이미 적용)
4. **프론티어 정렬**: Claude Code(asyncio), LangGraph 4.x(native async), OpenClaw(Spawn+Announce)

## Considered Options

### Option A: Big-Bang 전환 (전체 async 전환)

모든 노드를 `async def`로, `graph.stream()` → `graph.astream()`으로 일괄 전환.

| 장점 | 단점 |
|------|------|
| 깔끔한 코드베이스 | 9개 노드 + 3개 stream 호출 + 23개 테스트 파일 일괄 변경 |
| 최대 성능 | 중간 상태 없음 (작동하거나 깨지거나) |
| | LangGraph mixed sync/async 미지원 → 전부 바꿔야 함 |

### Option B: 하이브리드 전환 (LLM client async + sync 노드 유지)

LLM client에 async 변형 추가하되, 노드는 sync로 유지. 노드 내부에서 `asyncio.to_thread()` 역패턴 사용.

| 장점 | 단점 |
|------|------|
| 노드 시그니처 유지 | sync 노드 안에서 async 호출은 안티패턴 |
| 테스트 영향 최소 | 실질적 병렬 이득 없음 (event loop 중첩 불가) |

### Option C: 단계적 전환 + Feature Flag (채택)

3 Phase로 나누어 점진적 전환. Feature flag로 sync/async 경로 공존.

| 장점 | 단점 |
|------|------|
| 각 Phase 독립 검증 가능 | 코드 중복 (sync + async 경로 공존) |
| 기존 테스트 유지 | Feature flag 관리 부담 |
| 롤백 안전 | 완전 전환까지 시간 소요 |

## Decision

**Option C: 단계적 전환 + Feature Flag**를 채택합니다.

## Implementation Plan

### Phase 1: AsyncAnthropic LLM Client

**범위**: `core/llm/client.py`에 async 함수 추가

```python
# 신규 함수 (기존 sync 함수 유지)
async def acall_llm(system: str, user: str, **kwargs) -> str: ...
async def acall_llm_parsed(system: str, user: str, *, output_model: type[T]) -> T: ...
```

**영향**: 0개 기존 파일 변경. 신규 함수만 추가.
**검증**: 단위 테스트로 async LLM 호출 검증.

### Phase 2: Async 노드 + astream 경로

**범위**: 9개 노드 함수를 `async def`로 전환, `graph.astream()` 경로 추가

```python
# AS-IS
def analyst_node(state: GeodeState) -> dict[str, Any]:
    result = parsed_fn(system, user, output_model=AnalysisResult)
    return {"analyses": [result]}

# TO-BE
async def analyst_node(state: GeodeState) -> dict[str, Any]:
    result = await acall_llm_parsed(system, user, output_model=AnalysisResult)
    return {"analyses": [result]}
```

**영향**:
- `core/nodes/*.py`: 6개 노드 함수 → `async def`
- `core/graph.py`: `_make_hooked_node`, `_verification_node`, `_gather_node` → `async def`
- `core/graph.py`: `compile_graph()` 내부 변경 없음 (LangGraph가 async 노드 자동 감지)
- `core/runtime.py`: `graph.stream()` → `graph.astream()` (feature flag)
- `core/cli/__init__.py`: 2개 stream 호출 → astream (feature flag)

**Feature Flag**:
```python
# core/config.py
async_pipeline: bool = False  # GEODE_ASYNC_PIPELINE=true로 활성화
```

**검증**: `uv run geode analyze "Berserk" --dry-run`이 동일 결과 산출.

### Phase 3: Hook System async 선택적 지원

**범위**: `_make_hooked_node`가 async가 되면 Hook trigger도 async 가능

```python
# _make_hooked_node 내부 (async 노드 경로)
async def _wrapped(state):
    hooks.trigger(HookEvent.NODE_ENTER, data)  # sync hook — 여전히 동작
    result = await node_fn(state)              # async 노드 실행
    hooks.trigger(HookEvent.NODE_EXIT, data)   # sync hook — 여전히 동작
    return result
```

**핵심 결정**: Hook trigger는 **sync 유지**. async 노드 안에서 sync 함수 호출은 문제 없음 (반대가 문제).

## Impact Analysis

| 구성 요소 | 파일 수 | 변경 유형 |
|----------|--------|----------|
| LLM client | 1 | 신규 async 함수 추가 |
| 노드 함수 | 6 | `def` → `async def` + `await` |
| graph.py 내부 노드 | 3 | `def` → `async def` |
| Stream 호출 | 3 | `.stream()` → `.astream()` (flag) |
| Hook system | 0 | 변경 없음 (sync 유지) |
| 테스트 | 23 파일 | async 경로 테스트 추가 (기존 유지) |

## Frontier Alignment — GitHub 코드베이스 기반 실증

### Anthropic Claude Agent SDK (`anthropics/claude-agent-sdk-python`)

**아키텍처**: Async-first. 진입점이 `anyio.run(main)`, 에이전트 루프가 `async for message in query()`.

```python
# Claude Agent SDK 패턴
async def main():
    async for message in query(prompt="Hello"):
        print(message)
anyio.run(main)
```

**도구 실행**: 순차 (병렬 아님). 각 `ToolUseBlock`을 하나씩 처리 후 결과 반환.
**Hook**: **Sync 콜백**을 async 루프 안에서 호출. `PreToolUse`/`PostToolUse` hook은 sync function.
**MCP**: In-process MCP 서버 (subprocess 대신 동일 프로세스에서 async 실행).

> **GEODE 시사점**: Claude Agent SDK는 "async 루프 + sync hook" 패턴을 공식 채택. GEODE의 "async 노드 + sync Hook trigger" 결정과 정확히 일치.

### OpenAI Codex (`openai/codex`)

**아키텍처**: Rust async (tokio). 도구 호출을 `FuturesOrdered`로 병렬 디스패치.

```rust
// Codex 병렬 도구 실행 패턴 (PR #10505, 2026-02)
if let Some(tool_future) = output_result.tool_future {
    in_flight.push_back(tool_future);  // 큐에 추가, 즉시 await 안 함
}
```

**문제 발견**: 3+ 병렬 tool_call 시 `ResponseEvent::Completed`가 모든 future 완료 전에 도착 → 응답 유실 (#8479). **async 병렬의 실전 위험**을 보여줌.
**시사점**: 병렬 도구 실행은 race condition 위험이 있으며, drain/completion 보장 메커니즘 필수.

### CrewAI (`crewAIInc/crewAI`)

**아키텍처**: `async_execution=True` 플래그로 태스크별 병렬 전환.

```python
# CrewAI 패턴
task1 = Task(description="...", async_execution=True)
task2 = Task(description="...", async_execution=True)
# asyncio.gather()로 병렬 실행
```

**시사점**: 태스크 레벨 `async_execution` 플래그는 GEODE의 feature flag 전략과 동일한 접근.

### LangGraph (`langchain-ai/langgraph`)

**아키텍처**: Superstep 모델. 동일 depth의 노드는 동시 실행. `.astream()`으로 async 노드 네이티브 지원.

```python
# LangGraph 공식 패턴
async def my_node(state):
    result = await llm.ainvoke(state["messages"])
    return {"messages": [result]}

graph.add_node("chat", my_node)  # async def 직접 등록
async for event in graph.astream(input):  # async 스트리밍
    process(event)
```

**검증 결과**: Send API + async 노드 4개 → 0.103초 (sync 대비 3.9x speedup). `max_concurrency` 설정으로 동시 노드 수 제한 가능.

### 프론티어 비교 매트릭스

| 차원 | Claude Agent SDK | Codex | CrewAI | LangGraph | **GEODE (현재)** | **GEODE (전환 후)** |
|------|-----------------|-------|--------|-----------|-----------------|-------------------|
| **코어 루프** | async iterator | Rust async | asyncio.gather | superstep | sync for-loop | async superstep |
| **도구 병렬** | 순차 | 병렬 (race 위험) | 플래그 기반 | Send API | Send + sync | Send + async |
| **Hook** | **sync** callback | N/A | N/A | N/A | **sync** | **sync (유지)** |
| **LLM 호출** | async | async | async | async | **sync** | **async** |
| **스트리밍** | async iterator | SSE | N/A | `.astream()` | `.stream()` | `.astream()` |

> **핵심 발견**: 모든 프론티어가 **LLM 호출은 async, Hook/이벤트는 sync**를 채택. GEODE의 "Phase 2에서 노드 async 전환, Hook은 sync 유지" 전략은 프론티어 컨센서스와 일치.

## Trade-offs

| 측면 | Sync (현재) | Async (전환 후) |
|------|-----------|----------------|
| **4 Analyst 병렬** | Send API 라우팅만, LLM 순차 | 4개 동시 `await` → 3.9x speedup |
| **디버깅** | 직관적 스택트레이스 | async 스택 깊어짐 |
| **테스트** | 단순 assert | `pytest-asyncio` 필요 (async 경로) |
| **시간 예산** | iteration count (간접) | `asyncio.timeout()` (직접) |
| **Hook** | sync 유지 | sync 유지 (변경 없음) |
| **롤백** | N/A | Feature flag로 즉시 sync 복귀 |

## Risks

1. **LangGraph mixed sync/async**: 모든 노드가 일괄 전환되어야 함. 부분 전환 불가.
   - **완화**: Feature flag로 sync/async 그래프를 별도 빌드.

2. **Nested event loop**: Typer CLI 안에서 `asyncio.run()` 중첩 위험.
   - **완화**: 진입점 하나에서만 `asyncio.run()`. REPL은 이미 `asyncio.run(agentic.arun())` 사용.

3. **ContextVar 전파**: async task 간 contextvars 전파 확인 필요.
   - **완화**: Python 3.12+ `asyncio.TaskGroup`은 자동 전파.

## Consequences

- Phase 1 후: 코드 변경 최소, 성능 변화 없음 (인프라 준비)
- Phase 2 후: 4 Analyst 병렬 LLM 호출 → 분석 시간 ~70% 단축
- Phase 3 후: Hook은 sync 유지하므로 영향 없음

## References

- LangGraph async 검증: `uv run python` 직접 테스트 (Send + async 4x parallel, 3.9x speedup)
- [LangGraph async example](https://github.com/langchain-ai/langgraph/blob/main/examples/async.ipynb)
- [LangGraph Send API parallel execution](https://dev.to/sreeni5018/leveraging-langgraphs-send-api-for-dynamic-and-parallel-workflow-execution-4pgd)
- OpenClaw Spawn+Announce: `.claude/skills/openclaw-patterns/SKILL.md` §4
- Karpathy P3 Fixed Time Budget: `.claude/skills/karpathy-patterns/SKILL.md` §P3
- P3 asyncio 리버트 이력: commit 5357e66 → 59ddde3
