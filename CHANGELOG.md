# Changelog

All notable changes to the GEODE project will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Scope Rules

**What to record**:
- New features (Added) — user-facing capabilities, new modules, new tools
- Breaking changes (Changed) — API changes, renamed modules, behavior shifts
- Bug fixes (Fixed) — corrected behavior, edge case handling
- Removals (Removed) — deleted modules, deprecated features
- Infrastructure (Infrastructure) — CI, build, dependency changes
- Architecture (Architecture) — structural decisions that affect future development

**What NOT to record**:
- Internal refactors that don't change behavior (unless architecturally significant)
- Code quality passes (R1→R8 rounds) — summarize as one entry
- Merge commits, branch operations
- Documentation-only changes (blogs, README updates)
- Commit-level granularity — aggregate by feature area

**Granularity**: Feature-level, not commit-level. One entry per logical change.

---

## [Unreleased]

### Changed
- NL Router 이중 라우팅 제거 — 모든 자유 텍스트 AgenticLoop 직행. ip_names.py, system_prompt.py 분리 추출
- README NL Router → AgenticLoop 표기 전환 + 도구 수 46개 반영

### Added
- `frontier-harness-research` 스킬 — Claude Code/Codex/OpenClaw/autoresearch 4종 비교 리서치 프로세스
- `verification-team` 스킬 — 4인 페르소나 검증 (Beck/Karpathy/Steinberger/Cherny)
- 워크플로우 Step 1d(리서치 검증) + Step 3v(구현 검증) 검증팀 병렬 배치
- tests/ per-file-ignores에 E501 추가

---

## [0.19.0] — 2026-03-18

외부 메시징 (Slack/Discord/Telegram) + 캘린더 (Google Calendar/Apple Calendar) 통합. OpenClaw Gateway 패턴 적용.

### Added
- NotificationPort Protocol + contextvars DI — 외부 메시징 서비스 추상화 계층
- CalendarPort Protocol + CalendarEvent 모델 — 캘린더 서비스 추상화 계층
- GatewayPort Protocol — 인바운드 메시지 게이트웨이 추상화
- Slack/Discord/Telegram Notification Adapters — MCP 기반 아웃바운드 메시징 (3 어댑터)
- CompositeNotificationAdapter — 채널별 라우팅 합성 어댑터
- Google Calendar / Apple Calendar (CalDAV) Adapters — MCP 기반 캘린더 (2 어댑터)
- CompositeCalendarAdapter — 다중 소스 이벤트 병합
- MCP Catalog에 telegram, google-calendar, caldav 3개 서버 추가 (총 42개)
- send_notification 도구 업그레이드 — 스텁 → NotificationPort 기반 실제 전송 (discord/telegram 채널 추가)
- calendar_list_events (SAFE), calendar_create_event (WRITE), calendar_sync_scheduler (WRITE) 도구 3개 추가
- Notification Hook Plugin — PIPELINE_END/ERROR, DRIFT_DETECTED, SUBAGENT_FAILED → 자동 알림 전송
- CalendarSchedulerBridge — 스케줄러 ↔ 캘린더 양방향 동기화 ([GEODE] 접두사 기반)
- Gateway 인바운드 모듈 — ChannelManager + Slack/Discord/Telegram Poller (OpenClaw Binding 패턴)
- Gateway Session Key — `gateway:{channel}:{channel_id}:{sender_id}` 형식 세션 격리
- Gateway → Lane Queue 연결 — 인바운드 메시지 동시성 제어 (OpenClaw Lane 패턴)
- ChannelBinding.allowed_tools 적용 — 바인딩별 도구 접근 제한
- Binding Config Hot Reload — TOML 기반 게이트웨이 바인딩 로드 (`load_bindings_from_config`)
- HookEvent에 GATEWAY_MESSAGE_RECEIVED, GATEWAY_RESPONSE_SENT 추가 (30→32 이벤트)
- TriggerEndpoint에 discord, telegram 소스 추가
- Notification Hook YAML auto-discovery 지원 — hook_discovery.py 호환 `handler` 필드 + `handle()` 진입점
- Config에 notification/gateway/calendar 설정 섹션 추가
- VALID_CATEGORIES에 notification, calendar 추가
- 테스트 105개 추가 (notification_adapters 27, calendar_adapters 26, notification_hook 10, calendar_bridge 10, gateway 32)

### Changed
- README에 Prompt Assembly Pipeline 섹션 추가 — 5단계 조합 파이프라인 Mermaid 다이어그램 + 노드 호출 시퀀스
- README에 Development Workflow 섹션 추가 — 재귀개선 루프 Mermaid 다이어그램 + 품질 게이트 테이블
- README Game IP Domain 섹션 분리 — DomainPort Protocol과 Game IP 파이프라인을 독립 서브섹션으로 확장

### Fixed
- README 수치 정합성 수정 — MCP catalog 38→39, SAFE_BASH_PREFIXES 38→41, MCP adapters 5→4, User Profile 경로, prompt 템플릿 수 11→10, slash commands 17→20, config vars 30+→57


---

## [0.18.1] — 2026-03-17

Report 보강, Evaluator UI 개선, Spinner/색상 안정화.

### Changed
- `generate_report` 보강 -- Evaluator 3명 축별 점수, PSM ATT/Z/Gamma, Scoring 6가중치, BiasBuster 플래그, 외부 시그널 수치를 리포트에 전체 포함
- Evaluator UI를 Rich Table로 변경 -- Analyst 패널과 동일 형식
- Evaluator 진행 카운터 -- `evaluator ✓` 반복 → `Evaluate (1/3)` 형태

### Fixed
- TextSpinner 줄 늘어짐 -- `\r` → `\r\x1b[2K` ANSI 라인 클리어로 동일 줄 덮어쓰기
- Pipeline 진행 표시 터미널 폭 초과 시 축약 -- 첫 2단계 + `... (+N tasks)` 형태로 truncate
- HITL 승인 프롬프트 색상 톤다운 -- `bold yellow` → GEODE `warning` 테마 (brand gold) 통일 (3곳 잔여분 포함)

---

## [0.18.0] — 2026-03-17

AgenticLoop 병렬 도구 실행 (Tiered Batch Approval), Pipeline None guard, 구형 정체성 제거, LLM 안정성.

### Changed
- AgenticLoop 병렬 도구 실행 -- Tiered Batch Approval 패턴. TIER 0-1 즉시 병렬, TIER 2 일괄 비용 확인 후 병렬, TIER 3-4 개별 승인 순차
- AGENTIC_SUFFIX 프롬프트에 병렬 도구 호출 가이드 추가

### Fixed
- Pipeline 노드 None 반환 방어 (`_merge_event_output` null guard)
- 구형 버전/정체성 하드코딩 제거 (panels.py v0.9.0 → 동적 `__version__`)
- LLM read timeout 120s → 300s (1M 컨텍스트)
- LangSmith 429 로그 스팸 suppression
- LangGraph checkpoint deserialization 경고 제거

---

## [0.17.0] — 2026-03-17

.geode Phase 2 (Cost Tracker, Agent Reflection, Cache Expiry, geode history), tool_handlers 그룹 분할.

