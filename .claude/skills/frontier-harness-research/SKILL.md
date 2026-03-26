---
name: frontier-harness-research
description: 기능 구현 전 프론티어 하네스 4종(Claude Code, Codex, OpenClaw, autoresearch)에서 관련 패턴을 탐색하고 GAP 분석을 수행하는 리서치 프로세스. "리서치", "research", "gap", "frontier", "harness", "사례 조사", "패턴 탐색", "비교 분석" 키워드로 트리거.
user-invocable: false
---

# Frontier Harness Research — 프론티어 비교 리서치 프로세스

> **목적**: 기능 구현 전에 4개 프론티어 하네스에서 주제 관련 패턴을 탐색하고, GEODE에 적용할 설계 판단 근거를 확보한다.
> **적용 시점**: Implementation Workflow Step 1 (Research → Plan) 단계에서 반드시 수행.

## 프론티어 하네스 4종

| # | 시스템 | 유형 | 핵심 패턴 영역 | GEODE 스킬 참조 |
|---|--------|------|---------------|----------------|
| 1 | **Claude Code** | CLI 에이전트 | 권한 모델, Hook, Memory, Skill, Context 관리, UI | (내장 지식) |
| 2 | **Codex** | 클라우드 에이전트 | Sandbox 실행, TDD 루프, PR 워크플로우, 코드 리뷰, 멀티파일 편집 | (내장 지식) |
| 3 | **OpenClaw** | 채팅 에이전트 | Gateway, Session Key, Binding, Lane Queue, Plugin, Failover, 4계층 자동화 | `openclaw-patterns` |
| 4 | **autoresearch** | 자율 실험 루프 | 제약 기반 설계, 래칫, Context Budget, program.md, Simplicity Selection | `karpathy-patterns` |

## 리서치 프로세스

### Step 1: 주제 정의

구현할 기능을 한 줄로 정의하고, 관련 키워드를 추출한다.

```
예시:
  주제: "Model Failover 자동화"
  키워드: failover, fallback, retry, circuit breaker, model switching
```

### Step 2: 4종 패턴 탐색

각 시스템에서 주제 관련 패턴을 탐색한다. **스킬 파일이 있으면 먼저 읽고**, 없으면 내장 지식에서 추출한다.

#### 2a. Claude Code 패턴 탐색

| 탐색 영역 | 확인 포인트 |
|----------|-----------|
| Permission Model | allowlist/denylist, auto-approve, 거부 후 fallback |
| Hook System | pre/post tool hooks, settings.json 기반 자동화 |
| Memory | CLAUDE.md, project memory, 자동 기억 |
| Skill System | skill discovery, trigger 키워드, 4단계 우선순위 |
| Context Management | sliding window, compression, token 관리 |
| UI Patterns | status line, progress indicators, error display |
| Safety | HITL tiers, bash safety, dangerous tool gates |

#### 2b. Codex 패턴 탐색

| 탐색 영역 | 확인 포인트 |
|----------|-----------|
| Sandbox Execution | 격리 환경, 파일시스템 제한, 네트워크 제한 |
| TDD Loop | test-first, red-green-refactor, 자동 검증 |
| PR Workflow | 브랜치 생성, 변경사항 요약, 리뷰 요청 |
| Multi-file Editing | 의존성 추적, 일관성 유지, 리팩토링 범위 |
| Task Decomposition | 복합 작업 분해, 순차/병렬 판단 |

#### 2c. OpenClaw 패턴 탐색 (`openclaw-patterns` 스킬 참조)

| 탐색 영역 | 확인 포인트 |
|----------|-----------|
| Gateway + Agent 이중 체계 | 제어 플레인 vs 실행 플레인 분리 |
| Session Key 계층 | `agent:{id}:{context}` 형식 세션 격리 |
| Binding 라우팅 | Most-Specific Wins, 정적 규칙, hot reload |
| Lane Queue | Session/Global/Subagent Lane 동시성 제어 |
| Sub-agent Spawn+Announce | 격리 실행, 결과 자동 주입 |
| 4계층 자동화 | Heartbeat, Cron, Internal Hooks, Gateway Hooks |
| Plugin 아키텍처 | Channel/Tool/Skill/Hook 4가지 확장점 |
| Policy Chain | 6-계층 도구 접근 제어 |
| Failover | Auth Rotation, Thinking Fallback, Context Overflow, Model Failover |
| 운영 패턴 | Coalescing, Atomic Store, Run Log, Hot Reload, Stuck Detection |

