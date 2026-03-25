<p align="center">
  <img src="assets/geode-mascot.png" alt="GEODE — Autonomous Execution Harness" width="360" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/while(tool__use)-agentic%20loop-1e293b?style=flat-square" alt="while(tool_use)">
  <img src="https://img.shields.io/badge/Opus%204.6-1M%20context-1e293b?style=flat-square" alt="Opus 4.6">
  <img src="https://img.shields.io/badge/46%20tools-MCP%20native-1e293b?style=flat-square" alt="46 Tools">
  <img src="https://img.shields.io/badge/LangGraph-StateGraph-1e293b?style=flat-square" alt="LangGraph">
  <a href="https://github.com/mangowhoiscloud/geode/actions"><img src="https://img.shields.io/github/actions/workflow/status/mangowhoiscloud/geode/ci.yml?style=flat-square&label=ci&logo=github&logoColor=white" alt="CI"></a>
</p>

# GEODE v0.27.0 — Autonomous Execution Harness

범용 자율 실행 에이전트. 자연어 한 줄로 리서치, 분석, 자동화, 스케줄링을 수행합니다.

## Development Workflow

> **원칙**: 행동 목록이 아닌 **가드레일(CANNOT)**이 품질을 담보한다. (Karpathy P1)

```mermaid
graph TB
    CANNOT["CANNOT<br/><i>절대 금지 가드레일</i>"]
    CANNOT -.->|"위반 시 즉시 중단"| W

    W["0. Worktree<br/>동기화 검증 → 격리 공간"] --> Plan["1. Plan<br/>EnterPlanMode<br/>→ 설계 → 승인"]
    Plan --> Impl["2. Implement<br/>코드 변경 → lint<br/>→ type → test"]
    Impl --> Verify["3. Verify<br/>E2E + 검증팀<br/>(4인 페르소나 병렬)"]
    Verify -->|"fail"| Impl
    Verify -->|"pass"| Docs["4. Docs-Sync<br/>CHANGELOG + 버전<br/>4곳 동기화"]
    Docs --> PR["5. PR & Merge<br/>feature → develop<br/>→ main"]
    PR -->|"CI fail"| Impl
    PR -->|"pass"| Board["6. Board<br/>progress.md<br/>칸반 갱신"]

    style CANNOT fill:#1e293b,stroke:#ef4444,color:#fca5a5,stroke-width:2px
    style W fill:#1e293b,stroke:#06b6d4,color:#e2e8f0
    style Plan fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style Impl fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style Verify fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style Docs fill:#1e293b,stroke:#8b5cf6,color:#e2e8f0
    style PR fill:#1e293b,stroke:#ef4444,color:#e2e8f0
    style Board fill:#1e293b,stroke:#ec4899,color:#e2e8f0
```

<details>
<summary><b>CANNOT — 절대 금지 규칙</b></summary>

어떤 단계에서든 위반 불가. 위반 시 즉시 중단하고 수정.

| 영역 | 금지 사항 |
|------|----------|
| **Git** | worktree 없이 작업 시작 / main·develop 직접 push / 타 세션 worktree 삭제 / feature에서 progress.md 수정 / **동기화 미확인 상태에서 feature 생성** |
| **워크플로우** | **Plan 없이 구현 착수** (단순 버그·문서 수정 제외) / **칸반 필수 컬럼 빈칸 기재** |
| **품질** | lint·type·test 실패 상태 커밋 / 테스트 수치 자리표시자(XXXX) / live 테스트 무단 실행 |
| **문서** | 코드 커밋에서 CHANGELOG 누락 / main에 `[Unreleased]` 잔류 / 버전 4곳 불일치 |
| **PR** | 인라인 `--body` 사용 / 변경 파일 Why 근거 누락 / HEREDOC 미사용 |

</details>

| 단계 | 게이트 | 재귀 조건 |
|------|--------|-----------|
| **0. Worktree** | `git fetch` → main·develop 동기화 검증 → `git worktree add` + `.owner` | — |
| **1. Plan** | EnterPlanMode → 설계 → ExitPlanMode → TaskCreate (칸반 연동) | — |
| **2. Implement** | `ruff check` + `mypy` + `pytest` | 실패 시 수정 반복 |
| **3. Verify** | Mock E2E + CLI dry-run + 검증팀 4인 병렬 | 실패 시 **2번 복귀** |
| **4. Docs-Sync** | CHANGELOG + 버전 4곳 + 수치 동기화 | — |
| **5. PR & Merge** | feature → develop → main (GitFlow) | CI 실패 시 **2번 복귀** |
| **6. Board** | `docs/progress.md` 칸반 갱신 (main에서만) | — |

**품질 게이트:**

