# GEODE v0.7.0 — Undervalued IP Discovery Agent

LangGraph 기반 게임화 IP 도메인 자율 에이전트입니다. 주요 기능은 아래와 같습니다. 
- 미디어 IP(애니메이션, 만화 등)의 게임화 잠재력을 6-Layer 아키텍처로 분석하고, PSM 14-Axis 루브릭으로 평가 및 리포트를 생성합니다.
- 분석 루프 외에도 Runtime Orchestration, Tool-Registry/Tool-Use, Bash, Hook-System으로 Agentic Loop(Gather->Action->Verify)를 구성, 자율 행동이 가능합니다.
- 사용자의 의도와 맥락을 파악하기 위한 메모리 시스템, Multi-turn, Multi-intent도 내장되어 있습니다.
- Observability는 LangSmith, Evaluation은 CUSUM Drift 감지를 지원합니다.
- 다음 업데이트는 Swiss Cheese Model based Eval Pipeline 구축으로 예정되어 있습니다.

## Features

| Feature | Description |
|---------|-------------|
| **6-Layer Pipeline** | Router → Signals → Analysts → Evaluators → Scoring → Verification → Gather/Synthesizer (8 nodes) |
| **Agentic Loop** | `while(tool_use)` 멀티 라운드 실행 (max 10 rounds), multi-intent 자동 chaining, offline mode |
| **Multi-turn Context** | 슬라이딩 윈도우 대화 기록 (max 20 turns), 대명사 해석 + follow-up |
| **HITL Bash** | 셸 명령 실행 + 위험 패턴 차단 (9종) + 사용자 승인 게이트 |
| **Sub-Agent** | 병렬 태스크 위임 (`IsolatedRunner`, MAX_CONCURRENT=5), TaskGraph DAG, CoalescingQueue 중복 제거 |
| **14-Axis Rubric** | PSM(Prospect Scoring Model) 기반 정량 평가 |
| **Cross-LLM Ensemble** | Claude Opus 4.6 + GPT-5.4 듀얼 평가, `cross` / `primary_only` 모드 |
| **Prompt Caching** | Anthropic `cache_control` 적용, 40-60% 비용 절감 |
| **19 Tool Definitions** | `definitions.json` 기반 + ToolRegistry 런타임 확장 + PolicyChain 접근 제어 |
| **MCP Adapters** | Steam, Brave Search, KG Memory 외부 데이터 소스 연결 |
| **MCP Server** | FastMCP 기반 6 tools + 2 resources (다른 에이전트에서 GEODE 호출) |
| **Prompt Templates** | `.md` 템플릿 8종 + YAML/JSON 설정 분리 (content/code separation) |
| **Batch Analysis** | 멀티 IP 동시 분석, Rich 테이블 렌더링 |
| **Streaming Output** | `--stream` 플래그로 실시간 진행 표시 |
| **자연어 입력** | 한국어/영어 자유 입력 (NL Router intent classification) |
| **Report Generation** | HTML/JSON/Markdown 다중 포맷, 외부 템플릿 |
| **Graceful Degradation** | API 키 없으면 자동 dry-run, 있으면 LLM 분석 |
| **Project Memory** | `.claude/MEMORY.md` + `rules/`로 분석 맥락 유지 |
| **Checkpoint** | SqliteSaver 기반 파이프라인 상태 영속화 |
| **Feedback Loop** | Confidence < 0.7이면 자동 재분석 (최대 3회) |
| **LangSmith Observability** | 토큰 추적 + 비용 계산, RunTree 메트릭, 조건부 tracing |
| **Dynamic Tools** | ToolRegistry 기반 런타임 tool 추가, plugin activate → 즉시 반영 |
| **Pipeline Flexibility** | Analyst 타입 YAML 동적 로드, `interrupt_before` 사용자 개입 |
| **Pre-commit Hooks** | ruff lint/format + mypy + bandit + standard hooks |
| **1950 Tests** | 116 modules, coverage ≥ 75%, pytest + ruff + mypy strict + bandit 전체 통과 |

## Architecture

### 6-Layer Architecture

