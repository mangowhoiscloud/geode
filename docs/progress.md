# GEODE Progress Board

> 멀티 에이전트 공유 칸반 보드. 모든 세션/에이전트가 이 파일을 읽고 갱신한다.
> 마지막 갱신: 2026-03-29 (세션 46 — system-hardening 착수)
> **규칙**: progress.md는 main에서만 수정. feature/develop 수정 금지.

---

## Kanban

### Backlog

| task_id | 작업 내용 | 우선순위 | plan | 비고 |
|---------|----------|:--------:|------|------|
| ~~shared-services~~ | ~~SharedServices Gateway — single factory + time_budget migration + HookSystem wiring + ContextVar fix~~ | ~~P0~~ | ~~shared-services-gateway.md~~ | **In Progress** |
| ~~system-hardening~~ | ~~System Hardening — agentic_ref race, orchestration locks, SubAgent safety, HookSystem wiring, Scheduler daemon~~ | ~~P0~~ | ~~system-hardening.md~~ | **In Progress** |
| concurrency-redesign | 동시성 시스템 재설계 — 워크로드별 세마포어 분리 + Gateway 제한 + 데드라인 큐잉 | P1 | — | 감사 완료, 구현 미착수 |
| ~~i18n-english~~ | ~~LLM 소비 문서 영어 전환 — 39 files (GEODE.md, CLAUDE.md, definitions.json, SKILL.md ×30, rules, PROJECT.md)~~ | ~~P1~~ | ~~#523~~ | **Done** |
| ~~kent-beck-p1~~ | ~~Phase 1 — dry-run 파싱 + Safety 상수 추출~~ | ~~P0~~ | ~~#462~~ | **Done** |
| ~~kent-beck-p2~~ | ~~Phase 2 — Provider 디스패치 딕셔너리 통합~~ | ~~P0~~ | ~~#463~~ | **Done** |
| ~~kent-beck-p3~~ | ~~Kent Beck Phase 3 — CLI God Object 분해 (~800줄 감소)~~ | ~~P1~~ | ~~#464~~ | **Done** |
| ~~kent-beck-p4~~ | ~~Kent Beck Phase 4 — runtime + agentic_loop 추출 (~265줄 감소)~~ | ~~P1~~ | ~~#465~~ | **Done** |
| ~~task-tools~~ | ~~Task Tool 노출 — task_create/update/get/list/stop + definitions.json + handlers~~ | ~~P1~~ | ~~#466~~ | **Done** |
| ~~kent-beck-p5~~ | ~~Kent Beck Phase 5 — 핸들러 레지스트리 + Executor 분해~~ | ~~P2~~ | ~~#467~~ | **Done** |
| ~~action-summary~~ | ~~Action Summary — 결정론적 Tier1~~ | ~~P1~~ | ~~#507~~ | **Done** |
| ~~autonomous-safety~~ | ~~야간 무인 3조건 — 비용 자동 정지 + 런타임 래칫 + 다양성 강제~~ | ~~P0~~ | ~~#513~~ | **Done** |
| graph-partial-state | graph.py 재시도 전 상태 스냅샷 (Karpathy P2) | P2 | — | 구조 변경 필요 |
| ~~proxy-cleanup~~ | ~~구 경로 proxy 파일 최종 삭제~~ | ~~P3~~ | ~~#470~~ | **Done** |
| e2e-phase6 | E2E 검증 Phase 6 — 서브에이전트, 스케줄러, 모델 전환, 세션 복원 | P2 | e2e-validation-plan.md | live LLM 필요 |
| ~~mcp-simplify~~ | ~~MCP 카탈로그 단일화~~ | ~~P1~~ | ~~#469~~ | **Done** |
| ~~scheduler-callback~~ | ~~스케줄러 callback 와이어링 — action 필드 + 큐 연결~~ | ~~P1~~ | ~~tool-mcp-architecture-review.md~~ | **Done** |
| ~~scheduler-nl-fix~~ | ~~스케줄러 NL 정규식 제거 → 원문 저장 + LLM 프레이밍 위임~~ | ~~P0~~ | ~~#483~~ | **Done** |
| ~~runtime-decompose-v2~~ | ~~runtime.py 1475→380줄 — 5-module split~~ | ~~P0~~ | ~~#484~~ | **Done** |
| ~~di-cleanup~~ | ~~불필요 ContextVar DI 8개 제거 — 직접 import로 대체~~ | ~~P0~~ | ~~#486~~ | **Done** |
| ~~cron-session-isolation~~ | ~~Cron systemEvent vs agentTurn 구분~~ | ~~P2~~ | ~~#487~~ | **Done** |
| ~~hook-turn-complete~~ | ~~TURN_COMPLETE 자동 메모리~~ | ~~P1~~ | ~~#488~~ | **Done** |
| ~~geode-dir-hierarchy~~ | ~~.geode/ 디렉토리 계층화~~ | ~~P1~~ | ~~#491~~ | **Done** |
| ~~hook-context-action~~ | ~~CONTEXT_CRITICAL 행동 위임~~ | ~~P2~~ | ~~#490~~ | **Done** |
| ~~hook-session-start~~ | ~~SESSION_START 동적 프롬프트~~ | ~~P2~~ | ~~#489~~ | **Done** |
| ~~hook-llm-lifecycle~~ | ~~LLM_CALL_START/END — latency/cost 관측~~ | ~~P2~~ | ~~#492~~ | **Done** |
| ~~hook-tool-approval~~ | ~~TOOL_APPROVAL 3종 — HITL 승인 패턴~~ | ~~P2~~ | ~~#494~~ | **Done** |
| ~~context-long-session~~ | ~~장시간 운용 컨텍스트 관리 — Provider별 압축 전략 분화 + 대화 요약 + 압축 알림~~ | ~~P0~~ | ~~#500~~ | **Done** |
| ~~hook-model-switched~~ | ~~MODEL_SWITCHED — 전환 사유 기록~~ | ~~P3~~ | ~~#503~~ | **Done** |
| ~~hook-filesystem-plugin~~ | ~~파일시스템 Hook 플러그인 — .geode/hooks/ 자동 발견~~ | ~~P3~~ | ~~#503~~ | **Done** |
| ~~gateway-binding-hotreload~~ | ~~바인딩 핫 리로드 — config.toml 재시작 불필요~~ | ~~P3~~ | ~~#504~~ | **Done** |
| ~~gateway-hooks-l4~~ | ~~Gateway Hooks (L4) — 외부 웹훅 → 에이전트 트리거~~ | ~~P3~~ | ~~#504~~ | **Done** |
| ~~agentic-provider-merge~~ | ~~agent/adapters/ → llm/providers/ 통합~~ | ~~P2~~ | ~~#473~~ | **Done** |
| ~~ports-migrate~~ | ~~infrastructure/ports/ → domain co-locate 이동 (8포트, 40+ 소비자)~~ | ~~P2~~ | ~~#474~~ | **Done** |
### In Progress

