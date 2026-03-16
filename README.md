<p align="center">
  <img src="assets/geode-mascot.png" alt="GEODE — Autonomous Research Harness" width="360" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/while(tool__use)-agentic%20loop-1e293b?style=flat-square" alt="while(tool_use)">
  <img src="https://img.shields.io/badge/Opus%204.6-1M%20context-1e293b?style=flat-square" alt="Opus 4.6">
  <img src="https://img.shields.io/badge/38%20tools-MCP%20native-1e293b?style=flat-square" alt="38 Tools">
  <img src="https://img.shields.io/badge/LangGraph-StateGraph-1e293b?style=flat-square" alt="LangGraph">
  <a href="https://github.com/mangowhoiscloud/geode/actions"><img src="https://img.shields.io/github/actions/workflow/status/mangowhoiscloud/geode/ci.yml?style=flat-square&label=ci&logo=github&logoColor=white" alt="CI"></a>
</p>

# GEODE v0.15.0 — Autonomous Research Harness

범용 자율 실행 에이전트. `while(tool_use)` 루프를 핵심 프리미티브로 하여 리서치, 분석, 자동화, 스케줄링을 자연어 한 줄로 수행합니다.

> *"AI 에이전트 트렌드 조사해줘", "이 URL 요약해줘", "매주 월요일 뉴스 브리핑 잡아줘" -- 자연어로 요청하면 LLM이 도구를 호출하고, 결과를 관찰하고, 다음 행동을 결정하는 루프를 반복합니다. 복합 요청은 자동 분해하고, 실패는 자동 복구하며, 도메인별 분석 파이프라인은 플러그인으로 교체됩니다.*

### Highlights

- **Natural Language Interface** — 자연어 한 줄로 리서치, 분석, 자동화, 스케줄링 수행
- **`while(tool_use)` Loop** — 모든 자율 행동의 핵심 프리미티브. 도구를 호출하고, 관찰하고, 반복
- **38 Tools + MCP** — 웹 검색, URL 요약, YouTube, arXiv, LinkedIn 등 38개 도구 + MCP 자동설치
- **Goal Decomposition** — 복합 요청을 하위 목표 DAG로 자동 분해 (Haiku, ~$0.01/호출)
- **Error Recovery** — 실패 시 retry → alternative → fallback → escalate 4단계 자동 복구
- **Sub-Agent** — 부모 역량 전체 상속, 병렬 위임, Token Guard, as_completed 수집
- **3-Tier Memory** — SOUL → Organization → Project → Session 계층적 맥락 조합
- **Domain Plugin** — `DomainPort` Protocol로 도메인별 파이프라인 교체 (Game IP 기본 탑재)
- **Safety** — 4-tier HITL (SAFE/STANDARD/WRITE/DANGEROUS), Grounding Truth, 9종 bash 차단

## Installation

```bash
uv sync
```

## Quick Start

```bash
# 인터랙티브 REPL (권장) — 자연어로 무엇이든 요청
uv run geode

# 자연어 쿼리 (CLI에서 직접)
uv run geode "최근 AI 에이전트 프레임워크 트렌드 조사해줘"

# 웹 리서치
uv run geode "이 URL 내용 요약해줘: https://example.com/article"

# 스케줄링
uv run geode "매주 월요일 AI 뉴스 브리핑 스케줄 잡아줘"

# Domain Plugin: 게임 IP 분석 (API 키 있으면 LLM 호출, 없으면 자동 dry-run)
uv run geode analyze "Berserk"
```

### Setup

```bash
# 1. 환경 변수 설정
cp .env.example .env

# 2. .env 편집 — API 키 입력
ANTHROPIC_API_KEY=sk-ant-...

# 3. REPL 시작
uv run geode
```

API 키 없이 시작하면 자동으로 dry-run 모드로 전환됩니다.

---

## Architecture Overview

### 6-Layer Architecture