### Added
- Cost Tracker -- `~/.geode/usage/YYYY-MM.jsonl`에 LLM 비용 영속 저장 (`UsageStore`)
- Agent Reflection -- `PIPELINE_END` Hook으로 `learned.md` 자동 패턴 추출 (Karpathy P4 Ratchet)
- Cache Expiry -- ResultCache 24h TTL + SHA-256 content hash 검증
- `geode history` 서브커맨드 -- 실행 이력 + 모델별 비용 요약 조회

### Architecture
- `_build_tool_handlers` 957줄 → 그룹별 헬퍼 함수 분할 (~50줄 디스패처) — 10개 논리 그룹(Analysis, Memory, Plan, HITL, System, Execution, Delegated, Profile, Signal, MCP)으로 분리

---

## [0.16.0] — 2026-03-17

.geode Phase 1 (Config Cascade, Run History, geode init), Clean Architecture 레이어 수정, CLI 입력 UX 개선, 코드 퀄리티 리팩터링.

### Added
- Config Cascade -- `~/.geode/config.toml` (글로벌) + `.geode/config.toml` (프로젝트) TOML 설정 지원. 4-level 우선순위: CLI > env > project TOML > global TOML > default
- Run History Context -- ContextAssembler에 최근 실행 이력 3건 자동 주입 (Karpathy P6 L3 judgment-level compression)
- `geode init` 서브커맨드 -- `.geode/` 디렉토리 구조 + 템플릿 config.toml + .gitignore 자동 생성

### Architecture
- CLI 레이어 분리 -- `__init__.py` (2842줄) -> `repl.py` + `tool_handlers.py` + `result_cache.py` 추출. 모듈별 단일 책임 원칙 적용
- `anthropic` SDK 직접 참조 제거 -- CLI 레이어(`agentic_loop.py`, `nl_router.py`)에서 `core.llm.client` 래퍼(`LLMTimeoutError` 등) 사용으로 전환. Port/Adapter 경계 유지
- L5→L3 레이어 위반 수정 -- `calculate_krippendorff_alpha` 순수 수학 함수를 `core/verification/stats.py`로 이동. `expert_panel.py`는 역호환 re-export 유지
- L5→L1 config 의존성 제거 -- `nodes/analysts.py`와 `verification/cross_llm.py`에서 `settings` 직접 접근 → state/파라미터 주입으로 전환
- `_maybe_traceable` → `maybe_traceable` 공개 API 전환 -- 외부 모듈이 private 함수를 import하던 위반 해소. 역호환 alias 유지

### Removed
- `core/ui/streaming.py` 삭제 (198줄 데드코드, 전체 코드베이스에서 미참조)

### Changed
- `check_status` 도구에 MCP 서버 가시성 추가 -- 활성 서버(json_config/auto_discovered) 목록과 비활성 서버(환경변수 누락) 목록을 함께 표시. "MCP 리스트 보여줘" 등 자연어 쿼리 지원
- CLI 입력 UX 개선 -- renderer.reset() 제거, ANSI 재페인팅 제거, 50ms 폴링 제거, TextSpinner 도입, 동적 터미널 폭
- CircuitBreaker 스레드 안전성 추가 (threading.Lock) -- sub-agent ThreadPool(MAX_CONCURRENT=5) 환경에서 경합 조건 방지
- Token usage 기록 3x 중복 → `_record_response_usage()` 헬퍼 추출 -- call_llm, call_llm_parsed, call_llm_with_tools, call_llm_streaming 4곳 통합
- YAML frontmatter 파서 중복 제거 -- project.py가 canonical `_frontmatter.py`의 `_FRONTMATTER_RE` 사용
- `_API_ALLOWED_KEYS` 루프 내 재생성 → 모듈 레벨 `frozenset` 상수로 이동

### Fixed
- MCP 카탈로그 이름 불일치 해소 -- `linkedin` -> `linkedin-reader` (mcp_servers.json과 일치), `arxiv` 카탈로그 항목 추가 (DEFAULT_SERVERS에 등록)

---

## [0.15.0] — 2026-03-16

Tier 0.5 User Profile, MCP 코드 레벨 영속화, Token Guard/턴 제한 철폐, APIConnectionError 해소, README 리서치 에이전트 정체성 반영.

### Added
- Tier 0.5 User Profile 시스템 -- `~/.geode/user_profile/` 글로벌 + `.geode/user_profile/` 프로젝트 로컬 오버라이드, 프로필/선호/학습 패턴 영속 저장
- `UserProfilePort` Protocol + `FileBasedUserProfile` 어댑터 (`core/memory/user_profile.py`)
- 프로필 도구 4종 (`profile_show`, `profile_update`, `profile_preference`, `profile_learn`) -- ContextAssembler Tier 0.5 주입
- MCP 서버 코드 레벨 등록 (`MCPRegistry`) — 카탈로그 기반 자동 탐지로 세션 간 설정 영속화. 기본 서버 4종(steam, fetch, sequential-thinking, playwright) 항상 등록, env var 보유 서버 19종 자동 발견, `.claude/mcp_servers.json` 파일 오버라이드 병합

### Changed
- README 예시 리뉴얼 — 게임 IP 중심 예시를 범용 리서치 에이전트 자연어 쿼리로 교체. Quick Start REPL 우선, 자연어 입력 예시 7종 추가, Game IP는 Domain Plugin 하위로 이동
- Token Guard 상한 제거 — `MAX_TOOL_RESULT_TOKENS` 기본값 0 (무제한). 프론티어 합의: 하드 캡 대신 압축(Karpathy P6) + `clear_tool_uses` 서버측 정리로 컨텍스트 관리. `GEODE_MAX_TOOL_RESULT_TOKENS` 환경변수로 필요 시 상한 재설정 가능
- 대화 턴/라운드 제한 대폭 완화 — `max_turns` 20→200, `DEFAULT_MAX_ROUNDS` 30→50. 1M 컨텍스트 + 서버측 `clear_tool_uses`가 주 관리 담당, 클라이언트 제한은 극단적 runaway 방지용 안전망으로만 유지

### Fixed
- 프롬프트/REPL 출력에서 장식용 이모지 제거 — 리포트 생성 외 모든 CLI 출력에서 이모지(⚡⚠✏⏸) 삭제, UI 마커(✓✗✢●)는 유지
- APIConnectionError 간헐 반복 — httpx 커넥션 풀 설정 추가 (max_connections=20, keepalive_expiry=30s), 싱글턴 Anthropic 클라이언트로 전환, 재시도 백오프 2s/4s/8s로 단축, 연결 관련 설정 config.py로 이관

---

## [0.14.0] — 2026-03-16

Identity Pivot 완성, 1M 컨텍스트 활용 극대화, tool_result 고아 400 에러 3중 방어, HITL 완화, UI 톤다운.

### Added
- 복사/붙여넣기 알림 — 멀티라인 paste 감지 시 `[Pasted text +N lines]` 표시 후 추가 입력 대기 (즉시 실행 방지)

### Fixed
- 멀티턴 tool_result 고아 참조 400 에러 — 3중 방어: (1) Anthropic `clear_tool_uses` 서버사이드 컨텍스트 관리, (2) `ConversationContext._trim()`에 tool pair sanitization 추가, (3) 기존 `_repair_messages()` 유지
- 스케줄 생성/삭제 즉시 영속화 — `add_job()`/`remove_job()` 후 `save()` 호출 추가 (crash 시 job 소실 방지)
- `core/__init__.py` 버전 0.13.0→0.13.2 동기화 누락 수정
- README 뱃지 에이전틱 네이티브 스타일 교체 (while(tool_use), Opus 4.6 1M, 38 tools MCP, LangGraph)