| task_id | 작업 내용 | 담당 | 브랜치 | 시작일 | 비고 |
|---------|----------|------|--------|--------|------|
| system-hardening | System Hardening — C1-C4 + H1-H9 + M1 + Scheduler daemon | @mangowhoiscloud | feature/system-hardening | 2026-03-29 | 감사 결과 기반 |

### In Review

| task_id | 작업 내용 | PR | 담당 | CI | 비고 |
|---------|----------|-----|------|-----|------|

### Done (2026-03-29 — 세션 46)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| shared-services | SharedServices Gateway — single factory + time_budget + HookSystem + ContextVar | #525 | @mangowhoiscloud | 2026-03-29 |

### Done (2026-03-29 — 세션 45-46)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| skill-2.0 | Skill 2.0 — Progressive Disclosure + fork + Dynamic Context + Multi-scope | #521 | @mangowhoiscloud | 2026-03-29 |
| subprocess-isolation | Sub-Agent Subprocess Isolation + IsolatedRunner dual-mode | v0.34.0 | @mangowhoiscloud | 2026-03-29 |
| scheduler-async-drain | 스케줄 잡 비동기 실행 — IsolatedRunner.run_async() 전환 | #519 #520 | @mangowhoiscloud | 2026-03-29 |

### Done (2026-03-27 — 세션 44)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| autonomous-safety | 야간 무인 3조건 — 비용 자동 정지 + 런타임 래칫 + 다양성 강제 | #513 | @mangowhoiscloud | 2026-03-28 |
| action-summary | Action Summary Tier 1 — 결정론적 per-tool 요약 (토큰 비용 0) | #507 | @mangowhoiscloud | 2026-03-28 |
| p3-gateway-batch | binding hot-reload + L4 webhook endpoint | #504 | @mangowhoiscloud | 2026-03-28 |
| p3-hook-batch | MODEL_SWITCHED + filesystem plugin + README docs-sync | #503 | @mangowhoiscloud | 2026-03-28 |
| context-long-session | Provider-aware context compaction — GAP-1~5 일괄 해소 (Anthropic 서버사이드 + OpenAI/GLM 클라이언트) | #500 | @mangowhoiscloud | 2026-03-28 |
| hook-approval-fix | TOOL_APPROVAL 이벤트명 불일치 수정 — decided→granted/denied (SOT 점검) | #497 | @mangowhoiscloud | 2026-03-28 |
| hook-tool-approval | TOOL_APPROVAL 3종 — HITL 승인 패턴 추적 (L4 Autonomy) | #494 | @mangowhoiscloud | 2026-03-27 |
| hook-llm-lifecycle | LLM_CALL_START/END — latency/cost 관측 (L1 Observe) | #492 | @mangowhoiscloud | 2026-03-27 |
| hook-context-action | CONTEXT_OVERFLOW_ACTION — 압축 전략 Hook 위임 + trigger_with_result() | #490 | @mangowhoiscloud | 2026-03-27 |
| hook-session-start | SESSION_START/END — 세션 라이프사이클 이벤트 | #489 | @mangowhoiscloud | 2026-03-27 |
| hook-turn-complete | TURN_COMPLETE 자동 메모리 — OpenClaw command:new 패턴 | #488 | @mangowhoiscloud | 2026-03-27 |
| openai-responses-v2 | OpenAI Responses API 전환 + 3사 네이티브 웹 검색 fallback + Brave 제거 | #485 | @mangowhoiscloud | 2026-03-27 |

