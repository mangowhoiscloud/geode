# GEODE 6-Layer Architecture 구현 계획서

> **목적**: 슬라이드 2 "GEODE 시스템 개요도"의 6-Layer 아키텍처를 실제 코드로 구현하기 위한 상세 설계서
> **작성 방법**: 4개 서브 에이전트(L1+L2, L3, L4+L4.5, L5+Tool)가 병렬 분석 → 통합
> **기준**: `docs/architecture-v6.md` (SOT)

---

## 아키텍처 개요 (슬라이드 2)

```
┌─────────────────────────────────────────────────────────────┐
│  L5: EXTENSIBILITY — Custom Agents, Plugins, Reports        │
├─────────────────────────────────────────────────────────────┤
│  L4.5: AUTOMATION — Trigger Manager, Snapshot (Peekaboo)    │
├─────────────────────────────────────────────────────────────┤
│  L4: ORCHESTRATION — Planner, Plan Mode, Task System, Hooks │
├─────────────────────────────────────────────────────────────┤
│  L3: AGENTIC CORE — Agent Loop, Analysts×4, Evaluators×3   │
├─────────────────────────────────────────────────────────────┤
│  L2: MEMORY — Organization > Project > Session              │
├─────────────────────────────────────────────────────────────┤
│  L1: FOUNDATION — MonoLake, LLM Clients, APIs, Skills      │
└─────────────────────────────────────────────────────────────┘

TOOL SYSTEM: register() | get() | list_tools()
├── DATA TOOLS: query_monolake, cortex_analyst, cortex_search
├── SIGNAL TOOLS: youtube_search, reddit_sentiment, twitch_stats, steam_info, google_trends
├── ANALYSIS TOOLS: run_analyst, run_evaluator, psm_calculate
├── MEMORY TOOLS: memory_search, memory_get, memory_save
└── OUTPUT TOOLS: generate_report, export_json, send_notification

ORCHESTRATION FLOW: User Input → Planner → Plan Mode → Task System → Hooks → Agent Loop
```

---

## 현재 구현 상태 (AS-IS)

| 계층 | 구현 수준 | 핵심 파일 |
|------|----------|----------|
| **L1: Foundation** | 30% — Anthropic만 동기 지원, fixture 하드코딩 | `llm/client.py`, `fixtures/__init__.py` |
| **L2: Memory** | 0% — 전혀 없음 | — |
| **L3: Agentic Core** | 70% — 단일 패스 선형 파이프라인 (Feedback Loop 없음) | `graph.py`, `nodes/*.py` |
| **L4: Orchestration** | 5% — 정적 router만 존재 | `nodes/router.py` |
| **L4.5: Automation** | 0% — 전혀 없음 | — |
| **L5: Extensibility** | 0% — 전혀 없음 | — |
| **Tool System** | 0% — 노드 함수만 존재, Tool Protocol 없음 | `nodes/*.py` |

**현재 동작**: 98 tests pass, 3 IPs (Berserk S/82.2, Cowboy Bebop A/69.4, Ghost in the Shell B/54.0)

---

## L1: FOUNDATION

### 1.1 LLM Client Layer (Multi-Provider Port/Adapter)

현재 `llm/client.py`는 Anthropic 동기 클라이언트만 지원. 아키텍처 스펙은 역할별 모델 배치를 요구:

| 역할 | 모델 | 용도 |
|------|------|------|
| Analyst, Evaluator, Synthesizer | Claude Opus | 깊은 추론 |
| Cortex Agent | GPT-5.2 | SQL 생성 정확도 |
| Planner | Gemini 3.0 Flash | 빠른 라우팅 |
| LLM Judge | Claude Sonnet | 비용 효율 평가 |
| Guardrail | Claude Haiku | 경량 검증 |

**구현 계획:**

```
geode/infrastructure/
├── ports/
│   └── llm_port.py          # LLMClientPort ABC (generate, generate_structured, generate_stream)
├── adapters/
│   └── llm/
│       ├── claude_adapter.py  # AsyncAnthropic 기반
│       ├── openai_adapter.py  # AsyncOpenAI 기반
│       └── gemini_adapter.py  # google-genai 기반
└── dependencies.py           # 싱글톤 팩토리 + 역할별 매핑
```

**핵심 인터페이스:**