### Changed
- 컨텍스트 제한 완화 — `max_turns` 20→50, `DEFAULT_MAX_ROUNDS` 15→30, `DEFAULT_MAX_TOKENS` 16384→32768, prune threshold 10→30 (1M 모델 활용 극대화)
- Identity Pivot 완성 — `analyst.md` SYSTEM 프롬프트에서 "undervalued IP discovery agent" 제거, 게임 전용 예시를 도메인 비의존적 예시로 교체
- `ANALYST_SYSTEM` 해시 핀 갱신 (`924433f5bf11` → `90acc856a5b2`)
- UI 팔레트 톤다운 — 선명한 5색(coral/gold/cyan/magenta/crystal)을 차분한 톤(rose/amber/cadet/iris/lavender)으로 교체. HTML 리포트 CSS 변수 + gradient 동기화
- HITL 가드레일 완화 — 읽기 전용 bash 명령(cat/ls/grep/git/uv 등 35종) 자동 승인, MCP 읽기 전용 서버(brave-search/steam/arxiv/linkedin-reader) 초회 승인 생략

---

## [0.13.2] — 2026-03-16

Pre-commit 안정화, cron weekday 버그 수정, UI 마커 브랜딩 통일.

### Fixed
- Pre-commit mypy/bandit "files were modified" 오탐 — `uv run --frozen` + mypy `--no-incremental` 전환으로 uv.lock 수정 방지
- Cron weekday 변환 버그 — Python weekday(0=Mon) → cron 표준(0=Sun) 미변환으로 일요일 스케줄이 월요일에 실행되던 문제
- `/trigger fire` 명령이 TriggerManager 없이 성공으로 표시되던 문제를 경고 메시지로 변경

### Changed
- UI 마커 브랜딩 통일 — 비표준 이모지(⏳, ✻, ⏺)를 GEODE 표준 마커(✢, ●)로 일괄 교체
- Docs-Sync 워크플로우 강화 — MINOR/PATCH 판단 기준 명시, `[Unreleased]` 잔류 금지 규칙, ABOUT 동기화 섹션 추가

---

## [0.13.1] — 2026-03-16

### Fixed
- Anthropic API tool 전달 시 `category`/`cost_tier` extra fields 400 에러 — underscore prefix 필터를 허용 키 화이트리스트(`name`, `description`, `input_schema`, `cache_control`, `type`)로 교체

---

## [0.13.0] — 2026-03-16

자율 실행 강화 — Signal Liveification, Plan 자율 실행, Dynamic Graph, 적응형 오류 복구, Goal Decomposition, 에이전트 그라운딩 트루스.

### Changed
- 서브에이전트 결과 수집 `as_completed` 패턴 — 순차 블로킹 → polling round-robin 전환. 먼저 끝난 태스크의 SUBAGENT_COMPLETED 훅이 즉시 발행

### Added
- HITL 승인 후 스피너 — `_tool_spinner()` 컨텍스트 매니저로 bash/MCP/write/expensive 도구 실행 중 `✢` dots 스피너 표시, 승인 거부·Safe/Standard 도구에는 미표시
- Signal Liveification — MCP 기반 라이브 시그널 수집 (`CompositeSignalAdapter` → `SteamMCPSignalAdapter` + `BraveSignalAdapter`), fixture fallback 보존, `signal_source` 필드로 provenance 추적
- Plan 자율 실행 모드 — `GEODE_PLAN_AUTO_EXECUTE=true`로 계획 생성→승인→실행을 사용자 개입 없이 자동 수행, step 실패 시 재시도 1회 후 partial success로 계속 진행 (`PlanExecutionMode.AUTO`)
- Dynamic Graph — 분석 결과에 따라 노드 동적 건너뛰기/enrichment 경로 분기 (`skip_nodes`, `skipped_nodes`, `enrichment_needed` state 필드 + `skip_check` 조건부 노드)
- 적응형 오류 복구 시스템 — `ErrorRecoveryStrategy` 전략 패턴 (retry → alternative → fallback → escalate), 2회 연속 실패 시 자동 복구 체인 실행, DANGEROUS/WRITE 도구 안전 게이트 보존
- `TOOL_RECOVERY_ATTEMPTED`/`SUCCEEDED`/`FAILED` HookEvent 3종 — 오류 복구 수명주기 관측성 (HookSystem 30 events)
- 자율 목표 분해 (Goal Decomposition) — `GoalDecomposer` 클래스로 고수준 복합 요청을 하위 목표 DAG로 자동 분해. Haiku 모델 사용으로 비용 최소화 (~$0.01/호출). 단순 요청은 휴리스틱으로 LLM 호출 없이 패스스루
- LinkedIn MCP 어댑터 — `LinkedInPort` Protocol + `LinkedInMCPAdapter` 구현 (Port/Adapter 패턴, graceful degradation)
- 도구 카테고리/비용 태깅 — `definitions.json` 전 38개 도구에 `category`(8종)와 `cost_tier`(3종) 메타데이터 추가, `ToolRegistry.get_tools_by_category()`/`get_tools_by_cost_tier()` 필터링 메서드
- MCP 서버별 세션 승인 캐시 — 한 서버 최초 승인 후 동일 세션 내 재승인 생략 (`_mcp_approved_servers`)
- 에이전트 그라운딩 트루스 — AGENTIC_SUFFIX에 Citation & Grounding 규칙 추가 (출처 인용 강제, 미확인 정보 생성 금지)
- web_fetch/web_search 소스 태깅 — `source` 필드 명시, web_search에 `source_urls` 추출
- G3 그라운딩 비율 산출 — `grounding_ratio` 필드, evidence 대비 signal 근거 비율 계산
- 리포트 Evidence Chain — 분석가별 evidence 목록을 Markdown 리포트에 포함

### Fixed
- 연속 실패 도구 스킵 메시지 중복 출력 — `skipped` 결과 이중 로깅 방지
- APITimeoutError 소진 시 에러 상세 정보 누락 — `_last_llm_error`로 에러 유형/재시도 횟수 표시

### Changed
- NL Router 시스템 프롬프트 Tool Selection Priority Matrix 추가 — 12개 의도별 1st/2nd Choice + 사용 금지 도구 매트릭스, 비용 인식 규칙, 도구 호출 금지 사항 (AGENTIC_SUFFIX)
- MCP 통합 Deferred Loading 강화 — Native + MCP 도구를 통합 병합 후 deferred loading 적용, 임계값 5→10 상향, 6개 핵심 도구 항상 로드, ToolSearchTool MCP 검색 지원

### Infrastructure
- Test count: 2226+ → 2366+
- Module count: 132 → 134
- HookEvent count: 27 → 30

---

## [0.12.0] — 2026-03-15

HITL 보안 강화 + README/CLAUDE.md 자율 실행 코어 재구성 + Domain Plugin 아키텍처 문서화.