```mermaid
graph TB
    subgraph L0["L0 — CLI & Agentic Interface"]
        CLI["CLI (Typer)"]
        NLR["NL Router"]
        AL["AgenticLoop<br/>while(tool_use)"]
        Search["IP Search Engine"]
        Batch["Batch Analysis"]
    end

    subgraph L1["L1 — Infrastructure (Port/Adapter)"]
        direction LR
        Ports["Ports (Protocol)"]
        Claude["ClaudeAdapter"]
        OpenAI["OpenAIAdapter"]
        MCP["MCP Adapters"]
    end

    subgraph L2["L2 — Memory (3-Tier)"]
        Org["Organization<br/>(fixtures, immutable)"]
        Project["Project Memory<br/>(.claude/MEMORY.md)"]
        Session["Session Store<br/>(in-memory TTL)"]
        Checkpoint["SqliteSaver"]
    end

    subgraph L3["L3 — LangGraph Pipeline"]
        Graph["StateGraph"]
        Nodes["Pipeline Nodes (8)"]
        State["GeodeState"]
    end

    subgraph L4["L4 — Orchestration"]
        Hooks["HookSystem (23)"]
        Tasks["TaskGraph (DAG)"]
        Plan["PlanMode"]
        Coal["CoalescingQueue"]
        Lanes["Lane Queue"]
        RunLog["Run Log"]
    end

    subgraph L5["L5 — Extensibility"]
        Tools["ToolRegistry (19)"]
        Policy["PolicyChain"]
        Reports["Report Generator"]
        Templates["Prompt Skills"]
    end

    L0 --> L3
    L3 --> L1
    L3 --> L2
    L3 --> L4
    L3 --> L5
    L0 -.->|"offline"| L5

    style L0 fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style L1 fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style L2 fill:#1e293b,stroke:#8b5cf6,color:#e2e8f0
    style L3 fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style L4 fill:#1e293b,stroke:#ef4444,color:#e2e8f0
    style L5 fill:#1e293b,stroke:#06b6d4,color:#e2e8f0
```

### Pipeline Flow

```mermaid
graph LR
    START((START)) --> Router
    Router -->|"signals"| Signals
    Router -->|"evaluators"| Eval
    Router -->|"scoring"| Scoring
    Signals --> A1["Analyst<br/>game_mechanics"]
    Signals --> A2["Analyst<br/>player_experience"]
    Signals --> A3["Analyst<br/>growth_potential"]
    Signals --> A4["Analyst<br/>discovery"]
    A1 --> Eval["Evaluator ×3<br/>(Cross-LLM)"]
    A2 --> Eval
    A3 --> Eval
    A4 --> Eval
    Eval --> Scoring["Scoring<br/>PSM 14-Axis"]
    Scoring --> Verify["Verification<br/>G1-G4 + BiasBuster"]
    Verify -->|"confidence ≥ 0.7"| Synth["Synthesizer"]
    Verify -->|"confidence < 0.7"| Gather["gather"]
    Gather -->|"retry (max 5)"| Signals
    Synth --> END((END))

    style START fill:#10b981,stroke:#10b981,color:#fff
    style END fill:#ef4444,stroke:#ef4444,color:#fff
    style Gather fill:#8b5cf6,stroke:#8b5cf6,color:#fff
    style Eval fill:#3b82f6,stroke:#3b82f6,color:#fff
    style Scoring fill:#f59e0b,stroke:#f59e0b,color:#fff
    style Verify fill:#8b5cf6,stroke:#8b5cf6,color:#fff
    style Synth fill:#06b6d4,stroke:#06b6d4,color:#fff
```

### Agentic Loop

```mermaid
graph TB
    Input["User Input<br/>(한국어/영어)"] --> Mode{offline?}
    Mode -->|Yes| Regex["Regex Pattern<br/>Matching (10 rules)"]
    Mode -->|No| LLM["Claude Opus 4.6<br/>Tool Use API"]
    Regex --> Exec
    LLM --> Decision{stop_reason}
    Decision -->|tool_use| Exec["ToolExecutor<br/>(17 handlers)"]
    Exec --> Results["tool_result"]
    Results --> LLM
    Decision -->|end_turn| Output["AgenticResult<br/>(text + tool_calls)"]
    Decision -->|max_rounds| Output

    LLM -.->|"track_token_usage()"| LS["LangSmith<br/>RunTree"]
    LLM -.->|"rate limit"| Retry["Retry ×3<br/>10s/20s/40s"]
    Retry -.-> LLM

    style Input fill:#10b981,stroke:#10b981,color:#fff
    style Output fill:#3b82f6,stroke:#3b82f6,color:#fff
    style LLM fill:#f59e0b,stroke:#f59e0b,color:#fff
    style Exec fill:#8b5cf6,stroke:#8b5cf6,color:#fff
    style LS fill:#06b6d4,stroke:#06b6d4,color:#fff
```