```mermaid
graph TB
    subgraph L0["L0 — CLI & Agentic Interface"]
        CLI["CLI (Typer)"]
        NLR["NL Router"]
        AL["AgenticLoop<br/>while(tool_use)"]
        SubA["SubAgentManager<br/>parallel delegation"]
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

    subgraph L3["L3 — Orchestration"]
        Hooks["HookSystem (30)"]
        Tasks["TaskGraph (DAG)"]
        Plan["PlanMode"]
        Coal["CoalescingQueue"]
        Lanes["Lane Queue"]
        RunLog["Run Log"]
    end

    subgraph L4["L4 — Extensibility"]
        Tools["ToolRegistry (38)"]
        Policy["PolicyChain"]
        Reports["Report Generator"]
        Skills["Skills System"]
        MCPCat["MCP Catalog (38)"]
    end

    subgraph L5["L5 — Domain Plugins"]
        Domain["DomainPort Protocol"]
        GameIP["GameIPDomain"]
        Pipeline["LangGraph StateGraph"]
    end

    L0 --> L1
    L0 --> L2
    L0 --> L3
    L0 --> L4
    L4 --> L5
    style L0 fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style L1 fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style L2 fill:#1e293b,stroke:#8b5cf6,color:#e2e8f0
    style L3 fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style L4 fill:#1e293b,stroke:#ef4444,color:#e2e8f0
    style L5 fill:#1e293b,stroke:#06b6d4,color:#e2e8f0
```

| Layer | 구성 요소 | 설명 |
|-------|----------|------|
| **L0** CLI & Agent | Typer CLI, NL Router, AgenticLoop, SubAgentManager, Batch | 사용자 인터페이스 + 자율 실행 코어 |
| **L1** Infra | Ports (Protocol), ClaudeAdapter, OpenAIAdapter, MCP Adapters | Port/Adapter DI — `contextvars` 주입 |
| **L2** Memory | Organization → Project → Session (3-Tier), SqliteSaver | 계층적 메모리 + LangGraph 체크포인트 |
| **L3** Orchestration | HookSystem (30 events), TaskGraph DAG, PlanMode, CoalescingQueue | 라이프사이클 이벤트, 동시성 제어 |
| **L4** Extensibility | ToolRegistry (38), PolicyChain, Skills, MCP Catalog (38) | 런타임 tool/skill 확장, MCP 자동설치 |
| **L5** Domain Plugins | DomainPort Protocol, GameIPDomain, LangGraph StateGraph | 도메인별 파이프라인 플러그인 교체 |

---

## Autonomous Core

### Agentic Loop

모든 자율 실행의 핵심 프리미티브. LLM이 `tool_use`를 반환하는 한 루프를 계속합니다.

```mermaid
graph TB
    Input["User Input<br/>(한국어/영어)"] --> LLM["Claude Opus 4.6<br/>Tool Use API"]
    LLM --> Decision{stop_reason}
    Decision -->|tool_use| Exec["ToolExecutor<br/>(38 base + MCP)"]
    Exec --> Check{clarification<br/>needed?}
    Check -->|Yes| Clarify["LLM asks<br/>clarifying question"]
    Clarify --> Output
    Check -->|No| Results["tool_result"]
    Results --> Recovery{"2+ consecutive<br/>failures?"}
    Recovery -->|Yes| ER["ErrorRecoveryStrategy<br/>retry → alt → fallback → escalate"]
    ER --> LLM
    Recovery -->|No| LLM
    Decision -->|end_turn| Output["AgenticResult<br/>(text + tool_calls)"]
    Decision -->|max_rounds| Output

    LLM -.->|"track_token_usage()"| LS["LangSmith<br/>RunTree"]

    style Input fill:#10b981,stroke:#10b981,color:#fff
    style Output fill:#3b82f6,stroke:#3b82f6,color:#fff
    style LLM fill:#f59e0b,stroke:#f59e0b,color:#fff
    style Exec fill:#8b5cf6,stroke:#8b5cf6,color:#fff
    style LS fill:#06b6d4,stroke:#06b6d4,color:#fff
    style ER fill:#ef4444,stroke:#ef4444,color:#fff
```

| 구성 요소 | 설명 |
|----------|------|
| **LLM Tool Use** | Claude Opus 4.6 — base 38 + MCP 20+ tool 정의 전달, `stop_reason` 기반 루프 제어 |
| **ToolExecutor** | 4-tier safety: SAFE / STANDARD / WRITE / DANGEROUS (bash 사용자 승인 필수) |
| **Clarification** | 필수 파라미터 누락 시 LLM이 사용자에게 되묻기 |
| **max_rounds** | 기본 50 라운드 — 마지막 2라운드에서 텍스트 응답 강제 (1M 컨텍스트 + `clear_tool_uses` 활용) |
| **Multi-turn** | 슬라이딩 윈도우 (max 200 turns) — 서버측 `clear_tool_uses`가 주 컨텍스트 관리, 클라이언트 제한은 안전망 |
| **LangSmith** | 토큰 수/비용을 RunTree에 기록, 세션 합산 |