### Added
- 시작 화면 초기화 진행 표시 — Domain/Memory/MCP/Skills/Scheduler 단계별 `ok`/`skip` 상태 출력
- LinkedIn 우선 라우팅 — 프로필/커리어/채용 쿼리 시 `site:linkedin.com` 프리픽스 우선 검색 (AGENTIC_SUFFIX)
- `WRITE_TOOLS` 안전 분류 — `memory_save`/`note_save`/`set_api_key`/`manage_auth` 쓰기 작업 HITL 확인 게이트
- MCP 도구 안전 라우팅 — 외부 MCP 도구 호출 시 `_execute_mcp()` 경유, 사용자 승인 게이트 적용
- G3 그라운딩 비율 산출 — `grounding_ratio` 필드 추가, evidence 대비 signal 근거 비율 계산
- Quantitative analyst 그라운딩 강제 — `growth_potential`/`discovery` 분석가의 evidence가 0% 그라운딩이면 G3 hard fail
- 리포트 Evidence Chain 섹션 — 분석가별 evidence 목록을 Markdown 리포트에 포함

### Fixed
- DANGEROUS 도구(bash) `auto_approve` 우회 차단 — 서브에이전트에서도 항상 사용자 승인 필수

### Changed
- LinkedIn MCP: `linkedin-mcp-runner` (LiGo, 자기 콘텐츠) → `linkedin-scraper-mcp` (타인 프로필 검색 가능, Patchright 브라우저)
- README 구조 재편: `Architecture — Autonomous Core` 상위 배치, Game IP 파이프라인을 `Domain Plugin` 하위 분리
- CLAUDE.md: Sub-Agent System, Domain Plugin System, 6-Layer Architecture 갱신

### Infrastructure
- Test count: 2168+ → 2179+
- Module count: 131 → 132

---

## [0.11.0] — 2026-03-15

서브에이전트 Full AgenticLoop 상속 + asyncio 전환 + 외부 IP 분석 지원 + BiasBuster 성능 최적화 + D1-D5 운영 디버깅 감사 + MCP 정합성.

### Added
- 미등록 IP 외부 시그널 수집 — `signals.py` 3단계 fallback (adapter → fixture → Anthropic web search)
- 외부 IP graceful degradation — `router.py` fixture 미존재 시 최소 `ip_info` 스켈레톤 자동 생성
- P2 서브에이전트 Full AgenticLoop 상속 — 동일 tools/MCP/skills/memory 제공, 재귀 depth 제어 (max_depth=2, max_total=15)
- `SubAgentResult` 표준 스키마 + `ErrorCategory` 에러 분류 — 단건/배치 응답 통일
- P3 asyncio dual-interface — `AgenticLoop.arun()`, `_acall_llm()`, `_aprocess_tool_calls()` async 경로 추가
- `HookSystem.atrigger()` — 비동기 훅 트리거 (`asyncio.gather()` 기반 동시 실행)
- `SubAgentManager.adelegate()` — asyncio 기반 비동기 위임 (`asyncio.gather()` 병렬)
- `AsyncAnthropic` 클라이언트 — agentic loop에서 비차단 LLM 호출
- REPL에서 `asyncio.run(agentic.arun())` 기본 사용 — sync `run()` 호환 유지

### Changed
- BiasBuster 통계 fast path — CV≥0.10 && score range≥0.5일 때 LLM 호출 생략 (10-30초 절감)
- 외부 IP feedback loop 1회 제한 (`max_iterations=1`) — 동일 웹 검색 데이터 재분석 방지
- `batch.py` 3함수 `dry_run` 기본값 `True` → `False` — caller 결정 원칙 적용
- `graph.py` cross_llm 검증 결과 누락 시 fail-safe (`passed=True` → `False`)
- OpenAI 7개 모델 가격 공식 그라운딩 (GPT-4.1, 4o, o3, o4-mini 등)
- `pyproject.toml` live 테스트 기본 제외 (`addopts += -m 'not live'`)
- `DEFAULT_MAX_TOKENS` 8192 → 16384
- `tool_result` 토큰 가드 — 4096 토큰 초과 시 summary 보존 truncation
- MCP 카탈로그 LinkedIn 패키지 정합성 — `kimtaeyoon87` → `linkedin-scraper-mcp` (Claude Code 글로벌 세팅 일치)

### Fixed
- MCP orphan 프로세스 방지 — REPL 종료 시 `close_all()` + `atexit.register()` 호출
- MCP 미연결 서버 제거 (discord/e2b/igdb → 4개 유지: brave-search, steam, arxiv, playwright)
- MCP 미설정 서버 자동 skip — env 빈 값 체크 + `.env` fallback
- REPL memory contextvars 초기화 — `note_read` 등 6개 메모리 도구 "not available" 해소
- 서브에이전트 dry-run 강제 해제 (ADR-008) — API 키 존재 시 live LLM 호출 가능
- CLI 한글 wide-char 백스페이스 잔상 + 방향키 escape code 필터링
- prompt_toolkit Backspace/Delete 키 바인딩 — `renderer.reset()` + `invalidate()` 강제 redraw로 와이드 문자 잔상 해소
- D1: `sub_agent.py` 리포트 경로 `force_dry_run` 적용
- D3: `trigger_endpoint.py` 메모리 ContextVar 초기화 누락
- D4: `triggers.py` 클로저 config 선캡처 + `isolated_execution.py` cancel_flags lock
- D5: `hybrid_session.py` L1(Redis) 예외 시 L2 fallback 추가

### Infrastructure
- Test count: 2077+ → 2168+
- Module count: 125 → 131

---

## [0.10.1] — 2026-03-13

UI/UX 리브랜딩 + 터미널 안정성 강화 + Agentic 강건성 + 리포트 상용화 + Domain Plugin + MCP 버그 수정.

### Added

#### UI/UX 리브랜딩
- Axolotl 마스코트 + Claude Code 스타일 시작 화면 (9 표정 애니메이션)
- Rich Markdown 렌더링 — LLM 응답의 마크다운을 터미널에서 Rich로 렌더링
- 도구 실행 중 `Running {tool_name}...` 스피너 표시 (UI 공백 해소)
- `_restore_terminal()` — 매 입력 전 termios ECHO/ICANON 복원 (스페이스+백스페이스 멈춤 수정)
- `_suppress_noisy_warnings()` — Pydantic V1 / msgpack deserialization 경고 필터링
- HTML 리포트 상용화 — SVG 게이지, 서브스코어 바차트, 반응형 + 인쇄 최적화

#### Agentic Loop 강건성
- `max_rounds` 7→15, `max_tokens` 4096→8192
- `WRAP_UP_HEADROOM=2` — 마지막 2라운드에서 텍스트 응답 강제
- 연속 실패 자동 스킵 — 같은 도구 2회 연속 실패 시 자동 스킵

#### Domain Plugin Architecture (Phase 1-4)
- `DomainPort` Protocol — 도메인별 analysts, evaluators, scoring weights, decision tree, prompts 플러그인 인터페이스
- `GameIPDomain` 어댑터 — 기존 게임 IP 평가 로직을 DomainPort 구현체로 캡슐화
- `load_domain_adapter()` / `set_domain()` — 도메인 어댑터 동적 로딩 + contextvars DI
- `GeodeRuntime.create(domain_name=)` — 런타임 생성 시 도메인 어댑터 자동 와이어링