```python
class LLMClientPort(ABC):
    async def generate(self, prompt: str, *, system_prompt: str | None = None) -> str: ...
    async def generate_structured(self, prompt: str, response_schema: type[T]) -> T: ...
    async def generate_stream(self, prompt: str) -> AsyncIterator[str]: ...
```

**싱글톤 + 역할 매핑 (`dependencies.py`):**

```python
def get_llm_for_role(role: str) -> LLMClientPort:
    role_map = {
        "analyst": get_claude_client("claude-opus-4-5-20250929"),
        "planner": get_gemini_client("gemini-3-flash-preview"),
        "cortex_agent": get_openai_client("gpt-5.2"),
        "judge": get_claude_client("claude-sonnet-4-20250514"),
        "guardrail": get_claude_client("claude-haiku-4-20250514"),
    }
    return role_map[role]
```

### 1.2 MonoLake Integration (DataPort Adapter)

현재 fixture 직접 호출 → Port/Adapter 패턴으로 전환:

```
geode/infrastructure/adapters/
├── fixture_adapter.py      # P0: FixtureDataAdapter (현재 동작 보존)
├── snowflake_adapter.py    # P1: SnowflakeDataAdapter (Cortex Agent SQL)
└── signal_adapter.py       # P1: ExternalSignalAdapter (YouTube/Reddit/Steam/Trends)
```

현재 `cortex_node`, `signals_node`가 `load_fixture()` 직접 호출 → adapter 주입 방식으로 변경.

### 1.3 Config 확장

```python
# geode/config.py 확장 필요
class Settings(BaseSettings):
    # 기존
    anthropic_api_key: str
    openai_api_key: str
    model: str

    # 신규 — 역할별 모델
    analyst_model: str = "claude-opus-4-5-20250929"
    planner_model: str = "gemini-3-flash-preview"
    cortex_model: str = "gpt-5.2"

    # 신규 — 인프라
    google_api_key: str = ""
    redis_url: str = "redis://localhost:6379/0"
    postgres_url: str = ""
    session_ttl_hours: int = 4
```

---

## L2: MEMORY

### 2.1 3-Tier Memory 계층

| 계층 | 저장소 | 범위 | 데모 구현 |
|------|--------|------|----------|
| Organization | MonoLake (Snowflake) | 전사 공통 IP 마스터 | fixture 기반 |
| Project | `.claude/MEMORY.md` + rules/ | 팀/프로젝트별 | 파일 시스템 |
| Session | Redis L1 + PostgreSQL L2 | 개별 세션 (4시간 TTL) | InMemoryDict |

```
geode/memory/
├── __init__.py       # MemoryLayer 통합 인터페이스
├── organization.py   # Organization Memory (fixture/Snowflake)
├── project.py        # Project Memory (.claude/MEMORY.md)
├── session.py        # Session Memory (InMemory | Redis+PG)
└── context.py        # Context Assembler (3계층 → LLM 프롬프트)
```

**Context Assembler**: LLM 호출 시 3계층에서 컨텍스트 조립

```python
class ContextAssembler:
    async def assemble(self, session_id: str, ip_name: str) -> dict:
        # Organization: IP 마스터 데이터 (SSOT)
        # Project: 팀 규칙, 가중치 오버라이드
        # Session: 현재 분석 중간 결과, 캐시
        # 우선순위: Project > Organization (루브릭 가중치)
```

### 2.2 Checkpoint (LangGraph)

현재 `graph.compile()` 체크포인터 미연결 → SqliteSaver 연결:

```python
# graph.py 수정
def compile_graph(checkpoint_db: str | None = None):
    graph = build_graph()
    if checkpoint_db:
        from langgraph.checkpoint.sqlite import SqliteSaver
        return graph.compile(checkpointer=SqliteSaver.from_conn_string(checkpoint_db))
    return graph.compile()
```

---

## L3: AGENTIC CORE — Gap Analysis

### 현재 구현됨 (7항목)

| 항목 | 파일 | 상태 |
|------|------|------|
| Agent Loop (Linear) | `graph.py` | START→router→cortex→signals→analyst×4→eval→score→verify→synth→END |
| Analysts ×4 (Send API, Clean Context) | `nodes/analysts.py` | game_mechanics, player_experience, growth_potential, discovery |
| Evaluators ×3 | `nodes/evaluators.py` | quality_judge, hidden_value, community_momentum |
| PSM Engine | `nodes/scoring.py` | ATT%, Z-value, Rosenbaum Gamma, 6 subscores, Tier |
| Synthesizer (Decision Tree) | `nodes/synthesizer.py` | D-E-F 프로파일 → 6유형 분류 |
| Guardrails G1-G4 | `verification/guardrails.py` | Schema, Range, Grounding, Consistency |
| BiasBuster 4-Step | `verification/biasbuster.py` | CV 기반 앵커링 탐지 + 편향 체크 |