### Goal Decomposition

복합 요청을 하위 목표 DAG로 자동 분해합니다. 단순 요청은 LLM 호출 없이 통과시켜 비용을 최소화합니다.

```mermaid
graph LR
    Input["User Input"] --> Simple{"< 15자 or<br/>slash cmd?"}
    Simple -->|Yes| Pass["Passthrough<br/>(skip LLM)"]
    Simple -->|No| Compound{"복합 지표?<br/>그리고/다음에/and"}
    Compound -->|No| Pass
    Compound -->|Yes| LLM["GoalDecomposer<br/>(Haiku, ~$0.01)"]
    LLM --> DAG["SubGoal DAG<br/>+ TaskGraph"]
    DAG --> Loop["AgenticLoop<br/>(guided execution)"]
    Pass --> Loop2["AgenticLoop<br/>(normal)"]

    style LLM fill:#f59e0b,stroke:#f59e0b,color:#fff
    style Pass fill:#10b981,stroke:#10b981,color:#fff
    style DAG fill:#3b82f6,stroke:#3b82f6,color:#fff
```

| 단계 | 동작 | 비용 |
|------|------|------|
| **Heuristic 1** | `_is_clearly_simple()` — slash 명령, 15자 미만 → 즉시 패스스루 | 0 |
| **Heuristic 2** | `_has_compound_indicators()` — "그리고", "다음에", "and then" 등 복합 지표 탐지 | 0 |
| **LLM Decompose** | Haiku 모델로 SubGoal 리스트 생성, 의존관계 포함 | ~$0.01 |
| **TaskGraph 변환** | SubGoal → TaskGraph DAG, 의존성 기반 실행 순서 결정, 실패 전파 | 0 |

### Error Recovery

도구 실행 연속 실패 시 4단계 전략 체인으로 자동 복구합니다.

```mermaid
graph LR
    Fail["Tool Failure<br/>(2+ consecutive)"] --> R["Retry<br/>(1s backoff)"]
    R -->|fail| A["Alternative<br/>(same category)"]
    A -->|fail| F["Fallback<br/>(cheaper tier)"]
    F -->|fail| E["Escalate<br/>(HITL needed)"]

    style R fill:#3b82f6,stroke:#3b82f6,color:#fff
    style A fill:#f59e0b,stroke:#f59e0b,color:#fff
    style F fill:#8b5cf6,stroke:#8b5cf6,color:#fff
    style E fill:#ef4444,stroke:#ef4444,color:#fff
```

| 전략 | 동작 | 예시 |
|------|------|------|
| **Retry** | 동일 도구 재실행 (1s backoff) | `web_fetch` 재시도 |
| **Alternative** | 같은 `category` 다른 도구 (`definitions.json`) | `web_fetch` → `general_web_search` |
| **Fallback** | 더 낮은 `cost_tier` 도구 | `expensive` → `cheap` → `free` |
| **Escalate** | 사용자 개입 요청 (terminal) | HITL 승인 |

**안전 제외**: `run_bash`, `memory_save`, `set_api_key` 등 DANGEROUS/WRITE 도구는 자동 복구 대상에서 제외.

Hook: `TOOL_RECOVERY_ATTEMPTED` / `SUCCEEDED` / `FAILED` — 복구 수명주기 관측.

### Dynamic Graph

파이프라인 토폴로지를 분석 결과에 따라 실행 시점에 동적으로 변형합니다.

```mermaid
graph LR
    Scoring["Scoring"] --> Skip{"skip_check"}
    Skip -->|"score ≥ 90 or ≤ 20"| Synth["Synthesizer<br/>(verification skip)"]
    Skip -->|"40-80 (mid-range)"| V["Verification<br/>(threshold +0.1)"]
    Skip -->|"normal"| V2["Verification<br/>(normal)"]

    style Skip fill:#f59e0b,stroke:#f59e0b,color:#fff
    style Synth fill:#10b981,stroke:#10b981,color:#fff
    style V fill:#8b5cf6,stroke:#8b5cf6,color:#fff
```