#### Clarification 시스템 확장 (3/33 → 25/33 핸들러)
- `_clarify()` 표준 응답 헬퍼, `_safe_delegate()` 래퍼, `MAX_CLARIFICATION_ROUNDS = 3`

#### LLM Cost Tracking (3계층)
- Real-time UI `render_tokens()`, Session summary, `/cost` 명령어

#### Whisking UI
- `GeodeStatus._format_spinner()` — Claude Code 스타일 라이브 스피너

### Changed
- 브랜드 팔레트 통합: Coral/Gold/Cyan/Magenta/Crystal → GEODE_THEME 전역 적용
- `_normalise_mcp_tool()` — MCP camelCase(`inputSchema`) → Anthropic snake_case(`input_schema`) 정규화
- LangGraph API 호출 시 `_mcp_server` 등 내부 메타데이터 필드 자동 제거
- 버전 표기 0.9.0 → 0.10.1 전면 갱신 (`core/__init__`, CLI help, Typer callback)

### Fixed
- MCP 도구 `input_schema: Field required` API 400 에러 (camelCase→snake_case 변환 누락)
- MCP 도구 `_mcp_server: Extra inputs are not permitted` API 400 에러 (내부 필드 누출)
- 터미널 상태 복원 — Rich Status/Live 종료 후 echo/cooked 모드 미복원으로 입력 불가 현상
- LangGraph 1.1.2 타입 시그니처 변경 대응 (`invoke`/`stream` overload 주석 갱신)
- 파이프라인 예외 경로에서 `console.show_cursor(True)` 누락 수정

### Infrastructure
- `langgraph` 1.0.9 → 1.1.2 (minor, xxhash 의존성 추가)
- `langchain-core` 1.2.14 → 1.2.18 (patch)
- `langsmith` 0.7.5 → 0.7.17 (patch)
- `langgraph-checkpoint` 4.0.0 → 4.0.1 (patch)

---

## [0.10.0] — 2026-03-12

SubAgent 병렬 실행 완성 + SchedulerService 프로덕션 와이어링 + NL 자연어 스케줄 E2E 통합.

### Added

#### SchedulerService 프로덕션 와이어링
- `SchedulerServicePort` Protocol — Clean Architecture DI 포트 (`automation_port.py`)
- `GeodeRuntime._build_automation()` — SchedulerService 인스턴스 생성 + predefined cron 자동 등록
- `config.py` — `scheduler_interval_s`, `scheduler_auto_start` 설정 추가
- `cmd_schedule()` 7-sub-command 확장 — list/create/delete/status/enable/disable/run
- `CronParser` step syntax 지원 — `*/N`, `M-N/S` 파싱 (기존 `*/30` 파싱 실패 버그 수정)
- `NLScheduleParser` → `SchedulerService` E2E 연결 — 자연어 "매일 오전 9시 분석" → ScheduledJob 생성
- `_TOOL_ARGS_MAP` + `definitions.json` — `schedule_job` expression 필드 + 7-enum sub_action
- `tests/test_scheduler_integration.py` — 22 tests (NL→Scheduler, Predefined, CLI, Port)

#### SubAgent Manager Wiring (G1-G6)
- `make_pipeline_handler()` — analyze/search/compare 라우팅 팩토리
- `_build_sub_agent_manager()` — CLI → ToolExecutor 연결 팩토리
- `_resolve_agent()` + `AgentRegistry` 주입 — 에이전트 정의 → 실행 연결
- `delegate_task` 배치 스키마 — `tasks` 배열 필드 + `_execute_delegate` 배치 지원
- `on_progress` 콜백 — 병렬 실행 중 진행 표시
- `SUBAGENT_STARTED/COMPLETED/FAILED` 전용 훅 이벤트 (HookEvent 23 → 26)

#### OpenClaw 세션 키 격리 (G7)
- `build_subagent_session_key()` — `ip:X:Y:subagent:Z` 5-part 세션 키
- `build_subagent_thread_config()` — LangGraph config + LangSmith metadata
- `_subagent_context` 스레드 로컬 + `get_subagent_context()` — 부모-자식 컨텍스트 전파
- `SubagentRunRecord` — 부모-자식 관계 추적 (run_id, session_key, outcome)
- `GeodeRuntime.is_subagent` — 서브에이전트 시 MemorySaver 자동 전환 (SQLite 경합 제거)

#### Live E2E 테스트
- `TestSubAgentLive` 7개 시나리오 (E1-E7): delegate 단건/배치, wiring, 훅, registry, 비회귀
- `TestSubAgentSessionIsolation` 3개 테스트 (스레드 로컬, 세션 키, 런타임 플래그)
- `TestSubAgentSessionIsolationE2E` — 병렬 SQLite 비경합 검증

### Changed
- `delegate_task` 스키마: `bash` 타입 제거, `required: []`로 변경 (단건/배치 공존)
- `_execute_delegate()`: 단건 flat dict / 다건 `{results, total, succeeded}` 반환
- `parse_session_key()`: 5-part 서브에이전트 키 인식
- `SubTask` dataclass: `agent: str | None` 필드 추가

### Fixed
- `delegate_task` 도구가 `SubAgentManager not configured` 에러만 반환하던 문제 (G1+G2)
- 병렬 서브에이전트 실행 시 SQLite `database disk image is malformed` 에러 (G7)
- `NODE_ENTER/EXIT/ERROR` 훅이 서브에이전트와 파이프라인 노드를 구분하지 못하던 문제 (G6)
- `CronParser.matches()` — `*/30` 등 step syntax 미지원으로 predefined cron 파싱 실패하던 문제

### Architecture
- `core/llm/token_tracker.py` — TokenTracker 단일주입 패턴 (`get_tracker().record()`) 으로 토큰 비용 계산 일원화
- 24개 모델 가격 검증 및 수정 (Opus 4.6: $15/$75 → $5/$25, Haiku 4.5: $0.80/$4 → $1/$5)
- client.py, nl_router.py, agentic_loop.py, openai_adapter.py 중복 비용 계산 코드 제거 (~250줄 삭감)

### Infrastructure
- Test count: 2033+ → 2077+
- Module count: 121 → 125
- `docs/plans/P1-subagent-parallel-execution.md` — GAP 분석 + 구현 플랜
- `docs/blogs/20-subagent-parallel-execution-e2e.md` — 기술 블로그 (네러티브)

---

## [0.9.0] — 2026-03-11

General Assistant Transformation, Skills 시스템, MCP 자동설치, Clarification 파이프라인, 마스코트 브랜딩.

### Added

#### General Assistant Transformation (PR #32)
- Offline mode 제거 — AgenticLoop always-online (API 키 없으면 자동 dry-run)
- `key_registration_gate()` — Claude Code 스타일 API 키 등록 게이트
- 9개 신규 도구: `web_fetch`, `general_web_search`, `read_document`, `note_save`, `note_read`, `youtube_search`, `reddit_sentiment`, `steam_info`, `google_trends`
- `StdioMCPClient` — JSON-RPC stdio 기반 MCP 서버 클라이언트
- `MCPServerManager` — MCP 서버 설정 로딩 + 연결 관리 + 도구 디스커버리
- `/mcp` CLI 커맨드 — MCP 서버 상태/도구/재로딩
- `ToolExecutor` MCP fallback — 미등록 도구를 MCP 서버로 자동 라우팅

