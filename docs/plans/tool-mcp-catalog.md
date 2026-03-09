# GEODE Tool & MCP Catalog

> Status: Draft | Date: 2026-03-09 | Author: AI Engineer

## 1. 현재 Tool 인벤토리

### 1.1 등록된 도구 (ToolRegistry, 3개)

| Tool | 설명 | 파라미터 |
|---|---|---|
| `run_analyst` | IP 분석가 실행 (4종) | `analyst_type`, `ip_name` |
| `run_evaluator` | 루브릭 평가자 실행 (3종) | `evaluator_type`, `ip_name` |
| `psm_calculate` | PSM 노출 효과 계산 | `ip_name` |

### 1.2 미등록 도구 (구현 완료, 11개)

**Data Tools** (`tools/data_tools.py`):

| Tool | 설명 | 상태 |
|---|---|---|
| `query_monolake` | IP 게임 메트릭 조회 (DAU, 매출, 메타크리틱) | Fixture 기반 |
| `cortex_analyst` | Snowflake Cortex NL→SQL 쿼리 | Stub (demo) |
| `cortex_search` | Cortex 시맨틱 검색 (리뷰, 커뮤니티) | Stub (demo) |

**Signal Tools** (`tools/signal_tools.py`):

| Tool | 설명 | 상태 |
|---|---|---|
| `youtube_search` | YouTube 조회수, 댓글 센티먼트 | Fixture fallback |
| `reddit_sentiment` | Reddit 구독자, 포스트 빈도, 감성 | Fixture fallback |
| `twitch_stats` | Twitch 동접, 스트림 시간 | Fixture fallback |
| `steam_info` | Steam 리뷰, 플레이어수, 가격 | Fixture fallback |
| `google_trends` | Google Trends 관심도 인덱스 | Fixture fallback |

**Memory Tools** (`tools/memory_tools.py`):

| Tool | 설명 | 상태 |
|---|---|---|
| `memory_search` | 3-tier 메모리 검색 | ContextVar 주입 |
| `memory_get` | 세션 ID로 메모리 조회 | ContextVar 주입 |
| `memory_save` | 세션 메모리 저장/병합 | ContextVar 주입 |

**Output Tools** (`tools/output_tools.py`):

| Tool | 설명 | 상태 |
|---|---|---|
| `generate_report` | 분석 리포트 생성 (MD/JSON/HTML) | 완전 구현 |
| `export_json` | 분석 결과 JSON 내보내기 | 완전 구현 |
| `send_notification` | Slack/Email/Webhook 알림 | Stub |

---

## 2. MCP 서버 카탈로그

### 2.1 공식 Reference 서버 (modelcontextprotocol/servers)

| MCP 서버 | 용도 | GEODE 관련성 |
|---|---|---|
| **Memory** | Knowledge Graph 기반 영속 메모리 | **높음** — 3-tier 메모리 확장 |
| **Fetch** | 웹 콘텐츠 수집 (Markdown 변환) | **높음** — 신호 수집 |
| **Filesystem** | 로컬 파일 읽기/쓰기 | 중간 — fixture 관리 |
| **Git** | Git 작업 (diff, log, commit) | 낮음 |
| **Sequential Thinking** | 복잡 추론 체인 | 중간 — 분석 파이프라인 |

### 2.2 데이터 수집 & 신호 MCP

| MCP 서버 | 용도 | 우선순위 |
|---|---|---|
| **Steam MCP** (algorhythmic/steam-mcp) | Steam 플레이어수, 리뷰, 뉴스 | **P0** — 핵심 게임 데이터 |
| **Brave Search** | 웹 검색 (2,000 무료/월) | **P0** — 범용 검색 |
| **Google Trends MCP** | IP 관심도 트렌드 | **P1** |
| **Firecrawl** | 웹 스크래핑 (76.8% 성공률) | **P2** |
| **Tavily Search** | 실시간 검색 + 데이터 추출 | **P2** |

### 2.3 소셜 & 커뮤니티 MCP

| MCP 서버 | 용도 | 우선순위 |
|---|---|---|
| **Reddit MCP** | 서브레딧 분석, 감성 | **P1** |
| **X (Twitter) MCP** | 트위터 멘션, 트렌드 | **P1** |
| **Xpoz** | 멀티플랫폼 (Twitter/IG/TikTok/Reddit) | **P2** |
| **OmniSearch** | 통합 검색 (Tavily+Brave+Kagi+Perplexity) | **P2** |

### 2.4 메모리 & Knowledge Graph MCP

