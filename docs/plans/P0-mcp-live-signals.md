# P0: MCP 기반 라이브 신호 수집

> Priority: P0 | Effort: Medium | Impact: Fixture → 실시간 데이터 전환

## 현황

- 모든 신호 데이터가 `geode/fixtures/*.json`에 하드코딩
- `LiveSignalAdapter`는 stub 상태 (항상 fixture fallback)
- `SignalEnrichmentPort` + Port/Adapter 패턴은 이미 구현

## 목표

MCP 서버 3종 연결로 실시간 데이터 수집:
1. **Steam MCP** — 게임 메트릭 (플레이어수, 리뷰, 뉴스)
2. **Brave Search MCP** — 웹 검색 (IP 관련 최신 뉴스)
3. **Knowledge Graph Memory MCP** — 분석 결과 영속 저장

## 구현 계획

### Phase 1: MCP Client 인프라

```
geode/infrastructure/adapters/mcp/
├── __init__.py
├── base.py          # MCPClientBase (연결, 도구 호출, 에러 처리)
├── steam_adapter.py # SteamMCPSignalAdapter implements SignalEnrichmentPort
├── brave_adapter.py # BraveSearchAdapter
└── memory_adapter.py # KGMemoryAdapter implements SessionStorePort
```

### Phase 2: Steam MCP 연결

```python
class SteamMCPSignalAdapter:
    """Steam MCP 서버를 SignalEnrichmentPort로 래핑."""

    def __init__(self, mcp_client: MCPClientBase):
        self._client = mcp_client

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        # Steam API → 정규화된 신호 딕셔너리
        player_count = self._client.call_tool("get_player_count", {"app_id": ...})
        reviews = self._client.call_tool("get_reviews", {"app_id": ...})
        return {
            "steam_players_current": player_count,
            "steam_review_score": reviews["score"],
            "steam_review_count": reviews["total"],
            ...
        }

    def is_available(self) -> bool:
        return self._client.is_connected()
```

### Phase 3: Brave Search 연결

```python
class BraveSearchSignalAdapter:
    """Brave Search로 IP 관련 최신 뉴스/트렌드 수집."""

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        results = self._client.call_tool("brave_web_search", {
            "query": f"{ip_name} game news 2026",
            "count": 5,
        })
        return {
            "web_news_count": len(results),
            "web_sentiment": self._analyze_sentiment(results),
            "latest_news": results[:3],
        }
```

### Phase 4: Runtime 배선

```python
# runtime.py GeodeRuntime.create() 확장
def _build_mcp_adapters(self) -> dict[str, Any]:
    adapters = {}
    if settings.steam_mcp_url:
        steam = MCPClientBase(settings.steam_mcp_url)
        adapters["steam"] = SteamMCPSignalAdapter(steam)
    if settings.brave_api_key:
        brave = MCPClientBase(settings.brave_mcp_url)
        adapters["brave"] = BraveSearchSignalAdapter(brave)
    return adapters
```

## 설정 (.env)

```env
# MCP Servers
STEAM_MCP_URL=stdio://steam-mcp
BRAVE_MCP_URL=stdio://brave-search-mcp
BRAVE_API_KEY=BSA...
KG_MEMORY_MCP_URL=stdio://memory-server
```

## Graceful Degradation

```
MCP 연결 시도 → 성공: 라이브 데이터
                → 실패: LiveSignalAdapter fallback
                        → 실패: FixtureSignalAdapter fallback
```

## 수정 파일

| 파일 | 변경 |
|---|---|
| `geode/infrastructure/adapters/mcp/` | 신규 디렉토리 |
| `geode/config.py` | MCP URL/키 설정 추가 |
| `geode/runtime.py` | MCP 어댑터 빌드 + 주입 |
| `geode/nodes/signals.py` | 복합 어댑터 체인 지원 |