#### NL Router 개선 (PR #32)
- Scored matching — `_OfflinePattern` dataclass + priority-based 5-phase matching
- Fuzzy IP matching — `difflib.get_close_matches` ("Bersek" → "Berserk")
- Multi-intent — compound splitting ("하고", "and", 쉼표) → 복수 NLIntent 반환
- Disambiguation — `NLIntent.ambiguous` + `alternatives` 필드
- Context injection — 대화 히스토리 (최근 3턴) → LLM 라우터에 전달

#### Skills 시스템 (PR #33)
- `core/extensibility/skills.py` — SkillDefinition + SkillLoader + SkillRegistry
- `core/extensibility/_frontmatter.py` — 공유 YAML frontmatter 파서 (agents.py에서 추출)
- `.claude/skills/*/SKILL.md` 자동 발견 + 시스템 프롬프트 `{skill_context}` 주입
- `/skills` CLI 커맨드 — 목록/상세/reload/add 서브커맨드
- `/skills add <path>` — 외부 스킬 동적 등록 + .claude/skills/ 복사

#### MCP 강화 (PR #33)
- `MCPServerManager.add_server()` — 런타임 서버 등록 + JSON 영속화
- `MCPServerManager.check_health()` / `reload_config()` — 헬스체크 + 설정 재로딩
- `/mcp status|tools|reload|add` 서브커맨드 확장
- `/mcp add <name> <cmd> [args]` — 동적 MCP 서버 추가

#### MCP 자동설치 파이프라인 (PR #33)
- `core/infrastructure/adapters/mcp/catalog.py` — 31개 빌트인 MCP 서버 카탈로그
- `install_mcp_server` 도구 — NL로 MCP 서버 검색/설치 ("LinkedIn MCP 달아줘")
- `search_catalog()` — 키워드 기반 가중 매칭 (name > tags > description > package)
- `AgenticLoop.refresh_tools()` — MCP 도구 핫 리로드 (세션 재시작 불필요)
- `_build_tool_handlers()` 시그니처 확장 — `mcp_manager`, `agentic_ref` 클로저 패턴

#### Report Generation 강화 (PR #33)
- `_build_skill_narrative()` — geode-scoring/analysis/verification 스킬 주입 → LLM 전문 분석 내러티브 생성
- 리포트 자동 저장 — `.geode/reports/{ip}-{template}.{ext}` 경로로 파일 생성
- `generate_report` → `read_document` 체이닝 — 리포트 생성 후 즉시 열기 가능

#### Clarification 파이프라인 (PR #33)
- Tool parameter validation — `handle_compare_ips`, `handle_analyze_ip`, `handle_generate_report`에 필수 파라미터 검증
- `clarification_needed` 응답 프로토콜 — `missing`, `hint` 필드 포함
- AGENTIC_SUFFIX clarification rules — slot filling, disambiguation, missing parameter 처리 지침
- "Berserk 분석하고 비교하고 리포트" → max_rounds 미도달, 되묻기 정상 동작

#### 마스코트 브랜딩 (PR #33)
- `assets/geode-mascot.png` — GEODE 마스코트 (파란 구체 두구 우파루파)
- `assets/geode-avatar-{128,256,512}.png` — 원형 얼굴 아바타 (RGBA 투명)
- `assets/geode-social-preview.png` — GitHub Social Preview (1280×640)
- `_render_mascot()` — Harness GEODE ASCII art CLI splash (6-color Rich 마크업)

### Changed
- Tool count: 21 → 31 (definitions.json)
- Handler count: 17 → 30
- System prompt: IP 분석 전문 → General AI Assistant + IP 전문성
- `_build_tool_handlers()`: `verbose` only → `verbose`, `mcp_manager`, `agentic_ref`
- `AgenticLoop.__init__()`: `skill_registry`, `mcp_manager` 파라미터 추가
- `agents.py`: inline frontmatter parser → `_frontmatter.py` 공유 모듈 위임
- CLI 브랜딩: "Undervalued IP Discovery Agent" → "게임화 IP 도메인 자율 실행 하네스"
- 7개 Response dataclass에 `to_dict()` 추가 — None 필드 직렬화 시 자동 제외
  (AgenticResult, SubResult, IsolationResult, HookResult, TriggerResponse, ParseResult)
- `ReportGenerator.generate()`: `enhanced_narrative` 파라미터 추가 (스킬 기반 전문 분석 주입)
- `generate_report` 핸들러: `file_path` + `content_preview` 반환, `.geode/reports/` 자동 저장
- `definitions.json` `generate_report`: `format`/`template` enum 파라미터 추가, `read_document` 체이닝 안내
- `cmd_schedule()`: `scheduler_service` 파라미터 추가

### Fixed
- "Berserk 분석하고 비교하고 리포트" max_rounds 도달 → clarification 되묻기로 해결
- `{skill_context}` KeyError — `router.md`에서 `{{skill_context}}` 이스케이프
- `_render_mascot()` E501 — Rich 마크업 변수 리팩토링
- `report.html` 버전 0.7.0 → 0.9.0 정합성 수정
- mypy strict: `call_llm()` Any 반환 → `str()` 래핑, 3개 함수 시그니처 정합성 수정

### Infrastructure
- Test count: 2000+ → 2033+
- Module count: 118 → 121
- `docs/plans/clarification-pipeline.md` — Clarification 설계 문서
- `docs/plans/tool-mcp-catalog.md` — MCP 카탈로그 리서치
- pre-commit: mypy cache → `/tmp` 이동 (hook conflict 방지)

---

## [0.8.0] — 2026-03-11

Plan/Sub-agent NL integration, Claude Code-style UI, response quality hardening.

### Added

#### Plan & Sub-agent NL Integration
- `create_plan` tool — NL로 분석 계획 생성 ("Berserk 분석 계획 세워줘")
- `approve_plan` tool — 계획 승인 및 실행 ("계획 승인해")
- `delegate_task` tool — 서브에이전트 병렬 위임 ("병렬로 처리해")
- NL Router tool count: 17 → 20 (plan/delegate 3개 추가)
- Offline fallback: plan/delegate regex 패턴 추가 (LLM 없이 동작)

#### Claude Code-style UI
- `core/ui/agentic_ui.py` — tool call/result/error/token/plan 렌더러
- `core/ui/console.py` — Rich Console 싱글톤 (width=120, GEODE 테마)
- Marker system: `▸` tool call, `✓` success, `✗` error, `✢` tokens, `●` plan

#### LangSmith Trace Coverage
- `@_maybe_traceable` added to verification layer: `run_guardrails`, `run_biasbuster`, `run_cross_llm_check`, `check_rights_risk`
- Full pipeline tracing coverage: router → signals → analysts → evaluators → scoring → verification → synthesizer

### Changed
- `AgenticLoop._process_tool_calls()`: `str(result)` → `json.dumps(result, ensure_ascii=False, default=str)` — LLM이 파싱 가능한 JSON 형식으로 tool 결과 전달
- `snapshot._persist_snapshot()`: `json.dumps(..., default=str)` — non-serializable 필드 안전 처리
- `snapshot.capture()`: `_sanitize_state()` 추가 — `_`-prefixed 내부 필드 필터링
- NL Router offline fallback 순서: plan/delegate 패턴을 known IP 매칭보다 먼저 검사

