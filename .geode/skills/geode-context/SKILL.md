---
name: geode-context
visibility: public
description: GEODE 프로젝트 핵심 기술 증류. 6-Layer Architecture, AgenticLoop, HookSystem, Memory, Verification, Fault Tolerance, Prompt Engineering, Sub-Agent, Automation. 이력서/커버레터 작성 시 기술 근거 참조. "geode", "harness", "에이전트", "agent", "파이프라인", "pipeline" 키워드로 트리거.
---

# GEODE — 범용 자율 실행 에이전트 (기술 증류)

## 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 기간 | 2026.02 - 현재 |
| 목적 | LangGraph 기반 범용 자율 실행 에이전트 |
| 규모 | ~54K LOC, 192 모듈, 3,540+ tests, 592 PR |
| 도구 | Python 3.12+, uv, ruff, mypy strict, pytest |
| LLM | Claude Opus 4.6 (Primary) + OpenAI GPT-5.4 (Cross-LLM) |
| 하네스 | Claude Code (Opus 4.6) — 전체 설계·구현·테스트 단독 수행 |

---

## 1. Architecture

### 4-Layer Stack (Model → Runtime → Harness → Agent)

```
AGENT:    AgenticLoop (while tool_use), SubAgentManager, CLIPoller, Gateway
HARNESS:  SessionLane, LaneQueue(global:8), PolicyChain, TaskGraph, HookSystem(42 events)
RUNTIME:  ToolRegistry(52), MCP Catalog(44), Skills, Memory(4-Tier), Reports
MODEL:    ClaudeAdapter, OpenAIAdapter, GLMAdapter (3-provider fallback)
─────────────────────────────────────────────────────────────────
⊥ DOMAIN: DomainPort Protocol, GameIPDomain (cross-cutting, binds to Runtime + Harness via Port)
```

### Hexagonal Architecture (Port/Adapter)

- **Port**: `@runtime_checkable Protocol` — LLMClientPort, HookSystemPort, SessionStorePort, DomainPort
- **Adapter**: ClaudeAdapter, OpenAIAdapter, MockAdapter
- **효과**: 비즈니스 로직이 Provider를 모름 → 런타임 어댑터 교체로 모델/인프라 전환

### Runtime Factory Pattern

- `AgentRuntime.create()` — 20+ 컴포넌트 결정론적 조립
- 6 Sub-builders: hooks, memory, automation, task_graph, prompt_assembler, auth
- 명시적 의존성 순서 보장

---

## 2. Agentic Loop & Orchestration

### AgenticLoop — while(tool_use) 자율 실행

- LLM `stop_reason == "tool_use"` 동안 도구 호출 → 결과 피드백 → 자기수정 반복
- `max_rounds=15`, `ConversationContext` 20턴 슬라이딩 윈도우
- NL Router의 시스템 프롬프트를 AgenticLoop이 상속

### Plan-and-Execute DAG (vs ReAct)

- 고정 토폴로지 DAG + Send API 병렬 (analysts×4, evaluators×3)
- ReAct 대비: O(nodes) vs O(steps), 예측 가능, 도메인 지식 재발견 불필요
- Confidence Gate < 0.7 → gather → signals 루프백 (최대 5회)

### Goal Decomposition

- 복합 요청 → 2단계 휴리스틱(70-80% LLM 미호출) → Haiku $0.01 DAG 생성
- 시스템 프롬프트 주입 방식 (서브에이전트 생성 없이 실행)

### PlanMode State Machine

- DRAFT → PRESENTED → APPROVED → EXECUTING → COMPLETED
- 6-Route Classification: SCRIPT($0.05) ~ FULL_PIPELINE($1.50)

### NL Router 3-Stage Fallback

- LLM Tool Use(0.95) → Scored Pattern Matching(0.5-0.8) → Help(0.3)
- Hybrid: startswith("/") → 결정론적 COMMAND_MAP 28종, 나머지 → AgenticLoop