### Done (2026-03-27 — 세션 43)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| cron-session-isolation | Cron 세션 격리 — OpenClaw agentTurn/systemEvent 패턴 | #487 | @mangowhoiscloud | 2026-03-27 |
| di-cleanup | 불필요 ContextVar DI 8개 제거 — 모듈 변수로 대체 (프론티어 패턴 정렬) | #486 | @mangowhoiscloud | 2026-03-27 |
| fixtures-cleanup | core/fixtures/ 삭제 + scaffold skills .claude/skills/ 분리 | #478 | @mangowhoiscloud | 2026-03-27 |
| runtime-decompose-v2 | runtime.py 1476→517줄 — 5-module OpenClaw-style decomposition | #484 | @mangowhoiscloud | 2026-03-27 |
| scheduler-nl-fix | NL 정규식 제거 → 원문 저장 + LLM 프레이밍 위임 | #483 | @mangowhoiscloud | 2026-03-27 |
| scheduler-callback | 스케줄러 action queue 와이어링 — NL job 발화 시 AgenticLoop 실행 | #482 | @mangowhoiscloud | 2026-03-27 |

### Done (2026-03-27 — 세션 42)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| runtime-decompose | GeodeRuntime.create() 243줄 → 4 sub-builder 분해 (1488→1477줄) | #481 | @mangowhoiscloud | 2026-03-27 |
| claude-md-skill-cleanup | CLAUDE.md clean-architecture + architecture-patterns 제거 | #480 | @mangowhoiscloud | 2026-03-27 |
| port-cleanup-3 | memory/port.py 단일 구현 Protocol 3개 삭제 + calendar_bridge automation/ 이동 | #479 | @mangowhoiscloud | 2026-03-27 |

