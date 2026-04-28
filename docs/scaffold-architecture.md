# GEODE Scaffold Architecture & Call Flow Documentation

> 작성일: 2026-03-31 | 출처: portfolio/geode v028 슬라이드 + workspace/geode/core 트리 분석

---

## 1. 포트폴리오 섹션 요약 (Part 1: Workflow + Part 2: System)

### Part 1 — Workflow (HE-0: SCAFFOLDING)

#### 1.1 CANNOT/CAN 이원 구조
- **Git/Branch 제약**: main/develop 직접 push 금지, worktree 없이 코드 작업 금지, 동기화 미확인 브랜치 생성 금지
- **코드 품질 제약**: lint/type/test 실패 커밋 금지, Plan 승인 없이 구현 착수 금지
- **문서/버전 제약**: CHANGELOG 누락 금지, 버전 번호 4곳 불일치 금지
- **CAN**: CANNOT에 없으면 자유 (단순 버그 수정은 Plan 없이, 도구 선택 자유, 커밋 언어 자유)

#### 1.2 8단계 Harness Engineering 루프
```
0.Worktree격리 → 1.GAP Audit → 2.Socratic 5문 → 3.Implement → 4.Verify(4인 리뷰) → 5.Docs → 6.PR → 7.Board(칸반)
```
- **GAP Audit**: 구현 전 코드베이스 실측 → 구현완료/부분구현/미구현 3분류
- **소크라틱 5문**: Q1(이미 있는가?) Q2(안하면 뭐가 깨지나?) Q3(측정 방법?) Q4(최소 구현?) Q5(프론티어 3종 합의?)
- **재귀 구조**: Step 4 실패 → Step 3, Step 6 실패 → Step 3 (전진만 하는 경로 없음)

#### 1.3 검증팀 4인 페르소나
| 페르소나 | 출처 | 점검 영역 |
|---------|------|----------|
| Kent Beck | XP/TDD | 테스트 커버리지, DRY, 과잉 추상화 |
| Andrej Karpathy | autoresearch | 컨텍스트 예산, 래칫, 제약 기반 설계 |
| Peter Steinberger | OpenClaw | Atomic write, 세션 격리, Failover, 플러그인 |
| Boris Cherny | Claude Code | 도구 라우팅, HITL, 서브에이전트, 프롬프트 |

#### 1.4 프론티어 패턴 마이닝
- **4종 소스**: autoresearch(Karpathy), OpenClaw(Steinberger), Claude Code(Cherny), Codex CLI(OpenAI)
- **채택 기준**: 3종 이상 동일 → 반드시 채택 / 2종 유사 → 핵심 추출 변형 / 1종만 → 소크라틱 재검증
- **리서치 시간 < 구현 시간** (Karpathy P3 고정 시간 예산)

#### 1.5 Compound Iteration Velocity
| Phase | 기간 | 커밋 | 릴리스 | 핵심 |
|-------|------|------|--------|------|
| 0 | 2/21-3/9 (18일) | 23 | 0 | 아키텍처 스캐폴딩 |
| 1 | 3/10-3/11 (2일) | 100 | 4 | MCP + Skills |
| 2 | 3/12-3/14 (3일) | 106 | 3 | 서브에이전트, Domain Plugin |
| 3 (Peak) | 3/15-3/16 (2일) | 209 | 7 | Identity Pivot (전체 32%) |
| 4 | 3/17-3/20 (4일) | 219 | 7 | 멀티 프로바이더, Gateway |

### Part 2 — System (HE-1: AUTONOMOUS)

#### 2.1 3-Tier 아키텍처
```
Orchestration → Agent → Pipeline
(에이전트는 파이프라인을 모름. analyze_ip 도구를 호출할 뿐)
```

#### 2.2 에이전틱 루프
- while(tool_use) 디스패치: LLM이 46개 도구 중 자율 선택
- 3경로 디스패치 + 4단계 오류 복구 + 3사 LLM Failover