---

## 3. Memory Systems

### 3-Tier Hierarchical Memory

- Organization(전사 불변) → Project(MEMORY.md, 규칙/인사이트) → Session(인메모리 TTL)
- ContextAssembler: dict.update() 순서 override + freshness threshold(3600s)
- Clean Context: 병렬 분석자에게 analyses 필드 제거 전달 (앵커링 방지)

### Write-Through Hybrid L1/L2 Session Store

- L1: 인메모리 dict(TTL + lazy eviction)
- L2: 파일 기반(checkpoint)
- Write-through 일관성

### ContextVar-Based DI

- `contextvars.ContextVar`로 인프라 주입 — LangGraph 노드 시그니처 오염 없이 DI
- Thread-safe, async-safe

---

## 4. Prompt Engineering

### PromptAssembler 6-Phase (ADR-007)

1. Prompt Override (append-only)
2. Skill Fragment Injection
3. Memory Context (300char 상한)
4. Bootstrap Instructions
5. Token Budget (6000char hard, 4000char warning)
6. Hash + Event (SHA-256 무결성 + 캐시 키)

### Prompt Caching

- SHA-256 해시 안정성 → Anthropic prompt caching 활성화
- 반복 호출 시 90% 비용 절감 (cache read = input × 0.10)

### Structured Output

- Anthropic `messages.parse()` + 평가자별 Pydantic 모델 → 14-axis rubric 강제
- Generation-time 스키마 검증

---

## 5. Verification & Evaluation

### Swiss Cheese 다층 검증 (5-Layer)

1. **Guardrails G1-G4**: Schema, Range, Grounding, 2σ Consistency
2. **BiasBuster 6-Bias**: Recency, Extremity, Anchoring, Egocentric, Availability, Certainty (CV < 0.05 감지)
3. **Cross-LLM**: Anthropic vs OpenAI 병렬 → Krippendorff's α ≥ 0.67
4. **Confidence Gate**: ≥ 0.7 통과, else 약한 축 선별 재분석 (max 5)
5. **Rights Risk**: CLEAR / NEGOTIABLE / RESTRICTED / EXPIRED / UNKNOWN

### Scoring

- 6-Weighted Composite: 25% PSM + 20% Quality + 18% Recovery + 12% Growth + 20% Momentum + 5% Dev
- Confidence Multiplier: `final = base × (0.7 + 0.3 × confidence/100)`
- Decision Tree: D-E-F 축 code-only 원인 분류 (LLM 미사용)

---

## 6. Fault Tolerance

### Circuit Breaker 3-State

- Closed → Open(5회 실패) → Half-Open(60s 후 프로브)

### 4-Stage Failover

- Retry(exponential+jitter) → Fallback Chain(Opus→Sonnet→Haiku) → Circuit Break → Recovery

### Degraded Response

- `is_degraded=True` + 최소 점수 주입 → 단일 노드 실패 시 파이프라인 유지

### Error Recovery Strategy

- Retry → Alternative Tool → Fallback → Escalate (도구별 정책)

---

## 7. Observability

### 42-Event Hook Observer

- Pipeline(3), Node(4), Analysis(3), Verification(2), Automation(6), Memory(4), SubAgent(5), ToolRecovery(2), Context(4), Session(2), LLM(3), ToolApproval(2), ModelSwitch(1), TurnComplete(1)
- Hooked Node Wrapper: 순수 노드 함수를 데코레이터로 감싸 자동 이벤트 발행
- Priority-Based Handler: 낮은 priority 먼저 실행 (30→50→90)

### Task Graph DAG

- 13-task DAG + 6-state machine (PENDING→READY→RUNNING→COMPLETED→FAILED→SKIPPED)
- Observer over Controller: Hook 수신만, StateGraph 제어 안 함
- propagate_failure() BFS → 하류 SKIP

### RunLog JSONL Audit Trail