| 게이트 | 명령어 | 기준 |
|--------|--------|------|
| Lint | `uv run ruff check core/ tests/` | 0 errors |
| Type | `uv run mypy core/` | 0 errors |
| Test | `uv run pytest tests/ -q` | 3088+ pass |

### 칸반 보드 (`docs/progress.md`)

멀티 에이전트 공유 칸반. 모든 세션이 읽고 갱신합니다.

```
Backlog → In Progress → In Review → Done
```

| 규칙 | 설명 |
|------|------|
| **main-only** | progress.md는 main에서만 수정 (feature/develop 금지) |
| **3-Checkpoint** | alloc(Step 0) → free(PR merge 후) → session-start(교차 검증) |
| **필수 컬럼** | task_id·작업 내용은 모든 상태에서 필수. 빈칸 금지, "—" 허용 |
| **Task 연동** | TaskCreate subject ↔ 칸반 task_id 1:1 매핑 |

### `.geode/` — 프로젝트-로컬 컨텍스트

`geode init`으로 생성되는 프로젝트별 영속 저장소. 에이전트의 학습, 실행 기록, 산출물이 여기에 쌓입니다.

```
.geode/
├── journal/           # 실행 기록 (append-only JSONL)
│   ├── runs.jsonl     # 파이프라인 실행 이력
│   └── errors.jsonl   # 에러 로그
├── memory/            # 프로젝트 메모리
│   └── PROJECT.md     # 학습된 인사이트·규칙
├── rules/             # 도메인별 학습 규칙 (자동 생성)
│   └── *.md           # anime-ip.md, indie-steam.md 등
├── vault/             # 산출물 영속 저장소
│   ├── profile/       # 사용자 프로필 산출물
│   ├── research/      # 리서치 결과
│   ├── applications/  # 지원서·트래커
│   └── general/       # 범용 산출물
├── reports/           # IP 분석 리포트 (MD/HTML)
├── result_cache/      # 분석 결과 캐시 (24h TTL + SHA-256)
├── snapshots/         # 파이프라인 스냅샷 (JSON)
└── models/            # 모델 레지스트리
```

| 디렉토리 | 생명주기 | 용도 |
|----------|---------|------|
| `journal/` | Append-only | Hook(PIPELINE_END/ERROR)이 자동 기록. 실행 이력 감사 추적 |
| `memory/` | 누적 (max 50, 회전) | Agent Reflection이 패턴 추출 → `PROJECT.md` 갱신 |
| `rules/` | 자동 생성 | 도메인별 학습 규칙 (장르 패턴, IP 특성) |
| `vault/` | 영구 | 분석 리포트·리서치·지원서 등 산출물 보관 |
| `result_cache/` | 24h TTL | SHA-256 content hash로 무결성 검증. 만료 시 재분석 |
| `snapshots/` | 자동 | 파이프라인 중간 상태 캡처. 장애 복구용 |

### 왜 만들었는가

**문제.** 2026년 현재, AI 코딩 에이전트는 눈부시게 발전했습니다. 코드를 읽고, 쓰고, 고치고, 테스트까지 자율적으로 수행합니다. 그런데 실제 업무에서 코딩이 차지하는 비중은 얼마나 될까요? 리서치, 문서 분석, 일정 관리, 알림 전송, 데이터 파이프라인, 의사결정을 위한 다축 평가 — 코딩 *이외의* 자율 실행이 필요한 영역이 훨씬 넓습니다. 기존 에이전트들은 이 공간에 거의 도달하지 못합니다.

**인사이트.** 그런데 이 모든 자율 행동의 핵심은 놀라울 만큼 단순합니다. LLM이 도구를 호출하고, 결과를 관찰하고, 다음 행동을 결정하는 `while(tool_use)` 루프. Claude Code, Codex, OpenClaw — 프론티어 하네스들이 모두 이 프리미티브 위에 서 있습니다. 코딩 에이전트와 범용 에이전트의 차이는 루프 자체가 아니라, 루프에 연결된 도구와 도메인의 폭입니다.

**출발점.** GEODE는 넥슨 AI 엔지니어 과제에서 시작했습니다. 게임 IP의 저평가 여부를 추론하는 단방향 LLM/ML 기반 DAG — 4명의 Analyst가 병렬 평가하고, 3명의 Evaluator가 14축 루브릭으로 채점하고, PSM 기반 스코어링과 Decision Tree로 원인을 분류하는 파이프라인이었습니다. 과제는 합격했지만, 이 파이프라인은 에이전트가 아니라 *워크플로우*였습니다. 한 도메인에 고정된 일회성 DAG로는, 코딩 너머의 자율 실행이라는 원래 목표에 닿을 수 없었습니다.