#### 2.3 Port/Adapter DI (contextvars)
- 38개 Protocol 포트 → 13개 파일
- contextvars로 런타임 주입 (DI 프레임워크 불필요)
- 피봇 시 L0-L4 핵심 레이어 수정 0줄

#### 2.4 Prompt Assembly Pipeline (5단계)
```
0.System Base → 1.Skill Injection → 2.Tool Context → 3.Memory Context → 4.Agentic Suffix
```

#### 2.5 HookSystem (36 이벤트)
- PIPELINE_*, NODE_*, ANALYST_*, SUBAGENT_*, CONTEXT_*, GATEWAY_*, MCP_*, TOOL_RECOVERY_*
- 구독자: RunLog, DriftDetector, AgentReflection, ProjectJournal, NotificationHook

#### 2.6 큐 체인
```
CoalescingQueue(250ms 중복제거) → LaneQueue(세마포어 동시성) → IsolatedRunner(ThreadPool max5, 120s timeout)
```

#### 2.7 4단계 오류 복구
1. **Retry**: 지수 백오프 (1s/2s/4s)
2. **Alternative**: 같은 카테고리 다른 도구 자동 선택
3. **Fallback**: 저렴한 모델 tier 전환 (Opus→Sonnet→Haiku)
4. **Escalate**: 사용자 결정 요청 (WRITE/DANGEROUS는 항상 HITL)

#### 2.8 Gateway + 세션 격리
- ChannelManager: Slack/Discord/Telegram → ChannelBinding 정적 규칙 (LLM 0회)
- Session Key 3형식: `ip:{name}:{phase}`, `ip:{name}:subagent:{task_id}`, `gateway:{channel}:{channel_id}:{sender_id}`

#### 2.9 메모리 4-Tier Cascade
```
0.5 User Profile → 0.Organization(Fixture) → 1.Project(.claude/MEMORY.md) → 2.Session(InMemory+SQLite WAL)
```
- ContextAssembler가 전 계층 병합, 하위가 상위 오버라이드
- 1M 컨텍스트 전략: 80% WARNING(Haiku 압축) / 95% CRITICAL(기계적 prune)

---

## 2. core/ 스캐폴드 파일 구조 (6-Layer)

### Layer 0 — CLI/Entry (`core/cli/`)
```
cli/
├── __init__.py
├── _helpers.py          # CLI 유틸리티
├── agentic_response.py  # 에이전틱 응답 처리
├── bash_tool.py         # 쉘 명령 실행
├── batch.py             # 배치 분석
├── bootstrap.py         # CLI 부트스트랩
├── cmd_schedule.py      # 스케줄 명령
├── commands.py          # Typer 명령 정의 (진입점)
├── ip_names.py          # IP 이름 매핑
├── ipc_client.py        # IPC 클라이언트
├── pipeline_executor.py # 파이프라인 실행기
├── project_detect.py    # 프로젝트 감지
├── redaction.py         # 민감정보 마스킹
├── report_renderer.py   # 리포트 렌더링
├── result_cache.py      # 결과 캐시
├── search.py            # 검색 기능
├── session_checkpoint.py # 세션 체크포인트
├── session_state.py     # 세션 상태
├── startup.py           # 시작 시퀀스
├── tool_handlers.py     # 도구 핸들러
├── transcript.py        # 대화 기록
└── ui/                  # Rich 기반 UI
    ├── agentic_ui.py    # 에이전틱 UI
    ├── console.py       # 콘솔 출력
    ├── event_renderer.py # 이벤트 렌더링
    ├── mascot.py        # 마스코트 표시
    ├── panels.py        # 패널 레이아웃
    ├── status.py        # 상태 표시
    └── tool_tracker.py  # 도구 추적 UI
```