> **Note:** 위 다이어그램의 Retry 10s/20s/40s는 AgenticLoop 레벨의 rate limit 재시도입니다. 파이프라인 내부 LLM 호출(`core/llm/client.py`)은 별도의 1s/2s/4s exponential backoff를 사용합니다.

### Cross-LLM Ensemble

```mermaid
graph TB
    subgraph Primary["Claude Opus 4.6 (primary_analysts)"]
        GM["game_mechanics"]
        GP["growth_potential"]
    end

    subgraph Secondary["GPT-5.4 (secondary_analysts)"]
        PE["player_experience"]
        DI["discovery"]
    end

    GM --> Merge["Score Merge<br/>agreement ≥ 0.67"]
    GP --> Merge
    PE --> Merge
    DI --> Merge
    Merge --> Final["Reliability<br/>Krippendorff's α"]

    style Primary fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style Secondary fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style Merge fill:#3b82f6,stroke:#3b82f6,color:#fff
```

> `ensemble_mode=cross` 시 `primary_analysts`/`secondary_analysts` 설정으로 모델 분배 결정. `primary_only` 모드에서는 모든 analyst가 Claude 사용.

### Sub-Agent Orchestration

```mermaid
graph LR
    Main["AgenticLoop"] --> SAM["SubAgentManager"]
    SAM --> TG["TaskGraph<br/>(DAG)"]
    SAM --> CQ["CoalescingQueue<br/>(dedup)"]
    SAM --> IR["IsolatedRunner<br/>(MAX_CONCURRENT=5)"]

    IR --> W1["Worker 1"]
    IR --> W2["Worker 2"]
    IR --> W3["Worker N"]

    SAM -.->|NODE_ENTER| HS["HookSystem"]
    W1 -.->|NODE_EXIT| HS
    W2 -.->|NODE_ERROR| HS

    style Main fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style SAM fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style IR fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style HS fill:#1e293b,stroke:#ef4444,color:#e2e8f0
```

### MCP & Tool Architecture

```mermaid
graph TB
    subgraph GEODE["GEODE Pipeline"]
        Registry["ToolRegistry<br/>19 base tools"]
        Policy["PolicyChain<br/>+ NodeScopePolicy"]
        TS["tool_search<br/>(meta-tool)"]
    end

    subgraph MCPAdapters["MCP Adapters (Client)"]
        Steam["Steam MCP"]
        Brave["Brave Search"]
        KGMem["KG Memory"]
        CompSig["CompositeSignal"]
        FixSig["FixtureSignal"]
    end

    subgraph MCPServer["MCP Server (FastMCP)"]
        T1["analyze_ip"]
        T2["quick_score"]
        T3["get_ip_signals"]
        T4["list_fixtures"]
        T5["query_memory"]
        T6["get_health"]
    end

    Registry --> Policy
    TS --> Registry
    GEODE --> MCPAdapters
    MCPServer --> GEODE

    style GEODE fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style MCPAdapters fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style MCPServer fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
```

### LangSmith Observability

```mermaid
graph LR
    LLM["LLM Call"] --> Track["track_token_usage()"]
    Track --> Cost["calculate_cost()<br/>MODEL_PRICING"]
    Track --> RT["RunTree.extra.metrics"]
    Cost --> Acc["LLMUsageAccumulator<br/>(context-local)"]

    Acc --> Summary["Session Summary<br/>total_tokens + cost_usd"]

    style LLM fill:#f59e0b,stroke:#f59e0b,color:#fff
    style Track fill:#3b82f6,stroke:#3b82f6,color:#fff
    style Acc fill:#8b5cf6,stroke:#8b5cf6,color:#fff
    style RT fill:#06b6d4,stroke:#06b6d4,color:#fff
```