### Done (2026-03-27 — 세션 41)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| hook-extract | HookSystem → core/hooks/ 분리 (cross-cutting concern, L0→L3 의존성 위반 해소) | #477 | @mangowhoiscloud | 2026-03-27 |
| prompt-cleanup | 프롬프트 영어 통일 + output_language 파이프라인 + 언어 감지 (Karpathy P7) | #476 | @mangowhoiscloud | 2026-03-27 |
| ports-cleanup-2 | 단일 구현 Protocol 6개 삭제 — HookSystemPort/ToolPort/GatewayPort/AutomationPort/OrchestrationPort/AuthPort | #475 | @mangowhoiscloud | 2026-03-27 |
| agentic-provider-merge | agent/adapters/ → llm/providers/ 통합 — 모듈 수 195 → 187 | #473 | @mangowhoiscloud | 2026-03-27 |
| ports-migrate | infrastructure/ports/ → domain co-locate — infrastructure/ 디렉터리 제거 | #474 | @mangowhoiscloud | 2026-03-27 |

### Done (2026-03-27 — 세션 37)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| proxy-cleanup | 구 경로 proxy/stub 삭제 + atomic_io/signal_adapter 이동 | #470 | @mangowhoiscloud | 2026-03-27 |
| mcp-simplify | MCP 카탈로그 단일화 — registry 삭제 + catalog 축소 + config.toml 통합 | #469 | @mangowhoiscloud | 2026-03-27 |

### Done (2026-03-27 — 세션 35)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| task-tools | Task Tool 노출 — task_create/update/get/list/stop + /tasks 커맨드 | #466 | @mangowhoiscloud | 2026-03-27 |

### Done (2026-03-26 — 세션 36)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| kent-beck-p5 | Kent Beck Phase 5 — 핸들러 레지스트리 + Executor 분해 | #467 | @mangowhoiscloud | 2026-03-26 |

### Done (2026-03-26 — 세션 35)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| kent-beck-p4 | Kent Beck Phase 4 — runtime 훅 추출 + MCP 팩토리 + arun 결과 DRY | #465 | @mangowhoiscloud | 2026-03-26 |
| kent-beck-p3 | Kent Beck Phase 3 — CLI God Object 분해 (session_state + cmd_schedule 추출) | #464 | @mangowhoiscloud | 2026-03-26 |


### Done (2026-03-26 — 세션 33)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| kent-beck-p2 | Kent Beck Phase 2 — Provider 디스패치 딕셔너리 통합 | #463 | @mangowhoiscloud | 2026-03-26 |
| kent-beck-p1 | Kent Beck Phase 1 — dry-run 파싱 + Safety 상수 추출 (DRY) | #462 | @mangowhoiscloud | 2026-03-26 |
| gateway-config | Gateway-REPL 통합 팩토리 + config.toml 상수화 + SUFFIX 적극성 조정 | #461 | @mangowhoiscloud | 2026-03-26 |
| gateway-multiturn | Gateway 멀티턴 대화 지원 — thread_id 기반 세션 영속화 + MessageProcessor 확장 | #459 | @mangowhoiscloud | 2026-03-26 |

### Done (2026-03-26 — 세션 32)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| action-display | Action Display 개선 — tool-type 그루핑 + 서브에이전트 progressive counter + 턴 끝 컴팩트 요약 | — | @mangowhoiscloud | 2026-03-26 |
| docs-sync-v0291 | v0.29.1 릴리스 docs-sync — 버전 4곳 + 3219 tests + CHANGELOG | main direct | @mangowhoiscloud | 2026-03-26 |