- per-run JSONL, 2000-line/2MB auto-pruning

### Stuck Detection

- 7200s 타임아웃, 60s 체크 간격, auto-release + PIPELINE_ERROR

---

## 8. Concurrency & Queue

### CoalescingQueue

- 250ms debounce, Timer 리셋, 동일 task_id 중복 병합

### Lane Queue 2-Level

- SessionLane(per-key serial, max_sessions=256) + Lane("global", max=8, 병렬)
- Ordered acquire(session→global), reverse release → 데드락 방지

---

## 9. Tool & Skill Management

### 3-Source Tool Registry

- definitions.json(47) + ToolRegistry(52) + MCP Catalog(44), name dedup

### Deferred Tool Loading

- >5 tools → tool_search 메타 도구 → 85% 토큰 절감

### PolicyChain

- AND-combined, NodeScopePolicy(노드별 화이트리스트), Dry-Run Cost Protection
- PolicyAuditResult로 차단 사유 추적

### Tool Safety 4-Tier

- SAFE → STANDARD → DANGEROUS(HITL 필수) → MCP_FALLBACK

### Progressive Disclosure

- 스킬 메타데이터만 초기 인지 → 의도 파악 후 전체 프롬프트 주입
- SkillRegistry 8000char 버짓

---

## 10. Sub-Agent System

### SubAgentManager

- Lane("global", max=8), timeout 120s, max_depth=1, max_total=15
- 부모 tools/MCP/skills/memory 전체 상속

### Token Guard

- SubAgentResult 출력 토큰 초과 시 summary + 경량 필드만 보존
- 부모 컨텍스트 폭발 방지

---

## 11. Automation

### CUSUM Drift Detection

- WARNING=2.5, CRITICAL=4.0, slack parameter k
- DRIFT_DETECTED Hook → 스냅샷 캡처

### 4-Phase RLHF Feedback Loop

- Collection(n≥30) → Analysis(Spearman ρ) → Improvement(가중치 조정) → Validation

### Model Registry

- Staging → Canary → Production, MODEL_PROMOTED Hook

---

## 12. 하네스 워크플로우 인프라 (.claude/ 디렉토리 체계)

GEODE의 .claude/ 디렉토리 전체가 하네스의 "컨텍스트 뼈대"이며, 이 구조 자체가 하네스 엔지니어링의 실체.

### .claude/ 디렉토리 구조

```
.claude/
├── MEMORY.md          # 프로젝트 메모리 (3-Tier 최상위, 분석 인사이트 자동 기록)
├── SOUL.md            # 조직 아이덴티티 (미션, 5대 원칙, Guardrails, 도메인 플러그인 목록)
├── settings.json      # 도구 권한 (Bash uv run 허용 등)
├── mcp_servers.json   # 5개 MCP 어댑터 (brave-search, steam, arxiv, playwright, linkedin)
├── rules/             # 도메인 규칙 (anime-ip, dark-fantasy, indie-steam, schedule-date-aware)
├── skills/            # 12개 스킬 + 4개 분석자 프롬프트
│   ├── geode-pipeline/         # StateGraph 토폴로지, Send API, Reducer
│   ├── geode-scoring/          # PSM Engine, 14-axis rubric, 최종 스코어 공식
│   ├── geode-analysis/         # 4 Analysts + 3 Evaluators, Clean Context
│   ├── geode-verification/     # G1-G4, BiasBuster, Decision Tree
│   ├── geode-e2e/              # Mock/Live 테스트 티어, LangSmith 검증
│   ├── geode-gitflow/          # feature→develop→main, Pre-PR 5-Step Quality Gate
│   ├── geode-changelog/        # Keep a Changelog, SemVer
│   ├── agent-ops-debugging/    # 5 디버깅 패턴 (Safe Default, ContextVar 생명주기 등)
│   ├── karpathy-patterns/      # autoresearch/AgentHub 10대 설계 원칙
│   ├── openclaw-patterns/      # Gateway, Session Key, Lane Queue, Policy Chain
│   ├── architecture-patterns/  # Clean Architecture, Hexagonal, DDD
│   ├── tech-blog-writer/       # 기술 블로그 작성 가이드
│   └── geode-analysts/         # 4개 분석자별 프롬프트 (discovery, mechanics, experience, growth)
└── worktrees/         # Git worktree 격리 작업 공간 (.gitignored)
```

