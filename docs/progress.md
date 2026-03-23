# GEODE Progress Board

> 멀티 에이전트 공유 칸반 보드. 모든 세션/에이전트가 이 파일을 읽고 갱신한다.
> 마지막 갱신: 2026-03-22 (세션 12 — 날짜 주입 + Slack 에코 제거 + @멘션 게이트)
> **규칙**: progress.md는 main에서만 수정. feature/develop 수정 금지.

---

## Kanban

### Backlog

| task_id | 작업 내용 | 우선순위 | plan | 비고 |
|---------|----------|:--------:|------|------|
| mcp-tool-refresh | MCP startup 후 AgenticLoop 도구 목록 갱신 — Playwright 등 MCP 도구 미인식 문제 | P1 | — | MCP 연결 후 refresh_tools() 호출 |
| mcp-singleton-notify | MCPServerManager 싱글턴 → NotificationAdapter 공유 완성 — Poller 우회 제거 | P1 | — | runtime.py 구조 리팩토링 |
| youtube-api-key | YouTube MCP 활성화 — YOUTUBE_API_KEY 설정 + fixture↔API 이중 구현 정리 | P2 | — | GOOGLE_API_KEY와 별개 |
| playwright-catalog-sync | Playwright catalog 패키지명 @playwright/mcp로 갱신 | P3 | — | JSON override와 정합성 |
| career-identity | C0 Identity career.toml 로딩 + 시스템 프롬프트 주입 | P1 | geode-context-hub.md Phase E | UserProfile 확장 |
| app-tracker | C4 Plan tracker.json 지원 상태 CRUD + /apply 커맨드 | P1 | geode-context-hub.md Phase F | Vault applications 연동 |
| context-command | /context 슬래시 커맨드 + Startup 자동 주입 | P2 | geode-context-hub.md Phase C | 전 계층 요약 표시 |

### In Progress

| task_id | 작업 내용 | 담당 | 브랜치 | 시작일 | 비고 |
|---------|----------|------|--------|--------|------| — | — | — | — | — | — |

### In Review

| task_id | 작업 내용 | PR | 담당 | CI | 비고 |
|---------|----------|-----|------|-----|------|
| — | — | — | — | — | — |

### Done (2026-03-22)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| deadcode-handler-unify | 인라인 handler 898줄 삭제 + tool_handlers.py 단일 소스화 (__init__.py -26%) | #376→#377 | @mangowhoiscloud | 2026-03-23 |
| serve-e2e-parity | serve CLI 완전 동등성 — tool_handlers.py 빌더 + readiness 초기화 + 44 handlers E2E 검증 | #374→#375 | @mangowhoiscloud | 2026-03-23 |
| gateway-exclusive | Gateway를 geode serve 전용으로 분리 — REPL 이중 폴링 제거 (OpenClaw 패턴) | #372→#373 | @mangowhoiscloud | 2026-03-23 |
| serve-full-capability | geode serve processor REPL 동등 역량 — MCP 86 + SubAgent + Skills 추가 | main direct | @mangowhoiscloud | 2026-03-23 |
| slack-mention-botid | Slack Bot ID 멘션 인식 + 리액션 눈알 이모지 | main direct | @mangowhoiscloud | 2026-03-23 |
| slack-reaction-mention | Slack 리액션을 @멘션 메시지에만 추가 | main direct | @mangowhoiscloud | 2026-03-23 |
| model-match | switch_model 퍼지 매칭 — 하이픈/공백 정규화로 GLM5→glm-5 등 인식 | #369→#371 | @mangowhoiscloud | 2026-03-22 |
| slack-reaction-ux | Slack 리액션 UX — 처리 중 모래시계 + 완료 체크마크, 파라미터 수정 | #370→#371 | @mangowhoiscloud | 2026-03-22 |
| context-claude-align | Context management Claude Code 정합 — 80% compaction 제거, clear_tool_uses 의존, -54줄 | #367→#368 | @mangowhoiscloud | 2026-03-22 |
| web-fetch-hardcap | web_fetch max_chars 하드캡 10000 + Token Guard 0 복원 (프론티어 정합) | main direct | @mangowhoiscloud | 2026-03-22 |
| mention-gate | Slack @멘션 전용 응답 게이트 + 멘션 태그 제거 | #363→#364 | @mangowhoiscloud | 2026-03-22 |
| slack-echo-fix | Slack Gateway 사용자 메시지 반복 에코 제거 + 리액션 인디케이터 | #359→#360 | @mangowhoiscloud | 2026-03-22 |
| date-injection | 시스템 프롬프트 현재 날짜 주입 — LLM 연도 오류 방지 | #353→#356 | @mangowhoiscloud | 2026-03-22 |
| context-overflow-fix | Context overflow 방지 — Token Guard 4000 + tool_result 절삭 + keep_recent 설정 | #365→#366 | @mangowhoiscloud | 2026-03-22 |
| mcp-parallel-startup | MCP 서버 병렬 연결 — 순차 110s→~15s (ThreadPoolExecutor) | #361→#362 | @mangowhoiscloud | 2026-03-22 |
| glm-failover-noise | Failover 로그 노이즈 제거 (warning→debug) + LLM timeout 90s→120s | #357→#358 | @mangowhoiscloud | 2026-03-22 |
| gateway-bidirectional | Gateway 양방향 소통 — 로깅 추가, 중복 방지(ts seeding), 메시지별 독립 context, 에러 가시성 | #354→#355 | @mangowhoiscloud | 2026-03-22 |
| mcp-singleton | MCPServerManager 싱글턴화 — 좀비 프로세스 근절 + 4곳 get_mcp_manager() 전환 | main direct | @mangowhoiscloud | 2026-03-22 |
| slack-adapter-fix | Slack MCP tool 이름 정합성 + NotificationAdapter kwargs 전달 + MCP content wrapper 파싱 | main direct | @mangowhoiscloud | 2026-03-22 |
| slack-poller-fix | SlackPoller channel→channel_id + MCP JSON wrapper 파싱 + bot_id 필터 | main direct | @mangowhoiscloud | 2026-03-22 |
| geode-serve | geode serve 커맨드 — headless Gateway 데몬 모드 (nohup 실행 가능) | main direct | @mangowhoiscloud | 2026-03-22 |
| glm-url-fix | GLM base URL api.z.ai→open.bigmodel.cn + keepalive 15s→30s + MCP 테스트 격리 | #343→#344 | @mangowhoiscloud | 2026-03-22 |
| mcp-log-noise | MCP startup 로그 warning→debug — 유저 콘솔 노출 방지 | #345→#346 | @mangowhoiscloud | 2026-03-22 |
| slack-echo-fix | Slack Gateway 사용자 메시지 반복 에코 제거 + 리액션 인디케이터 | #359→#360 | @mangowhoiscloud | 2026-03-22 |
| date-injection | 시스템 프롬프트 현재 날짜 주입 — LLM 연도 오류 방지 | #353→#356 | @mangowhoiscloud | 2026-03-22 |