| 점수 범위 | 동작 | 이유 |
|-----------|------|------|
| **≥ 90 또는 ≤ 20** | verification 건너뛰기 → 바로 synthesizer | 극단 점수는 검증 불필요 (높은 확신) |
| **40 ~ 80** | `enrichment_needed=True`, confidence 임계값 +0.1 | 모호한 중간 점수 → 재평가 유도 |
| **그 외** | 정상 verification 경로 | 표준 흐름 |

`skipped_nodes` 필드에 건너뛴 노드를 누적 기록하여 감사 추적(audit trail) 가능.

### Signal Liveification

MCP 어댑터 우선 호출 → fixture fallback 전략으로 시그널을 수집합니다.

```mermaid
graph LR
    SN["signals_node"] --> Adapter{"MCP Adapter<br/>available?"}
    Adapter -->|Yes| Composite["CompositeSignalAdapter<br/>Steam + Brave"]
    Composite --> Keys{"data keys<br/>≥ 2?"}
    Keys -->|Yes| Live["signal_source=live"]
    Keys -->|No| Mix["Merge with fixture<br/>signal_source=mixed"]
    Adapter -->|No/Error| Fix["Fixture fallback<br/>signal_source=fixture"]

    style Live fill:#10b981,stroke:#10b981,color:#fff
    style Mix fill:#f59e0b,stroke:#f59e0b,color:#fff
    style Fix fill:#3b82f6,stroke:#3b82f6,color:#fff
```

| signal_source | 조건 | 설명 |
|---------------|------|------|
| `live` | MCP 반환 데이터 키 ≥ 2개 | 충분한 라이브 데이터 |
| `mixed` | MCP 반환 1개 + fixture 존재 | live 값이 fixture를 override |
| `fixture` | MCP 미연결/에러 | 자동 fallback |

`CompositeSignalAdapter`는 여러 MCP 어댑터(Steam, Brave 등)를 체이닝하며, `_enrichment_sources` 리스트로 provenance를 추적합니다.

### Plan Auto-Execute

계획 생성 → 승인 → 실행을 사용자 개입 없이 자동 수행합니다.

| 모드 | 흐름 | 설정 |
|------|------|------|
| **MANUAL** (기본) | create → present → [사용자 승인] → execute | `plan_auto_execute=false` |
| **AUTO** | create → auto_execute (승인+실행 일괄) | `GEODE_PLAN_AUTO_EXECUTE=true` |

- **Partial Success**: step 실패 시 1회 재시도 후 `failed`로 마킹하고 나머지 step 계속 진행
- **HITL 보존**: AUTO 모드에서도 DANGEROUS/WRITE 도구는 사용자 승인 필수 (ToolExecutor 레이어에서 별도 게이트)

### Sub-Agent System

부모 AgenticLoop의 전체 역량(tools, MCP, skills, memory)을 상속받아 독립 컨텍스트에서 병렬 실행합니다.

```mermaid
graph TB
    subgraph Parent["Parent AgenticLoop"]
        LLM["Claude Opus 4.6<br/>Tool Use"]
        DT["delegate_task<br/>(single / batch)"]
    end

    subgraph SAM["SubAgentManager"]
        CQ["CoalescingQueue<br/>(250ms dedup)"]
        TG["TaskGraph<br/>(DAG dependency)"]
        IR["IsolatedRunner<br/>(MAX_CONCURRENT=5)"]
    end

    subgraph Workers["Parallel Workers"]
        W1["Worker 1<br/>AgenticLoop"]
        W2["Worker 2<br/>AgenticLoop"]
        W3["Worker N<br/>AgenticLoop"]
    end

    LLM -->|tool_use| DT
    DT --> SAM
    CQ --> TG --> IR
    IR --> W1 & W2 & W3
    W1 & W2 & W3 -->|SubAgentResult| TGD["Token Guard<br/>(4096 tokens)"]
    TGD -->|tool_result| LLM

    style Parent fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style SAM fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style Workers fill:#1e293b,stroke:#10b981,color:#e2e8f0
```

| 제어 | 값 | 설명 |
|------|-----|------|
| **max_depth** | 2 | 재귀 위임 최대 깊이 (Root=0 → depth 2) |
| **max_total** | 15 | 세션당 최대 서브에이전트 수 |
| **MAX_CONCURRENT** | 5 | 동시 병렬 워커 수 |
| **timeout_s** | 120s | 개별 태스크 타임아웃 |
| **Token Guard** | 4096 tokens | tool_result 초과 시 `summary`만 보존 |
| **as_completed** | polling round-robin | 먼저 끝난 태스크 결과 즉시 반환 |