### 14-Axis Rubric (PSM Engine)

```mermaid
graph TB
    subgraph Evaluators["3 Evaluators"]
        QJ["quality_judge<br/>(8 axes: A,B,C,B1,C1,C2,M,N)"]
        HV["hidden_value<br/>(3 axes: D,E,F)"]
        CM["community_momentum<br/>(3 axes: J,K,L)"]
    end

    subgraph Scoring["PSM Scoring"]
        W["6-Weighted Composite"]
        Conf["Confidence Multiplier"]
        Tier["Tier Classification<br/>S / A / B / C"]
    end

    QJ --> W
    HV --> W
    CM --> W
    W --> Conf
    Conf --> Tier

    style Evaluators fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style Scoring fill:#1e293b,stroke:#10b981,color:#e2e8f0
```

> 각 축은 1-5점 한국어 루브릭 앵커 사용. `evaluator_axes.yaml`에서 SSOT 관리. Prospect IP용 9-axis 확장 루브릭도 지원.

### Multi-turn Context

```mermaid
graph LR
    U1["User Turn 1"] --> A1["Assistant 1"]
    A1 --> U2["User Turn 2<br/>(follow-up)"]
    U2 --> A2["Assistant 2"]
    A2 --> U3["..."]
    U3 --> Window["Sliding Window<br/>max 20 turns"]
    Window --> Trim["Oldest pair trimmed"]

    style Window fill:#3b82f6,stroke:#3b82f6,color:#fff
```

> `ConversationContext` — 슬라이딩 윈도우 (max 20 turns). 대명사 해석("그거 다시 분석해")과 follow-up 쿼리 지원. 각 턴은 user/assistant/tool_result 메시지 포함.

### HITL Bash

```mermaid
graph LR
    Cmd["Shell Command"] --> Block{Blocked<br/>Pattern?}
    Block -->|"9 patterns<br/>(rm -rf /, sudo, fork bomb...)"| Deny["BLOCKED"]
    Block -->|Safe| Approve{User<br/>Approval?}
    Approve -->|Yes| Exec["Execute<br/>(timeout 30s)"]
    Approve -->|No| Skip["DENIED"]
    Exec --> Result["stdout/stderr<br/>(max 10K/5K chars)"]

    style Deny fill:#ef4444,stroke:#ef4444,color:#fff
    style Exec fill:#10b981,stroke:#10b981,color:#fff
    style Skip fill:#f59e0b,stroke:#f59e0b,color:#fff
```

> `BashTool` — 9개 위험 패턴 사전 차단 (`rm -rf /`, `sudo`, `curl|sh`, `mkfs`, `dd`, `chmod 777 /`, fork bomb 등). 나머지 명령은 사용자 승인 후 실행.

### Feedback Loop

```mermaid
graph LR
    V["Verification"] --> Gate{confidence<br/>≥ 0.7?}
    Gate -->|Yes| S["Synthesizer → END"]
    Gate -->|No| Check{iteration<br/>< max?}
    Check -->|Yes| G["gather → signals<br/>(loopback)"]
    Check -->|No| S2["Synthesizer<br/>(force proceed)"]

    style Gate fill:#f59e0b,stroke:#f59e0b,color:#fff
    style G fill:#8b5cf6,stroke:#8b5cf6,color:#fff
```

> Confidence < 0.7이면 `gather` 노드가 상태를 수집하고 `signals`로 loopback. `GEODE_MAX_ITERATIONS` (기본 5)회까지 재시도 후 강제 진행.

### Prompt Caching

> Anthropic `cache_control: {"type": "ephemeral"}` 적용. 시스템 프롬프트와 루브릭 데이터를 캐시하여 반복 호출 시 40-60% 비용 절감. `ClaudeAdapter`에서 자동 적용.

### Checkpoint (State Persistence)

> `SqliteSaver` (LangGraph 내장)로 파이프라인 상태 영속화. 각 노드 실행 후 자동 체크포인트. 장애 시 마지막 체크포인트부터 재개. `GEODE_CHECKPOINT_DB` 환경변수로 DB 경로 지정.

### Dynamic Tools (ToolRegistry)