### Done (2026-03-26 — 세션 30)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| llm-layer-f-p2 | F안 Phase 2 — client.py 분할(Provider Module) + Adapter 이동 + Proxy 47파일 삭제 (-710줄) | — | @mangowhoiscloud | 2026-03-26 |
| context-persistence | .geode/ 컨텍스트 영속성 — geode init 글로벌→프로젝트 시딩 + 로드 상태 표시 + 경고 로그 | — | @mangowhoiscloud | 2026-03-26 |
| docs-sync-v029 | v0.29.0 릴리스 docs-sync — 버전 4곳 + 202 modules + 3202 tests + CHANGELOG | main direct | @mangowhoiscloud | 2026-03-26 |

### Done (2026-03-26 — 세션 29)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| native-tools | 3사 Agent SDK 네이티브 도구 통합 — Anthropic web_search/web_fetch/code_exec + OpenAI Responses API + GLM-5 web_search | #456 | @mangowhoiscloud | 2026-03-26 |

### Done (2026-03-26 — 세션 28)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| pipeline-model-fixed | 파이프라인 모델 고정 — Analyst/Evaluator/Synthesizer Opus 4.6 고정 + 실행 전 유저 안내 | — | @mangowhoiscloud | 2026-03-26 |
| glm-pipeline-routing | GLM-5 파이프라인 라우팅 — call_llm_parsed provider 분기 수정 | #450 | @mangowhoiscloud | 2026-03-26 |
| status-line-per-turn | Status line per-turn — SessionMeter/TokenTracker 턴 단위 리셋 | #450 | @mangowhoiscloud | 2026-03-26 |
| portfolio-carousel | 포트폴리오 REPL 유즈케이스 캐러셀 — 좌우 네비게이션, 3카드, GLM-5 실측 | portfolio | @mangowhoiscloud | 2026-03-26 |

### Done (2026-03-26 — 세션 27)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| signal-live-api | Signal Tools 5종 MCP 라이브 연동 — stub→MCP-first+fixture fallback | #447→#448 | @mangowhoiscloud | 2026-03-26 |

### Done (2026-03-26 — 세션 26)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| ui-parallel-spinner | 서브에이전트 병렬 실행 시 UI 스피너 과다 출력 정돈 | #441→#442 | @mangowhoiscloud | 2026-03-26 |
| docs-sync | v0.27.0 릴리스 docs-sync — 버전 4곳 + Tests 3088 + CHANGELOG | main direct | @mangowhoiscloud | 2026-03-26 |
| model-switch-guard | 모델 스위칭 컨텍스트 가드 — 선제적 적응 (방안 E 하이브리드) | #443→#444 | @mangowhoiscloud | 2026-03-26 |

### Done (2026-03-25 — 세션 25)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| glm-context-guard | GLM-5 컨텍스트 오버플로우 방어 — 모델별 동적 tool result 가드 | #439→#440 | @mangowhoiscloud | 2026-03-25 |
| gateway-resource-sharing | Gateway 리소스 공유 — env cascade + 글로벌 메모리 fallback + User Context 주입 | #437→#438 | @mangowhoiscloud | 2026-03-25 |