### Worktree 기반 병렬 개발

- `git worktree add .claude/worktrees/<name> -b feature/<branch>` 로 격리된 작업 공간 생성
- main 저장소 오염 없이 병렬 실험/개발 가능
- `.claude/worktrees/`는 .gitignore에 포함, 원격 푸시 안 됨
- 작업 완료 후: push → worktree remove → branch delete

### 시스템 프롬프트 템플릿 (core/llm/prompts/)

| 파일 | 역할 | 핵심 설계 |
|------|------|----------|
| router.md | NL 의도 분류 + 20 tools | Tool Priority Matrix, Clarification rules |
| analyst.md | 4종 분석자 (Send API 병렬) | "Do NOT reference other analysts" (Clean Context) |
| evaluator.md | 3종 평가자 (14-axis rubric) | "Missing evidence = score 3.0, not 1.0" |
| biasbuster.md | 편향 감지 | Confirmation, Recency, Anchoring |
| cross_llm.md | Cross-LLM 합의 검증 | Agreement ≥ 0.67 |
| synthesizer.md | 최종 판정 + 내러티브 | Decision Tree + cause→action |
| decomposer.md | 복합 요청 분해 | Goal Decomposition DAG |
| commentary.md | 사용자 피드백 생성 | — |
| tool_augmented.md | 도구 사용 가이드 | — |

### Progressive Disclosure 실체

1. Skills는 YAML frontmatter의 triggers로 자동 감지
2. LLM이 처음엔 스킬 이름만 인지 (SkillRegistry 8000char 요약 블록)
3. 사용자 의도 파악 후 전체 프롬프트가 주입
4. SOUL.md가 조직 수준 원칙을 항상 주입, MEMORY.md가 프로젝트 컨텍스트 주입
5. Rules/가 엔티티별 조건부 규칙을 YAML glob 매칭으로 자동 로딩

### Self-Improving Loop 실체 (재귀 개선 워크플로우)

```
Research → Plan → Implement → Unit Verify(ruff/mypy/pytest)
                                    ↓ 실패 시 ↑ 복귀
                               E2E Verify(Mock→CLI→Live→LangSmith)
                                    ↓ 실패 시 ↑ 복귀
                               Docs-Sync(CHANGELOG+README+CLAUDE.md 동일 커밋)
                                    ↓
                               PR & Merge(feature→develop→main, 5-Job CI)
```

- **매 단계에서 실패/품질 저하 시 이전 단계로 즉시 복귀**
- CLAUDE.md가 이 워크플로우를 시스템 프롬프트로 주입 → 에이전트가 이 루프를 자율 실행
- .claude/skills가 각 단계의 도메인 지식을 on-demand로 제공

### 이력서 불릿 활용 포인트

이 워크플로우 인프라는 다음 직무에서 어필 가능:
- **Backend**: Worktree 병렬 개발 → 마이크로서비스 독립 배포 경험과 유사
- **Platform**: .claude/ 디렉토리 체계 → 플랫폼 수준의 컨텍스트 관리 설계
- **Agent**: Progressive Disclosure + 9개 시스템 프롬프트 → Prompt Engineering 체계
- **DevOps/SRE**: 5-Step Quality Gate + CI 파이프라인 → 배포 자동화 역량

---

## 13. Development Metrics

