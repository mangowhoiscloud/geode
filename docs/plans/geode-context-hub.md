# .geode Context Hub — 목적 중심 컨텍스트 계층 설계

> Date: 2026-03-18 | Status: **Planning**
> 선행: `research-geode-enhancement.md`, `ADR-011`, 프론티어 4종 리서치

## 1. 설계 원칙

**"각 계층은 하나의 질문에 답한다."**

현재 GEODE의 컨텍스트는 **저장 위치** 중심으로 분류된다 (`~/.geode/`, `.geode/`, `.claude/`). 이를 **목적** 중심으로 재구성한다. 각 계층이 에이전트의 특정 질문에 답하도록 설계하면, 어떤 정보가 어디에 있어야 하는지가 자명해진다.

## 2. 5-Layer Context Hierarchy

```
Layer  질문                    수명         소유자          저장소
─────────────────────────────────────────────────────────────────────
 C0    "나는 누구인가?"          영구         사용자          ~/.geode/identity/
 C1    "이 프로젝트는 무엇인가?"  프로젝트      프로젝트        .geode/project/
 C2    "지금까지 무엇을 했는가?"  누적(불변)    에이전트        .geode/journal/
 C3    "지금 무엇을 하고 있는가?" 세션         에이전트        .geode/session/
 C4    "다음에 무엇을 해야 하는가?" 단기        에이전트+사용자  .geode/plan/
```

### C0: Identity — "나는 누구인가?"

**목적**: 프로젝트/사용자와 무관하게 유지되는 에이전트의 정체성과 사용자 선호.

| 파일 | 역할 | 생산자 | 소비자 |
|------|------|--------|--------|
| `~/.geode/identity/profile.md` | 사용자 역할, 전문성, 선호 언어 | 사용자 (수동 편집) | 시스템 프롬프트 |
| `~/.geode/identity/preferences.toml` | 구조화된 선호 (모델, 출력 형식, 예산) | `/cost budget`, `/model` | Config Cascade, cmd_cost |
| `~/.geode/identity/policies.toml` | 사용자 수준 도구 정책 (ProfilePolicy) | 사용자 (수동) | PolicyChain Layer 1 |
| `~/.geode/config.toml` | 글로벌 기본 설정 | `geode init` | Settings Cascade |

**핵심 속성**:
- 전 프로젝트 공유 (Cross-project)
- 사용자가 명시적으로 작성/수정
- 거의 변하지 않음

**프론티어 매핑**: Claude Code `~/.claude/`, Cursor global settings, Karpathy P7 program.md

---

### C1: Project — "이 프로젝트는 무엇인가?"

**목적**: 이 프로젝트의 목표, 규칙, 도메인 지식. 에이전트가 "이 프로젝트에서 무엇이 중요한지" 판단하는 근거.

| 파일 | 역할 | 생산자 | 소비자 |
|------|------|--------|--------|
| `.geode/project/config.toml` | 프로젝트별 설정 오버라이드 | 사용자 | Settings Cascade |
| `.geode/project/policies.toml` | 조직/프로젝트 도구 정책 (OrgPolicy) | 사용자 | PolicyChain Layer 2 |
| `.claude/CLAUDE.md` | 프로젝트 지시서 (Claude Code 호환) | 사용자 | 시스템 프롬프트 |
| `.claude/MEMORY.md` | 프로젝트 메모리 (200줄, Claude Code 호환) | 에이전트+사용자 | ContextAssembler |
| `.claude/SOUL.md` | 조직 미션 | 사용자 | ContextAssembler Tier 0 |
| `.claude/rules/*.md` | 조건부 규칙 | 사용자 | ProjectMemory |
| `.claude/skills/` | 프로젝트 스킬 | 사용자 | SkillRegistry |

**핵심 속성**:
- Git 추적 가능 (팀 공유)
- 사용자가 주도적으로 관리
- `.claude/`는 Claude Code 호환 유지, `.geode/project/`는 GEODE 전용

**프론티어 매핑**: Claude Code `.claude/`, Codex `AGENTS.md`, Cursor `.cursor/rules`

---

### C2: Journal — "지금까지 무엇을 했는가?"

**목적**: 프로젝트 내 모든 실행의 **불변 기록**. 에이전트가 과거를 참조하여 더 나은 판단을 내리는 근거. Append-only — 절대 삭제/수정하지 않는다.

