# P1: 전체 도구 등록 + PolicyChain 확장

> Priority: P1 | Effort: Low | Impact: Tool-augmented 노드 활용도 극대화

## 현황

- 14개 도구 중 3개만 ToolRegistry에 등록
- tool-augmented 경로 (Synthesizer, BiasBuster)가 3개 도구만 접근 가능
- Signal/Memory/Output 도구는 구현돼 있지만 비활성

## 목표

- 14개 전체 도구 등록
- 파이프라인 모드별 PolicyChain으로 접근 제어
- LLM이 memory_search, signal 도구를 분석 중 활용 가능

## 구현 계획

### 1. Registry 빌더 확장

```python
# runtime.py
def _build_default_registry() -> ToolRegistryPort:
    registry = ToolRegistry()

    # Analysis (기존)
    registry.register(RunAnalystTool())
    registry.register(RunEvaluatorTool())
    registry.register(PSMCalculateTool())

    # Data
    registry.register(QueryMonoLakeTool())
    registry.register(CortexAnalystTool())
    registry.register(CortexSearchTool())

    # Signals
    registry.register(YouTubeSearchTool())
    registry.register(RedditSentimentTool())
    registry.register(TwitchStatsTool())
    registry.register(SteamInfoTool())
    registry.register(GoogleTrendsTool())

    # Memory
    registry.register(MemorySearchTool())
    registry.register(MemoryGetTool())
    registry.register(MemorySaveTool())

    # Output
    registry.register(GenerateReportTool())
    registry.register(ExportJsonTool())
    registry.register(SendNotificationTool())

    return registry
```

### 2. PolicyChain 모드별 제어

```python
def _build_default_policies() -> PolicyChainPort:
    chain = PolicyChain()

    # dry_run: LLM 도구 차단
    chain.add_policy(ToolPolicy(
        name="dry_run_block_llm",
        mode="dry_run",
        denied_tools={"run_analyst", "run_evaluator"},
        priority=100,
    ))

    # dry_run: 데이터/메모리 도구는 허용
    chain.add_policy(ToolPolicy(
        name="dry_run_allow_data",
        mode="dry_run",
        allowed_tools={
            "query_monolake", "memory_search", "memory_get",
            "psm_calculate", "steam_info",
        },
        priority=90,
    ))

    # evaluation 모드: 분석+데이터만
    chain.add_policy(ToolPolicy(
        name="evaluation_tools",
        mode="evaluation",
        allowed_tools={
            "run_analyst", "run_evaluator", "psm_calculate",
            "query_monolake", "memory_search",
        },
        priority=100,
    ))

    # full_pipeline: 알림 제외 전부 허용
    chain.add_policy(ToolPolicy(
        name="full_block_notification",
        mode="full_pipeline",
        denied_tools={"send_notification"},  # 명시적 요청 시만
        priority=100,
    ))

    return chain
```

### 3. Memory 도구 ContextVar 주입

Memory 도구는 `SessionStorePort`가 필요 → runtime에서 주입:

```python
# runtime.py GeodeRuntime.create()
from core.tools.memory_tools import set_memory_session_store
set_memory_session_store(session_store)
```

## 수정 파일

| 파일 | 변경 |
|---|---|
| `geode/runtime.py` | 전체 도구 등록 + memory store 주입 |
| `geode/tools/policy.py` | 모드별 정책 추가 |
| `tests/test_tools.py` | 14개 도구 등록 테스트 |
| `tests/test_policy.py` | 모드별 필터링 테스트 |