**전환.** 그래서 IP 분석 파이프라인 전체를 `DomainPort` Protocol 뒤의 플러그인으로 내렸습니다. 그리고 그 위에 범용 자율 실행 하네스를 올렸습니다. `while(tool_use)` 루프 하나로 리서치, 분석, 자동화, 스케줄링을 수행하는 에이전트. 도메인은 교체 가능한 플러그인이고, 하네스는 도메인을 가리지 않습니다.

> *"AI 에이전트 트렌드 조사해줘", "이 URL 요약해줘", "매주 월요일 뉴스 브리핑 잡아줘"*
>
> 자연어로 요청하면 LLM이 46개 도구 중 적합한 것을 골라 호출하고, 결과를 관찰하고, 다음 행동을 결정합니다. 서브에이전트에게 병렬 위임하고, 실패하면 대안 도구로 복구하고, 계획이 필요하면 DAG를 세워 단계별로 실행합니다. 이 루프가 끝날 때까지.

### Highlights

| 기능 | 설명 |
|------|------|
| **`while(tool_use)` Loop** | 모든 자율 행동의 핵심 프리미티브. 서브에이전트, 계획 실행, 배치 분석 전부 AgenticLoop 인스턴스 |
| **46 Tools + MCP** | 네이티브 46개 도구 + MCP 카탈로그 42종 자동 설치. Bash 실행 (41종 자동승인, 9종 차단) |
| **Sub-Agent** | 부모 역량 전체 상속, 최대 5 병렬, Token Guard, DAG 의존성 |
| **Multi-Provider LLM** | Anthropic + OpenAI + ZhipuAI 3-provider failover chain. 자동 모델 전환 + circuit breaker |
| **4-Tier Memory** | SOUL → User Profile → Organization → Project → Session. 프로젝트별 컨텍스트 자동 구성 |
| **`.geode/` Context** | 프로젝트-로컬 영속 저장소 — journal, vault, rules, cache. `geode init`으로 초기화 |
| **Domain Plugin** | `DomainPort` Protocol로 파이프라인 교체 — Game IP 분석 기본 탑재 |
| **CANNOT Workflow** | 가드레일 기반 7단계 워크플로우 — 동기화 검증, Plan 강제, 칸반 추적 |
| **Safety** | 4-tier HITL (SAFE/STANDARD/WRITE/DANGEROUS), 9종 bash 차단, Grounding Truth |

### Tool Execution Hierarchy

```mermaid
flowchart LR
    NL["AgenticLoop<br/>(LLM tool_use)"]

    NL --> Builtin["Built-in Tools<br/>(46 definitions)"]
    NL --> MCP["MCP Tools<br/>(auto-discovered)"]
    NL --> Bash["Bash<br/>(run_bash)"]

    Builtin --> S1["SAFE<br/>auto-execute"]
    Builtin --> S2["STANDARD<br/>execute"]
    Builtin --> S3["WRITE<br/>HITL approval"]

    MCP --> MA["AUTO_APPROVED<br/>brave-search, steam,<br/>arxiv, linkedin-reader"]
    MCP --> MO["Other<br/>first-call approval"]

    Bash --> BBlk["Blocked<br/>(9 patterns)"]
    Bash --> BSafe["SAFE_BASH_PREFIXES<br/>(41 read-only)"]
    Bash --> BHitl["Other<br/>HITL approval"]

    style NL fill:#1e293b,stroke:#475569,color:#e2e8f0
    style Builtin fill:#1e3a5f,stroke:#3b82f6,color:#93c5fd
    style MCP fill:#1e3a5f,stroke:#3b82f6,color:#93c5fd
    style Bash fill:#1e3a5f,stroke:#3b82f6,color:#93c5fd
    style S1 fill:#064e3b,stroke:#10b981,color:#6ee7b7
    style S2 fill:#1e3a5f,stroke:#3b82f6,color:#93c5fd
    style S3 fill:#7c2d12,stroke:#f97316,color:#fed7aa
    style MA fill:#064e3b,stroke:#10b981,color:#6ee7b7
    style MO fill:#1e3a5f,stroke:#3b82f6,color:#93c5fd
    style BBlk fill:#7f1d1d,stroke:#ef4444,color:#fca5a5
    style BSafe fill:#064e3b,stroke:#10b981,color:#6ee7b7
    style BHitl fill:#7c2d12,stroke:#f97316,color:#fed7aa
```

AgenticLoop가 LLM의 tool_use 응답을 3가지 경로로 디스패치합니다:

| 경로 | 도구 수 | 승인 방식 |
|------|--------|----------|
| Built-in Tools | 46 | SAFE 자동승인, STANDARD 실행, WRITE HITL 승인 |
| MCP Tools | 카탈로그 42종 | AUTO_APPROVED 서버 4종 자동승인, 그 외 초회 승인 |
| Bash | shell 명령 | SAFE_BASH_PREFIXES 41종 자동승인, 9종 차단, 그 외 HITL |

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