에러 분류: `TIMEOUT`, `API_ERROR` (retryable) / `VALIDATION`, `RESOURCE`, `DEPTH_EXCEEDED` (non-retryable).

### 3-Tier Memory

계층적 메모리 시스템으로 분석 맥락을 조합합니다. 상위 tier의 값은 하위 tier에 의해 override됩니다.

```mermaid
graph TB
    Soul["SOUL.md<br/>(Organization Identity)"] --> Org["Tier 1: Organization<br/>Fixtures, immutable<br/>IP context, rubric"]
    Org --> Proj["Tier 2: Project<br/>.claude/MEMORY.md<br/>rules, insights (max 50)"]
    Proj --> Sess["Tier 3: Session<br/>In-memory, TTL 1h<br/>ephemeral analysis context"]
    Sess --> Asm["ContextAssembler<br/>→ _llm_summary (280 chars)"]

    style Soul fill:#1e293b,stroke:#06b6d4,color:#e2e8f0
    style Org fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style Proj fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style Sess fill:#1e293b,stroke:#8b5cf6,color:#e2e8f0
    style Asm fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
```

| Tier | 소스 | 영속성 | 용도 |
|------|------|--------|------|
| **SOUL** | `.claude/SOUL.md` | 영구 | 조직 미션, 원칙 |
| **Organization** | `core/fixtures/*.json` | Read-only | IP context, rubric, 기대 결과 |
| **Project** | `.claude/MEMORY.md`, `.claude/rules/` | 파일 기반 | 학습된 규칙, 인사이트 (최대 50개, 회전) |
| **Session** | In-memory dict | TTL 1h | 현재 분석 컨텍스트, 체크포인트 |

`ContextAssembler`가 4-tier를 조합하여 `_llm_summary` (280자, SOUL 10% / Org 25% / Project 25% / Session 40% 예산)로 압축합니다.

---

## Safety & HITL

자율 에이전트의 안전을 보장하는 다층 게이트 시스템.

| 계층 | 메커니즘 | 설명 |
|------|----------|------|
| **Tool 분류** | SAFE / STANDARD / WRITE / DANGEROUS | 4-tier safety classification (`definitions.json`) |
| **HITL 승인** | DANGEROUS 도구 실행 전 사용자 확인 | `run_bash` 등 위험 명령 차단 |
| **MCP 세션 승인** | 서버별 최초 1회 승인, 세션 내 캐시 | `_mcp_approved_servers` |
| **Bash 차단** | 9종 위험 패턴 자동 거부 | `rm -rf /`, `sudo`, fork bomb 등 |
| **서브에이전트** | `auto_approve=True`이나 DANGEROUS/WRITE 제외 | 자식도 위험 도구는 승인 필수 |
| **Error Recovery 제외** | DANGEROUS/WRITE 도구 자동 복구 안 함 | 안전 게이트 우회 방지 |
| **Grounding Truth** | tool_result 기반 출처 인용 강제 | 미확인 정보 생성 금지 |

---

## Extensibility

### Tool & MCP

```mermaid
graph TB
    subgraph GEODE["GEODE Autonomous Core"]
        Registry["ToolRegistry<br/>38 base tools"]
        Policy["PolicyChain"]
        SkillReg["SkillRegistry<br/>(auto-inject)"]
        MCPInstall["MCP Auto-Install<br/>(38 catalog)"]
    end

    subgraph MCPAdapters["MCP Adapters (5 active)"]
        Brave["Brave Search"]
        Steam["Steam MCP"]
        ArXiv["arXiv MCP"]
        PW["Playwright MCP"]
        LI["LinkedIn Reader"]
    end

    subgraph MCPServer["MCP Server (FastMCP)"]
        T1["analyze_ip / quick_score"]
        T2["get_ip_signals"]
        T3["list_fixtures / query_memory / get_health"]
    end

    Registry --> Policy
    SkillReg --> Registry
    MCPInstall --> MCPAdapters
    GEODE --> MCPAdapters
    MCPServer --> GEODE

    style GEODE fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style MCPAdapters fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style MCPServer fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
```

