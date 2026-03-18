# GEODE Progress Board

> 멀티 에이전트 공유 칸반 보드. 모든 세션/에이전트가 이 파일을 읽고 갱신한다.
> 마지막 갱신: 2026-03-18 (세션 3)

---

## Kanban

### Backlog

| task_id | 설명 | 우선순위 | plan | 비고 |
|---------|------|:--------:|------|------|
| context-overflow | Context Overflow Detection — Token 초과 자동 압축 | P1 | — | Karpathy P6 Context Budget |
| policy-6layer | 6-계층 Policy Chain 확대 | P1 | — | OpenClaw Policy Resolution |
| cost-approval | EXPENSIVE_TOOLS 비용 조회+승인 UI | P1 | — | Claude Code Permission 패턴 |
| multi-provider | AgenticLoop 멀티 프로바이더 — Anthropic SDK 결합 해제 | P1 | — | P2→P1 승격 (GLM-5 버그 발견). LLMClientPort 추상화 |
| write-fallback | WRITE_TOOLS 거부 후 fallback 경로 | P2 | — | Claude Code Permission 패턴 |

### In Progress

| task_id | 설명 | 담당 | 브랜치 | 시작일 | 비고 |
|---------|------|------|--------|--------|------|
| — | — | — | — | — | — |

### In Review

| task_id | PR | 담당 | CI | 비고 |
|---------|-----|------|-----|------|
| — | — | — | — | — |

### Done (2026-03-18)

| task_id | 설명 | PR | 담당 | 완료일 |
|---------|------|----|------|--------|
| model-failover | Model Failover — call_with_failover + circuit breaker | #269→#270 | @mangowhoiscloud | 2026-03-18 |
| mcp-lifecycle | MCP Lifecycle — startup/shutdown + SIGTERM + atexit | #269→#270 | @mangowhoiscloud | 2026-03-18 |
| subagent-announce | Sub-agent Announce — drain queue + conversation 주입 | #269→#270 | @mangowhoiscloud | 2026-03-18 |
| batch-approval | Tiered Batch Tool Approval — 5단계 안전등급 분류 | #269→#270 | @mangowhoiscloud | 2026-03-18 |
| kanban-cleanup | Worktree 누수 3건 + 좀비 브랜치 40건 + Stop Hook 보강 | #269→#270 | @mangowhoiscloud | 2026-03-18 |
| messaging-v019 | Slack/Discord/Telegram + Google/Apple Calendar 통합 (v0.19.0) | #241→#242 | @mangowhoiscloud | 2026-03-18 |
| gateway-wiring | 검증팀 발견 — GatewayPort + runtime 와이어링 수정 | #241 | @mangowhoiscloud | 2026-03-18 |
| openclaw-gap6 | OpenClaw GAP 6건 수정 (Lane Queue, Session Key 등) | #241 | @mangowhoiscloud | 2026-03-18 |
| runtime-wiring5 | 런타임 와이어링 5건 (Gateway, CalendarBridge, Hook) | #241 | @mangowhoiscloud | 2026-03-18 |
| nl-router-remove | NL Router 제거 → AgenticLoop 직행 | #243→#244 | @mangowhoiscloud | 2026-03-18 |
| research-workflow | 프론티어 하네스 리서치 워크플로우 + 스킬 | #245→#246 | @mangowhoiscloud | 2026-03-18 |
| verify-team-wf | 검증팀 워크플로우 배치 (안 C) | #247→#248 | @mangowhoiscloud | 2026-03-18 |
| verify-team-skill | 검증팀 4인 페르소나 스킬 | #249→#250 | @mangowhoiscloud | 2026-03-18 |
| docs-sync-final | 문서 싱크 + README 수치 + progress.md | #251→#252 | @mangowhoiscloud | 2026-03-18 |
| nl-router-delete | nl_router.py 완전 삭제 + v0.19.1 릴리스 | #255→#256 | @mangowhoiscloud | 2026-03-18 |
| progress-kanban | progress.md 칸반 보드 고도화 + Step 6 | #259→#260 | @mangowhoiscloud | 2026-03-18 |
| dag-research | Claude Code Tasks DAG 리서치 리포트 | #261→#262 | @mangowhoiscloud | 2026-03-18 |
| kanban-design | 칸반 시스템 설계 문서 (Karpathy Dumb Platform) | #261→#262 | @mangowhoiscloud | 2026-03-18 |
| kanban-blog | GEODE 칸반 기술 블로그 (14,517자) | #261→#262 | @mangowhoiscloud | 2026-03-18 |
| pr-body-align | PR body 규칙 geode-gitflow 스킬 정렬 | #261→#262 | @mangowhoiscloud | 2026-03-18 |
| cli-audit | CLI 점검 감사 (코드 레벨) | 리서치 | @mangowhoiscloud | 2026-03-18 |
| gap-detection | Claude Code/Codex/OpenClaw GAP 탐지 | 리서치 | @mangowhoiscloud | 2026-03-18 |
| glm5-500-retry | LLM 500 에러 retry 미동작 수정 (LLMInternalServerError) | #265→#266 | @mangowhoiscloud | 2026-03-18 |