# 2. .env 편집 — 최소 Anthropic API 키 입력
ANTHROPIC_API_KEY=sk-ant-...

# 3. REPL 시작
uv run geode
```

API 키 없이 시작하면 자동으로 dry-run 모드로 전환됩니다.

#### Global Installation (어디서든 `geode` 실행)

```bash
cd /path/to/geode
uv tool install . --force
```

설치 후 `geode`를 아무 디렉토리에서 실행할 수 있습니다.
프로젝트별 `.env`가 없으면 `~/.geode/.env`에서 글로벌 키를 읽습니다.

#### Global API Keys (`~/.geode/.env`)

```bash
mkdir -p ~/.geode
cat > ~/.geode/.env << 'EOF'
# LLM Providers
ANTHROPIC_API_KEY=sk-ant-...       # https://console.anthropic.com/settings/keys
OPENAI_API_KEY=sk-proj-...         # https://platform.openai.com/api-keys
ZAI_API_KEY=...                    # https://open.bigmodel.cn/usercenter/apikeys (선택)

# Search & Data
BRAVE_API_KEY=...                  # https://brave.com/search/api/
GOOGLE_API_KEY=...                 # https://console.cloud.google.com/apis/credentials
YOUTUBE_API_KEY=...                # 위 Google API Key와 동일 (YouTube Data API v3 활성화)

# Messaging (Slack Gateway)
SLACK_BOT_TOKEN=xoxb-...           # https://api.slack.com/apps → OAuth & Permissions
SLACK_TEAM_ID=T...                 # Slack 워크스페이스 설정에서 확인