### Fixed
- Offline mode `_run_offline()`: action name("list") → tool name("list_ips") 매핑 누락 수정 (`_ACTION_TO_TOOL` dict 추가)
- `_TOOL_ACTION_MAP` 누락: `create_plan`, `approve_plan`, `delegate_task` 미등록 → 추가

### Infrastructure
- Test count: 1909+ → 2000+
- Module count: 116 → 118
- `tests/test_agentic_ui.py` (20 tests), plan/delegate NL tests (20 tests)

---

## [0.7.0] — 2026-03-11

Pipeline flexibility improvements (C2-C5), LangSmith observability, orchestration integration.

### Added

#### Pipeline Flexibility (C2-C5)
- **C2**: Analyst types dynamically loaded from YAML (`ANALYST_SPECIFIC.keys()`) — add analyst = add YAML key
- **C3**: `interrupt_before` support via `GEODE_INTERRUPT_NODES` env — pipeline pauses at specified nodes for user review
- **C4**: Dynamic tool addition via `ToolRegistry` in `AgenticLoop` — plugins register tools at runtime
- **C5**: `offline_mode` for `AgenticLoop` — regex-based tool routing without LLM (1 deterministic round)

#### LangSmith Observability
- Token tracking: `track_token_usage()` records input/output tokens + cost per LLM call
- `_maybe_traceable` decorator on `AgenticLoop.run()` and `_call_llm()` for RunTree tracing
- Cost calculation with per-model pricing (Opus, Sonnet, Haiku, GPT)
- `UsageAccumulator` for session-level cost aggregation

#### Orchestration Integration
- `SubAgentManager` integration with `TaskGraph`, `HookSystem`, `CoalescingQueue`
- `AgenticLoop` rate limit retry with exponential backoff (3× at 10s/20s/40s)
- Tool handler enrichment: 17 handlers with structured return data

#### Testing & Verification
- `tests/test_e2e_live_llm.py` — 13 live E2E scenarios (AgenticLoop, LangSmith, Pipeline, Offline)
- `tests/_live_audit_runner.py` — 17-tool parallel audit framework
- 17/17 tool handlers verified via AgenticLoop + Opus 4.6 (live audit PASS)
- `docs/e2e-orchestration-scenarios.md` — E2E scenario documentation

#### Documentation
- `docs/as-is-to-be-flexibility.md` — C1-C5 AS-IS → TO-BE analysis
- `docs/plans/observability-langsmith-plan.md` — LangSmith integration plan
- `.claude/skills/geode-e2e/SKILL.md` — E2E testing skill guide

### Changed
- `ANALYST_TYPES`: hardcoded list → `list(ANALYST_SPECIFIC.keys())` (1-line change)
- `AGENTIC_TOOLS`: module-level constant → `get_agentic_tools(registry)` function
- `AgenticLoop.__init__()`: added `tool_registry`, `offline_mode` parameters
- `AgenticLoop._call_llm()`: added retry logic + token tracking
- `compile_graph()`: `interrupt_before` parameter wired from settings
- `ProfileStore` access: `.profiles` → `.list_all()` (mypy fix)

### Fixed
- `ProfileStore.profiles` → `ProfileStore.list_all()` attribute error
- Null-safe `model_dump()` in analyze handler (union-attr mypy error)
- Rate limit exhaustion: 3× retry with exponential backoff prevents transient failures

### Infrastructure
- Test count: 1879 → 1909+ (30 new tests)
- Module count: 115 → 116
- `langsmith` added as optional dependency

---

## [0.6.1] — 2026-03-10

Content/code separation + infrastructure hardening. No new user-facing features.

### Changed
- Package structure: `src/geode/` → `core/` (315 files removed, all imports updated)
- Prompt templates: Python strings → 8 `.md` template files with `load_prompt()` loader
- Tool definitions: inline dicts → `core/tools/definitions.json` (19 tools) + `tool_schemas.json` (11 schemas)
- Domain data: hardcoded axes/actions → `evaluator_axes.yaml`, `cause_actions.yaml`
- Report templates: inline strings → `core/extensibility/templates/` (HTML + 2 Markdown)
- Constants: hardcoded values → `pydantic-settings` (`router_model`, `agreement_threshold`, etc.)
- `VALID_AXES_MAP` / `EVALUATOR_TYPES` derived from canonical YAML (SSOT)

### Fixed
- CI: `--cov=geode` → `--cov=core`, 85 test files import path 수정
- Bandit B404/B602: `# nosec` for intentional subprocess in `bash_tool.py`
- 201 fixture JSON files: missing EOF newline

### Infrastructure
- Pre-commit hooks: ruff lint/format, mypy, bandit, standard hooks (local via `uv run`)
- `pre-commit` added as dev dependency
- Test count: 1823 → 1879

---

## [0.6.0] — 2026-03-10

Initial release of GEODE — Undervalued IP Discovery Agent.
56 commits across 5 development phases.

### Added

#### Core Pipeline (LangGraph StateGraph)
- 7-node pipeline: `router → signals → analyst×4 → evaluator×3 → scoring → verification → synthesizer`
- LangGraph `Send()` API for parallel analyst/evaluator fan-out
- `GeodeState` (TypedDict) with Pydantic validation models
- `GeodeRuntime` — production wiring with dependency injection
- Streaming mode (`_execute_pipeline_streaming`) — progressive panel rendering

#### Analysis Engine
- 4 Analysts: `game_mechanics`, `player_experience`, `growth_potential`, `discovery`
- Clean Context anchoring prevention (no cross-analyst contamination)
- 3 Evaluators: `quality_judge`, `hidden_value`, `community_momentum`
- 14-Axis Rubric Scoring (PSM Engine)
- 6-weighted composite score × confidence multiplier → Tier S/A/B/C classification

#### Verification Layer
- Guardrails G1–G4 (score bounds, consistency, genre-fit, data quality)
- BiasBuster — 6-bias detection (anchoring, genre, recency, popularity, cultural, survivorship)
- Cross-LLM validation (agreement threshold ≥ 0.67)
- Rights Risk assessment (GAP-5)
- Cause Classification Decision Tree

#### CLI (Typer + Rich)
- Interactive REPL with dual routing: `/command` (deterministic) + free-text (NL Router)
- 16+ slash commands: `/analyze`, `/compare`, `/search`, `/batch`, `/report`, `/model`, `/status`, etc.
- NL Router — Claude Opus 4.6 Tool Use (12 tools, autonomous routing)
- 3-stage graceful degradation: LLM Tool Use → offline pattern matching → help fallback
- IP search engine with keyword/genre matching
- Report generation (HTML, JSON, Markdown × Summary/Detailed/Executive templates)
- Batch analysis with parallel execution and ranking table

#### Agentic Loop (v0.6.0-latest)
- `AgenticLoop` — `while(tool_use)` multi-round execution (max 10 rounds)
- `ConversationContext` — sliding-window multi-turn history (max 20 turns)
- `ToolExecutor` — 17 tool handlers with HITL safety gate
- `BashTool` — shell execution with 9 blocked dangerous patterns + user approval
- `SubAgentManager` — parallel task delegation via `IsolatedRunner` (MAX_CONCURRENT=5)
- Multi-intent support: sequential tool chaining by LLM decision
- Multi-turn context: pronoun resolution, follow-up queries