```mermaid
graph LR
    Plugin["Plugin"] -->|"activate()"| Reg["ToolRegistry"]
    Reg -->|"register(tool)"| Tools["19 base + N extra"]
    Tools --> AL["AgenticLoop<br/>get_agentic_tools()"]
    Reg --> Policy["PolicyChain<br/>+ NodeScopePolicy"]

    style Reg fill:#3b82f6,stroke:#3b82f6,color:#fff
    style Policy fill:#f59e0b,stroke:#f59e0b,color:#fff
```

> `definitions.json` 19개 기본 도구 + `ToolRegistry.register()` 런타임 확장. `get_agentic_tools(registry)` 호출 시 base + plugin 도구 병합. `PolicyChain`으로 노드별 도구 접근 제어.

### Pipeline Flexibility (C2-C5)

| 항목 | 방식 |
|------|------|
| **Analyst 타입** | `evaluator_axes.yaml` → `ANALYST_TYPES = list(ANALYST_SPECIFIC.keys())` — YAML에 키 추가만으로 analyst 확장 |
| **중간 개입** | `GEODE_INTERRUPT_NODES=verification,scoring` → 해당 노드 전에 파이프라인 일시 중단 |
| **동적 Tool** | `ToolRegistry` + `get_agentic_tools()` — 플러그인 런타임 등록 |
| **오프라인 모드** | `AgenticLoop(offline_mode=True)` → regex 기반 10-패턴 라우팅, LLM 불필요 |

## Installation

```bash
uv sync
```

## Quick Start

```bash
# 인터랙티브 모드 (권장)
uv run geode

# IP 분석 (API 키 있으면 LLM 호출, 없으면 자동 dry-run)
uv run geode analyze "Berserk"

# 명시적 dry-run (API 키 있어도 LLM 호출 안 함)
uv run geode analyze "Berserk" --dry-run

# Streaming 분석
uv run geode analyze "Berserk" --stream

# 배치 분석 (--dry-run 권장, batch는 기본 --live 모드)
uv run geode batch --top 5 --dry-run

# 리포트 생성
uv run geode report "Berserk" --format html --output berserk.html

# MCP 서버 실행
uv run python -m core.mcp_server
```

## Setup

```bash
# 1. 환경 변수 설정
cp .env.example .env

# 2. .env 편집 — API 키 입력
ANTHROPIC_API_KEY=sk-ant-...

# 3. Full 분석 실행
uv run geode analyze "Cowboy Bebop"
```

API 키 없이 시작하면 자동으로 dry-run 모드로 전환됩니다 (API 키 설정 시 LLM 분석 자동 활성화):

```
  ✓ Dry-Run Analysis
  ✓ IP Search
  ✗ LLM Analysis (ANTHROPIC_API_KEY not set)

  API key not configured — dry-run mode only
```

## Usage

### Interactive Mode

```bash
uv run geode
```

**슬래시 커맨드:**

| Command | Alias | Description |
|---------|-------|-------------|
| `/analyze <IP>` | `/a` | IP 분석 (API 키 유무에 따라 자동 모드 결정) |
| `/run <IP>` | `/r` | IP 분석 (동일) |
| `/search <query>` | `/s` | IP 검색 |
| `/report <IP> [fmt]` | `/rpt` | 리포트 생성 (md/html/json) |
| `/list` | | IP 목록 |
| `/generate [count]` | `/gen` | 합성 데모 데이터 생성 |
| `/model` | | LLM 모델 선택 |
| `/key [value]` | | API 키 설정 |
| `/auth` | | 인증 프로필 관리 |
| `/batch [--top N]` | `/b` | 배치 분석 |
| `/status` | | 시스템 상태 (모델, API 키, 메모리) |
| `/compare <A> <B>` | | 두 IP 비교 분석 (Interactive) |
| `/schedule <cron>` | `/sched` | 배치 스케줄 설정 |
| `/trigger <event>` | | 이벤트 트리거 (drift scan 등) |
| `/verbose` | | 상세 출력 토글 |
| `/help` | | 도움말 |
| `/quit` | `/q` | 종료 |

**자연어 입력:**

```
> Berserk 분석해           → LLM 분석 (API 키 있을 때) / dry-run (없을 때)
> 소울라이크 찾아줘         → 장르 검색
> Berserk vs Cowboy Bebop  → 비교 분석
> Berserk 리포트 생성해     → 리포트 생성
> 뭐가 있어?               → IP 목록
> 시스템 상태              → 상태 확인
> API 키 설정해            → API 키 설정
> 스케줄 걸어줘            → 배치 스케줄
```