# Observability (선택)
LANGSMITH_API_KEY=lsv2_pt_...      # https://smith.langchain.com/settings
EOF
chmod 600 ~/.geode/.env
```

**우선순위**: 환경변수 > 프로젝트 `.env` > `~/.geode/.env` > 코드 기본값

#### Slack Gateway (양방향 소통)

GEODE를 Slack 채널과 연결하면 메시지로 대화할 수 있습니다.

**1. Slack Bot 생성**
- [api.slack.com/apps](https://api.slack.com/apps) → Create New App
- Bot Token Scopes: `chat:write`, `channels:history`, `channels:read`
- Bot Token (`xoxb-...`)과 Team ID를 `~/.geode/.env`에 설정

**2. Gateway 활성화**

```bash
# ~/.geode/.env에 추가
GEODE_GATEWAY_ENABLED=true
```

**3. 채널 바인딩** (`.geode/config.toml`)

```toml
[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0ALBPUFXL5"    # Slack 채널 ID
auto_respond = true
require_mention = false
max_rounds = 5
```

**4. 실행**

```bash
# 포그라운드 (REPL + Gateway 동시)
geode

# 헤드리스 모드 (Gateway만 백그라운드)
nohup geode serve > /tmp/geode-gateway.log 2>&1 &
```

`geode serve`는 REPL 없이 Gateway만 실행합니다. MCP 서버 14종이 순차 연결되므로 시작까지 2-3분 소요됩니다.

#### HITL Level (자율성 조절)

```bash
# 0 = 완전 자율 (모든 승인 생략)
GEODE_HITL_LEVEL=0

# 1 = WRITE만 묻기 (bash/MCP는 자동 승인)
GEODE_HITL_LEVEL=1

# 2 = 전부 묻기 (기본값)
GEODE_HITL_LEVEL=2
```

---

## Architecture Overview

### 6-Layer Architecture

```mermaid
graph TB
    subgraph L0["L0 — CLI & Agentic Interface"]
        CLI["CLI (Typer)"]
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

    subgraph L2["L2 — Memory (4-Tier)"]
        UserProf["User Profile<br/>(Tier 0.5, preferences)"]
        Org["Organization<br/>(fixtures, immutable)"]
        Project["Project Memory<br/>(.claude/MEMORY.md)"]
        Session["Session Store<br/>(in-memory TTL)"]
        Checkpoint["SqliteSaver"]
    end

    subgraph L3["L3 — Orchestration"]
        Hooks["HookSystem (36)"]
        Tasks["TaskGraph (DAG)"]
        Plan["PlanMode"]
        Coal["CoalescingQueue"]
        Lanes["Lane Queue"]
        RunLog["Run Log"]
    end

    subgraph L4["L4 — Extensibility"]
        Tools["ToolRegistry (46)"]
        Policy["PolicyChain"]
        Reports["Report Generator"]
        Skills["Skills System"]
        MCPCat["MCP Catalog (42)"]
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
| **L0** CLI & Agent | Typer CLI, AgenticLoop, SubAgentManager, Batch, Gateway | 사용자 인터페이스 + 자율 실행 코어 |
| **L1** Infra | Ports (Protocol), ClaudeAdapter, OpenAIAdapter, MCP Adapters | Port/Adapter DI — `contextvars` 주입 |
| **L2** Memory | SOUL → User Profile → Organization → Project → Session (4-Tier), SqliteSaver | 계층적 메모리 + LangGraph 체크포인트 |
| **L3** Orchestration | HookSystem (36 events), TaskGraph DAG, PlanMode, CoalescingQueue | 라이프사이클 이벤트, 동시성 제어 |
| **L4** Extensibility | ToolRegistry (46), PolicyChain, Skills, MCP Catalog (42) | 런타임 tool/skill 확장, MCP 자동설치 |
| **L5** Domain Plugins | DomainPort Protocol, GameIPDomain, LangGraph StateGraph | 도메인별 파이프라인 플러그인 교체 |

---

## Autonomous Core

### Agentic Loop

모든 자율 실행의 핵심 프리미티브. LLM이 `tool_use`를 반환하는 한 루프를 계속합니다.

```mermaid
graph TB
    Input["User Input<br/>(한국어/영어)"] --> LLM["Claude Opus 4.6<br/>Tool Use API"]
    LLM --> Decision{stop_reason}
    Decision -->|tool_use| Exec["ToolExecutor<br/>(46 base + MCP)"]
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
| **LLM Tool Use** | Claude Opus 4.6 — base 46 + MCP 20+ tool 정의 전달, `stop_reason` 기반 루프 제어 |
| **ToolExecutor** | 4-tier safety: SAFE / STANDARD / WRITE / DANGEROUS (bash 사용자 승인 필수) |
| **Clarification** | 필수 파라미터 누락 시 LLM이 사용자에게 되묻기 |
| **max_rounds** | 기본 50 라운드 — 마지막 2라운드에서 텍스트 응답 강제 (1M 컨텍스트 + `clear_tool_uses` 활용) |
| **Multi-turn** | 슬라이딩 윈도우 (max 200 turns) — 서버측 `clear_tool_uses`가 주 컨텍스트 관리, 클라이언트 제한은 안전망 |
| **LangSmith** | 토큰 수/비용을 RunTree에 기록, 세션 합산 |

<details>
<summary><strong>Advanced: Goal Decomposition / Error Recovery / Dynamic Graph / Signal Liveification / Plan Auto-Execute</strong></summary>

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

</details>

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
    W1 & W2 & W3 -->|SubAgentResult| TGD["Token Guard<br/>(unlimited, configurable)"]
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
| **Token Guard** | unlimited (0), configurable via GEODE_MAX_TOOL_RESULT_TOKENS | tool_result 제한 시 `summary`만 보존 |
| **as_completed** | polling round-robin | 먼저 끝난 태스크 결과 즉시 반환 |

에러 분류: `TIMEOUT`, `API_ERROR` (retryable) / `VALIDATION`, `RESOURCE`, `DEPTH_EXCEEDED` (non-retryable).

### 4-Tier Memory

계층적 메모리 시스템으로 분석 맥락을 조합합니다. 상위 tier의 값은 하위 tier에 의해 override됩니다.

```mermaid
graph TB
    Soul["SOUL.md<br/>(Organization Identity)"] --> UProf["Tier 0.5: User Profile<br/>preferences, timezone<br/>personalization context"]
    UProf --> Org["Tier 1: Organization<br/>Fixtures, immutable<br/>IP context, rubric"]
    Org --> Proj["Tier 2: Project<br/>.claude/MEMORY.md<br/>rules, insights (max 50)"]
    Proj --> Sess["Tier 3: Session<br/>In-memory, TTL 1h<br/>ephemeral analysis context"]
    Sess --> Asm["ContextAssembler<br/>→ _llm_summary (280 chars)"]

    style Soul fill:#1e293b,stroke:#06b6d4,color:#e2e8f0
    style UProf fill:#1e293b,stroke:#ec4899,color:#e2e8f0
    style Org fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style Proj fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style Sess fill:#1e293b,stroke:#8b5cf6,color:#e2e8f0
    style Asm fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
```

| Tier | 소스 | 영속성 | 용도 |
|------|------|--------|------|
| **SOUL** | `.claude/SOUL.md` | 영구 | 조직 미션, 원칙 |
| **User Profile** (0.5) | `~/.geode/user_profile/` | 파일 기반 | 사용자 선호, 타임존, 개인화 맥락 |
| **Organization** | `core/fixtures/*.json` | Read-only | IP context, rubric, 기대 결과 |
| **Project** | `.claude/MEMORY.md`, `.claude/rules/` | 파일 기반 | 학습된 규칙, 인사이트 (최대 50개, 회전) |
| **Session** | In-memory dict | TTL 1h | 현재 분석 컨텍스트, 체크포인트 |

`ContextAssembler`가 4-tier를 조합하여 `_llm_summary` (280자, SOUL 10% / Org 25% / Project 25% / Session 40% 예산)로 압축합니다.

<details>
<summary><strong>Prompt Assembly Pipeline</strong> — 5단계 프롬프트 조합 (ADR-007)</summary>

모든 노드(Analyst, Evaluator, Synthesizer, BiasBuster)는 동일한 5단계 조합 파이프라인(ADR-007)을 거쳐 LLM을 호출합니다.

```mermaid
graph LR
    T["Base Template<br/>prompts/*.md<br/>(10 templates)"] --> P0["Phase 0<br/>.format(**kwargs)"]
    P0 --> P1["Phase 1<br/>Prompt Override"]
    P1 --> P2["Phase 2<br/>Skill Injection<br/>(top 3, ≤500c)"]
    P2 --> P3["Phase 3<br/>Memory Context<br/>(_llm_summary, ≤300c)"]
    P3 --> P4["Phase 4<br/>Bootstrap Extra<br/>(5 × 100c)"]
    P4 --> Budget["Token Budget<br/>(hard limit 6000c)"]
    Budget --> AP["AssembledPrompt<br/>+ SHA-256[:12] hash"]
    AP --> Cache["cache_control:<br/>ephemeral"]
    Cache --> LLM["call_llm_parsed()<br/>→ Pydantic model"]

    style T fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style P0 fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style P1 fill:#1e293b,stroke:#8b5cf6,color:#e2e8f0
    style P2 fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style P3 fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style P4 fill:#1e293b,stroke:#06b6d4,color:#e2e8f0
    style Budget fill:#7c2d12,stroke:#f97316,color:#fed7aa
    style AP fill:#1e293b,stroke:#ec4899,color:#e2e8f0
    style Cache fill:#064e3b,stroke:#10b981,color:#6ee7b7
    style LLM fill:#f59e0b,stroke:#f59e0b,color:#fff
```

| 단계 | 입력 | 제한 | 설명 |
|------|------|------|------|
| **Phase 0** | `prompts/*.md` (9개 `.md` + `axes.py`) | — | `=== SYSTEM ===` / `=== USER ===` 구분자로 분리, `.format(**kwargs)` 렌더링 |
| **Phase 1** | `state._prompt_overrides` | append-only (기본) | 노드별 프롬프트 오버라이드. full replace opt-in |
| **Phase 2** | `SkillRegistry` | top 3, 500c/skill | `.claude/skills/` YAML frontmatter 기반 자동 발견, `node` + `role_type` 필터, priority 정렬 |
| **Phase 3** | `ContextAssembler._llm_summary` | 300c | 4-tier 메모리 압축 요약 주입 |
| **Phase 4** | `BootstrapManager._extra_instructions` | 5개 × 100c | 노드 사전 실행 컨텍스트 (pre-execution injection) |
| **Budget** | 전체 조합 결과 | hard limit 6000c, warning 4000c | 초과 시 truncation, 이벤트 기록 |

**노드 호출 패턴** — 모든 노드가 동일한 3단계를 따릅니다:

```mermaid
sequenceDiagram
    participant Node as Node (analyst, evaluator, ...)
    participant Asm as PromptAssembler
    participant LLM as Claude Opus 4.6

    Node->>Node: base_system = TEMPLATE.format(...)
    Node->>Node: base_user = TEMPLATE.format(...)
    Node->>Asm: assemble(base_system, base_user, state, node, role_type)
    Asm->>Asm: Phase 1-4 injection + budget check
    Asm-->>Node: AssembledPrompt (system, user, hash, fragments)
    Node->>LLM: call_llm_parsed(system, user, output_model=PydanticModel)
    LLM-->>Node: Typed result (AnalysisResult, EvaluatorOutput, ...)
```

| 호출 함수 | 출력 타입 | 용도 |
|-----------|----------|------|
| `call_llm_parsed()` | Pydantic model | **주력** — Anthropic `messages.parse()` 구조화 출력 |
| `call_llm()` | `str` | 텍스트 생성 (내러티브, 코멘터리) |
| `call_llm_json()` | `dict` | 레거시 JSON 파싱 (fallback) |

**무결성 보장**: 모든 템플릿에 SHA-256[:12] 핀 해시 저장. CI `verify_prompt_integrity()`로 의도치 않은 변경 감지 (Karpathy P4 Ratchet).

</details>

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
        Registry["ToolRegistry<br/>46 base tools"]
        Policy["PolicyChain"]
        SkillReg["SkillRegistry<br/>(auto-inject)"]
        MCPInstall["MCP Auto-Install<br/>(42 catalog)"]
    end

    subgraph MCPAdapters["MCP Adapters (4 active)"]
        Brave["Brave Search"]
        Steam["Steam MCP"]
        LI["LinkedIn Reader"]
        Mem["Memory MCP"]
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

- **46 base tools** — `web_fetch`, `general_web_search`, `youtube_search`, `read_document` 등 범용 도구 + `category`/`cost_tier` 메타데이터
- **MCP Adapters** — Brave Search, Steam, LinkedIn, Memory (env var 비어있으면 graceful skip)
- **MCP Server** — `uv run python -m core.mcp_server` 로 GEODE를 외부 에이전트에서 호출 가능 (6 tools, 2 resources)
- **Skills** — `.claude/skills/` 자동 발견 + YAML frontmatter 기반 도구 핫 리로드
- **MCP 자동설치** — `install_mcp_server` tool → 42개 카탈로그 검색 + 설치 + `refresh_tools()`

### Domain Plugin

`DomainPort` Protocol로 도메인별 분석 파이프라인을 플러그인으로 교체합니다. 동일한 자율 실행 하네스 위에 게임 IP, 금융, 콘텐츠 등 다양한 도메인 파이프라인을 탑재할 수 있습니다.

```python
# DomainPort Protocol — 도메인 플러그인 인터페이스
class DomainPort(Protocol):
    name: str; version: str; description: str
    def get_analyst_types(self) -> list[str]: ...
    def get_evaluator_types(self) -> list[str]: ...
    def get_scoring_weights(self) -> dict[str, float]: ...
    def get_tier_thresholds(self) -> dict[str, float]: ...
    def get_cause_values(self) -> list[str]: ...
    # ... 12 methods total
```

- **ContextVar 주입**: `set_domain()` / `get_domain()` — 런타임에 도메인 교체
- **동적 로딩**: `load_domain_adapter(name)` — 레지스트리 기반 임포트
- **확장**: `register_domain(name, path)` 후 `DomainPort` Protocol 구현체 교체

<details>
<summary><strong>Game IP Domain (Default Plugin)</strong> — 게임 IP 가치 평가 파이프라인 (LangGraph 9-node)</summary>

기본 탑재된 게임 IP 가치 평가 파이프라인. LangGraph StateGraph 기반 9-node 토폴로지.

```mermaid
graph LR
    START((START)) --> Router
    Router --> Signals["Signals<br/>(MCP → fixture fallback)"]
    Signals --> A["Analyst ×4<br/>(Send API, Clean Context)"]
    A --> E["Evaluator ×3<br/>(14-Axis Rubric)"]
    E --> Scoring["Scoring<br/>(PSM 6-Weighted)"]
    Scoring --> SkipCheck{"skip_check"}
    SkipCheck -->|"normal"| V["Verification<br/>(G1-G4 + BiasBuster)"]
    SkipCheck -->|"score ≥90 or ≤20"| Synth
    V -->|"confidence ≥ 0.7"| Synth["Synthesizer<br/>(Decision Tree + Narrative)"]
    V -->|"< 0.7"| Gather["gather"]
    Gather -->|"max 5 iter"| Signals
    Synth --> END((END))

    style START fill:#10b981,stroke:#10b981,color:#fff
    style END fill:#ef4444,stroke:#ef4444,color:#fff
    style SkipCheck fill:#f59e0b,stroke:#f59e0b,color:#fff
    style A fill:#3b82f6,stroke:#3b82f6,color:#fff
    style E fill:#8b5cf6,stroke:#8b5cf6,color:#fff
    style V fill:#ec4899,stroke:#ec4899,color:#fff
```

#### 4 Analysts (Send API 병렬)

| Analyst | 역할 | Clean Context |
|---------|------|---------------|
| `game_mechanics` | 게임 메커니즘 적합성 평가 | `analyses` 필드 제외 (앵커링 방지) |
| `player_experience` | 플레이어 경험/감성 분석 | 동일 |
| `growth_potential` | 성장 잠재력/시장 확장성 | 동일 |
| `discovery` | 발견 가능성/접근성 분석 | 동일 |

#### 3 Evaluators (14-Axis Rubric)

| Evaluator | 축 | 축 ID |
|-----------|-----|-------|
| `quality_judge` | 8축 | A, B, C, B1, C1, C2, M, N |
| `hidden_value` | 3축 | D (Discovery), E (Exposure), F (Fandom) |
| `community_momentum` | 3축 | J, K, L |

Prospect Mode (비게임화 IP): `prospect_judge` 1개 (9축: G, H, I, O, P, Q, R, S, T).

#### Scoring Formula

```
Final = (0.25×PSM + 0.20×Quality + 0.18×Recovery + 0.12×Growth + 0.20×Momentum + 0.05×Dev)
        × (0.7 + 0.3 × Confidence/100)

Tier: S ≥ 80, A ≥ 60, B ≥ 40, C < 40
```

#### Cause Classification (Decision Tree)

D-E-F 축 기반 코드 분류 (LLM이 아닌 룰 기반):

| 조건 | 분류 | 권장 조치 |
|------|------|----------|
| D≥3, E≥3 | `conversion_failure` | 전환 최적화 |
| D≥3, E<3 | `undermarketed` | 마케팅 강화 |
| D≤2, E≥3 | `monetization_misfit` | 수익 모델 재설계 |
| D≤2, E≤2, F≥3 | `niche_gem` | 니치 커뮤니티 육성 |
| D≤2, E≤2, F≤2 | `discovery_failure` | 노출 확대 |

#### Verification (5-Layer)

| Layer | 메커니즘 | 기준 |
|-------|----------|------|
| **G1-G4** | Schema, Range, Grounding, 2σ Consistency | 구조적 무결성 |
| **BiasBuster** | 6 bias types (REAE framework), CV-based fast path | CV < 0.05 → anchoring flag |
| **Cross-LLM** | Claude Opus 4.6 + GPT-5.4, Krippendorff's α | agreement ≥ 0.67 |
| **Confidence Gate** | 신뢰도 판정 | ≥ 0.7 → proceed, else loopback (max 5) |
| **Rights Risk** | IP 권리 리스크 | CLEAR / NEGOTIABLE / RESTRICTED |

#### Core Fixtures (golden set)

| IP | Tier | Score | Cause | Genre |
|----|------|-------|-------|-------|
| Berserk | S | 81.3 | conversion_failure | Dark Fantasy |
| Cowboy Bebop | A | 68.4 | undermarketed | SF Noir |
| Ghost in the Shell | B | 51.6 | discovery_failure | Cyberpunk |

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
| `GEODE_ENSEMBLE_MODE` | `single` | 앙상블 모드 (`single` / `cross`) |
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
uv run pytest                                        # 전체 (3088+ passed)
uv run pytest tests/test_e2e_live_llm.py -v -m live  # Live E2E
uv run ruff check core/ tests/                       # Lint
uv run mypy core/                                    # Type check (175 files)
uv run bandit -r core/ -c pyproject.toml             # Security
```

## Project Structure

```
core/
├── cli/                        # CLI + Agentic Loop + Sub-Agent
│   ├── __init__.py             # Typer app, REPL, pipeline execution
│   ├── agentic_loop.py         # while(tool_use) multi-round execution + Token Guard
│   ├── error_recovery.py       # ErrorRecoveryStrategy (retry → alternative → fallback → escalate)
│   ├── sub_agent.py            # SubAgentManager + SubAgentResult + ErrorCategory
│   ├── tool_executor.py        # Tool dispatch + HITL approval gate
│   ├── system_prompt.py        # System prompt builder for AgenticLoop
│   ├── conversation.py         # Multi-turn sliding-window (max 200 turns, server-side clear_tool_uses)
│   ├── bash_tool.py            # Shell execution + HITL safety gate
│   ├── batch.py                # Batch analysis (ThreadPoolExecutor)
│   ├── commands.py             # Slash command dispatch (21 commands)
│   ├── project_detect.py       # Project type auto-detection (7 types)
│   ├── search.py               # IP search engine (synonym expansion)
│   └── startup.py              # Readiness check, Graceful Degradation
├── config.py                   # Settings (pydantic-settings, 57 vars)
├── state.py                    # GeodeState (TypedDict + Pydantic models)
├── graph.py                    # LangGraph StateGraph + skip_check node
├── runtime.py                  # GeodeRuntime (production DI wiring)
├── infrastructure/
│   ├── ports/                  # LLMClientPort, SignalEnrichmentPort, DomainPort
│   └── adapters/
│       ├── llm/                # ClaudeAdapter, OpenAIAdapter
│       └── mcp/                # Steam, Brave, LinkedIn + CompositeSignalAdapter + catalog (42)
├── llm/                        # LLM client (prompt caching, streaming, cost tracking)
├── memory/                     # 4-Tier: SOUL → User Profile → Organization → Project → Session
├── nodes/                      # Pipeline nodes (router, signals, analyst, evaluator, scoring, verification, gather, synthesizer)
├── orchestration/
│   ├── hooks.py                # HookSystem (36 events + async atrigger)
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

Apache License 2.0 — [LICENSE](./LICENSE) 참조