| MCP 서버 | 용도 | 우선순위 |
|---|---|---|
| **Knowledge Graph Memory** (공식) | Entity-Relation-Observation 그래프 | **P0** |
| **mcp-memory-service** | 5ms 조회, 멀티에이전트 인과 KG | **P1** |
| **Zep** | 시간축 지식 그래프 | **P2** |
| **AIM Memory Bank** | Primary DB + Named DB + Project-local | **P2** |

### 2.5 Vector DB & RAG MCP

| MCP 서버 | 용도 | 우선순위 |
|---|---|---|
| **Qdrant MCP** | 벡터 DB (self-hosted) | **P2** |
| **Pinecone MCP** | 벡터 DB (managed) | **P2** |
| **MindsDB Unified** | Pinecone+Weaviate+Qdrant 추상화 | **P3** |

---

## 3. tool_search 도입 계획

### 3.1 배경

Anthropic의 `tool_search`는 대규모 도구 집합에서 관련 도구만 선택적으로 로딩하는 메타 도구.

- **85% 컨텍스트 토큰 절감** (191,300 토큰 절약)
- **정확도 향상**: Opus 4 49% → 74%, Opus 4.5 79.5% → 88.1%
- `defer_loading: true` 설정으로 도구 정의를 lazy-load

### 3.2 GEODE에서의 구현 방향

```python
# ToolRegistry 확장
class ToolRegistry:
    def to_anthropic_tools_with_defer(
        self,
        *,
        policy: PolicyChainPort | None = None,
        mode: str = "full_pipeline",
    ) -> list[dict[str, Any]]:
        """tool_search 메타 도구 포함 Anthropic 포맷 반환."""
        all_tools = self.to_anthropic_tools(policy=policy, mode=mode)

        # 도구가 5개 이하면 defer 불필요
        if len(all_tools) <= 5:
            return all_tools

        # tool_search 메타 도구 + deferred tools
        deferred = []
        for tool in all_tools:
            tool["defer_loading"] = True
            deferred.append(tool)

        tool_search = {
            "type": "tool_search",
            "name": "tool_search",
            "description": "Search available GEODE tools by keyword",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
        }
        return [tool_search] + deferred
```

### 3.3 검색 전략

| 전략 | 방식 | 적합 케이스 |
|---|---|---|
| **Regex** (내장) | 도구명/설명 패턴 매칭 | 빠른 키워드 매칭 |
| **BM25** (내장) | TF-IDF 기반 키워드 검색 | 중간 규모 (10-50 도구) |
| **Embedding** (커스텀) | 시맨틱 유사도 검색 | 대규모 (50+ 도구) |

GEODE 현재 14개 도구 → **BM25 기본**, 30+개 초과 시 Embedding 전환 권장.

---

## 4. MCP 통합 아키텍처

### 4.1 Port/Adapter 패턴 유지 (Option A: MCP as Adapter)

```
                   Clean Architecture
┌─────────────────────────────────────────────┐
│  Port (Protocol)                            │
│    SignalEnrichmentPort                     │
│    OrganizationMemoryPort                   │
│    ToolRegistryPort                         │
├─────────────────────────────────────────────┤
│  Adapter (MCP Client)                       │
│    SteamMCPSignalAdapter                    │
│    KnowledgeGraphMemoryAdapter              │
│    MCPToolRegistryAdapter                   │
├─────────────────────────────────────────────┤
│  MCP Server (외부)                           │
│    steam-mcp, brave-search, memory-server   │
└─────────────────────────────────────────────┘
```

**노드 코드 수정 없이** 어댑터만 교체하면 MCP 서버 연결 가능.

### 4.2 통합 우선순위 로드맵

| Phase | 서버 | 효과 |
|---|---|---|
| **P0** | Brave Search + KG Memory + Steam MCP | 라이브 데이터 + 영속 메모리 |
| **P1** | Reddit MCP + Google Trends MCP | 커뮤니티 신호 강화 |
| **P2** | Qdrant/Pinecone MCP + Firecrawl | RAG + 웹 스크래핑 |
| **P3** | tool_search defer + GEODE as MCP Server | 도구 확장성 + 외부 노출 |

---

## 5. Anthropic SDK 현황

| 항목 | 값 |
|---|---|
| pyproject.toml 요구 | `>=0.80.0` |
| 설치 버전 | `0.83.0` |
| 최신 버전 | `0.84.0` (2026-02-25) |
| 주요 신기능 | MCP 변환 헬퍼, Prompt Caching 자동화 |
| 권장 | `>=0.84.0`으로 범프 + Prompt Caching 활성화 |