### Layer 1 — Agent (`core/agent/`)
```
agent/
├── agentic_loop.py      # ★ while(tool_use) 핵심 루프
├── conversation.py      # 대화 관리
├── error_recovery.py    # 4단계 오류 복구
├── safety_constants.py  # HITL 안전 상수
├── sub_agent.py         # 서브에이전트 매니저
├── system_prompt.py     # 시스템 프롬프트 빌더
├── tool_executor.py     # 도구 실행기 (3경로 디스패치)
└── worker.py            # 워커 스레드
```

### Layer 2 — Infrastructure (`core/infrastructure/`, `core/llm/`, `core/mcp/`)
```
infrastructure/
├── adapters/llm/        # LLM 어댑터 (빈 — llm/providers로 이동)
├── adapters/mcp/        # MCP 어댑터 (빈 — mcp/로 이동)
└── ports/               # 포트 인터페이스 (빈 — 각 모듈 port.py로 분산)

llm/
├── client.py            # ★ LLM 클라이언트 (멀티 프로바이더)
├── commentary.py        # 코멘터리 생성
├── errors.py            # LLM 에러 타입
├── fallback.py          # 3사 Failover 체인
├── prompt_assembler.py  # ★ 5단계 프롬프트 조립
├── prompts/             # 프롬프트 템플릿 (.md)
├── providers/           # Anthropic, OpenAI, GLM 어댑터
├── router.py            # 모델 라우터
├── skill_registry.py    # 스킬 레지스트리
├── token_tracker.py     # 토큰 사용량 추적
└── usage_store.py       # 사용량 저장소

mcp/
├── base.py              # MCP 베이스 클래스
├── manager.py           # ★ MCP 서버 매니저
├── stdio_client.py      # stdio 클라이언트
├── catalog.py           # MCP 카탈로그
├── *_adapter.py         # 각 서비스 어댑터 (Slack, Discord, Telegram, Steam, Calendar...)
├── *_port.py            # 포트 인터페이스 (Calendar, Notification, Signal)
└── composite_*.py       # 복합 어댑터 (Calendar, Notification, Signal)
```

### Layer 3 — Memory (`core/memory/`)
```
memory/
├── agent_memory.py      # 에이전트 메모리 통합
├── context.py           # ★ ContextAssembler (4-Tier 병합)
├── hybrid_session.py    # HybridSession (InMemory + SQLite WAL)
├── journal_hooks.py     # 저널 훅
├── organization.py      # Organization 메모리 (Tier 0)
├── port.py              # 메모리 포트 인터페이스
├── project.py           # Project 메모리 (Tier 1)
├── project_journal.py   # 프로젝트 저널
├── session.py           # Session 메모리 (Tier 2)
├── session_key.py       # 세션 키 생성
├── session_manager.py   # 세션 매니저
├── user_profile.py      # User Profile (Tier 0.5)
└── vault.py             # 시크릿 볼트
```

### Layer 4 — Orchestration (`core/orchestration/`)
```
orchestration/
├── bootstrap.py         # 오케스트레이션 부트스트랩
├── compaction.py        # ★ 컨텍스트 압축 (80%/95%)
├── context_monitor.py   # 컨텍스트 모니터
├── goal_decomposer.py   # 목표 분해기
├── hot_reload.py        # 핫 리로드
├── isolated_execution.py # 격리 실행 (ThreadPool)
├── lane_queue.py        # ★ LaneQueue (세마포어 동시성)
├── plan_mode.py         # 플랜 모드
├── planner.py           # 플래너
├── run_log.py           # 실행 로그
├── stuck_detection.py   # 스턱 감지
├── task_bridge.py       # 태스크 브릿지
└── task_system.py       # ★ TaskGraph DAG (13-task)
```

