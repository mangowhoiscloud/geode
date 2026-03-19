# P1: tool_search + defer_loading 도입

> Priority: P1 | Effort: Medium | Impact: 컨텍스트 85% 절감, 정확도 향상

## 현황

- GEODE에 14개 도구 존재 (3개 등록, 11개 미등록)
- 모든 도구를 한 번에 LLM에 전달 → 컨텍스트 낭비
- 도구 수 증가 시 (MCP 연동 후 30+개) 성능 저하 예상

## 목표

- Anthropic `tool_search` 메타 도구로 필요한 도구만 lazy-load
- 컨텍스트 토큰 85% 절감
- 도구 선택 정확도 향상 (Opus 4: 49% → 74%)

## 구현 계획

### 1. ToolRegistry 확장

```python
# geode/tools/registry.py
class ToolRegistry:
    def to_anthropic_tools_with_defer(
        self,
        *,
        policy: PolicyChainPort | None = None,
        mode: str = "full_pipeline",
        defer_threshold: int = 5,
    ) -> list[dict[str, Any]]:
        """도구 5개 초과 시 tool_search + defer_loading 자동 적용."""
        tools = self.to_anthropic_tools(policy=policy, mode=mode)

        if len(tools) <= defer_threshold:
            return tools  # 소규모: 전체 로딩

        # defer_loading 플래그 추가
        for tool in tools:
            tool["defer_loading"] = True

        # tool_search 메타 도구 삽입
        return self._build_tool_search_meta(tools)

    def _build_tool_search_meta(
        self,
        deferred_tools: list[dict],
    ) -> list[dict]:
        """BM25 기반 tool_search 메타 도구 생성."""
        # 도구 설명 인덱스 구축
        descriptions = {t["name"]: t["description"] for t in deferred_tools}

        tool_search = {
            "type": "tool_search",
            "name": "tool_search",
            "max_results": 5,
            "description": (
                "Search GEODE analysis tools. Categories: "
                "data (monolake, cortex), signals (youtube, reddit, steam, trends), "
                "memory (search, get, save), analysis (analyst, evaluator, psm), "
                "output (report, export, notification)"
            ),
        }
        return [tool_search] + deferred_tools
```

### 2. Runtime 배선 업데이트

```python
# runtime.py
def get_tool_state_injection(self, *, mode: str = "full_pipeline") -> dict[str, Any]:
    # defer_loading 사용 (도구 5개 초과 시 자동)
    tool_defs = self.tool_registry.to_anthropic_tools_with_defer(
        policy=self.policy_chain, mode=mode,
    )
    ...
```

### 3. 검색 전략 선택

현재 14개 → **BM25 (내장)** 기본.

향후 30+개 시:
```python
# Embedding 기반 검색 (커스텀)
from sentence_transformers import SentenceTransformer

class EmbeddingToolSearch:
    def __init__(self, tools: list[dict]):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.embeddings = self.model.encode([t["description"] for t in tools])

    def search(self, query: str, top_k: int = 5) -> list[str]:
        q_emb = self.model.encode(query)
        scores = cosine_similarity([q_emb], self.embeddings)[0]
        indices = scores.argsort()[-top_k:][::-1]
        return [self.tools[i]["name"] for i in indices]
```

## 효과 추정

| 시나리오 | 도구 수 | 기존 토큰 | defer 후 토큰 | 절감률 |
|---|---|---|---|---|
| 현재 (등록 3개) | 3 | ~3K | 적용 안 함 | 0% |
| 전체 등록 (14개) | 14 | ~15K | ~2.5K | 83% |
| MCP 연동 후 (30+개) | 30 | ~35K | ~4K | 89% |

## 수정 파일

| 파일 | 변경 |
|---|---|
| `geode/tools/registry.py` | `to_anthropic_tools_with_defer()` 추가 |
| `geode/runtime.py` | defer 방식 호출로 전환 |
| `tests/test_tools.py` | defer 테스트 추가 |