| 파일 | 역할 | 생산자 | 소비자 |
|------|------|--------|--------|
| `.geode/journal/runs.jsonl` | 실행 이력 (분석, 리서치, 자동화) | Hook: PIPELINE_END | ContextAssembler, `/context history` |
| `.geode/journal/costs.jsonl` | 프로젝트 수준 비용 기록 | TokenTracker | `/cost`, 예산 관리 |
| `.geode/journal/learned.md` | 프로젝트 수준 학습 패턴 | Hook: Agent Reflection | 시스템 프롬프트, ContextAssembler |
| `.geode/journal/errors.jsonl` | 실패 기록 (에러 타입, 복구 여부) | Hook: PIPELINE_ERROR | ErrorRecovery 학습 |

**핵심 속성**:
- **Append-only** (불변 로그 — 신뢰의 근거)
- 에이전트가 자동 생성 (사용자 편집 불필요)
- 시간순 누적 — 오래된 항목은 pruning 가능하되 요약은 보존
- gitignored (프로젝트별 실행 데이터)

**프론티어 매핑**: Karpathy P4 Ratchet (tier 변동 기록), P5 Git State (실험 기록), OpenClaw Run Log JSONL

**설계 판단 — 왜 Journal이 C2인가?**

Journal이 Project(C1) 아래, Session(C3) 위에 있는 이유: 세션은 소멸하지만, 그 세션에서 배운 것은 프로젝트 수준에서 영속해야 한다. Journal은 "세션의 결과가 침전되는 곳"이다.

---

### C3: Session — "지금 무엇을 하고 있는가?"

**목적**: 현재 실행 중인 세션의 라이브 상태. 세션 재개(resume)와 멀티턴 대화 연속성의 근거.

| 파일 | 역할 | 생산자 | 소비자 |
|------|------|--------|--------|
| `.geode/session/active.json` | 현재 활성 세션 메타 (세션 ID, 시작 시각, 모델) | REPL 시작 시 | REPL 시작 시 (재개 판단) |
| `.geode/session/{id}/messages.json` | 대화 이력 체크포인트 (최근 N턴) | AgenticLoop 라운드 종료 시 | `geode resume` |
| `.geode/session/{id}/tools.json` | 도구 호출 기록 | AgenticLoop | 세션 재개 시 복원 |
| `.geode/session/{id}/state.json` | 세션 메타 (round_idx, model, status) | AgenticLoop | 세션 재개 시 복원 |

**핵심 속성**:
- **Mutable** (매 라운드 갱신)
- 세션 종료 시 핵심 결과 → C2(Journal)로 침전
- 72시간 후 자동 정리 (cleanup)
- 비정상 종료 시에도 마지막 체크포인트에서 재개 가능

**프론티어 매핑**: OpenClaw Session Persistence, Karpathy P6 Context Budget (최근 N턴만 보존)

**생명주기**:
```
세션 시작 → active.json 생성 → 매 라운드 체크포인트 → 세션 종료
  → active.json 삭제
  → 핵심 결과 Journal로 침전 (runs.jsonl, learned.md)
  → 체크포인트 72h 후 정리
```

---

### C4: Plan — "다음에 무엇을 해야 하는가?"

**목적**: 미완료 작업, 분해된 목표, 예약된 자동화. 에이전트가 "아직 안 한 것"을 추적하는 근거.

| 파일 | 역할 | 생산자 | 소비자 |
|------|------|--------|--------|
| `.geode/plan/goals.json` | 분해된 목표 DAG (GoalDecomposer 결과) | GoalDecomposer | AgenticLoop (다음 액션 결정) |
| `.geode/plan/pending.json` | 미완료 도구 호출 (거부된 WRITE 등) | ToolExecutor | 다음 세션 시작 시 알림 |
| `.geode/plan/schedule.json` | 예약된 자동화 (cron, 반복 작업) | SchedulerService | Cron Runner |

**핵심 속성**:
- **Consumable** (완료되면 삭제/아카이브)
- 에이전트 + 사용자 공동 생산
- 세션 시작 시 "이전에 못 끝낸 작업이 있습니다" 알림의 근거

**프론티어 매핑**: Claude Code Tasks, OpenClaw TaskGraph, Codex auto-plan

---

## 3. 계층 간 데이터 흐름