### Done (2026-03-25 — 세션 24)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| quality-thread-safety | Thread Safety 4건 — HookSystem/ResultCache/Stats Lock 추가 | #436 | @mangowhoiscloud | 2026-03-25 |
| quality-error-handling | Error Handling 4건 — synthesizer KeyError 방어 + MemoryTools 경고 + scoring 검증 | #436 | @mangowhoiscloud | 2026-03-25 |
| quality-dry-resource | DRY + Resource 4건 — retry 통합 + httpx lifecycle + DAG strict + MCP shim 삭제 | #436 | @mangowhoiscloud | 2026-03-25 |
| quality-tool-extract | AgenticLoop ToolCallProcessor 추출 (agentic_loop -477줄) | #436 | @mangowhoiscloud | 2026-03-25 |
| quality-test-isolation | Flaky test SnapshotManager 격리 (tmp_path) | #436 | @mangowhoiscloud | 2026-03-25 |
| repl-interception-remove | REPL 입력 가로채기 제거 — detect_api_key + dry-run regex + is_glm_key 강화 | #436 | @mangowhoiscloud | 2026-03-25 |
| billing-ux | 빌링 에러 UI 보강 — BillingError 전용 예외 | #434→#435 | @mangowhoiscloud | 2026-03-25 |

### Done (2026-03-25 — 세션 23)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| memory-hierarchy-prompt | 메모리 계층 4-tier 시스템 프롬프트 주입 (GEODE.md + MEMORY.md + LEARNING.md) | #429→#431 | @mangowhoiscloud | 2026-03-25 |
| mcp-bootstrap-fix | MCP 부트스트랩 수정 — 외부 디렉토리 MCP 0 이슈 + load_config 추가 | #430→#431 | @mangowhoiscloud | 2026-03-25 |
| mcp-lazy-parallel | MCP get_all_tools() lazy parallel 연결 — REPL ~100s 멈춤 해소 | #432→#433 | @mangowhoiscloud | 2026-03-25 |

### Done (2026-03-25 — 세션 22)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| skills-geode-path | Skills 경로 .claude/skills → .geode/skills 마이그레이션 + CWD 독립 해석 | #427→#428 | @mangowhoiscloud | 2026-03-25 |
| docs-sync-v0242 | v0.24.2 docs-sync — CHANGELOG + 버전 4곳 + 수치 실측 갱신 | main direct | @mangowhoiscloud | 2026-03-25 |

### Done (2026-03-25 — 세션 21)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| fix-memory-path | 메모리 경로 표시 .claude/ → .geode/ 수정 (startup + memory_tools + docstring) | #425→#426 | @mangowhoiscloud | 2026-03-25 |
| docs-sync | v0.24.1 docs-sync — CHANGELOG + 버전 4곳 + 수치 실측 갱신 | main direct | @mangowhoiscloud | 2026-03-25 |

### Done (2026-03-25 — 세션 20)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| atomic-context-career | Atomic write + /context + career.toml 병합 | #337→#406 | @mangowhoiscloud | 2026-03-24 |
| verification-remediation | 검증팀 P0/P1 — tool guard, fsync, CI ratchet, prompt integrity | #407→#408 | @mangowhoiscloud | 2026-03-24 |
| god-object-logging | Runtime DRY + 로깅 구조화 + tool desc -47% | #409→#410 | @mangowhoiscloud | 2026-03-24 |
| folder-phase1 | 폴더 구조 Phase 1 — nodes/fixtures/config/ui 이동 + Strangler Fig proxy | #411→#412 | @mangowhoiscloud | 2026-03-24 |
| folder-phase2-4 | 폴더 구조 Phase 2-4 — import 마이그레이션 + proxy 제거 + CI 래칫 | #413→#414 | @mangowhoiscloud | 2026-03-24 |
| folder-phase5 | auth→gateway/auth + extensibility→skills | #415→#416 | @mangowhoiscloud | 2026-03-24 |
| folder-agent-mcp | agent/ 분리 + mcp/ 통합 — 폴더 구조 최종 수렴 | #417→#418 | @mangowhoiscloud | 2026-03-24 |
| quality-p0 | 코드 품질 P0 6건 — 거짓 주석, path traversal, race condition, redaction, 에러 메시지, env 보안 | #419→#420 | @mangowhoiscloud | 2026-03-25 |
| quality-p1 | 코드 품질 P1 6건 — 매직 넘버, safety gates, 약어, 로그 승격, 디렉토리 권한 | #421→#422 | @mangowhoiscloud | 2026-03-25 |
| model-nontty | /model non-tty graceful fallback + 테스트 mock | #423→#424 | @mangowhoiscloud | 2026-03-25 |

