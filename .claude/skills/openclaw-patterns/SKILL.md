---
name: openclaw-patterns
description: OpenClaw 코드베이스에서 증류한 에이전트 시스템 설계 패턴. Gateway 중심 제어, Session Key 계층, Binding 라우팅, Lane Queue 동시성, Sub-agent Spawn+Announce, 4계층 자동화, Plugin 아키텍처, Policy Chain, Failover 전략. "gateway", "session", "binding", "lane", "spawn", "announce", "heartbeat", "cron", "hook", "plugin", "policy", "failover" 키워드로 트리거.
user-invocable: false
---

# OpenClaw Patterns — 에이전트 시스템 설계 증류

> **출처**: `github.com/openclaw/openclaw` (TypeScript, ~48 소스 파일)
> **철학**: 모든 것은 세션이고, 모든 실행은 큐를 거치며, 모든 확장은 플러그인이다.

## 시스템 구조 — Gateway + Agent 이중 체계

```
┌─────────────────────────────────────────────────────────┐
│  Gateway (제어 플레인)                                     │
│  ├── Channel Manager — 7+ 채널 플러그인 통합              │
│  ├── Session Manager — 계층적 세션 키 관리                │
│  ├── Binding Router  — 결정적 메시지→에이전트 매핑        │
│  └── Node Registry   — 분산 노드 등록/조회                │
├─────────────────────────────────────────────────────────┤
│  Agent Runtime (실행 플레인)                               │
│  ├── Attempt Loop    — LLM 호출 + 도구 실행 사이클        │
│  ├── Tool System     — Policy 기반 도구 접근 제어          │
│  ├── Skill Loader    — 4단계 우선순위 스킬 로딩            │
│  └── Sub-agent Pool  — Spawn + Announce 병렬 실행         │
└─────────────────────────────────────────────────────────┘
```

핵심 원칙: Gateway가 "어디로 보낼지"만 결정, Agent가 "무엇을 할지" 결정. 관심사 분리.

---

## 1. Session Key 계층 구조

세션 키는 에이전트, 채널, 피어를 조합한 계층적 문자열이다.

```
agent:{agentId}:{context}

agent:main:main                    # 메인 에이전트 기본 세션
agent:main:telegram:dm:123456      # 텔레그램 DM 세션
agent:work:discord:group:789       # 디스코드 그룹 세션
agent:main:subagent:run-abc123     # 서브에이전트 격리 세션
cron:{jobId}                       # 크론 격리 세션
hook:{hookId}                      # 웹훅 격리 세션
```

**설계 포인트**:
- 문자열 기반 → 직렬화/역직렬화 비용 없음
- 계층 구조 → 접두사 매칭으로 범위 필터링 가능
- 세션 = 컨텍스트 격리 경계 (같은 에이전트도 세션이 다르면 독립)

**적용**: `thread_id`에 `ip:{name}:{phase}` 형식 적용, Checkpoint 기반 복구 시 키로 활용.

---

## 2. Binding 기반 결정적 라우팅

인바운드 메시지를 **정적 매칭 규칙**으로 에이전트에 라우팅한다.

```json5
{
  bindings: [
    { agentId: "home", match: { channel: "whatsapp", accountId: "personal" } },
    { agentId: "work", match: { channel: "whatsapp", accountId: "biz" } },
    { agentId: "work", match: {
      channel: "whatsapp",
      peer: { kind: "group", id: "work-group@g.us" }
    }}
  ]
}
```

**우선순위 (Most-Specific Wins)**:
```
peer 매치 > guildId > teamId > accountId > channel > default agent
```

**특징**:
- LLM 판단 없이 config만으로 라우팅 (결정적, 예측 가능)
- Config hot reload 가능 (코드 변경/재배포 불필요)
- 1 메시지 → 정확히 1 에이전트 (fan-out은 Sub-agent로)

**적용**: 파이프라인 모드(`full_pipeline`, `evaluation`, `scoring`)별 노드 라우팅에 동일 원리 적용.

---

## 3. Lane Queue — 동시성 제어

기본 실행 모델은 **직렬**이다. 병렬이 필요하면 명시적으로 요청한다.

```
Session Lane — 같은 세션 요청은 순서 보장 (직렬)
Global Lane  — 전체 에이전트 동시성 제한 (N개)
Subagent Lane — Sub-agent 전용 (maxConcurrent: 8)
Hook Lane    — 웹훅 전용
```

**흐름**:
```
요청 → Session Lane 획득 → Global Lane 획득 → 실행 → 해제
```

**설계 포인트**:
- 기본이 직렬이므로 상태 충돌 없음 (안전 우선)
- 병렬이 필요한 곳만 Sub-agent로 명시적 전환
- 레인별 `maxConcurrent`, `runTimeoutSeconds` 독립 설정

---

## 4. Sub-agent Spawn + Announce 패턴