```
사용자 입력 → AgenticLoop
               │
               ├─ 읽기: C0(Identity) + C1(Project) + C2(Journal 최근 3건) + C4(Plan)
               │        → 시스템 프롬프트 조립
               │
               ├─ 실행 중: C3(Session) 체크포인트 매 라운드 갱신
               │
               └─ 종료 시:
                    ├─ C2(Journal) ← runs.jsonl append (불변 기록)
                    ├─ C2(Journal) ← learned.md append (학습 패턴)
                    ├─ C2(Journal) ← costs.jsonl append (비용 기록)
                    ├─ C3(Session) → 정리 or 보존 (재개용)
                    └─ C4(Plan) ← 미완료 작업 기록 (다음 세션용)
```

## 4. 물리적 디렉토리 매핑

```
~/.geode/                           C0: Identity (글로벌)
├── identity/
│   ├── profile.md                  사용자 역할/전문성
│   ├── preferences.toml            구조화된 선호
│   └── policies.toml               사용자 수준 도구 정책
├── config.toml                     글로벌 기본 설정
├── usage/                          글로벌 비용 (전 프로젝트 합산)
│   └── YYYY-MM.jsonl
└── scheduler/                      글로벌 스케줄러
    └── jobs.json

.geode/                             C1-C4: 프로젝트 컨텍스트 (gitignored)
├── project/                        C1: Project
│   ├── config.toml                 프로젝트 설정 오버라이드
│   └── policies.toml               조직 수준 도구 정책
├── journal/                        C2: Journal (append-only)
│   ├── runs.jsonl                  실행 이력
│   ├── costs.jsonl                 프로젝트 비용
│   ├── learned.md                  학습 패턴
│   └── errors.jsonl                에러 기록
├── session/                        C3: Session (mutable)
│   ├── active.json                 활성 세션 메타
│   └── {session-id}/               세션별 체크포인트
│       ├── messages.json
│       ├── tools.json
│       └── state.json
├── plan/                           C4: Plan (consumable)
│   ├── goals.json                  목표 DAG
│   ├── pending.json                미완료 작업
│   └── schedule.json               예약 자동화
├── cache/                          캐시 (TTL 기반, 계층 외)
│   └── {hash}.json
├── reports/                        산출물 (계층 외)
└── snapshots/                      스냅샷 (계층 외)

.claude/                            C1: Project (Claude Code 호환)
├── CLAUDE.md                       프로젝트 지시서
├── MEMORY.md                       프로젝트 메모리
├── SOUL.md                         조직 미션
├── rules/                          조건부 규칙
├── skills/                         프로젝트 스킬
└── mcp_servers.json                MCP 설정
```

## 5. 기존 구현 매핑 + 마이그레이션

### 5.1. 이미 구현된 것 → 새 계층 매핑

| 기존 구현 | 기존 위치 | 새 계층 | 변경 |
|----------|----------|:------:|------|
| FileBasedUserProfile | `~/.geode/user_profile/` | **C0** | `~/.geode/identity/`로 이동 |
| ProfilePolicy TOML | `~/.geode/user_profile/preferences.toml` | **C0** | `~/.geode/identity/policies.toml` |
| Config Cascade | `.geode/config.toml` | **C1** | `.geode/project/config.toml` |
| OrgPolicy TOML | `.geode/config.toml [policy.org]` | **C1** | `.geode/project/policies.toml` |
| RunLog | `~/.geode/runs/*.jsonl` | **C2** | `.geode/journal/runs.jsonl` (프로젝트 수준) |
| UsageStore | `~/.geode/usage/` | **C0+C2** | 글로벌 유지 + `.geode/journal/costs.jsonl` 추가 |
| Agent Reflection | `~/.geode/user_profile/learned.md` | **C0+C2** | 글로벌 유지 + `.geode/journal/learned.md` 추가 |
| InMemorySessionStore | `.geode/sessions/` | **C3** | `.geode/session/` (체크포인트 추가) |
| ResultCache | `.geode/result_cache/` | 캐시 | `.geode/cache/` |
| GoalDecomposer | 메모리 내 | **C4** | `.geode/plan/goals.json` 영속화 |

### 5.2. 하위 호환 전략

**Phase 0 (이번 구현)**: 새 디렉토리 구조를 생성하되, 기존 경로도 fallback으로 계속 읽는다.