### 미구현 Gap (8항목)

#### GAP-1: Feedback Loop (VERIFY → GATHER 재시도) — **P0 최우선**

**가장 중요한 Gap.** 현재는 단일 패스 선형 파이프라인이며, 아키텍처의 핵심인 반복적 Agent Loop이 없음.

```
현재:  VERIFY → (항상) → SYNTHESIZER
목표:  VERIFY → [confidence >= 0.7] → SYNTHESIZER
              → [confidence < 0.7 AND iteration < 3] → GATHER (루프백)
              → [iteration >= 3] → SYNTHESIZER (partial)
```

**구현:**

```python
# state.py 추가
class GeodeState(TypedDict, total=False):
    iteration: int          # 현재 반복 횟수 (기본 1)
    max_iterations: int     # 최대 반복 (기본 3)

# graph.py 수정
def _should_continue(state: GeodeState) -> str:
    confidence = state.get("analyst_confidence", 0)
    iteration = state.get("iteration", 1)
    if confidence >= 70.0 or iteration >= 3:
        return "synthesizer"
    return "cortex"  # LOOP BACK

graph.add_conditional_edges(
    "verification",
    _should_continue,
    {"synthesizer": "synthesizer", "cortex": "cortex"},
)
```

> **핵심 인사이트**: 이 변경이 GEODE를 "단순 파이프라인"에서 "Agentic Loop"으로 격상시키는 차별점. 없으면 "Agentic"이라는 이름에도 불구하고 single-pass linear pipeline.

#### GAP-2: Memory Context 조회 — P1

GATHER Phase 시작 시 Memory Layer 조회 → 이전 분석 결과 캐시 활용.

#### GAP-3: 데이터 신뢰성 체크 — P2

수집된 데이터의 신선도(freshness) 및 신뢰성 검증.

#### GAP-4: Cross-LLM Verification — P1

`verification/cross_llm.py` 존재하나 **완전한 placeholder** (mock agreement=0.82). `graph.py`에서 import조차 안 됨.

#### GAP-5: 권리 리스크 체크 (Sunrise 라이선스) — P1

IP 라이선스 상태 확인 기능 전무. `verification/rights_risk.py` 신규 생성 필요.

#### GAP-6: Confidence Threshold 0.7 적용 — P0

`scoring_node`에서 `_calc_analyst_confidence()`로 계산하지만, 0.7 threshold와 비교하여 재시도를 결정하는 로직 없음. GAP-1과 직접 연결.

#### GAP-7: Evaluators 병렬 실행 — P2

현재 순차 for loop → Send API 패턴으로 전환. 성능 최적화.

#### GAP-8: Cross-LLM Pipeline 통합 — P1

`cross_llm.py`를 `_verification_node()`에서 호출하도록 연결.

---

## L4: ORCHESTRATION

### 4.1 Planner

**모듈**: `geode/orchestration/planner.py`

Gemini 3.0 Flash를 사용하여 사용자 입력을 분석 → 6개 route 중 최적 선택:

| Route | 조건 | 비용 | 소요 시간 |
|-------|------|------|----------|
| `script_route` | /slash 커맨드 | $0.05 | ~15초 |
| `direct_answer` | Memory hit (10분 이내) | $0.02 | ~3초 |
| `data_refresh` | 데이터 TTL 만료 | $0.30 | ~45초 |
| `partial_rerun` | 특정 Aspect 재분석 | $0.15 | ~30초 |
| `prospect` | 비게임화 IP | $0.80 | ~80초 |
| `full_pipeline` | 기본 전체 분석 | $1.50 | ~120초 |

```python
class PlannerDecision(BaseModel):
    route: Literal["full_pipeline", "prospect", "direct_answer",
                    "partial_rerun", "data_refresh", "script_route"]
    intent: str
    requires_plan_mode: bool = False
    estimated_cost: str
    estimated_time: str
```

### 4.2 Plan Mode

**모듈**: `geode/orchestration/plan_mode.py`