**병렬 실행이 필요하면 명시적으로 Sub-agent를 생성**한다.

```
Parent Agent (agent:main:main)
    │
    ├── spawn("Reddit 분석")  → run-001 (격리 세션)
    ├── spawn("YouTube 분석") → run-002 (격리 세션)
    ├── spawn("Twitch 분석")  → run-003 (격리 세션)
    │
    │   [3개 동시 실행, maxConcurrent=8]
    │
    ├── ← announce(run-001, result)
    ├── ← announce(run-002, result)
    ├── ← announce(run-003, result)
    │
    └── 결과 종합
```

**SubagentRunRecord**:
```typescript
{
  runId, childSessionKey,     // 격리 세션 식별
  requesterSessionKey,        // 부모 세션 식별
  task,                       // 수행 지시 (문자열)
  cleanup: "delete" | "keep", // 완료 후 세션 처리
  outcome: { status: "ok" } | { status: "error", error? },
  archiveAtMs,                // 60분 후 자동 아카이빙
}
```

**Announce**: Sub-agent 완료 → Parent 세션에 시스템 이벤트로 결과 주입.

**적용**: LangGraph Send API가 이 패턴의 구조화된 버전. Private State로 타입 안전 + Reducer로 자동 합류.

---

## 5. 4계층 자동화 아키텍처

```
┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
│ L1 Heartbeat│  │ L2 Cron    │  │ L3 Internal│  │ L4 Gateway │
│ Runner      │  │ Service    │  │ Hooks      │  │ Hooks      │
│             │  │            │  │            │  │            │
│ 고정 간격   │  │ at/every/  │  │ command:new│  │ HTTP POST  │
│ 폴링        │  │ cron 표현식│  │ agent:boot │  │ + Bearer   │
└──────┬──────┘  └──────┬─────┘  └──────┬─────┘  └──────┬─────┘
       └────────────────┴───────────────┴───────────────┘
                         │
              System Events Queue (in-memory, max 20)
```

### L1: Heartbeat Runner

고정 간격 폴링. 실행 전 5가지 조건 모두 충족해야 실행:
- `heartbeatsEnabled` 전역 플래그
- `agents.size > 0`
- `now >= nextDueMs`
- `isWithinActiveHours()` — 타임존별 활성 시간
- `getQueueSize(MainLane) === 0` — 메인 레인 비어있을 때만

**Active Hours**: 자정 넘김(`22:00-06:00`) 자동 처리, 에이전트별 타임존 독립 설정.

### L2: Cron Service — 3종 스케줄

```
at    — 1회성 절대 시간 (성공 후 자동 비활성화/삭제)
every — 고정 간격 (anchorMs 기준 정렬 → 재시작 시 drift 방지)
cron  — 표현식 (타임존 지원)
```

**페이로드 2종**:
- `systemEvent` → 메인 세션에 텍스트 주입 (sessionTarget: "main")
- `agentTurn` → 격리 세션에서 에이전트 완전 실행 (sessionTarget: "isolated")

### L3: Internal Hooks — 이벤트 기반

```
command:new     → 세션 메모리 저장
command:reset   → 상태 초기화
agent:bootstrap → 시스템 프롬프트 주입/교체
gateway:startup → 초기화 스크립트
```

Hook 구조: `my-hook/HOOK.md` (YAML frontmatter) + `handler.ts` (핸들러 함수)

### L4: Gateway Hooks — 외부 웹훅

HTTP POST → Hook Mapping (URL/source 매칭) → wake(시스템 이벤트) 또는 agent(격리 실행)

Mustache 템플릿: `"New email from {{payload.from}}: {{payload.subject}}"`

---

## 6. Plugin 아키텍처 — 4가지 확장점

| 확장점 | 등록 방식 | 발견 |
|--------|----------|------|
| **Channel** | ChannelManager에 플러그인 등록 | 설정 기반 |
| **Tool** | createOpenClawTools + Policy 필터 | 정책 기반 |
| **Skill** | 4단계 우선순위 로딩 | 파일시스템 기반 |
| **Hook** | 4곳에서 자동 발견 | 디렉토리 기반 |

**스킬 로딩 우선순위** (낮음 → 높음):
```
1. Bundled Skills     (패키지 내장)
2. Extra Dirs         (설정에서 지정)
3. Managed Skills     (~/.openclaw/skills)
4. Workspace Skills   (./skills)  ← 최고 우선순위
```

**적용**: GEODE ToolRegistry가 이 패턴의 Python 구현. `register()` → `get()` → `to_anthropic_tools()`.

---

## 7. Policy Resolution Chain — 다층 도구 접근 제어

```
Profile Policy → Global Policy → Agent Policy
    → Group Policy → Sandbox Policy → Subagent Policy
    → [최종 허용 도구 목록]
```