```python
# 예: UserProfile 로딩
def _resolve_identity_dir() -> Path:
    new_path = Path.home() / ".geode" / "identity"
    old_path = Path.home() / ".geode" / "user_profile"
    if new_path.exists():
        return new_path
    return old_path  # fallback to old location
```

**Phase 1 (추후)**: `geode migrate` 명령으로 기존 파일을 새 위치로 이동.

## 6. 구현 계획

### Phase A: Journal + 자동 기록 (핵심)

**"무엇을 했는가"를 자동으로 쌓는다.**

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| A1 | `ProjectJournal` 모듈 | `core/memory/project_journal.py` (신규) | `.geode/journal/` 읽기/쓰기 (runs.jsonl, costs.jsonl, learned.md, errors.jsonl) |
| A2 | Hook 자동 기록 | `core/orchestration/hooks.py` 연동 | PIPELINE_END → runs.jsonl + learned.md, PIPELINE_ERROR → errors.jsonl |
| A3 | ContextAssembler 통합 | `core/memory/context.py` 수정 | C2(Journal) 최근 이력을 시스템 프롬프트에 주입 |
| A4 | `geode init` 확장 | `core/cli/__init__.py` 수정 | `.geode/journal/`, `.geode/session/`, `.geode/plan/`, `.geode/project/` 디렉토리 생성 |
| A5 | 비용 이중 기록 | `core/llm/token_tracker.py` 수정 | 글로벌(~/.geode/usage) + 프로젝트(.geode/journal/costs.jsonl) |

### Phase B: Session Checkpoint + Resume

**"중단해도 이어갈 수 있다."**

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| B1 | `SessionCheckpoint` 모듈 | `core/cli/session_checkpoint.py` (신규) | `.geode/session/` 체크포인트 저장/복원/정리 |
| B2 | AgenticLoop 통합 | `core/cli/agentic_loop.py` 수정 | 매 라운드 체크포인트, 세션 ID 관리 |
| B3 | `geode resume` 커맨드 | `core/cli/__init__.py` 수정 | 중단 세션 목록 + 선택 재개 |
| B4 | 침전 메커니즘 | `core/cli/agentic_loop.py` 수정 | 세션 종료 → Journal(C2)로 핵심 결과 기록 |
| B5 | REPL 시작 알림 | `core/cli/repl.py` 수정 | "이전 세션이 있습니다" 알림 |

### Phase C: Plan Persistence + Context Command

**"아직 안 한 것을 기억한다."**

| # | 작업 | 파일 | 설명 |
|---|------|------|------|
| C1 | Plan 영속화 | `core/orchestration/plan_mode.py` 수정 | goals.json 저장/복원 |
| C2 | Pending 추적 | `core/cli/tool_executor.py` 수정 | 거부된 WRITE → pending.json |
| C3 | `/context` 커맨드 | `core/cli/commands.py` 추가 | 전 계층 컨텍스트 요약 표시 |
| C4 | Startup 주입 | `core/cli/repl.py` 수정 | 시작 시 C2+C4 자동 요약 주입 |

### 구현 우선순위

```
Phase A (Journal) ──→ Phase B (Session) ──→ Phase C (Plan)
  "과거를 기억"          "현재를 보존"          "미래를 계획"
```

**Phase A만 완료해도** 프로젝트 컨텍스트 축적의 기본 메커니즘이 동작한다.

## 7. 프론티어 대비 차별점

| 프론티어 | 패턴 | GEODE 적용 | 차별점 |
|---------|------|-----------|--------|
| Claude Code | `.claude/` 단일 디렉토리 | C0-C4 5계층 분리 | 목적별 계층화 — "왜 이 데이터가 여기 있는지" 자명 |
| Codex | `AGENTS.md` 단일 파일 | C1(Project) + C2(Journal) | 지시서와 학습 기록 분리 — 지시는 사람이, 학습은 에이전트가 |
| Cursor | `.cursor/rules` | C1(Project rules) + C2(Journal learned) | 규칙(명시적)과 학습(암묵적) 구분 |
| OpenClaw | Session Key + Log | C3(Session checkpoint) + C2(Journal) | 세션 → 저널 침전 메커니즘 |
| Karpathy | P6 Context Budget | C2 1줄 요약 주입 | 계층별 예산 할당 (C0 10%, C1 25%, C2 25%, C3 40%) |