### Blocked

| task_id | 설명 | blocked_by | 사유 |
|---------|------|-----------|------|
| — | — | — | — |

---

## GAP Registry

프론티어 대비 누적 GAP. 해소되면 Resolved로 이동.

### P1 (High)

| gap_id | 설명 | 출처 | 관련 task_id |
|--------|------|------|-------------|
| gap-ctx-overflow | Token 초과 자동 압축 | OpenClaw + Karpathy P6 | context-overflow |
| gap-policy | 6-계층 Policy Chain | OpenClaw | policy-6layer |
| gap-cost-approval | EXPENSIVE_TOOLS 비용 조회+승인 UI | Claude Code | cost-approval |
| gap-multi-provider | Anthropic SDK 결합 해제 | Codex | multi-provider |

### P2 (Medium)

| gap_id | 설명 | 출처 | 관련 task_id |
|--------|------|------|-------------|
| gap-write-fallback | WRITE 거부 후 대안 경로 | Claude Code | write-fallback |
| gap-atomic-write | 모든 상태 파일 tmp+rename | OpenClaw | — |
| gap-webhook | HTTP Webhook Endpoint 완전 구현 | OpenClaw | — |

### Resolved

| gap_id | 해소 PR | 해소일 |
|--------|---------|--------|
| gap-gateway | #241→#242 | 2026-03-18 |
| gap-lane-queue | #241 | 2026-03-18 |
| gap-session-key | #241 | 2026-03-18 |
| gap-allowed-tools | #241 | 2026-03-18 |
| gap-trigger-src | #241 | 2026-03-18 |
| gap-hook-discovery | #241 | 2026-03-18 |
| gap-binding-reload | #241 | 2026-03-18 |
| gap-nl-router | #243→#244, #255→#256 | 2026-03-18 |
| gap-failover | — | 2026-03-18 |
| gap-announce | — | 2026-03-18 |
| gap-mcp-lifecycle | — | 2026-03-18 |

---

## Metrics

| 항목 | 값 | 갱신일 |
|------|-----|--------|
| Version | 0.19.1 | 2026-03-18 |
| Modules | 165 | 2026-03-18 |
| Tests | 2583 | 2026-03-18 |
| Tools | 46 | 2026-03-18 |
| MCP Catalog | 42 | 2026-03-18 |
| HookEvents | 34 | 2026-03-18 |
| Skills | 18 | 2026-03-18 |

---

## 규칙

1. **task_id**: 케밥 케이스, 고유, 변경 불가
2. **상태 흐름**: `Backlog → In Progress → In Review → Done` (역방향 이동 시 Blocked 경유)
3. **담당**: GitHub 계정 (`@username`)
4. **갱신 시점**: 세션 시작 시 읽기, 세션 종료 시 쓰기
5. **plan 연결**: `docs/plans/{task_id}.md` 경로로 연결
6. **GAP 연결**: GAP Registry의 `gap_id`와 Backlog의 `task_id` 매핑
7. **Done 이력**: 날짜별 그룹핑, 30일 초과 시 아카이브 (`docs/progress-archive/`)