- **38 base tools** — `web_fetch`, `general_web_search`, `youtube_search`, `read_document` 등 범용 도구 + `category`/`cost_tier` 메타데이터
- **MCP Adapters** — Brave Search, arXiv, Playwright, LinkedIn, Steam (env var 비어있으면 graceful skip)
- **MCP Server** — `uv run python -m core.mcp_server` 로 GEODE를 외부 에이전트에서 호출 가능 (6 tools, 2 resources)
- **Skills** — `.claude/skills/` 자동 발견 + YAML frontmatter 기반 도구 핫 리로드
- **MCP 자동설치** — `install_mcp_server` tool → 38개 카탈로그 검색 + 설치 + `refresh_tools()`

### Domain Plugin

`DomainPort` Protocol로 도메인별 분석 파이프라인을 플러그인으로 교체합니다. 동일한 자율 실행 하네스 위에 게임 IP, 금융, 콘텐츠 등 다양한 도메인 파이프라인을 탑재할 수 있습니다. 아래는 기본 탑재된 Game IP 도메인의 구조입니다.

```mermaid
graph LR
    START((START)) --> Router
    Router --> Signals
    Signals --> A["Analyst ×4<br/>(Send API, Clean Context)"]
    A --> E["Evaluator ×3<br/>(14-Axis Rubric)"]
    E --> Scoring["Scoring<br/>(PSM 6-Weighted)"]
    Scoring --> SkipCheck["skip_check"]
    SkipCheck --> V["Verification<br/>(G1-G4 + BiasBuster)"]
    V -->|"confidence ≥ 0.7"| Synth["Synthesizer"]
    V -->|"< 0.7"| Gather["gather → loopback"]
    Gather -->|"max 5"| Signals
    Synth --> END((END))

    style START fill:#10b981,stroke:#10b981,color:#fff
    style END fill:#ef4444,stroke:#ef4444,color:#fff
    style SkipCheck fill:#f59e0b,stroke:#f59e0b,color:#fff
```

<details>
<summary>Game IP Domain 상세</summary>

**Cross-LLM Ensemble**: Claude Opus 4.6 (primary) + GPT-5.4 (secondary), agreement ≥ 0.67, Krippendorff's α.

**14-Axis Rubric**: 3 Evaluators — `quality_judge` (8축), `hidden_value` (3축: D/E/F), `community_momentum` (3축: J/K/L).

**Scoring**: `Final = (0.25×PSM + 0.20×Quality + 0.18×Recovery + 0.12×Growth + 0.20×Momentum + 0.05×Dev) × (0.7 + 0.3 × Confidence/100)`. Tier: S ≥ 80, A ≥ 60, B ≥ 40, C < 40.

**Verification**: Guardrails G1-G4 (Schema, Range, Grounding, Consistency) + BiasBuster (6 bias, CV-based fast path) + Confidence Gate (≥ 0.7 or loopback, max 5 iter).

**Core Fixtures** (golden set):

| IP | Tier | Score | Genre |
|----|------|-------|-------|
| Berserk | S | 81.3 | Dark Fantasy |
| Cowboy Bebop | A | 68.4 | SF Noir |
| Ghost in the Shell | B | 51.6 | Cyberpunk |

**Steam Fixtures**: 201개 추가 게임 데이터 (`core/fixtures/steam/`).

</details>

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

| 항목 | 설명 |
|------|------|
| **track_token_usage()** | 각 LLM 호출 후 input/output 토큰 수 + cache hit 기록 |
| **calculate_cost()** | `MODEL_PRICING` dict 기반 비용 산출 (input/output/cache 단가 × 토큰) |
| **LLMUsageAccumulator** | `contextvars` 기반 세션 내 토큰/비용 누적, context-local 격리 |
| **조건부 활성화** | `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` 설정 시만 tracing 활성 |

<details>
<summary>Prompt Caching / Checkpoint / Dynamic Tools</summary>

**Prompt Caching**: Anthropic `cache_control: {"type": "ephemeral"}` 적용. 시스템 프롬프트와 루브릭 캐시로 40-60% 비용 절감.

**Checkpoint**: `SqliteSaver`로 파이프라인 상태 영속화. 장애 시 마지막 체크포인트부터 재개.

**Dynamic Tools**: `ToolRegistry` + `get_agentic_tools()` — 플러그인 런타임 등록. MCP 자동설치 후 `refresh_tools()` 핫 리로드.

</details>

---

## Usage

### Interactive Mode

```bash
uv run geode
```

**슬래시 커맨드:**