### Done (2026-03-24 — 세션 16)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| slack-bootstrap-pr | REPL bootstrap 통합 + Slack mrkdwn v2 — PR flow 정규화 (#402→#403) + CI 수정 (import 정렬 + flaky 격리) | #402→#403 | @mangowhoiscloud | 2026-03-24 |

### Done (2026-03-24 — 세션 14)

| task_id | 작업 내용 | PR | 담당 | 완료일 |
|---------|----------|----|------|--------|
| repl-bootstrap-unify | REPL→bootstrap_geode() 통합 — 인라인 6단계→bootstrap 호출 (serve/REPL 단일 경로) | main direct | @mangowhoiscloud | 2026-03-24 |
| slack-mrkdwn-v2 | Slack mrkdwn 개선 — ZWS 경계 수정 + 테이블→섹션 + 코드블록 보호 (33 tests) | main direct | @mangowhoiscloud | 2026-03-24 |
| slack-e2e-scenarios | Slack @GEODE 3시나리오 E2E — web_fetch + web_search + memory_save 실증 | main direct | @mangowhoiscloud | 2026-03-24 |
| context-quality-review | .geode/ + CLAUDE.md 컨텍스트 품질 — 3인 검증팀, -132줄 블로트 제거 | #400→#401 | @mangowhoiscloud | 2026-03-24 |
| gmail-integration | Gmail MCP 통합 — OAuth 기반, DEFAULT_SERVERS 등록, catalog 43개 | #396→#397 | @mangowhoiscloud | 2026-03-24 |
| serve-repl-unify | bootstrap_geode() 단일 초기화 + ContextVar 전파 (14 tests) | #394→#395 | @mangowhoiscloud | 2026-03-24 |
| web-fetch-ssl | web_fetch SSL fallback — Python 3.14 certifi 호환 | #392→#393 | @mangowhoiscloud | 2026-03-24 |
| wrapper-removal | _build_tool_handlers wrapper 삭제 — 상단 re-export + Beck/Karpathy 검증 | main direct | @mangowhoiscloud | 2026-03-24 |
| slack-mrkdwn | Slack mrkdwn 변환 — Markdown→Slack 포맷 자동 변환 (22 tests) | #390→#391 | @mangowhoiscloud | 2026-03-24 |
| context-hub | Context Hub 3건 — career.toml + /context + /apply (26 tests) | #388→#389 | @mangowhoiscloud | 2026-03-23 |
| backlog-sweep | Backlog 4건 일괄 — MCP lazy refresh + Playwright sync + YouTube key + API 발급 링크 | #386→#387 | @mangowhoiscloud | 2026-03-23 |
| runtime-builder | GeodeRuntime 30→3 params — RuntimeCoreConfig/AutomationConfig/MemoryConfig 데이터클래스 | #384→#385 | @mangowhoiscloud | 2026-03-23 |
| codebase-audit-skill | codebase-audit 스킬 증류 — 감사+리팩토링 워크플로우 (v0.24.0 실증) | #382→#383 | @mangowhoiscloud | 2026-03-23 |
| init-god-object | __init__.py God Object 분할 — pipeline_executor + report_renderer 추출 (-786줄, -31%) | #380→#383 | @mangowhoiscloud | 2026-03-23 |
| codebase-cleanup | 데드코드 6모듈 1,243줄 삭제 + 의존 테스트 5개 삭제 (Modules 184→178, Tests 3057→2972) | #378→#379 | @mangowhoiscloud | 2026-03-23 |
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
| Version | 0.29.1 | 2026-03-26 |
| Modules | 202 | 2026-03-26 |
| Tests | 3219 | 2026-03-26 |
| Tools | 47 (+MCP) | 2026-03-26 |
| MCP Catalog | 44 | 2026-03-26 |
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