### CLI Mode

```bash
geode analyze "Berserk"                          # LLM 분석 (API 키 있을 때)
geode analyze "Berserk" --dry-run                 # 명시적 dry-run
geode analyze "Berserk" --stream                  # streaming output
geode analyze "Berserk" --verbose                 # 상세 출력
geode analyze "Cowboy Bebop" --skip-verification  # 검증 생략
geode batch --top 5                               # 상위 5개 배치 분석
geode batch --genre "Dark Fantasy"                # 장르 필터 배치
geode report "Berserk"                            # Markdown summary
geode report "Berserk" -f html -o berserk.html    # HTML 파일 저장
geode search "사이버펑크"                          # 검색
geode list                                        # 목록
```

### MCP Server

GEODE를 MCP 서버로 실행하여 다른 에이전트에서 호출할 수 있습니다:

```bash
uv run python -m core.mcp_server
```

**제공 도구:** `analyze_ip`, `quick_score`, `get_ip_signals`, `list_fixtures`, `query_memory`, `get_health`

**리소스:** `geode://fixtures`, `geode://soul`

## Available IPs

**Core Fixtures** (hand-crafted, golden set):

| IP | Tier | Score | Genre |
|----|------|-------|-------|
| Berserk | S | 82.2 | Dark Fantasy |
| Cowboy Bebop | A | 69.4 | SF Noir |
| Ghost in the Shell | B | 54.0 | Cyberpunk |

**Steam Fixtures**: 201개 추가 게임 데이터 (`core/fixtures/steam/`), `/generate` 명령으로 합성 데이터 생성 가능.

## Project Structure

```
core/
├── cli/                        # CLI + NL Router + Agentic Loop
│   ├── __init__.py             # Typer app, REPL, pipeline execution
│   ├── agentic_loop.py         # while(tool_use) multi-round execution
│   ├── bash_tool.py            # Shell execution + HITL safety gate
│   ├── batch.py                # Batch analysis (ThreadPoolExecutor)
│   ├── commands.py             # Slash command dispatch (17 commands)
│   ├── conversation.py         # Multi-turn sliding-window context
│   ├── nl_router.py            # Natural language intent classification
│   ├── search.py               # IP search engine (synonym expansion)
│   ├── startup.py              # Readiness check, Graceful Degradation
│   ├── sub_agent.py            # Parallel task delegation (SubAgentManager)
│   └── tool_executor.py        # Tool dispatch + HITL approval gate
├── auth/                       # Auth profile management + rotation
├── automation/                 # Feedback loop, drift detection, triggers
├── config/                     # Externalized domain config (YAML)
│   ├── evaluator_axes.yaml     # 14-Axis rubric definitions + anchors
│   └── cause_actions.yaml      # Cause→Action mappings
├── config.py                   # Settings (pydantic-settings, 30+ vars)
├── data/                       # Synthetic data generation
├── extensibility/              # Report generation + templates
│   └── templates/              # HTML/Markdown report templates
├── fixtures/                   # Fixture data (3 core IPs + 201 Steam)
├── graph.py                    # LangGraph StateGraph definition
├── infrastructure/
│   ├── ports/                  # LLMClientPort, SignalEnrichmentPort, etc.
│   └── adapters/
│       ├── llm/                # ClaudeAdapter, OpenAIAdapter
│       └── mcp/                # Steam, Brave, KGMemory MCP adapters
├── llm/                        # LLM client (prompt caching, streaming)
│   ├── client.py               # Anthropic wrapper + token tracking + cost
│   └── prompts/                # Prompt templates (.md) + axes config
│       ├── analyst.md          # Analyst system prompt template
│       ├── evaluator.md        # Evaluator prompt template
│       ├── synthesizer.md      # Synthesizer prompt template
│       ├── cross_llm.md        # Cross-LLM verification prompts
│       ├── axes.py             # Axis definitions (loads from YAML)
│       └── ...                 # biasbuster, commentary, router, tool_augmented
├── mcp_server.py               # FastMCP server (6 tools, 2 resources)
├── memory/                     # 3-Tier memory system
├── nodes/                      # Pipeline nodes (8: router, signals, analyst, evaluator, scoring, verification, gather, synthesizer)
├── orchestration/
│   ├── hooks.py                # HookSystem (23 events)
│   ├── hook_discovery.py       # Plugin-based hook loading
│   ├── isolated_execution.py   # Concurrent runner (semaphore)
│   ├── task_system.py          # DAG-based task graph
│   ├── coalescing.py           # Duplicate request coalescing
│   ├── plan_mode.py            # DRAFT → APPROVED → EXECUTING workflow
│   ├── lane_queue.py           # Concurrency control lanes
│   ├── run_log.py              # Structured execution logging
│   └── ...                     # planner, bootstrap, stuck_detection, etc.
├── runtime.py                  # GeodeRuntime (production wiring)
├── state.py                    # GeodeState (TypedDict + Pydantic models)
├── tools/                      # Tool Protocol + Registry + Policy
│   ├── registry.py             # ToolRegistry (19 tools + runtime extensions)
│   ├── definitions.json        # Centralized tool definitions (19 tools)
│   ├── tool_schemas.json       # Parameter schemas for signal/analysis tools
│   ├── policy.py               # PolicyChain + NodeScopePolicy
│   └── ...                     # analysis, signal_tools, data_tools, etc.
├── ui/                         # Rich console + panels + streaming
└── verification/               # Guardrails + BiasBuster + Rights Risk
```