### Layer 5 — Extensibility (`core/hooks/`, `core/skills/`, `core/tools/`)
```
hooks/
├── approval_tracker.py  # 승인 추적
├── context_action.py    # 컨텍스트 액션
├── discovery.py         # 훅 디스커버리
├── system.py            # ★ HookSystem (36 이벤트)
└── plugins/notification_hook/  # 알림 훅 플러그인

skills/
├── _frontmatter.py      # 프론트매터 파서
├── agents.py            # 에이전트 스킬
├── plugins.py           # 플러그인 스킬
├── reports.py           # 리포트 스킬
├── skills.py            # ★ 스킬 로더/매처
└── templates/           # 리포트 템플릿 (HTML, MD)

tools/
├── analysis.py          # 분석 도구
├── base.py              # 도구 베이스
├── calendar_tools.py    # 캘린더 도구
├── data_tools.py        # 데이터 도구
├── definitions.json     # 도구 정의 (46개)
├── document_tools.py    # 문서 도구
├── mcp_tools.json       # MCP 도구 스키마
├── memory_tools.py      # 메모리 도구
├── output_tools.py      # 출력 도구
├── policy.py            # ★ 도구 정책 (HITL 5-tier)
├── profile_tools.py     # 프로필 도구
├── registry.py          # ★ ToolRegistry
├── signal_tools.py      # 시그널 도구
├── tool_schemas.json    # 도구 스키마
└── web_tools.py         # 웹 도구
```

### Layer 6 — Domain Plugin (`core/domains/`)
```
domains/
├── loader.py            # 도메인 로더
├── port.py              # DomainPort 인터페이스
└── game_ip/             # 게임 IP 분석 플러그인
    ├── adapter.py       # DomainPort 구현체
    ├── config/          # 평가 축, 원인-행동 매핑
    ├── fixtures/        # 골든셋 + Steam 데이터 (200+)
    └── nodes/           # LangGraph 노드
        ├── router.py    # IP 라우터
        ├── signals.py   # 시그널 수집
        ├── analysts.py  # 4인 분석가
        ├── evaluators.py # 3인 평가자
        ├── scoring.py   # PSM 스코어링
        └── synthesizer.py # 종합 리포트
```

### Cross-cutting (`core/gateway/`, `core/automation/`, `core/verification/`)
```
gateway/
├── auth/                # 인증 (cooldown, profiles, rotation)
├── channel_manager.py   # ★ 채널 라우팅 (Most-Specific Wins)
├── models.py            # 게이트웨이 모델
├── pollers/             # Slack/Discord/Telegram/CLI 폴러
├── shared_services.py   # 공유 서비스
├── slack_formatter.py   # Slack 포맷터
└── webhook_handler.py   # 웹훅 핸들러

automation/
├── calendar_bridge.py   # 캘린더 브릿지
├── correlation.py       # 상관관계 분석
├── drift.py             # 드리프트 감지
├── expert_panel.py      # 전문가 패널
├── feedback_loop.py     # 피드백 루프
├── model_registry.py    # 모델 레지스트리
├── nl_scheduler.py      # 자연어 스케줄러
├── outcome_tracking.py  # 결과 추적
├── predefined.py        # 사전 정의 작업
├── scheduler.py         # ★ APScheduler 래퍼
├── snapshot.py          # 스냅샷
└── triggers.py          # 트리거

verification/
├── biasbuster.py        # 편향 감지
├── calibration.py       # 캘리브레이션
├── cross_llm.py         # Cross-LLM 검증
├── guardrails.py        # 가드레일
├── rights_risk.py       # 권리 리스크
└── stats.py             # 통계
```

### Root-level (`core/`)
```
core/
├── config.py            # 설정 로더 (config.toml)
├── graph.py             # ★ LangGraph StateGraph 정의
├── paths.py             # 경로 상수
├── runtime.py           # ★ 런타임 (부트스트랩 → 실행)
├── runtime_wiring/      # DI 와이어링
│   ├── adapters.py      # 어댑터 바인딩
│   ├── automation.py    # 자동화 바인딩
│   ├── bootstrap.py     # 부트스트랩 시퀀스
│   └── infra.py         # 인프라 바인딩
├── state.py             # 전역 상태
└── mcp_server.py        # GEODE를 MCP 서버로 노출
```

---

## 3. 핵심 호출 흐름 (Call Flow)