복잡한 분석 요청 시: 계획 수립 → 사용자에게 제시 → 승인 후 실행

```
User Input → Planner.decide()
  ├── requires_plan_mode=False → Direct Execution (기존 StateGraph)
  └── requires_plan_mode=True → PlanMode Flow:
      1. PlanMode.create_plan() → 계획 수립
      2. 사용자에게 계획 제시 (Rich Panel)
      3. 승인 대기 (yes/no/modify)
      4. 승인 시 → TaskExecutor.execute_all()
```

### 4.3 Task System

**모듈**: `geode/orchestration/task_system.py`

복잡한 다중 IP 분석을 Task로 분해 + 의존성 그래프로 병렬/순차 실행:

```
단일 IP "Cowboy Bebop" 분석 시:
  task_1: Cortex 수집        [depends: 없음]  ─┐
  task_2: YouTube 신호       [depends: 없음]  ─┼─ 병렬
  task_3: Reddit 신호        [depends: 없음]  ─┤
  task_4: Twitch 신호        [depends: 없음]  ─┘
  task_5: Game Mechanics     [depends: 1-4]  ─┐
  task_6: Player Experience  [depends: 1-4]  ─┼─ 병렬 (Send API)
  task_7: Growth Potential   [depends: 1-4]  ─┤
  task_8: Discovery          [depends: 1-4]  ─┘
  task_9: Quality 평가       [depends: 5-8]  ─┐
  task_10: Hidden 평가       [depends: 5-8]  ─┼─ 병렬
  task_11: Community 평가    [depends: 5-8]  ─┘
  task_12: PSM + Scoring     [depends: 9-11]
  task_13: Synthesizer       [depends: 12]
```

### 4.4 Hook System

**모듈**: `geode/orchestration/hooks.py`

11종 이벤트, 우선순위 기반 핸들러 체인:

| 이벤트 | 시점 | 용도 |
|--------|------|------|
| `SESSION_START/END` | 세션 시작/종료 | 로깅, 리소스 관리 |
| `PRE/POST_ANALYSIS` | 분석 전후 | IP 유효성 검증, 결과 알림 |
| `PRE/POST_TOOL_USE` | Tool 호출 전후 | Rate limit, 캐싱 |
| `TASK_START/COMPLETE/FAIL` | Task 라이프사이클 | 진행률, 실패 알림 |
| `ON_ERROR` | 에러 발생 | Snapshot 캡처, 자동 복구 |

Hook 결과: `CONTINUE` (계속) | `ABORT` (중단) | `MODIFY` (데이터 수정 후 계속)

### 4.5 Orchestration Flow 통합

```python
class OrchestrationLayer:
    def __init__(self, foundation, memory, agent_core):
        self.planner = Planner(foundation, memory)
        self.plan_mode = PlanMode(foundation, memory)
        self.task_manager = TaskManager()
        self.hooks = HookSystem()

    async def process_request(self, session_id: str, user_input: str) -> dict:
        await self.hooks.trigger(SESSION_START)
        decision = await self.planner.decide(session_id, user_input)
        if decision.requires_plan_mode:
            plan = await self.plan_mode.create_plan(decision)
            return {"status": "awaiting_approval", "plan": plan}
        result = await self._execute_pipeline(decision)
        await self.hooks.trigger(POST_ANALYSIS)
        return result
```

**설계 원칙 충족:**

| Anthropic Tech Blog 원칙 | 구현 위치 |
|--------------------------|----------|
| Plan Before Execute | `plan_mode.py` — 계획 수립 → 승인 → 실행 |
| Event-Driven Control | `hooks.py` — 11종 이벤트, CONTINUE/ABORT/MODIFY |
| Task Decomposition | `task_system.py` — Dependency Graph 기반 분해 |
| User Approval Gate | `plan_mode.py` — 승인 대기 (yes/no/modify) |

---

## L4.5: AUTOMATION

### 5.1 Trigger Manager

4가지 트리거 유형 통합 디스패치:

| 유형 | 설명 | 예시 |
|------|------|------|
| Manual | CLI/Portal 수동 실행 | `geode analyze "Cowboy Bebop"` |
| Scheduled | CronTimer (매주 월 09:00) | 50개 IP 배치 스캔 |
| Event | Hook pipeline:complete | S-Tier 발견 시 리포트 자동 생성 |
| Webhook | External POST /hooks | MonoLake 데이터 갱신 알림 |