| Command | Alias | Description |
|---------|-------|-------------|
| `/analyze <IP>` | `/a` | IP 분석 (Domain Plugin) |
| `/search <query>` | `/s` | 검색 |
| `/report <IP> [fmt]` | `/rpt` | 리포트 생성 (md/html/json) |
| `/list` | | IP 목록 (Domain Plugin) |
| `/batch [--top N]` | `/b` | 배치 분석 |
| `/compare <A> <B>` | | 비교 분석 |
| `/schedule <cron>` | `/sched` | 작업 스케줄 |
| `/mcp status\|tools\|reload\|add` | | MCP 관리 |
| `/skills` | | 스킬 목록/상세 |
| `/status` | | 시스템 상태 |
| `/model` | | LLM 모델 선택 |
| `/verbose` | | 상세 출력 토글 |
| `/quit` | `/q` | 종료 |

**자연어 입력 (리서치 에이전트):**

```
> 최근 AI 에이전트 프레임워크 트렌드 조사해줘       → 웹 리서치 + 요약
> 이 사람 LinkedIn 프로필 분석해줘                  → LinkedIn MCP 호출
> YouTube에서 LangGraph 관련 영상 찾아서 요약해줘    → youtube_search + 요약
> 이 URL 내용 요약하고 핵심 포인트 정리해줘          → web_fetch + 분석
> 매주 월요일 AI 뉴스 브리핑 스케줄 잡아줘           → NL 스케줄 생성
> arXiv에서 RAG 관련 최신 논문 찾아줘               → arXiv MCP 검색
> LinkedIn MCP 달아줘                              → MCP 자동설치
```

**자연어 입력 (Game IP Domain Plugin):**

```
> Berserk 분석해           → LLM 분석 / dry-run
> 소울라이크 찾아줘         → 장르 검색
> Berserk vs Cowboy Bebop  → 비교 분석
```

### CLI Mode

```bash
# 범용 리서치 쿼리
uv run geode "최근 AI 에이전트 프레임워크 트렌드 조사해줘"
uv run geode "이 URL 요약해줘: https://example.com/article"
uv run geode "매주 월요일 AI 뉴스 브리핑 스케줄 잡아줘"

# Domain Plugin: 게임 IP 분석
uv run geode analyze "Berserk"                    # CLI 분석
uv run geode search "사이버펑크"                   # 장르 검색
uv run geode report "Berserk" -f html -o out.html # HTML 리포트
uv run geode batch --top 5                        # 배치 분석
```

---

## Configuration