## Testing

```bash
# 전체 테스트
uv run pytest

# 상세 출력
uv run pytest -v

# 특정 모듈
uv run pytest tests/test_graph.py
uv run pytest tests/test_batch.py
uv run pytest tests/test_mcp_server.py

# Live E2E (실제 LLM 호출)
uv run pytest tests/test_e2e_live_llm.py -v -m live

# 17-Tool Audit (실제 LLM 라우팅 검증)
uv run python tests/_live_audit_runner.py info

# 품질 검사
uv run ruff check core/ tests/
uv run ruff format --check core/ tests/
uv run mypy core/
uv run bandit -r core/ -c pyproject.toml

# Pre-commit (전체 검사)
uv run pre-commit run --all-files
```

## Configuration

`.env` 파일로 설정합니다 (전체 목록: `core/config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| **LLM** | | |
| `ANTHROPIC_API_KEY` | | Claude API 키 |
| `OPENAI_API_KEY` | | GPT API 키 (Cross-LLM) |
| `GEODE_MODEL` | `claude-opus-4-6` | 기본 LLM 모델 |
| `GEODE_ENSEMBLE_MODE` | `primary_only` | 앙상블 모드 (`primary_only` / `cross`) |
| `GEODE_ROUTER_MODEL` | `claude-opus-4-6` | NL Router 모델 |
| `GEODE_AGREEMENT_THRESHOLD` | `0.67` | Cross-LLM 합의 임계값 |
| **Pipeline** | | |
| `GEODE_CONFIDENCE_THRESHOLD` | `0.7` | 신뢰도 게이트 (미달 시 재분석) |
| `GEODE_MAX_ITERATIONS` | `5` | 최대 재분석 반복 횟수 |
| `GEODE_INTERRUPT_NODES` | | 중간 개입 노드 (쉼표 구분, e.g. `verification,scoring`) |
| `GEODE_CHECKPOINT_DB` | `geode_checkpoints.db` | Checkpoint DB 경로 |
| **MCP** | | |
| `GEODE_STEAM_MCP_URL` | | Steam MCP 서버 URL |
| `GEODE_BRAVE_MCP_URL` | | Brave Search MCP 서버 URL |
| `GEODE_BRAVE_API_KEY` | | Brave Search API 키 |
| `GEODE_KG_MEMORY_MCP_URL` | | KG Memory MCP 서버 URL |
| **Observability** | | |
| `LANGCHAIN_TRACING_V2` | `false` | LangSmith tracing 활성화 |
| `LANGCHAIN_API_KEY` | | LangSmith API 키 |
| `LANGCHAIN_PROJECT` | `geode` | LangSmith 프로젝트명 |
| **General** | | |
| `GEODE_VERBOSE` | `false` | 상세 출력 |

## License

Internal use only.