### 5.2 Snapshot Manager (Peekaboo)

OpenClaw 패턴 참조: 파이프라인 실행 시점 상태를 캡처, 디버깅/리플레이용.

```python
class SnapshotManager:
    async def capture(self, session_id, state) -> Snapshot:  # 메모리 저장, TTL 10분
    async def restore(self, snapshot_id) -> Snapshot:
    async def persist(self, snapshot_id, memory) -> bool:     # PostgreSQL 영구 저장
```

### 5.3 Pre-defined Automation

| ID | 이름 | 스케줄 | 용도 |
|----|------|--------|------|
| `weekly_discovery_scan` | 주간 IP 발굴 | 월 09:00 | 50개 IP 배치 |
| `calibration_drift_scan` | CUSUM Drift | 매일 06:00 | 모델 드리프트 탐지 |
| `outcome_tracker` | 성과 추적 | 매월 1일 | T+30/90일 실적 비교 |
| `auto_generate_report` | 자동 리포트 | Event 기반 | 분석 완료 → 리포트 |

---

## L5: EXTENSIBILITY + TOOL SYSTEM

### Tool Protocol & Registry

```python
# geode/tools/base.py
class Tool(Protocol):
    name: str
    description: str
    parameters: dict  # JSON Schema (LLM function calling 호환)
    async def execute(self, **kwargs) -> Any: ...

# geode/tools/registry.py
class ToolRegistry:
    def register(self, tool: Tool) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def list_tools(self) -> list[dict]: ...          # Anthropic/OpenAI 포맷 변환
    def to_anthropic_tools(self) -> list[dict]: ...
    def to_openai_tools(self) -> list[dict]: ...
```

### Tool Categories (5그룹, 17개 도구)

| 카테고리 | 도구 | 현재 상태 | 우선순위 |
|----------|------|----------|---------|
| **DATA** | `query_monolake` | Stub (fixture) | P0 |
| | `cortex_analyst` | Missing | P1 |
| | `cortex_search` | Missing | P2 |
| **SIGNAL** | `youtube_search` | Stub (fixture) | P1 |
| | `reddit_sentiment` | Stub (fixture) | P1 |
| | `twitch_stats` | Missing | P2 |
| | `steam_info` | Missing | P2 |
| | `google_trends` | Stub (fixture) | P1 |
| **ANALYSIS** | `run_analyst` | **Implemented** | P0 래핑 |
| | `run_evaluator` | **Implemented** | P0 래핑 |
| | `psm_calculate` | **Implemented** | P0 래핑 |
| **MEMORY** | `memory_search` | Missing (L2 미구현) | P1 |
| | `memory_get` | Missing | P1 |
| | `memory_save` | Missing | P1 |
| **OUTPUT** | `generate_report` | Partial (Rich 콘솔만) | P1 |
| | `export_json` | Missing | P1 |
| | `send_notification` | Missing | P2 |

### Custom Agents

`.claude/agents/anime_expert.md` 형태의 Markdown + YAML frontmatter로 커스텀 분석가 정의 → `SubagentLoader`가 파싱 → `AgentRegistry.register()` → LangGraph Send API 확장.

### Plugin System

```python
class Plugin(ABC):
    async def install(self) -> None: ...    # 의존성 설치
    async def activate(self) -> None: ...   # 레지스트리 등록
    async def deactivate(self) -> None: ... # 레지스트리 해제
    async def uninstall(self) -> None: ...  # 정리

class PluginManager:
    async def load_plugin(self, name: str) -> Plugin: ...
    async def unload_plugin(self, name: str) -> None: ...
```

### Report Generator

```python
class ReportGenerator:
    # 렌더러: HTMLRenderer (Jinja2), PDFRenderer (weasyprint), JSONRenderer
    async def generate(self, result: dict, fmt: ReportFormat, template: ReportTemplate) -> str | bytes
```

---

## 전체 디렉토리 구조 (TO-BE)