### 3.1 CLI 진입 → 에이전틱 루프
```
cli/commands.py (Typer app)
  → cli/bootstrap.py (초기화)
    → runtime.py (Runtime.boot)
      → runtime_wiring/bootstrap.py (DI 와이어링)
        → config.py (config.toml 로드)
        → runtime_wiring/adapters.py (LLM/MCP 어댑터 바인딩)
        → runtime_wiring/infra.py (인프라 바인딩)
        → runtime_wiring/automation.py (스케줄러/트리거 바인딩)
  → cli/startup.py (시작 시퀀스)
    → mcp/manager.py (MCP 서버 연결)
    → skills/skills.py (스킬 로드)
    → memory/context.py (ContextAssembler 초기화)
  → agent/agentic_loop.py ★ (while tool_use 루프 시작)
```

### 3.2 에이전틱 루프 내부
```
agent/agentic_loop.py
  while True:
    1. llm/prompt_assembler.py → 5단계 프롬프트 조립
    2. llm/client.py → LLM API 호출 (providers/anthropic|openai|glm)
    3. if response.has_tool_use:
         agent/tool_executor.py → 3경로 디스패치:
           a. tools/registry.py → 내장 도구 실행
           b. mcp/manager.py → MCP 도구 실행
           c. agent/sub_agent.py → 서브에이전트 위임
    4. if error:
         agent/error_recovery.py → 4단계 복구
    5. hooks/system.py → 이벤트 발행
    6. memory/context.py → 컨텍스트 업데이트
    7. orchestration/context_monitor.py → 토큰 체크
         → orchestration/compaction.py (80%/95% 압축)
    8. if no more tool_use: break → 최종 응답
```

### 3.3 도메인 파이프라인 (analyze_ip 호출 시)
```
tools/analysis.py (analyze_ip 핸들러)
  → domains/loader.py → domains/game_ip/adapter.py
    → graph.py (LangGraph StateGraph 실행)
      → nodes/router.py (IP 분류)
      → nodes/signals.py (시그널 수집: Steam, YouTube, Reddit, Trends)
      → nodes/analysts.py (4인 분석가 병렬 실행)
      → nodes/evaluators.py (3인 평가자)
      → nodes/scoring.py (PSM 스코어링)
      → verification/cross_llm.py (Cross-LLM 검증)
      → verification/biasbuster.py (편향 감지)
      → nodes/synthesizer.py (종합 리포트)
    → hooks/system.py (PIPELINE_END 이벤트)
    → memory/project.py (MEMORY.md 자동 학습)
```

### 3.4 Gateway 인바운드 흐름
```
gateway/pollers/slack_poller.py (데몬)
  → gateway/channel_manager.py (ChannelBinding 라우팅)
    → orchestration/lane_queue.py (세션별 직렬 + 전역 x4)
      → orchestration/isolated_execution.py (ThreadPool 격리)
        → agent/agentic_loop.py (에이전틱 루프)
          → ... (3.2와 동일)
        → gateway/slack_formatter.py (응답 포맷)
      → hooks/system.py (GATEWAY_RESPONSE_SENT)
```

### 3.5 스케줄/자동화 흐름
```
automation/scheduler.py (APScheduler)
  → automation/nl_scheduler.py (자연어 → cron 변환)
  → automation/triggers.py (이벤트 트리거)
    → agent/agentic_loop.py (자율 실행)
  → automation/calendar_bridge.py (캘린더 동기화)
```

---

## 4. .geode/ 설정 구조
```
.geode/
├── config.toml          # 메인 설정 (MCP 서버, 모델, 도메인)
├── MEMORY.md            # 프로젝트 메모리 (자동 학습)
├── LEARNING.md          # 학습 기록
├── memory/              # 영속 메모리 파일
├── models/              # 모델 설정
├── reports/             # 생성된 리포트
├── rules/               # 분석 규칙 (.md)
├── skills/              # 커스텀 스킬 (.md)
└── vault/               # 시크릿 저장소
```