### Done (2026-03-21)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| reode-skill-port | REODE 역수입 스킬 5건 — explore-reason-act, anti-deception, code-review-quality, dependency-review, kent-beck-review | #341→#342 | @mangowhoiscloud | 2026-03-21 |
| harness-patterns | REODE 하네스 패턴 7건 — HITL level 0/1/2, Session approval A=Always, Model/Cross-provider escalation, Backpressure, Convergence detection, Model-first inference | #339→#340 | @mangowhoiscloud | 2026-03-21 |
| sandbox-hardening | 샌드박스 보안 경계 4건 — PolicyChain L1-2, SubAgent denied_tools, Bash setrlimit, Secret redaction | #338→#340 | @mangowhoiscloud | 2026-03-21 |
| session-resume | Session resume — per-turn checkpoint + /resume 와이어링 + --continue/--resume CLI 플래그 | #334 | @mangowhoiscloud | 2026-03-21 |
| test-isolation | 테스트 세션 격리 — conftest.py에서 checkpoint/transcript 기본 경로 tmp 리다이렉트 | #334 | @mangowhoiscloud | 2026-03-21 |
| manage-auth-hint | manage_auth WRITE_FALLBACK_HINTS 누락 수정 | #334 | @mangowhoiscloud | 2026-03-21 |

### Done (2026-03-19)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| version-bump | v0.20.0 릴리스 — [Unreleased]→[0.20.0] + 4곳 동기화 + ABOUT 갱신 | #308→#309 | @mangowhoiscloud | 2026-03-19 |
| readme-update | README 칸반 + .geode/ 구조 + GAP 해소 | #306→#307 | @mangowhoiscloud | 2026-03-19 |
| workflow-hardening | 워크플로우 고도화 — 동기화 검증 + Plan 강제 + 칸반 규칙 강화 | #304→#305 | @mangowhoiscloud | 2026-03-19 |
| report-enrich | IP 보고서 DAG 정보 보강 — 4개 섹션 추가 + 테스트 + 보안 수정 | #298+#301→#300+#303 | @mangowhoiscloud | 2026-03-19 |
| multi-model-gap | 멀티모델 GAP 해소 — .env 자동 생성 + 키 검증 + 테스트 + 보안 수정 | #299+#302→#300+#303 | @mangowhoiscloud | 2026-03-19 |
| geode-system | .geode/ 시스템 구축 — 에이전트 정체성 분리 + 메모리 계층 정비 | #296→#297 | @mangowhoiscloud | 2026-03-19 |
| readme-narrative | README '왜 만들었는가' 내러티브 보강 | #294→#295 | @mangowhoiscloud | 2026-03-19 |
| multi-provider-glm | Multi-Provider GLM + CANNOT 워크플로우 + 모델 최신화 | #291+#292→#293 | @mangowhoiscloud | 2026-03-19 |
| version-sot | 버전 SOT 일원화 + 하네스 디렉토리 탐지 | #289→#290 | @mangowhoiscloud | 2026-03-19 |
| project-local-context | geode init 프로젝트-로컬 컨텍스트 어셈블리 개선 | #287→#288 | @mangowhoiscloud | 2026-03-19 |
| ci-self-hosted | CI self-hosted runner 전환 | #285→#286 | @mangowhoiscloud | 2026-03-19 |
| workflow-reode-sync | REODE 워크플로우 6건 이식 + 칸반 3-checkpoint | #283→#284 | @mangowhoiscloud | 2026-03-19 |