```
geode/
├── config.py                          # (수정) 역할별 모델, 인프라 URL
├── state.py                           # (수정) iteration, memory_context 필드 추가
├── graph.py                           # (수정) Feedback Loop, Checkpoint
├── cli.py                             # (수정) Orchestration Layer 연동
│
├── llm/
│   ├── client.py                      # (수정) 하위 호환 래퍼
│   └── prompts.py
│
├── nodes/                             # L3 (기존 유지)
│   ├── router.py                      # Planner가 pipeline_mode 설정
│   ├── cortex.py                      # (수정) adapter 주입
│   ├── signals.py                     # (수정) adapter 주입
│   ├── analysts.py
│   ├── evaluators.py
│   ├── scoring.py
│   └── synthesizer.py
│
├── verification/                      # L3 VERIFY
│   ├── guardrails.py
│   ├── biasbuster.py
│   ├── cross_llm.py                   # (수정) 실제 GPT 호출 + Pipeline 연결
│   └── rights_risk.py                 # (신규) 권리 리스크 체크
│
├── infrastructure/                    # L1 (신규)
│   ├── dependencies.py                # 싱글톤 팩토리
│   ├── rate_limiter.py
│   ├── ports/
│   │   ├── llm_port.py                # LLMClientPort ABC
│   │   └── signal_port.py             # SignalPort Protocol
│   ├── adapters/
│   │   ├── fixture_adapter.py         # Fixture DataPort
│   │   ├── snowflake_adapter.py       # Snowflake Cortex
│   │   ├── signal_adapter.py          # YouTube/Reddit/Steam/Trends
│   │   └── llm/
│   │       ├── claude_adapter.py
│   │       ├── openai_adapter.py
│   │       └── gemini_adapter.py
│   ├── checkpointer.py               # CachedPostgresSaver
│   └── migrations/
│       └── 001_initial.sql
│
├── memory/                            # L2 (신규)
│   ├── __init__.py                    # MemoryLayer 통합
│   ├── organization.py
│   ├── project.py
│   ├── session.py                     # InMemory + Redis+PG
│   └── context.py                     # Context Assembler
│
├── orchestration/                     # L4 (신규)
│   ├── __init__.py                    # OrchestrationLayer 통합
│   ├── planner.py                     # Gemini Flash 라우팅
│   ├── plan_mode.py                   # 계획-승인-실행 3단계
│   ├── task_system.py                 # Task 분해 + Dependency Graph
│   └── hooks.py                       # 11종 이벤트 시스템
│
├── automation/                        # L4.5 (신규)
│   ├── __init__.py
│   ├── triggers.py                    # 4-Trigger 통합
│   ├── predefined.py                  # 자동화 템플릿
│   └── snapshots.py                   # Peekaboo Snapshot
│
├── tools/                             # Tool System (신규)
│   ├── base.py                        # Tool Protocol
│   ├── registry.py                    # ToolRegistry
│   ├── data.py                        # DATA TOOLS (3개)
│   ├── signals.py                     # SIGNAL TOOLS (5개)
│   ├── analysis.py                    # ANALYSIS TOOLS (3개)
│   ├── memory.py                      # MEMORY TOOLS (3개)
│   └── output.py                      # OUTPUT TOOLS (3개)
│
├── extensibility/                     # L5 (신규)
│   ├── agents.py                      # AgentRegistry, CustomSubagent
│   ├── plugins.py                     # Plugin(ABC), PluginManager
│   └── reports.py                     # ReportGenerator (HTML/PDF/JSON)
│
├── templates/                         # 리포트 템플릿 (신규)
│   ├── summary.html.j2
│   ├── detailed.html.j2
│   └── base.html.j2
│
├── fixtures/                          # (기존 유지)
│   ├── __init__.py
│   ├── cowboy_bebop.json
│   ├── ghost_in_shell.json
│   └── berserk.json
│
└── ui/                                # (기존 유지)
    ├── console.py
    ├── panels.py
    └── streaming.py
```

---

## 구현 우선순위 로드맵

### P0: 데모 핵심 (아키텍처 정합성 확보)

| # | 작업 | 파일 | 근거 |
|---|------|------|------|
| 1 | **Feedback Loop** (VERIFY→GATHER) | `graph.py`, `state.py` | GAP-1: Agentic의 핵심 차별점 |
| 2 | **Confidence Threshold 0.7** | `graph.py` | GAP-6: Feedback Loop 조건 판단 |
| 3 | Tool Protocol + Registry | `tools/base.py`, `tools/registry.py` | 슬라이드 Tool System 대응 |
| 4 | Analysis Tools 래핑 | `tools/analysis.py` | 기존 노드를 Tool로 래핑 |
| 5 | LLMClientPort 정의 | `infrastructure/ports/llm_port.py` | Multi-provider 기반 |
| 6 | Claude Adapter | `infrastructure/adapters/llm/claude_adapter.py` | 비동기 전환 |
| 7 | Hook System 기본 | `orchestration/hooks.py` | 이벤트 인프라 |
| 8 | InMemory Session | `memory/session.py` | 데모용 메모리 |
| 9 | SqliteSaver Checkpoint | `graph.py` | 상태 복구 |