`.env` 파일로 설정합니다 (전체 목록: `core/config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| **LLM** | | |
| `ANTHROPIC_API_KEY` | | Claude API 키 |
| `OPENAI_API_KEY` | | GPT API 키 (Cross-LLM) |
| `GEODE_MODEL` | `claude-opus-4-6` | 기본 LLM 모델 |
| `GEODE_ENSEMBLE_MODE` | `primary_only` | 앙상블 모드 (`primary_only` / `cross`) |
| **Pipeline** | | |
| `GEODE_CONFIDENCE_THRESHOLD` | `0.7` | 신뢰도 게이트 |
| `GEODE_MAX_ITERATIONS` | `5` | 최대 재분석 반복 |
| `GEODE_PLAN_AUTO_EXECUTE` | `false` | 계획 자율 실행 모드 |
| `GEODE_INTERRUPT_NODES` | | 중간 개입 노드 |
| `GEODE_CHECKPOINT_DB` | `geode_checkpoints.db` | Checkpoint DB 경로 |
| **MCP** | | |
| `GEODE_STEAM_MCP_URL` | | Steam MCP 서버 URL |
| `GEODE_BRAVE_API_KEY` | | Brave Search API 키 |
| **Observability** | | |
| `LANGCHAIN_TRACING_V2` | `false` | LangSmith tracing |
| `LANGCHAIN_API_KEY` | | LangSmith API 키 |

## Testing

```bash
uv run pytest                                        # 전체 (2366+ passed)
uv run pytest tests/test_e2e_live_llm.py -v -m live  # Live E2E
uv run ruff check core/ tests/                       # Lint
uv run mypy core/                                    # Type check (134 files)
uv run bandit -r core/ -c pyproject.toml             # Security
```

## Project Structure

```
core/
├── cli/                        # CLI + NL Router + Agentic Loop + Sub-Agent
│   ├── __init__.py             # Typer app, REPL, pipeline execution
│   ├── agentic_loop.py         # while(tool_use) multi-round execution + Token Guard
│   ├── error_recovery.py       # ErrorRecoveryStrategy (retry → alternative → fallback → escalate)
│   ├── sub_agent.py            # SubAgentManager + SubAgentResult + ErrorCategory
│   ├── tool_executor.py        # Tool dispatch + HITL approval gate
│   ├── nl_router.py            # Natural language intent classification
│   ├── conversation.py         # Multi-turn sliding-window (max 200 turns, server-side clear_tool_uses)
│   ├── bash_tool.py            # Shell execution + HITL safety gate
│   ├── batch.py                # Batch analysis (ThreadPoolExecutor)
│   ├── commands.py             # Slash command dispatch (17 commands)
│   ├── search.py               # IP search engine (synonym expansion)
│   └── startup.py              # Readiness check, Graceful Degradation
├── config.py                   # Settings (pydantic-settings, 30+ vars)
├── state.py                    # GeodeState (TypedDict + Pydantic models)
├── graph.py                    # LangGraph StateGraph + skip_check node
├── runtime.py                  # GeodeRuntime (production DI wiring)
├── infrastructure/
│   ├── ports/                  # LLMClientPort, SignalEnrichmentPort, DomainPort
│   └── adapters/
│       ├── llm/                # ClaudeAdapter, OpenAIAdapter
│       └── mcp/                # Steam, Brave, LinkedIn + CompositeSignalAdapter + catalog (38)
├── llm/                        # LLM client (prompt caching, streaming, cost tracking)
├── memory/                     # 3-Tier: Organization → Project → Session
├── nodes/                      # Pipeline nodes (router, signals, analyst, evaluator, scoring, verification, gather, synthesizer)
├── orchestration/
│   ├── hooks.py                # HookSystem (30 events + async atrigger)
│   ├── goal_decomposer.py      # GoalDecomposer (compound request → sub-goal DAG)
│   ├── plan_mode.py            # DRAFT → APPROVED → EXECUTING (MANUAL / AUTO)
│   ├── task_system.py          # TaskGraph DAG (dependency, cycle detection)
│   ├── coalescing.py           # CoalescingQueue (250ms dedup window)
│   ├── isolated_execution.py   # IsolatedRunner (MAX_CONCURRENT=5)
│   └── ...                     # planner, bootstrap, lane_queue, run_log, etc.
├── automation/                 # Feedback loop, drift detection, scheduler, triggers
├── domains/                    # Domain plugin adapters (GameIPDomain)
├── tools/                      # Tool Protocol + Registry + Policy + definitions.json
├── verification/               # Guardrails (G1-G4) + BiasBuster + Rights Risk
├── extensibility/              # Report generation + Skills + AgentRegistry
├── fixtures/                   # Fixture data (3 core IPs + 201 Steam)
├── auth/                       # API key rotation, cooldown, profiles
├── ui/                         # Rich console + Claude Code-style agentic UI
└── mcp_server.py               # FastMCP server (6 tools, 2 resources)
```

## Design Choices

- **Natural language first.** 자연어 한 줄이 입력이고, 에이전트가 도구 선택부터 결과 종합까지 자율적으로 수행한다. 리서치, 요약, 스케줄링, 분석 -- 도메인을 가리지 않는다.
- **`while(tool_use)` as primitive.** 모든 자율 행동은 하나의 루프에서 나온다. 서브에이전트도, 계획 실행도, 배치 분석도 전부 AgenticLoop 인스턴스. 추상화가 아닌 구체적 실행 단위.
- **Port/Adapter DI.** 모든 인프라는 `Protocol` 포트 + `contextvars` 주입. LLM, 메모리, MCP 전부 교체 가능. 테스트에서 mock 주입, 프로덕션에서 실제 어댑터.
- **도메인은 플러그인.** `DomainPort` Protocol 구현체를 교체하면 게임 IP, 금융, 의료, 콘텐츠 등 어떤 도메인이든 동일한 자율 하네스 위에 탑재할 수 있다.
- **Safety by default.** 자율 에이전트는 위험하다. DANGEROUS 도구는 항상 사용자 승인, Error Recovery에서도 제외, 서브에이전트에서도 제외. 안전 게이트 우회 경로가 없다.
- **Graceful degradation.** API 키 없으면 dry-run, MCP 미연결이면 fixture fallback, LLM 실패하면 retry chain. 어떤 상태에서든 에이전트는 멈추지 않는다.

## License

Internal use only.