#### Memory System (3-Tier)
- Organization Memory (fixtures, immutable)
- Project Memory (`.claude/MEMORY.md`, persistent insights + rules)
- Session Memory (in-memory TTL, conversation context)
- Auto-learning loop: `PIPELINE_END` → insight write-back to `MEMORY.md`
- Rule CRUD: create/update/delete/list analysis rules

#### Infrastructure (Hexagonal Architecture)
- `LLMClientPort` / `ClaudeAdapter` / `OpenAIAdapter` — multi-provider LLM
- `SignalEnrichmentPort` — market signal adapters
- Prompt caching (Anthropic cache_control)
- Ensemble mode: single / cross-LLM
- MCP Server (FastMCP: 6 tools, 2 resources)
- Auth profile management

#### Orchestration
- `HookSystem` — 23 lifecycle events (pipeline, node, analysis, verification, memory, prompt)
- `IsolatedRunner` — concurrent execution with timeout + semaphore (MAX_CONCURRENT=5)
- `TaskGraph` — DAG-based task dependency tracking
- `StuckDetector` — pipeline deadlock detection via hooks
- `LaneQueue` — concurrency control lanes
- `RunLog` — structured execution logging
- `PlanMode` — DRAFT → APPROVED → EXECUTING workflow

#### Tools & Policies
- `ToolRegistry` — 24 registered tools with lazy loading
- `PolicyChain` — composable tool access policies
- `NodeScopePolicy` — per-node tool allowlists
- Tool-augmented analyst paths with node-level retry

#### Automation (L4.5)
- Drift detection and monitoring
- Model registry with promotion lifecycle
- Confidence gating (feedback loop)
- Snapshot capture for reproducibility
- Trigger system (event-driven + cron-based)

### Fixed
- Scoring confidence calculation — empty/single/zero-mean edge cases (`7591445`)
- Evaluator fallback defaults `1.0 → 3.0` neutral + CLI type safety (`76e4e30`)
- Session ID wiring into pipeline initial state — GAP-001 (`e8fbcfe`)
- Billing error detection with user-friendly message (`d878078`)
- Memory 6 issues from 3-agent quality audit (`4430fd4`)
- API key availability → dry-run mode decision logic (`eeec586`, `8ea0555`)
- CI: bandit false positives, ruff format, mypy errors across 3 fix cycles

### Architecture
- Clean Architecture (Hexagonal) — ports/adapters separation
- 6-Layer hierarchy: Foundation → Memory → Agentic Core → Orchestration → Automation → Extensibility
- `src/` layout migration (`bf2bc24`)
- OpenClaw-inspired patterns: Gateway, Session Key, Binding Router, Lane Queue

### Infrastructure
- CI: 5-job pipeline (lint, typecheck, test matrix 3.12/3.13, security, gate)
- Strict `mypy` type checking (zero errors)
- `ruff` linting with S-series security rules
- `bandit` security scanning
- 1,879 tests across 115 modules
- 8 Claude skills + 4 analyst sub-skills
- LangSmith tracing (conditional, via `_maybe_traceable`)

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 0.18.1 | 2026-03-17 | Report 보강, Evaluator UI 개선, Spinner/색상 안정화 |
| 0.18.0 | 2026-03-17 | 병렬 도구 실행 (Tiered Batch Approval), Pipeline 안정성 |
| 0.17.0 | 2026-03-17 | Cost Tracker, Agent Reflection, Cache Expiry, geode history, tool_handlers 분할 |
| 0.16.0 | 2026-03-17 | Config Cascade TOML, Run History Context, geode init, CLI 레이어 분리, 코드 퀄리티 |
| 0.15.0 | 2026-03-16 | Tier 0.5 User Profile, MCP 코드 레벨 영속화, Token Guard 철폐, README 정체성 반영 |
| 0.14.0 | 2026-03-16 | Identity Pivot, 1M 컨텍스트, tool_result 3중 방어, HITL 완화, 톤다운 UI |
| 0.13.2 | 2026-03-16 | Pre-commit 안정화, cron weekday 버그, UI 마커 브랜딩 통일, Docs-Sync 강화 |
| 0.13.1 | 2026-03-16 | Anthropic API extra fields 400 에러 수정 |
| 0.13.0 | 2026-03-16 | Signal Liveification, Plan 자율 실행, Dynamic Graph, 오류 복구, Goal Decomposition, 그라운딩 |
| 0.12.0 | 2026-03-15 | HITL 보안 강화, WRITE_TOOLS/MCP 안전 게이트, README 자율 실행 코어 재구성 |
| 0.11.0 | 2026-03-15 | SubAgent Full Inheritance, asyncio 전환, External IP, BiasBuster fast path, D1-D5 감사 |
| 0.10.1 | 2026-03-13 | UI/UX 리브랜딩, Domain Plugin, Agentic 강건성, 리포트 상용화, MCP 정규화 |
| 0.10.0 | 2026-03-12 | SubAgent 병렬 실행, SchedulerService 와이어링, NL 스케줄, OpenClaw 세션 격리 |
| 0.9.0 | 2026-03-11 | General Assistant, Skills, MCP 자동설치, Clarification, 마스코트 |
| 0.8.0 | 2026-03-11 | Plan/Sub-agent NL, Claude Code UI, response quality, verification tracing |
| 0.7.0 | 2026-03-11 | C2-C5 flexibility, LangSmith observability, orchestration integration, 17-tool audit |
| 0.6.1 | 2026-03-10 | Content/code separation, package rename, pre-commit hooks |
| 0.6.0 | 2026-03-10 | Initial release — full pipeline, agentic loop, 3-tier memory |

<!-- Links -->
[Unreleased]: https://github.com/mangowhoiscloud/geode/compare/v0.19.1...HEAD
[0.19.1]: https://github.com/mangowhoiscloud/geode/compare/v0.19.0...v0.19.1
[0.19.0]: https://github.com/mangowhoiscloud/geode/compare/v0.18.1...v0.19.0
[0.18.1]: https://github.com/mangowhoiscloud/geode/compare/v0.18.0...v0.18.1
[0.18.0]: https://github.com/mangowhoiscloud/geode/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/mangowhoiscloud/geode/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/mangowhoiscloud/geode/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/mangowhoiscloud/geode/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/mangowhoiscloud/geode/compare/v0.13.2...v0.14.0
[0.13.2]: https://github.com/mangowhoiscloud/geode/compare/v0.13.1...v0.13.2
[0.13.1]: https://github.com/mangowhoiscloud/geode/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/mangowhoiscloud/geode/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/mangowhoiscloud/geode/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/mangowhoiscloud/geode/compare/v0.10.1...v0.11.0
[0.10.1]: https://github.com/mangowhoiscloud/geode/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/mangowhoiscloud/geode/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/mangowhoiscloud/geode/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/mangowhoiscloud/geode/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/mangowhoiscloud/geode/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/mangowhoiscloud/geode/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/mangowhoiscloud/geode/releases/tag/v0.6.0
