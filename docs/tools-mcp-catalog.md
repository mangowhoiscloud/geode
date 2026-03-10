# GEODE Tool & MCP Server Catalog

> **Date**: 2026-03-09
> **Purpose**: GEODE 파이프라인에 활용 가능한 MCP 서버, 도구, 통합 패턴 카탈로그
> **Status**: Research / Planning

---

## 1. MCP (Model Context Protocol) 개요

MCP는 Anthropic이 2024년 11월 도입한 오픈 프로토콜로, LLM 애플리케이션과 외부 데이터 소스/도구 간의 표준화된 통신을 제공한다.

**핵심 개념**:
- **Server**: 외부 시스템(scraper, SQL, API)을 감싸서 tools/resources를 노출
- **Tool**: 모델이 호출 가능한 단일 함수 (e.g., `scrape_url`, `sql.query`)
- **Resource**: 읽기 전용 데이터 소스 (e.g., 파일, DB 스키마)
- **Prompt**: 재사용 가능한 프롬프트 템플릿

**레지스트리/디스커버리**:
- 공식 레지스트리: [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io/)
- GitHub: [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)
- 커뮤니티: [mcpservers.org](https://mcpservers.org/), [mcp.so](https://mcp.so/), [awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers)

---

## 2. Official Reference Servers (Anthropic 관리)

| Server | 언어 | 기능 | GEODE 관련도 |
|--------|------|------|-------------|
| **Memory** | TypeScript | Knowledge Graph 기반 persistent memory | **HIGH** — 3-tier 메모리와 통합 가능 |
| **Fetch** | Python/TS | 웹 콘텐츠 fetch + LLM-friendly 변환 | **HIGH** — signal 수집에 활용 |
| **Filesystem** | TypeScript | 파일 읽기/쓰기/검색 | MEDIUM — fixture/report 관리 |
| **Git** | TypeScript | Git 저장소 조작 | LOW — 개발용 |
| **Sequential Thinking** | TypeScript | 단계적 사고 프로세스 | MEDIUM — 분석 reasoning chain |
| **Everything** | TypeScript | 전체 프로토콜 기능 데모 | LOW — 참조용 |
| **Docs** | TypeScript | 문서 서빙 | LOW |

---

## 3. GEODE 파이프라인별 관련 MCP Servers

### 3.1 Data Collection & Signals (L1 Foundation)

| MCP Server | 제공자 | 기능 | 활용 시나리오 |
|------------|--------|------|-------------|
| **Steam MCP** | [algorhythmic/steam-mcp](https://github.com/algorhythmic/steam-mcp) | Steam Web API 게임 통계 | 게임 IP의 Steam 플레이어 수, 리뷰, 뉴스 |
| **Steam Reviews** | [Apify](https://apify.com/danek/steam-reviews/api/mcp) | Steam 리뷰 스크레이핑 | 커뮤니티 sentiment 분석 |
| **Firecrawl** | [firecrawl/firecrawl-mcp-server](https://github.com/firecrawl/firecrawl-mcp-server) | 웹 스크레이핑 + 검색 (76.8% success) | IP 관련 뉴스/데이터 수집 |
| **Brave Search** | [brave/brave-search-mcp-server](https://github.com/brave/brave-search-mcp-server) | 웹 검색 (2,000 free/month) | 트렌드 리서치, 뉴스 모니터링 |
| **Tavily Search** | Official | 실시간 웹 검색 + 데이터 추출 | 시장 데이터 실시간 수집 |
| **Google Trends** | [andrewlwn77/google-trends-mcp](https://github.com/andrewlwn77/google-trends-mcp) | Google Trends 데이터 | IP 관심도 트렌드 추적 |
| **Financial Datasets** | [financial-datasets/mcp-server](https://github.com/financial-datasets/mcp-server) | 주식/재무 데이터 | 관련 기업 재무 분석 |

### 3.2 Social & Community Signals

| MCP Server | 제공자 | 기능 | 활용 시나리오 |
|------------|--------|------|-------------|
| **Reddit MCP** | [arindam200/reddit](https://www.pulsemcp.com/servers/arindam200-reddit) | Reddit 검색/게시글 | IP 커뮤니티 활성도 측정 |
| **Reddit Sentiment** | Community | Reddit sentiment 분석 | 팬덤 감성 분석 |
| **X (Twitter) MCP** | [datawhisker/x](https://www.pulsemcp.com/servers/datawhisker-x) | Twitter/X 데이터 | IP 소셜 buzz 모니터링 |
| **Xpoz MCP** | [xpoz.ai](https://www.xpoz.ai/) | 멀티 플랫폼 (Twitter, IG, TikTok, Reddit) | 통합 소셜 시그널 수집 |
| **OmniSearch** | [spences10/mcp-omnisearch](https://github.com/spences10/mcp-omnisearch) | 통합 검색 (Tavily + Brave + Kagi + Perplexity) | 원스톱 리서치 |

### 3.3 Memory & Knowledge (L2 Memory)

| MCP Server | 제공자 | 기능 | 활용 시나리오 |
|------------|--------|------|-------------|
| **Knowledge Graph Memory** | [Official Reference](https://github.com/modelcontextprotocol/servers/tree/main/src/memory) | 로컬 Knowledge Graph (entity, relation, observation) | Organization tier 메모리 |
| **mcp-memory-service** | [doobidoo/mcp-memory-service](https://github.com/doobidoo/mcp-memory-service) | 멀티 에이전트 메모리 (5ms retrieval, causal KG) | Session/Project tier |
| **Zep Knowledge Graph** | [getzep.com](https://www.getzep.com/product/knowledge-graph-mcp/) | Temporal Knowledge Graph (Graphiti 기반) | IP 분석 이력 추적 |
| **AIM Memory Bank** | [shaneholloman/mcp-knowledge-graph](https://github.com/shaneholloman/mcp-knowledge-graph) | Primary DB + named DB + project-local (.aim) | GEODE 3-tier와 구조 유사 |

### 3.4 Vector DB & RAG

| MCP Server | 제공자 | 기능 | 활용 시나리오 |
|------------|--------|------|-------------|
| **Qdrant MCP** | [Qdrant](https://qdrant.tech/blog/webinar-vibe-coding-rag/) | 벡터 DB + semantic search | IP 유사도 검색, 과거 분석 RAG |
| **Pinecone MCP** | [sirmews/pinecone](https://www.pulsemcp.com/servers/sirmews-pinecone) | Pinecone 벡터 DB | 대규모 IP 임베딩 저장소 |
| **RAG Docs** | [qpd-v/ragdocs](https://www.pulsemcp.com/servers/qpd-v-ragdocs) | RAG 기반 문서 검색 | 분석 보고서 검색 |
| **GraphRAG** | [rileylemm/graphrag](https://www.pulsemcp.com/servers/rileylemm-graphrag) | 그래프 기반 RAG | IP 관계 네트워크 분석 |
| **MindsDB Unified** | [mindsdb.com](https://mindsdb.com/unified-model-context-protocol-mcp-server-for-vector-stores) | Pinecone + Weaviate + Qdrant 통합 | 벡터 스토어 추상화 |

### 3.5 Database & Infrastructure

| MCP Server | 제공자 | 기능 | 활용 시나리오 |
|------------|--------|------|-------------|
| **PostgreSQL** | Official/Community | SQL 쿼리 실행 | 분석 결과 영구 저장 |
| **Playwright** | Community | 브라우저 자동화 | 동적 웹사이트 데이터 수집 |
| **Puppeteer** | Official | 브라우저 자동화 | Playwright 대안 |

### 3.6 Company-Maintained Official Servers

| MCP Server | 제공자 | 기능 | GEODE 관련도 |
|------------|--------|------|-------------|
| **GitHub** | GitHub | 이슈, PR, 코드 검색 | LOW — 개발 워크플로우 |
| **Slack** | Slack | 채널/메시지 | LOW — 알림 |
| **Google Drive** | Google | 문서 관리 | MEDIUM — 보고서 공유 |
| **Microsoft MCP** | [microsoft/mcp](https://github.com/microsoft/mcp) | Azure, M365, etc. | LOW |

---

## 4. Tool Search (Dynamic Tool Discovery)

### 4.1 개념

Anthropic의 Tool Search Tool은 수천 개의 도구를 context window에 모두 로드하지 않고, 필요할 때 동적으로 검색/로드하는 패턴이다.

**성능 수치** (Anthropic 공식):
- Context 절약: 191,300 tokens (85% 감소)
- Opus 4 정확도: 49% -> 74% (+25pp)
- Opus 4.5 정확도: 79.5% -> 88.1% (+8.6pp)

### 4.2 defer_loading 패턴

```python
# API 호출 시 tool 정의
tools = [
    # 항상 로드되는 핵심 도구
    {
        "name": "analyze_ip",
        "description": "Run full IP analysis pipeline",
        "input_schema": {...},
        # defer_loading 없음 = 항상 컨텍스트에 포함
    },
    # 필요 시에만 로드되는 도구
    {
        "name": "steam_player_count",
        "description": "Get current Steam player count for a game",
        "input_schema": {...},
        "defer_loading": True,  # 초기에는 숨겨짐
    },
    {
        "name": "reddit_sentiment",
        "description": "Analyze Reddit sentiment for an IP",
        "input_schema": {...},
        "defer_loading": True,
    },
]
```

### 4.3 검색 전략

| 전략 | 구현 | 장점 | 단점 |
|------|------|------|------|
| **Regex** | Anthropic 내장 | 설정 불필요 | 의미 검색 불가 |
| **BM25 (Keyword)** | Anthropic 내장 | 키워드 매칭 강력 | 동의어 미지원 |
| **Embedding** | 커스텀 구현 필요 | Semantic search 가능 | 추가 인프라 필요 |

### 4.4 GEODE 적용 설계

```
GEODE Tool Categories:
├── Always Loaded (defer_loading: false)
│   ├── analyze_ip          — 핵심 분석 도구
│   ├── memory_recall       — 메모리 조회
│   └── search_tools        — 도구 검색 (meta-tool)
│
├── Deferred: Signal Collection
│   ├── steam_data          — Steam API 조회
│   ├── reddit_search       — Reddit 검색
│   ├── twitter_search      — Twitter/X 검색
│   ├── google_trends       — 트렌드 데이터
│   └── web_scrape          — 범용 웹 스크레이핑
│
├── Deferred: Analysis Tools
│   ├── sentiment_analysis  — 감성 분석
│   ├── trend_analysis      — 트렌드 분석
│   ├── market_comparison   — 시장 비교
│   └── rights_assessment   — IP 권리 평가
│
└── Deferred: Output Tools
    ├── generate_report     — 보고서 생성
    ├── export_csv          — CSV 내보내기
    └── visualization       — 차트/그래프
```

---

## 5. GEODE 기존 Tool 시스템과의 통합

### 5.1 현재 GEODE Tool 아키텍처

```
geode/tools/
├── base.py             # Tool 기본 클래스
├── registry.py         # ToolRegistry + PolicyChain
├── policy.py           # 모드별 접근 제어
├── memory_tools.py     # 메모리 관련 도구
├── signal_tools.py     # 시그널 수집 도구
├── analysis.py         # 분석 도구
├── data_tools.py       # 데이터 도구
└── output_tools.py     # 출력 도구

geode/infrastructure/ports/
├── tool_port.py        # ToolRegistryPort, PolicyChainPort
├── signal_port.py      # SignalPort
├── memory_port.py      # MemoryPort
└── llm_port.py         # LLMPort
```

### 5.2 MCP 통합 방안

**Option A: MCP 서버를 Adapter로 래핑** (권장)
```
Port (Protocol) → Adapter (MCP Client) → MCP Server → External API
```

```python
# geode/infrastructure/adapters/signal_mcp_adapter.py
class MCPSignalAdapter:
    """SignalPort 구현체 — MCP 서버를 통해 시그널 수집."""

    async def fetch_signals(self, ip_name: str) -> SignalData:
        # MCP 클라이언트로 steam-mcp, reddit-mcp 등 호출
        steam = await self.mcp_client.call_tool("steam_data", {"game": ip_name})
        reddit = await self.mcp_client.call_tool("reddit_search", {"query": ip_name})
        return SignalData(steam=steam, reddit=reddit)
```

**Option B: GEODE를 MCP 서버로 노출**
```
External Client → MCP Protocol → GEODE MCP Server → Pipeline
```

```python
# geode/mcp_server.py
@mcp.tool()
async def analyze_ip(ip_name: str, mode: str = "full") -> dict:
    """Run GEODE IP analysis pipeline."""
    runtime = GeodeRuntime()
    return await runtime.analyze(ip_name, mode=mode)
```

**Option C: 하이브리드 (A + B)** — GEODE가 MCP 클라이언트이자 서버

### 5.3 구현 우선순위

| 단계 | 통합 대상 | 이유 | 난이도 |
|------|----------|------|--------|
| P0 | Brave Search / Tavily | 시그널 수집의 핵심 | LOW |
| P0 | Knowledge Graph Memory | 3-tier 메모리 강화 | MEDIUM |
| P1 | Steam MCP | 게임 IP 직접 데이터 | LOW |
| P1 | Reddit MCP | 커뮤니티 시그널 | LOW |
| P1 | Google Trends MCP | 트렌드 정량화 | LOW |
| P2 | Qdrant/Pinecone MCP | IP 유사도 RAG | MEDIUM |
| P2 | Firecrawl | 고급 웹 스크레이핑 | MEDIUM |
| P3 | Tool Search (defer_loading) | 도구 확장 시 필요 | HIGH |
| P3 | GEODE as MCP Server | 외부 노출 | HIGH |

---

## 6. tool_search 구현 패턴

### 6.1 Anthropic 내장 방식 (API level)

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-opus-4-5-20250514",
    max_tokens=1024,
    tools=[
        # tool_search는 자동으로 추가됨
        {"name": "core_tool", "description": "...", "input_schema": {...}},
        {"name": "signal_a", "description": "...", "input_schema": {...}, "defer_loading": True},
        {"name": "signal_b", "description": "...", "input_schema": {...}, "defer_loading": True},
    ],
    messages=[{"role": "user", "content": "Analyze Cowboy Bebop IP"}],
)
```

### 6.2 커스텀 Embedding 기반 구현

```python
# Anthropic cookbook 패턴
from numpy import dot
from numpy.linalg import norm

class ToolSearchEngine:
    """Embedding 기반 tool discovery."""

    def __init__(self, tools: list[Tool], embed_model: str = "text-embedding-3-small"):
        self.tools = tools
        self.embeddings = self._build_index(tools, embed_model)

    def search(self, query: str, top_k: int = 5) -> list[Tool]:
        query_emb = self._embed(query)
        scores = [
            (tool, dot(query_emb, emb) / (norm(query_emb) * norm(emb)))
            for tool, emb in zip(self.tools, self.embeddings)
        ]
        return [t for t, _ in sorted(scores, key=lambda x: x[1], reverse=True)[:top_k]]
```

### 6.3 GEODE ToolRegistry 확장

```python
# geode/tools/registry.py 확장안
class ToolRegistry:
    def search(self, query: str, *, strategy: str = "keyword") -> list[Tool]:
        """Dynamic tool discovery within GEODE registry."""
        if strategy == "keyword":
            return self._bm25_search(query)
        elif strategy == "embedding":
            return self._embedding_search(query)
        else:
            return self._regex_search(query)

    def to_anthropic_tools_with_defer(
        self, *, always_loaded: set[str] | None = None
    ) -> list[dict[str, Any]]:
        """Export tools with defer_loading for non-essential tools."""
        always = always_loaded or {"analyze_ip", "memory_recall"}
        result = []
        for name, tool in self._tools.items():
            spec = tool.to_anthropic_format()
            if name not in always:
                spec["defer_loading"] = True
            result.append(spec)
        return result
```

---

## 7. 권장 사항

### 7.1 단기 (현재 Sprint)

1. **Brave Search MCP 연동** — `signal_tools.py`의 fixture 데이터를 실제 웹 검색으로 교체
2. **Knowledge Graph Memory** — Organization tier를 KG 기반으로 영속화
3. **Steam MCP** — 게임 IP의 실시간 플레이어/리뷰 데이터 수집

### 7.2 중기 (다음 Sprint)

4. **tool_search 패턴 적용** — 도구가 15개 이상이면 defer_loading 도입
5. **Qdrant MCP** — 과거 분석 결과 벡터 저장 + 유사 IP RAG
6. **Reddit + Twitter MCP** — 커뮤니티/소셜 시그널 실시간 수집

### 7.3 장기

7. **GEODE as MCP Server** — 외부 에이전트가 GEODE 분석 파이프라인 호출 가능
8. **OmniSearch 통합** — Tavily + Brave + Kagi를 단일 인터페이스로
9. **Temporal KG (Zep)** — IP 분석 이력의 시간축 변화 추적

### 7.4 아키텍처 원칙

- **Port/Adapter 유지**: MCP 서버는 항상 Adapter 뒤에 위치 (Port는 변경 없음)
- **Fixture-first 개발**: MCP 서버 연동 전에 fixture로 인터페이스 확정
- **PolicyChain 통합**: MCP 도구도 `dry_run` 모드에서는 차단
- **비용 인식**: 유료 API(Tavily, Firecrawl)는 호출 횟수 추적 필수

---

## References

- [Model Context Protocol Official](https://modelcontextprotocol.io/)
- [MCP Servers Repository](https://github.com/modelcontextprotocol/servers)
- [Official MCP Registry](https://registry.modelcontextprotocol.io/)
- [Anthropic Tool Search Tool Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [Tool Search with Embeddings Cookbook](https://platform.claude.com/cookbook/tool-use-tool-search-with-embeddings)
- [Anthropic Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Awesome MCP Servers](https://github.com/punkpeye/awesome-mcp-servers)
- [mcpservers.org](https://mcpservers.org/)
- [MCP Browser Benchmark 2026](https://aimultiple.com/browser-mcp)