각 계층이 도구를 추가하거나 제거할 수 있다. 가장 구체적인 정책이 우선.

**적용**: GEODE에서 분석 모드별 도구 접근 제어에 활용 가능 (dry_run 시 LLM 도구 차단 등).

---

## 8. Failover 전략 — 4단계 자동 복구

```
1. Auth Profile Rotation — Rate Limit/Auth Error → 다음 프로필 → 재시도
2. Thinking Level Fallback — high 미지원 → medium → low → off
3. Context Overflow — 감지 → Auto-compaction → 압축 후 재시도
4. Model Failover — Primary 실패 → Fallback 모델 → 재시도
```

**적용**: GEODE Feedback Loop의 확장. confidence < 0.7일 때 모델 변경하며 재시도하는 전략.

---

## 9. 운영 패턴

### Coalescing (요청 병합)

```
250ms 윈도우 내 다중 wake 요청 → 1회 실행으로 병합
메인 레인 점유 시 → 1초 간격 재시도
timer.unref() → heartbeat만으로 프로세스 유지 안 함
```

### Atomic Store (안전 기록)

```
tmp 파일 생성 → rename (원자적) → .bak 백업 (best-effort)
```

### Run Log (JSONL + Pruning)

```
파일: ~/.openclaw/cron/runs/{jobId}.jsonl
자동 Pruning: maxBytes=2MB, keepLines=2000
```

### Config Hot Reload

```
chokidar 파일 감시 → 디바운스 300ms
hooks 변경 → reload-hooks
cron 변경  → restart-cron
gmail 변경 → restart-gmail
```

### Stuck Job 탐지

```
runningAtMs가 2시간 이상 → stuck 간주 → runningAtMs 해제
```

---

## 10. 소스 구조 (참고)

```
openclaw/src/
├── gateway/              # 제어 플레인
│   ├── routing.ts        # Binding 라우팅
│   ├── hooks.ts          # Gateway Hooks (HTTP)
│   ├── hooks-mapping.ts  # URL/source 매핑
│   ├── config-reload.ts  # Hot Reload
│   └── server/           # HTTP/WS 서버
├── agents/               # 실행 플레인
│   ├── run.ts            # runEmbeddedPiAgent
│   ├── attempt.ts        # Attempt Loop
│   ├── tools/            # 도구 팩토리 + 실행
│   └── bootstrap-hooks.ts
├── infra/                # 공유 인프라
│   ├── lane-queue.ts     # Lane Queue 동시성
│   ├── heartbeat-runner.ts # Heartbeat
│   ├── heartbeat-wake.ts # Coalescing
│   └── system-events.ts  # 이벤트 큐
├── cron/                 # 예약 작업
│   ├── service/          # CronService (타이머, 실행, 락)
│   ├── store.ts          # Atomic Store
│   ├── run-log.ts        # JSONL 이력
│   └── types.ts          # Job 타입
├── hooks/                # Internal Hooks
│   ├── internal-hooks.ts # 이벤트 엔진
│   ├── workspace.ts      # 4곳 자동 발견
│   ├── loader.ts         # Hook 로딩
│   └── bundled/          # 번들 Hook 4개
├── skills/               # 스킬 시스템
│   └── loader.ts         # 4단계 우선순위 로딩
└── config/               # 설정
    ├── types.hooks.ts    # Hook 타입
    └── zod-schema.*.ts   # Zod 검증
```

---

## 패턴 적용 체크리스트

GEODE에 OpenClaw 패턴을 적용할 때:

- [ ] Session Key: `thread_id`에 계층적 키 (`ip:{name}:{phase}`) 적용했는가
- [ ] 동시성: 기본 직렬 + 명시적 병렬 (Send API) 원칙을 따르는가
- [ ] Plugin: 새 기능을 기존 코드 수정 없이 등록할 수 있는가 (ToolRegistry)
- [ ] Policy: 모드/컨텍스트별 도구 접근을 제어하는 정책 체인이 있는가
- [ ] Failover: LLM 호출 실패 시 자동 복구 경로가 있는가
- [ ] Coalescing: 중복 실행 요청을 병합하는 메커니즘이 있는가
- [ ] Atomic Write: 상태 파일 기록 시 tmp+rename 패턴을 사용하는가
- [ ] Hot Reload: 설정 변경 시 재시작 없이 반영되는가
- [ ] Stuck Detection: 장시간 실행 작업을 자동 해제하는가
- [ ] Run Log: 실행 이력을 JSONL로 기록하고 자동 pruning 하는가

## References

- **OpenClaw 전체 분석**: `research/openclaw-analysis-report.md`
- **자동화 4계층**: `research/openclaw-automation-analysis.md`
- **라우팅 비교**: `research/openclaw-routing-analysis.md`
- **라우팅 다이어그램**: `diagrams/openclaw-routing.mmd`
