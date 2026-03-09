# P3: GEODE as MCP Server

> Priority: P3 | Effort: High | Impact: 외부 시스템에서 GEODE 분석 호출 가능

## 현황

- GEODE는 CLI 전용 파이프라인
- 외부 도구(Claude Code, Cursor, VS Code)에서 호출 불가
- 분석 결과를 다른 에이전트가 소비할 수 없음

## 목표

- GEODE를 MCP 서버로 노출
- Claude Code / Cursor에서 `geode_analyze "Cowboy Bebop"` 도구 호출 가능
- 분석 결과를 MCP 리소스로 제공

## 구현 계획

### 1. MCP 서버 정의

```python
# geode/mcp_server.py
from mcp.server import Server
from mcp.types import Tool, Resource

server = Server("geode-analysis")

@server.tool()
async def analyze_ip(ip_name: str, mode: str = "full") -> dict:
    """Run GEODE analysis pipeline on an IP."""
    runtime = GeodeRuntime.create(ip_name)
    graph = runtime.compile_graph()
    state = build_initial_state(ip_name, mode)
    result = await graph.ainvoke(state, config=runtime.thread_config)
    return format_result(result)

@server.tool()
async def query_memory(query: str, tier: str = "all") -> dict:
    """Search GEODE memory across tiers."""
    ...

@server.tool()
async def get_ip_signals(ip_name: str) -> dict:
    """Get community signals for an IP."""
    ...

@server.resource("geode://analyses/{ip_name}")
async def get_analysis(ip_name: str) -> str:
    """Get latest analysis result as MCP resource."""
    ...

@server.resource("geode://fixtures")
async def list_fixtures() -> str:
    """List all available IP fixtures."""
    ...
```

### 2. MCP 설정 파일

```json
// ~/.claude/mcp_servers.json
{
  "geode": {
    "command": "uv",
    "args": ["run", "python", "-m", "geode.mcp_server"],
    "cwd": "/path/to/geode"
  }
}
```

### 3. 노출 도구 목록

| MCP Tool | 설명 |
|---|---|
| `analyze_ip` | 전체 파이프라인 실행 |
| `quick_score` | scoring_only 모드 (빠른 스코어) |
| `query_memory` | 3-tier 메모리 검색 |
| `get_ip_signals` | 커뮤니티 신호 조회 |
| `compare_ips` | 2개 IP 비교 분석 |
| `get_health` | 파이프라인 헬스 체크 |

### 4. MCP 리소스 목록

| URI | 설명 |
|---|---|
| `geode://analyses/{ip}` | 최신 분석 결과 |
| `geode://fixtures` | 사용 가능 IP 목록 |
| `geode://rubric` | 14-axis 루브릭 정의 |
| `geode://soul` | SOUL.md 내용 |

## 수정 파일

| 파일 | 변경 |
|---|---|
| `geode/mcp_server.py` | 신규: MCP 서버 진입점 |
| `pyproject.toml` | `mcp` 의존성 추가 |
| `pyproject.toml` | `[project.scripts]` MCP 서버 엔트리 |