#### 2d. autoresearch 패턴 탐색 (`karpathy-patterns` 스킬 참조)

| 탐색 영역 | 확인 포인트 |
|----------|-----------|
| P1 제약 기반 설계 | "무엇을 할 수 없는가"를 먼저 정의 |
| P2 단일 파일 제약 | 수정 표면적 최소화 |
| P3 고정 시간 예산 | 스텝이 아닌 벽시계로 제한 |
| P4 래칫 메커니즘 | 개선만 유지, 악화 시 자동 복구 |
| P5 Git as State Machine | 커밋=실험, reset=폐기 |
| P6 Context Budget | 리다이렉트 + 선택 추출 |
| P7 program.md | 에이전트 행동 = 지시서 수정 |
| P10 Simplicity Selection | 코드 삭제 > 코드 추가 |

### Step 3: GAP 분석

탐색 결과를 GEODE 현재 상태와 대조하여 GAP을 식별한다.

```
출력 형식:

| # | 패턴 | 출처 | GEODE 상태 | GAP | 우선순위 |
|---|------|------|-----------|-----|---------|
| 1 | Model Failover | OpenClaw | ⚠️ 정의만 | 자동 전환 로직 없음 | P1 |
| 2 | Circuit Breaker | Codex | ✗ 없음 | 연속 실패 시 차단 없음 | P1 |
| 3 | Retry Budget | autoresearch P3 | ⚠️ 부분 | 시간 기반 제한 없음 | P2 |
```

### Step 4: 설계 판단

GAP 분석 결과에서 구현할 항목을 선택하고 설계 판단 근거를 문서화한다.

**판단 기준:**

| 기준 | 적용 |
|------|------|
| 3종 이상에서 동일 패턴 | → 반드시 채택 |
| 2종에서 유사 패턴 | → 핵심 추출, GEODE 맥락 변형 |
| 1종에서만 존재 | → 필요성 검증 후 판단 |
| 과잉 엔지니어링 위험 | → Karpathy P10 적용, 최소 구현 |
| 기존 GEODE 패턴과 충돌 | → 기존 패턴 우선, 점진적 전환 |

### Step 5: 계획 문서 작성

`docs/plans/`에 계획 문서를 작성한다. 반드시 리서치 결과 요약을 포함한다.

```markdown
# Plan: [기능명]

## 프론티어 리서치 요약

| 시스템 | 관련 패턴 | 채택 여부 | 근거 |
|--------|----------|----------|------|
| Claude Code | ... | 채택/변형/불채택 | ... |
| Codex | ... | 채택/변형/불채택 | ... |
| OpenClaw | ... | 채택/변형/불채택 | ... |
| autoresearch | ... | 채택/변형/불채택 | ... |

## 설계 판단
...

## 구현 Phase
...
```

## 리서치 체크리스트

기능 구현 전 아래를 확인한다:

- [ ] 주제 키워드 정의
- [ ] Claude Code 패턴 탐색 완료
- [ ] Codex 패턴 탐색 완료
- [ ] OpenClaw 패턴 탐색 완료 (`openclaw-patterns` 스킬 참조)
- [ ] autoresearch 패턴 탐색 완료 (`karpathy-patterns` 스킬 참조)
- [ ] GAP 분석 테이블 작성
- [ ] 설계 판단 근거 문서화
- [ ] docs/plans/ 계획 문서에 리서치 요약 포함

## 주의사항

- **리서치는 구현 전에 수행한다.** 구현 중 패턴을 발견해도 되돌아가지 않고, 다음 이터레이션에서 개선한다.
- **4종 모두 탐색할 필요는 없다.** 주제와 무관한 시스템은 "해당 없음"으로 스킵.
- **스킬 파일이 있으면 반드시 먼저 읽는다.** `openclaw-patterns`, `karpathy-patterns` 스킬은 이미 증류된 패턴을 담고 있으므로 중복 탐색을 방지한다.
- **과잉 리서치 방지**: 리서치 시간이 구현 시간을 초과하면 안 된다. Karpathy P3(고정 시간 예산) 적용.