### P1: 프로덕션 MVP

| # | 작업 | 파일 | 근거 |
|---|------|------|------|
| 10 | Cross-LLM 실제 구현 + 통합 | `verification/cross_llm.py`, `graph.py` | GAP-4+8 |
| 11 | 권리 리스크 체크 | `verification/rights_risk.py` | GAP-5: 사업 의사결정 |
| 12 | Planner (Gemini Flash) | `orchestration/planner.py` | L4 진입점 |
| 13 | Plan Mode | `orchestration/plan_mode.py` | User Approval Gate |
| 14 | Task System | `orchestration/task_system.py` | 복잡한 분석 분해 |
| 15 | OpenAI/Gemini Adapter | `infrastructure/adapters/llm/` | Multi-provider |
| 16 | Memory Layer (Redis+PG) | `memory/` | 세션간 영속성 |
| 17 | Signal Tools (외부 API) | `tools/signals.py` | 실시간 데이터 |
| 18 | Report Generator | `extensibility/reports.py` | HTML/PDF/JSON |
| 19 | Trigger Manager | `automation/triggers.py` | 자동화 진입점 |

### P2: 향후 확장

| # | 작업 | 파일 | 근거 |
|---|------|------|------|
| 20 | Evaluators 병렬 (Send API) | `nodes/evaluators.py` | GAP-7: 성능 |
| 21 | 데이터 신뢰성 체크 | `nodes/cortex.py` | GAP-3: Production |
| 22 | Snowflake Adapter | `infrastructure/adapters/snowflake_adapter.py` | 실 DB 연동 |
| 23 | Plugin System | `extensibility/plugins.py` | Hot-reload |
| 24 | Custom Agents | `extensibility/agents.py` | 커스텀 분석가 |
| 25 | Pre-defined Automation | `automation/predefined.py` | 자동 스케줄 |
| 26 | Snapshot Manager | `automation/snapshots.py` | 디버깅/리플레이 |

---

## 의존성 추가 필요

```toml
# pyproject.toml
# P0 (이미 존재하는 것 활용)
# langgraph-checkpoint-sqlite >= 2.0.0  # 이미 있음

# P1 (프로덕션 MVP)
"httpx>=0.27.0"                          # HTTP 클라이언트 풀링
"google-genai>=1.0.0"                    # Gemini Adapter
"redis[hiredis]>=5.0.0"                  # Redis L1
"asyncpg>=0.30.0"                        # PostgreSQL L2
"jinja2>=3.1.0"                          # 리포트 템플릿

# P2 (향후)
"snowflake-connector-python>=3.0.0"      # Snowflake Cortex
"weasyprint>=62.0"                       # PDF 생성
"watchdog>=4.0.0"                        # Plugin hot-reload
```

---

## 핵심 인사이트 요약

1. **가장 중요한 Gap은 Feedback Loop (GAP-1 + GAP-6)**. 현재 "Agentic"이라는 이름에도 single-pass linear pipeline. VERIFY→GATHER 루프백이 있어야 진정한 Agent Loop.

2. **Tool System은 현재 노드 함수 래핑으로 시작**. 기존 `_run_analyst()`, `_run_evaluator()`, `_compute_psm()`을 Tool Protocol로 래핑하면 즉시 Tool Registry 구축 가능.

3. **동기→비동기 전환이 기술적 전제**. 현재 모든 LLM 호출이 동기. Tool Protocol의 `async execute()`와 L4 Orchestration의 `asyncio.gather()` 병렬을 위해 `AsyncAnthropic` 전환 필요.

4. **데모 vs 프로덕션 분리 전략 유지**. fixture 기반 데모가 잘 동작하므로, 프로덕션 adapter는 환경변수로 전환. `GEODE_DATA_ADAPTER=fixture|snowflake`.

5. **L4 Orchestration은 CLI 레벨에서 기존 StateGraph 위에 래핑**. StateGraph 자체는 변경 최소화하고, Planner/PlanMode/TaskSystem이 `initial_state`를 구성하여 기존 파이프라인에 전달.