### Done (2026-03-18)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| vault-v0 | Vault (V0) — 산출물 영속 저장소 (profile/research/applications/general) | #279→#280 | @mangowhoiscloud | 2026-03-18 |
| context-hub-ab | .geode Context Hub Phase A+B — Journal + SessionCheckpoint | #277→#278 | @mangowhoiscloud | 2026-03-18 |
| multi-provider | Multi-Provider AgenticLoop — AgenticResponse + OpenAI 경로 | #275→#276 | @mangowhoiscloud | 2026-03-18 |
| write-fallback | WRITE 거부 후 대안 제안 fallback | #275→#276 | @mangowhoiscloud | 2026-03-18 |
| context-overflow | Context Overflow Detection — ContextMonitor + Hook | #273→#274 | @mangowhoiscloud | 2026-03-18 |
| policy-6layer | 6-Layer Policy Chain — Profile + Org 레이어 | #273→#274 | @mangowhoiscloud | 2026-03-18 |
| cost-approval | /cost 대시보드 — 세션/월간/예산 조회 + 예산 설정 | #273→#274 | @mangowhoiscloud | 2026-03-18 |
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

| task_id | 작업 내용 | blocked_by | 사유 |
|---------|------|-----------|------|
| — | — | — | — |

---

## GAP Registry

프론티어 대비 누적 GAP. 해소되면 Resolved로 이동.

### P1 (High)

| gap_id | 설명 | 출처 | 관련 task_id |
|--------|------|------|-------------|
| — | — | — | — |

### P2 (Medium)

| gap_id | 설명 | 출처 | 관련 task_id |
|--------|------|------|-------------|
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
| gap-ctx-overflow | — | 2026-03-18 |
| gap-policy | — | 2026-03-18 |
| gap-cost-approval | — | 2026-03-18 |
| gap-multi-provider | — | 2026-03-18 |
| gap-write-fallback | — | 2026-03-18 |
| gap-session-resume | #334 | 2026-03-21 |
| gap-test-isolation | #334 | 2026-03-21 |
| gap-manage-auth-hint | #334 | 2026-03-21 |

---

## Metrics

| 항목 | 값 | 갱신일 |
|------|-----|--------|
| Version | 0.24.0 | 2026-03-22 |
| Modules | 184 | 2026-03-22 |
| Tests | 3055 | 2026-03-22 |
| Tools | 46 (+MCP 86) | 2026-03-22 |
| MCP Catalog | 42 | 2026-03-19 |
| HookEvents | 36 | 2026-03-19 |
| Skills | 25 | 2026-03-21 |

---

## 규칙

1. **task_id**: 케밥 케이스, 고유, 변경 불가
2. **상태 흐름**: `Backlog → In Progress → In Review → Done` (역방향 이동 시 Blocked 경유)
3. **Backlog → Done 직행 금지** — 반드시 In Progress 경유 (REODE 패턴)
4. **main-only 편집** — progress.md는 feature/develop 브랜치에서 수정 금지 (REODE 패턴)
5. **3-Checkpoint 갱신**: alloc(Step 0) → free(PR merge 후) → session-start(교차 검증)
6. **담당**: GitHub 계정 (`@username`)
7. **plan 연결**: `docs/plans/{task_id}.md` 경로로 연결
8. **GAP 연결**: GAP Registry의 `gap_id`와 Backlog의 `task_id` 매핑
9. **Done 이력**: 날짜별 그룹핑, 30일 초과 시 아카이브 (`docs/progress-archive/`)
10. **필수 컬럼 누락 금지** — 모든 컬럼에 값 기입 필수. 해당 없으면 "—"으로 표기. 빈칸 방치 금지.
11. **컬럼 재선정** — 프로젝트 상황에 따라 컬럼 추가/제거/순서 변경 가능. 단, task_id·작업 내용은 모든 상태에서 필수 유지.
12. **Claude Code Task 연동** — TaskCreate로 생성한 세션 태스크의 subject를 칸반 task_id와 1:1 매핑. 상태 동기화: TaskUpdate status ↔ 칸반 상태 이동.
