# Signal Tools Liveification — MCP 연동 계획

**task_id**: signal-live-api
**Date**: 2026-03-26
**Branch**: feature/signal-live-api

## 목표

signal_tools.py의 5개 stub 도구를 MCP-first + fixture fallback 패턴으로 전환.

## 현황

| Tool | 현재 | MCP Server | 키 필요 |
|------|------|-----------|---------|
| SteamInfoTool | fixture stub | steam (활성) | X |
| RedditSentimentTool | fixture stub | reddit (미등록) | X |
| GoogleTrendsTool | fixture stub | google-trends (미등록) | X |
| YouTubeSearchTool | fixture stub | youtube (키 없으면 미활성) | YOUTUBE_API_KEY |
| TwitchStatsTool | fixture stub | igdb (키 없으면 미활성) | IGDB 키 |

## 구현 전략

### 3-Tier Fallback

```
Tier 1: Direct MCP 호출 (서버 활성 시)
  ↓ 실패/미연결
Tier 2: Brave Search 쿼리 (brave-search 활성 시)
  ↓ 실패/미연결
Tier 3: Fixture 반환 (기존 stub 동작)
```

### 변경 파일

| File | Change |
|------|--------|
| `core/tools/signal_tools.py` | 5개 도구 execute() → MCP-first + fallback |
| `core/mcp/registry.py` | DEFAULT_SERVERS에 reddit, google-trends 추가 |
| `core/mcp/catalog.py` | reddit, google-trends 패키지명 검증 |
| `tests/test_signal_tools.py` | MCP mock 테스트 추가 |

### 패턴: 공유 헬퍼

```python
def _try_mcp(server_name: str, tool_name: str, args: dict) -> dict | None:
    """MCP 호출 시도. 실패 시 None 반환."""

def _try_brave_search(query: str) -> str | None:
    """Brave Search fallback. 실패 시 None 반환."""
```

### MCP 도구명 (확인 필요)

Steam MCP의 `get_game_info`처럼, 각 서버의 도구명은 런타임에 discovery.
`manager.get_all_tools()` 필터링으로 서버별 도구 목록 확인.

## 소크라틱 5문

- Q1: 코드에 이미 있는가? → LiveSignalAdapter에 TODO만 존재. 미구현.
- Q2: 안 하면 무엇이 깨지는가? → 범용 에이전트로서 실시간 데이터 수집 불가.
- Q3: 효과 측정? → `source` 필드로 live/stub 추적. 테스트에서 MCP mock.
- Q4: 가장 단순한 구현? → 기존 execute() 메서드에 MCP 호출 추가, 실패 시 기존 로직 유지.
- Q5: 프론티어 패턴? → SteamMCPSignalAdapter, BraveSearchAdapter 동일 패턴.