| 지표 | 수치 |
|------|------|
| LOC | ~54,000 |
| 모듈 | 192 |
| 테스트 | 3,540+ |
| PR | 592 |
| 도구 | 52 (ToolRegistry) + 44 (MCP Catalog) |
| Hook 이벤트 | 42 |
| Skills | 21 (.claude/skills/) |
| 버전 | v0.40.0 |

---

## 직무별 핵심 매칭

| 직무 | 핵심 기법 |
|------|----------|
| **Backend** | Hexagonal, Runtime Factory, Circuit Breaker, Lane Queue, Degraded Response |
| **Performance** | CoalescingQueue, 4-Stage Failover, Task Graph, Prompt Caching |
| **AI Platform** | AgenticLoop, PlanMode, PromptAssembler, 3-Tier Memory, Progressive Disclosure |
| **AI Agent** | Goal Decomposition, NL Router, Swiss Cheese, Sub-Agent, Hook Observer |
| **Infra/SRE** | 42-Event Hook, Stuck Detection, CUSUM Drift, RunLog JSONL |
| **Data/ML** | Cross-LLM, BiasBuster, RLHF Feedback Loop, Decision Tree |

---

## 검증된 이력서 불릿 (2026.03 세션 확정)

### 불릿 1: 고정 DAG에서 자율 실행 엔진으로
- 8-Node 파이프라인이 새 도메인 수용 불가 → Claude Code while(tool_use) + OpenClaw Binding Router 탐색
- 결정론적 슬래시 커맨드(28종) + LLM 자율 판단을 하나의 루프로 결합한 AgenticLoop 설계
- 파이프라인을 도구 중 하나로 재배치, 52 tools × unlimited rounds 자율 실행 달성

### 불릿 2: Sub-Agent 병렬 위임 — 분산 동시성 제어
- CoalescingQueue(250ms dedup) 중복 제거 + Lane Queue 2-Level(세션 직렬 max=1 + 글로벌 병렬 max=4, ordered acquire 데드락 방지)
- SubAgentManager: 부모 tools/MCP/skills/memory 전체 상속, MAX_CONCURRENT=5, timeout 120s, max_depth=2
- Token Guard(출력 토큰 초과 시 summary만 보존) 컨텍스트 폭발 방지
- TaskGraph DAG topological_sort + propagate_failure() BFS 실패 격리

### 불릿 3: 비결정성 통제 — 프롬프트 레벨 가드레일과 검증 파이프라인
- PromptAssembler 6-Phase가 Token Budget + SHA-256 Hash로 입력 고정 → 비결정성 진입점 축소
- Confidence Gate(<0.7 약한 축 선별 재분석) → 적응형 루프로 품질 수렴
- 코드 기반 Decision Tree → LLM 오버라이드 불가 결정론적 최종 판정

### 불릿 4: Hexagonal + Hook Observer — 레이어별 독립 교체
- Port/Adapter Protocol(30 Ports) 비즈니스 로직-Provider 완전 분리
- 42-Event Hook Observer: 노드 코드 수정 없이 관측/로깅/드리프트 감지 플러그인
- Circuit Breaker 3-State + 4-Stage Failover + Degraded Response → fault-tolerant

### 불릿 5: DomainPort Plugin + MCP — 파이프라인과 외부 통합의 플러그인화
- DomainPort Protocol로 파이프라인 자체를 플러그인 교체 가능
- MCP 양방향(44개 카탈로그 클라이언트 + FastMCP 서버 6 tools) 외부 통합 표준화
- REODE 포크에서 GameIP 분리 + Migration Pipeline 등록으로 확장성 실증

### 불릿 6: Prompt Engineering 체계화 — 6-Phase 조립 + Caching
- PromptAssembler 6단계(Override / Skill Injection / Memory / Bootstrap / Token Budget / SHA-256 Hash)
- 3-Tier Memory(Organization > Project > Session) 에이전트 간 컨텍스트 일관성
- SHA-256 핀닝 → Anthropic Prompt Caching 자동 활성화 → 반복 호출 90% 비용 절감