---

## 5. 칸반 + 워크플로우 시스템 (자체 개발)

### 5.1 3-Checkpoint 칸반
REODE에서 이식한 칸반 시스템:
- **alloc**: 작업 할당 (worktree 생성 + .owner 소유권)
- **free**: 작업 해제 (worktree 정리)
- **session-start**: 세션 시작 (컨텍스트 로드)

### 5.2 Board 갱신 규칙
- Step 7에서 칸반 갱신 (8단계 루프의 마지막)
- Backlog → Done 직행 금지 (반드시 In Progress 거쳐야 함)
- main-only progress.md 편집 (브랜치에서 편집 금지)

### 5.3 TaskGraph DAG
- 13-task 의존성 그래프
- 위상 정렬 → 배치 실행
- 실패 전파 (하위 태스크 자동 취소)
- LangGraph StateGraph와 독립 (에이전트 레벨 복합 요청 분해용)

### 5.4 워크플로우 자동화
- `orchestration/task_system.py`: TaskGraph DAG 관리
- `orchestration/plan_mode.py`: 플랜 모드 (create → approve/reject)
- `orchestration/goal_decomposer.py`: 목표 → 서브태스크 분해
- `orchestration/stuck_detection.py`: 스턱 감지 → 자동 복구

---

## 6. 정리 완료 기록 (2026-03-31)

### 6.1 빈 디렉토리 제거 완료
- [x] `core/infrastructure/` 전체 제거 — Port/Adapter가 각 모듈 port.py로 분산 완료 (hexagonal arch 자연 진화)
- [x] `core/agent/adapters/` 제거 — 빈 디렉토리
- [x] `core/ui/` 제거 — 실제 UI는 `core/cli/ui/`에 통합

### 6.2 중복 구조 해소
- `core/ui/` vs `core/cli/ui/` → `core/ui/` 제거, `core/cli/ui/`로 단일화
- `hooks/plugins/notification_hook/` — 유일한 위치 확인 (중복 없음)

### 6.3 Layer 매핑 최종 결론
- `core/infrastructure/` 디렉토리 제거 → Port/Adapter는 각 모듈에 분산 (의도된 설계)
  - `core/memory/port.py`, `core/domains/port.py`, `core/mcp/*_port.py` 등
  - contextvars 기반 DI이므로 중앙 infrastructure 디렉토리 불필요
- import 참조 검증 완료: `core.infrastructure` 참조는 openai.py 주석 1건뿐 (실제 import 없음)

### 6.4 현재 정돈된 6-Layer 구조
```
core/
├── cli/          # L0: CLI/Entry (Typer + Rich UI)
├── agent/        # L1: Agent (AgenticLoop, SubAgent, ErrorRecovery)
├── llm/          # L2a: LLM Infrastructure (Client, Providers, PromptAssembler)
├── mcp/          # L2b: MCP Infrastructure (Manager, Adapters, Ports)
├── memory/       # L3: Memory (4-Tier Cascade, ContextAssembler)
├── orchestration/# L4: Orchestration (Compaction, LaneQueue, TaskGraph, Planner)
├── hooks/        # L5a: Extensibility - Hooks (36 events, plugins)
├── skills/       # L5b: Extensibility - Skills (loader, templates)
├── tools/        # L5c: Extensibility - Tools (46 tools, registry, policy)
├── domains/      # L6: Domain Plugins (game_ip)
├── gateway/      # Cross: Gateway (Channel routing, pollers, auth)
├── automation/   # Cross: Automation (scheduler, triggers, drift)
├── verification/ # Cross: Verification (cross-llm, bias, calibration)
├── runtime_wiring/ # Boot: DI wiring (adapters, infra, automation)
├── config.py     # 설정 로더
├── graph.py      # LangGraph StateGraph
├── runtime.py    # 런타임 부트스트랩
├── state.py      # 전역 상태
├── paths.py      # 경로 상수
└── mcp_server.py # GEODE as MCP server
```
