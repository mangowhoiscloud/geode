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

## [0.51.1] — 2026-04-25

### Fixed
- **OAuth device-code flow invisible in IPC mode** — `/login oauth openai`이 daemon 안에서 실행되며 native `print()`로 출력해서 thin-client REPL이 verification URL과 user code를 받지 못하던 버그. 사용자가 브라우저에 입력할 코드를 볼 수 없어 OAuth 등록 자체가 막혔습니다. (`core/gateway/auth/oauth_login.py`)
- **Billing error 메시지가 thin client에 도달 못 함** — `agentic_loop.py`가 `rich.console.Console()`을 직접 인스턴스화해서 `print()`로 출력. IPC 모드에서 daemon stdout(`/tmp/geode_serve.log`)에만 기록됐습니다.
- **`/clear` 확인 프롬프트 daemon hang** — `input()`이 daemon stdin을 블록하지만 thin client는 그것을 모름. 사용자가 무한 대기 상태에 빠질 수 있었음.

### Added
- **IPC OAuth events** — `oauth_login_started`, `oauth_login_pending`, `oauth_login_success`, `oauth_login_failed` (4종). thin-client renderer가 in-place 진행 표시(`Waiting... (5s)`) + URL/code highlight + 성공 metadata(account_id, plan, stored path) 렌더링. (`core/cli/ui/agentic_ui.py`, `core/cli/ui/event_renderer.py`, `core/cli/ipc_client.py`)
- **`billing_error` IPC event** — agentic loop의 `BillingError` catch 양 지점이 모두 `emit_billing_error(message)`로 전환.
- **IPC mode `/clear` 가드** — IPC mode 감지 시 interactive 확인 차단, `--force` 명시 요구. 사용자에게 명확한 안내 메시지 표시.

### Architecture
- **Daemon-side print/input ban** — daemon 코드 경로에서 native `print()` / `input()` / `rich.console.Console()` 직접 인스턴스화 사용 금지. 모든 사용자 가시 출력은 IPC event를 거쳐야 함. `tests/test_ipc_event_parity.py`가 신규 event 모두 `ipc_client.py` allowlist에 등록됐는지 검증.

## [0.51.0] — 2026-04-25

### Added
- **`ProfileRejectReason` + `EligibilityResult`** — `ProfileStore.evaluate_eligibility(provider)`가 모든 profile에 대해 (무엇이/왜) 거부됐는지 구조화된 verdict를 반환합니다. 이전에는 `list_available()`이 silent skip으로 처리해서 "왜 이 profile이 안 잡히지?" 추적이 불가능했습니다. 5종 이유: `provider_mismatch`, `disabled`, `expired`, `cooling_down`, `missing_key`. (`core/gateway/auth/profiles.py`)
- **Rotator 진단 로깅** — `ProfileRotator.resolve()`가 매칭 실패 시 모든 거부 사유를 한 줄에 요약 로그로 남깁니다 (예: `No eligible profiles for provider=openai (evaluated 2, rejected 2): openai:expired=expired(...) ; openai:cooldown=cooling_down(...)`). 마지막 verdict는 provider별로 캐시되어 LLM breadcrumb이 같은 정보를 참조합니다. (`core/gateway/auth/rotation.py`)
- **LLM-readable credential breadcrumb** — auth 에러로 LLM 호출이 실패하면 다음 agentic round에 `[system] credential note: ...` 시스템 메시지가 자동 주입됩니다. 거부된 profile별 reason + 다음 액션(예: `manage_login(subcommand='use', args='<other-plan>')`)이 포함되어 모델이 자가 복구하거나 사용자에게 의미 있는 메시지를 줄 수 있습니다. Claude Code `createModelSwitchBreadcrumbs` 패턴 차용. (`core/gateway/auth/credential_breadcrumb.py`, `core/agent/agentic_loop.py:_inject_credential_breadcrumb`)
- **`/login` dashboard reject badges** — Profiles 섹션의 각 행에 ✓/✗ 배지 + reason + detail 표시 (예: `✗ cooling_down (47s remaining, error_count=3)`). OpenClaw `auth-health.ts`의 `AuthProfileHealth.reasonCode` 패턴 차용. (`core/cli/commands.py:_login_show_status`)
- **`manage_login` 도구 응답에 eligibility verdict 포함** — `profiles[].eligible / reason / reason_detail` 필드 추가. LLM이 status 한 번 호출로 모든 거부 사유를 보고 후속 결정 가능. (`core/cli/tool_handlers.py:handle_manage_login`)

### Changed
- `ProfileRotator.resolve()`가 내부적으로 `list_available` 대신 `evaluate_eligibility`를 호출 (시그니처/반환 타입 보존, 동작 동일).

## [0.50.2] — 2026-04-25

### Changed
- **`~/.geode/auth.json` → `~/.geode/auth.toml` 단일 SOT 통합** — v0.50.0이 도입한 `auth.toml` Plan/Profile 영구 저장소가 OAuth 토큰까지 흡수합니다. `oauth_login.py`의 `_save_auth_store` / `_load_auth_store`가 내부적으로 `auth.toml`로 라우팅됩니다 (호출 시그니처는 호환 유지). `~/.geode/auth.json`이 발견되면 한 번 읽어 OAUTH_BORROWED Plan + Profile 쌍으로 변환한 뒤 `auth.json.migrated.bak`으로 자동 백업합니다. (`core/gateway/auth/oauth_login.py`)
- **OAuth Plan 표현** — GEODE가 직접 발급한 device-code OAuth는 `kind = "oauth_borrowed"`, `provider = "openai-codex"`, plan id = `openai-codex-geode`로 저장됩니다. 외부 Codex CLI(`~/.codex/auth.json`)는 이전과 동일하게 `managed_by="codex-cli"` Profile로 read-only 미러됩니다.

### Fixed
- **이중 SOT 혼동 제거** — pre-v0.50.0 시절의 `auth.json`이 v0.50.0 `auth.toml` 도입 후에도 잔존해서 `/login` dashboard가 두 파일을 동시에 참조하던 미세 버그가 해소됩니다. 한 번 마이그레이션 후 `auth.toml`만 SOT로 사용.

## [0.50.1] — 2026-04-25

### Added
- **`manage_login` agentic tool** — natural-language access to the unified `/login` command. Supports the same subcommands as the slash command (`status`, `add`, `oauth`, `set-key`, `use`, `route`, `remove`, `quota`, `help`). Returns a structured snapshot (plans, profiles, routing) so the LLM can reason about credential state without re-rendering the Rich dashboard. (`core/tools/definitions.json`, `core/cli/tool_handlers.py`)
- **Safety/policy registration** — `manage_login` is in `WRITE_TOOLS`, blocked for sub-agents (`SUBAGENT_DENIED_TOOLS`), excluded from auto-recovery (`error_recovery._EXCLUDED_TOOLS`), denied for read-only profiles, and emits an HITL approval card with `subcommand`/`args` summary. (`core/agent/safety_constants.py`, `core/agent/sub_agent.py`, `core/agent/error_recovery.py`, `core/tools/policy.py`, `core/agent/approval.py`)

### Changed
- **`set_api_key` and `manage_auth` tool descriptions** — both now point users (and the model) at `manage_login` as the preferred path. Approval denial messages updated to reference `/login` instead of the legacy `/key` and `/auth` commands.

## [0.50.0] — 2026-04-25

### Added
- **Plan + ProviderSpec credential model** — first-class `Plan` entity with `PlanKind` (PAYG / SUBSCRIPTION / OAUTH_BORROWED / CLOUD_PROVIDER), per-Plan endpoint binding, and optional `Quota(window_s, max_calls, model_weights)`. Built-in templates for GLM Coding Lite/Pro/Max. (`core/gateway/auth/plans.py`, `core/llm/registry.py`)
- **`/login` unified credentials command** — replaces split `/key` + `/auth` + `/login` UX with a single dashboard + verb hierarchy modeled on Hermes (`hermes auth ...`) and Claude Code (`/login` / `/status`). Subcommands: `add` (interactive wizard), `oauth openai`, `set-key`, `use`, `route`, `remove`, `quota`, `status`. The bare `/login` shows a unified view of Plans + Profiles + Routing + OAuth credentials. (`core/cli/commands.py`)
- **`~/.geode/auth.toml` persistence** — Plans and bound profiles survive process restarts in a single TOML file (0600 perms). First boot auto-migrates `.env` PAYG keys into PAYG plans. `GEODE_AUTH_TOML` env var redirects the path for testing/sandboxing. (`core/gateway/auth/auth_toml.py`)
- **Mascot plan line** — startup brand block shows the active subscription quota: `Plan: GLM Coding Lite (used 23/80 · 57 left · resets 134m)`. Hidden when no quota-bearing plan is registered. (`core/cli/ui/mascot.py`)
- **`AuthError` + `ERROR_HINTS`** — structured auth errors map to user-actionable hints (subscription upgrade URLs, `/login set-key` invocations, OAuth refresh prompts). Hermes `format_auth_error` pattern. (`core/gateway/auth/errors.py`)
- **Model-switch reason in IPC events** — `MODEL_SWITCHED` events now surface the trigger (`rate_limit`, `auth_cross_provider`, `failure_escalation`) inline so users can tell quota exhaustion apart from auth errors at a glance. (`core/cli/ui/event_renderer.py`)

### Fixed
- **Anthropic sampling parameters on adaptive-thinking models** — `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-4-6` rejected requests with `temperature` set ("temperature is deprecated for this model" → 400 BadRequest). Sampling parameters are now omitted on adaptive-thinking models per Anthropic's Opus 4.7 breaking change. `claude-opus-4-7` also registered for the context-management + compaction beta. Fixes the `/model` hot-swap to Opus 4.7. Source: https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7
- **Codex OAuth poisoning general OpenAI calls** — Codex CLI OAuth was registered as `provider="openai"`, so `ProfileRotator.resolve("openai")` returned the Codex token for every GPT call. Codex tokens lack `model.request` scope on `api.openai.com`, causing 403 + slow API-key fallback. The provider variant is now `openai-codex` with its own endpoint (`chatgpt.com/backend-api/codex`). (`core/runtime_wiring/infra.py`, `core/llm/providers/codex.py`)
- **GLM Coding Plan endpoint** — `GLM_BASE_URL` pointed at the metered PAYG endpoint (`api.z.ai/api/paas/v4`), so Coding Plan keys silently bypassed the subscription quota. Default flipped to `api.z.ai/api/coding/paas/v4`; PAYG endpoint preserved as `GLM_PAYG_BASE_URL`. (`core/config.py`, `core/llm/providers/glm.py`)
- **Dual ProfileStore drift** — CLI (`/auth`) and runtime LLM dispatch held separate `ProfileStore` instances. Credentials added through `/auth add` were invisible to `ProfileRotator.resolve()`. Single singleton via `runtime_wiring.infra.ensure_profile_store()`. (`core/runtime_wiring/infra.py`, `core/cli/commands.py`)
- **Provider label fragmentation (`zhipuai` vs `glm`)** — UI store used `provider="zhipuai"` while dispatch keyed off `provider="glm"`. Profile rotator could never find UI-added GLM keys. Normalized to `glm`. (`core/cli/commands.py`)
- **`MODEL_PROFILES` mislabel** — `gpt-5.4-mini` was advertised as `Codex (Plus)` even though it routes to plain `openai` (PAYG). Users believed they were on the Plus subscription while being billed metered. Now labeled `OpenAI`. (`core/cli/commands.py`)

### Changed
- **Cross-provider auto-escalation disabled for `glm` and `openai-codex`** — `CROSS_PROVIDER_FALLBACK["glm"]` and `["openai-codex"]` are now empty. A GLM Coding Plan auth error no longer silently diverts traffic to a metered OpenAI key. Cross-plan jumps will return as an explicit user-confirmed action in a future release. (`core/llm/adapters.py`)
- **`/key` and `/auth` are aliases that surface the unified `/login` dashboard** — bare `/key` redirects to `/login`. Setting an API key still works (`/key sk-...`) and now also seeds a PAYG plan into the registry so the credential is visible in `/login`.

### Architecture
- **Provider variant registry** — `core/llm/registry.py` introduces `ProviderSpec(id, display_name, default_base_url, auth_type, extra_headers_factory)` modeled on Hermes' `ProviderConfig`. Five variants registered: `anthropic`, `openai`, `openai-codex`, `glm`, `glm-coding`. The Codex variant carries the Cloudflare-bypass header factory.
- **`AuthProfile.plan_id`** — additive FK linking a profile to a Plan. `base_url_override` allows per-profile endpoint overrides (China-mainland mirrors etc.). Backward compatible — env-loaded profiles default to a synthetic PAYG Plan.

## [0.49.1] — 2026-04-23

### Infrastructure
- Added repo hygiene ratchet — CI blocks PRs introducing dangling symlinks, absolute-path symlinks, or orphan `.claude/worktrees/` entries missing `.owner` metadata (`scripts/check_repo_hygiene.py`, wired into the `lint` job).
- Removed stale tracked `.owner` at repo root (accidentally committed via 6d07637) and added `/.owner` to `.gitignore` so the worktree ownership convention in CLAUDE.md §0 no longer pollutes feature branches.

## [0.49.0] — 2026-04-23

### Architecture
- **Approval workflow extraction** — HITL approval logic extracted from `tool_executor.py` to `agent/approval.py`. SRP improvement (#750)
- **Hook interceptor/feedback pattern** — TOOL_EXEC hooks upgraded to interceptor pattern with aggressive recovery wiring (#751)
- **Adapter base classes** — `BaseNotificationAdapter` (Slack/Discord/Telegram), `BaseCalendarAdapter` (Google/Apple), `BasePoller` infra consolidation. ~200줄 중복 제거 (#731)
- **OAuth credential cache** — `CredentialCache` class extracts shared TTL+mtime cache pattern from 2 OAuth readers (#731)
- **Provider key resolution** — `resolve_provider_key()` centralizes ProfileRotator lookup (#731)
- **Scoring constants** — `scoring_constants.py` single source of truth for tier thresholds, weights, confidence multiplier (#731)

### Added
- **Tool hook matcher** — `register(matcher="run_bash|terminal")` regex 패턴으로 핸들러가 특정 도구에만 반응. 3가지 트리거 모드 모두 지원 (#759)
- **`TOOL_EXEC_FAILED` event** — 도구 실행 실패 시에만 발화하는 전용 observer hook. error, error_type, recoverable 포함 (#759)
- **`TOOL_RESULT_TRANSFORM` event** — TOOL_EXEC_END 관측과 분리된 결과 변환 전용 feedback hook. Hermes `transform_tool_result` 패턴 (#759)
- **Claude Opus 4.7** — ANTHROPIC_PRIMARY 승격. 1M context, $5/$25, 고해상도 비전, task budgets. Fallback: opus-4-7→opus-4-6→sonnet-4-6 (#771)
- **Codex OAuth pipeline** — proactive refresh (120s 전), 401 auto-refresh, credential scrubbing (`scrub.py`), ZAI profile 등록 (#763)
- **ProfileRotator wiring** — `mark_success()`/`mark_failure()` LLM 호출 체인에 와이어링. 8개 audit logger 비대칭 해소 (#765)
- **`geode skill` CLI** — `list`/`create`/`show`/`remove` + 3-tier visibility (`public`/`private`/`unlisted`) (#767)
- **GLM-5.1 model** — Z.AI GLM-5.1 (SWE-Bench Pro 1위, MIT) 추가 및 GLM_PRIMARY 승격. GLM-5V-Turbo, GLM-5-Turbo 가격 갱신 (#729)
- **`geode doctor slack`** — Slack Gateway 7-point diagnostic (env, token, scopes, bindings, serve, MCP, socket). CLI + natural language tool (#57)
- **Slack App Manifest URL** — `get_manifest_url()` 원클릭 앱 생성 URL
- **OSS compliance files** — NOTICE, CONTRIBUTING.md (DCO), CODE_OF_CONDUCT.md, SECURITY.md, Issue/PR templates, .env.example (#744)
- **OSS templates** — `docs/progress.md` kanban, `docs/plans/TEMPLATE.md`, `docs/workflow.md`, `.geode/skills/TEMPLATE.md` (#746)

### Fixed
- **GLM auth infinite retry** — `classify_llm_error()` now handles OpenAI SDK exceptions (was Anthropic-only). Auth errors trigger immediate cross-provider escalation instead of cycling within same provider (#740)
- **Model escalation ↔ settings sync** — `_persist_escalated_model()` prevents `_sync_model_from_settings()` from reverting escalation (#740)
- **BashTool cwd** — defaults to `get_project_root()` (user's workspace) instead of GEODE install path (#748)
- **LLM client resource leaks** — `try/finally` + `close()` for OpenAI/Anthropic clients in `llm_extract_learning.py` (#731)
- **CI flaky test** — `test_select_by_number` now sets initial model explicitly (#740)

### Removed
- **Internal docs** — `docs/progress.md` (kanban data), `docs/plans/` (32 planning docs), `docs/workflow.md` (internal scaffold), `docs/reports/` (5 completion reports) — replaced with public templates (#744)
- **Personal skills** — job-hunter, expense-tracker, youtube-planner, daily-briefing, weekly-retro, slack-digest (#744)

### Infrastructure
- **.gitignore guardrails** — blocks personal skills, memory, scaffold harness, temporary artifacts from being committed (#746)

## [0.48.0] — 2026-04-11

### Added
- **Hook interceptor pattern** — `trigger_interceptor()` method with block/modify chain semantics. Hooks can now block execution (`{"block": True}`) or modify event data (`{"modify": {...}}`), transitioning from pure observer to observer + interceptor. Per-hook timeout via `ThreadPoolExecutor`
- **6 new HookEvents (49 → 55)**: `USER_INPUT_RECEIVED` (interceptor-capable), `TOOL_EXEC_START/END` (tool execution observability), `COST_WARNING/LIMIT_EXCEEDED` (cost guard at 80%/100%), `EXECUTION_CANCELLED` (cancel audit trail)
- **Session cost guard** — `cost_limit_usd` config field. Fires `COST_WARNING` at 80% and `COST_LIMIT_EXCEEDED` at 100% of budget

### Fixed
- **Sandbox hardening** — 4 crash/safety fixes:
  - `path.resolve()` OSError defense in `add/remove_working_directory()`
  - macOS `/private/var` regex: `r"^/private/var/"` → `r"^/private/var(/|$)"` — trailing slash no longer required
  - `_additional_dirs` thread safety with `threading.Lock` — concurrent sub-agent safety
  - Symlink LRU cache removed — prevents stale resolution in long-running sessions

### Fixed
- **Slack poller message loss on processing failure** — ts was updated BEFORE processing, so if LLM call failed mid-batch, remaining messages were permanently skipped. Now uses deferred-ts pattern: advance only AFTER successful processing, break on failure for retry next cycle
- **Slack app mention not detected** — `<@A...>` (app mention format) was not matched by `_is_mentioned()` regex, causing `require_mention=true` channels to silently ignore app mentions. Added `A` to the `[UBA]` character class in both `_is_mentioned` and `_strip_mentions`

### Added
- **Lazy directory creation** — `ensure_directories()` in `core/paths.py` creates all `~/.geode/` and `.geode/` directories at bootstrap. Follows Claude Code's lazy `mkdir(recursive)` pattern. Fresh `uv run geode` on clean install now works without manual setup
- `.gitignore` auto-entry for `.geode/` on first run

### Architecture
- **Layer violation fix (3 cross-layer dependency violations resolved)**:
  - `agentic_response.py` moved from `core/cli/` (L5) → `core/llm/` (L2) — eliminates L2→L5 import in LLM providers/router. `core/cli/agentic_response.py` retained as backward-compatible re-export
  - `MODEL_PRICING` dead re-export removed from `core/config.py` — eliminates L1→L2 import (no callers used `core.config.MODEL_PRICING`)
  - `RightsRiskResult`, `RightsStatus`, `LicenseInfo` moved from `core/verification/` (L3) → `core/state.py` (L1) — eliminates L1→L3 import. `rights_risk.py` re-exports from `core.state`
- **ContextVar thread propagation fix** — `invoke_with_timeout()` ThreadPoolExecutor에 `contextvars.copy_context()` 추가. graph node에서 memory/profile/domain adapter가 None이 되던 CRITICAL race condition 수정
- **Hook deduplication** — `HookSystem.register()` name 기반 중복 방지. explicit + filesystem discovery 이중 등록 해소
- **LLM router decomposition** — `adapters.py` (355줄, Protocol 7개 + ClaudeAdapter + resolve_agentic_adapter) + `provider_dispatch.py` (269줄, retry/circuit breaker/cross-provider) 추출. router.py 1530→1062줄 (-31%)

### Added
- **Sandbox validation module (Claude Code parity)** — `core/tools/sandbox.py` 중앙 모듈 신설. 14/15 GAP 해소:
  - Shell expansion blocking ($VAR, ${VAR}, $(cmd), %VAR%, ~user) — TOCTOU prevention
  - Dangerous file/directory blocking (.gitconfig, .bashrc, .git/, .claude/) — write only
  - Symlink chain resolution with intermediate validation + lru_cache memoize
  - macOS path normalization (/private/var ↔ /var, /private/tmp ↔ /tmp bilateral)
  - Glob pattern blocking in write operations
  - Session-scoped additional working directories API (add/remove)
  - ReadDocumentTool offset/limit + file size guard (256KB pre-read, 25K token post-read)
  - Sandbox settings externalization (config.toml [sandbox] section)
  - Configurable limits for glob/grep results
  - Sub-agent working directory isolation

## [0.47.1] — 2026-04-07

### Added
- **Max jobs 50 제한** — `add_job()` 상한 체크. 무한 job 생성 방지 (claude-code MAX_JOBS 패턴)
- **Lock session identity** — `SchedulerLock`에 `session_id` 추가. serve restart 시 같은 세션이면 즉시 lock 재취득 (idempotent re-acquire)
- **Recurring age-out** — 30일 지난 recurring job 자동 삭제 + `permanent` flag 면제. stale job 누적 방지
- **Sub-agent scheduler routing** — `ScheduledJob.agent_id` 필드 + `OnJobFired` 4-arg callback. sub-agent별 job 소유 및 fire 라우팅

### Architecture
- **AgenticLoop SRP decomposition** — context window management extracted to `context_manager.py` (410 lines), convergence detection to `convergence.py` (114 lines). agentic_loop.py 1818 → 1405 lines (-23%)
- **CLI __init__.py module extraction** — memory_handler, scheduler_drain, terminal extracted to dedicated modules. cli/__init__.py 1892 → 1641 lines (-13%)
- **Runtime.create() staged builders** — monolithic 122-line factory split into 4 staged private methods (_build_core, _build_tools, _build_memory_and_automation)
- **Hook layer violation fix** — auto_learn.py L6→L5 dependency eliminated via profile_provider DI injection at bootstrap

### Fixed
- **FALLBACK_CROSS_PROVIDER hook never emitted** — cross-provider model escalation now fires the dedicated observability hook with provider-level context
- **signal_adapter ContextVar encapsulation** — added `get_signal_adapter()` public getter, replaced private `_signal_adapter_ctx.get()` access

## [0.47.0] — 2026-04-07

### Added
- **Scheduler GAP-close (claude-code alignment)** — 8 architectural gaps closed:
  - Project-local storage (`.geode/scheduled_tasks.json`) — per-project isolation
  - O_EXCL lock + PID liveness probe — cross-platform multi-session coordination
  - `on_job_fired` callback protocol — decoupled from `queue.Queue`
  - Session-only tasks (`durable=False`) — in-memory ephemeral scheduling
  - Deterministic per-job jitter (SHA-256 hash) — thundering herd prevention
  - 1s check interval + mtime file watch — responsive scheduling with external change detection
  - Missed task recovery — AT/EVERY jobs recovered on startup with grace window
  - `create_scheduler()` factory — library-style instantiation for any context
- **3 new test modules** — `test_scheduler_lock.py`, `test_scheduler_jitter.py`, `test_scheduler_missed.py` (36 tests)

### Changed
- Scheduler default check interval 60s → 1s
- `SchedulerService` default `enable_jitter=True`
- Legacy `fcntl.flock` replaced with `SchedulerLock` (O_EXCL + PID probe)
- `action_queue: queue.Queue` deprecated in favor of `on_job_fired: Callable`

### Fixed
- **Sandbox project root CWD 기반으로 전환** — `_PROJECT_ROOT = Path(__file__).parent³` 하드코딩 → `get_project_root()` (CWD 캡처). 외부 워크스페이스에서 `geode` 실행 시 파일 도구가 "path outside project directory" 오류 발생하던 버그 수정. Claude Code `originalCwd` 패턴 이식

## [0.46.0] — 2026-04-06

### Added
- **OpenAI Codex CLI OAuth 토큰 재사용** — `~/.codex/auth.json`에서 OAuth 토큰 자동 감지. ChatGPT 구독 범위 내 API 호출 (OpenAI 공식 허용). ProfileRotator OAUTH > API_KEY 우선순위
- **Computer-use 하네스** — PyAutoGUI 기반 provider-agnostic desktop automation. Anthropic `computer_20251124` + OpenAI `computer_use_preview` 양쪽 지원. DANGEROUS HITL 승인 필수
- **MCP tool result 토큰 가드** — `max_tool_result_tokens` 25000 기본값. Claude Code 패턴 이식 (`mcpValidation.ts` 25K)
- **HTML→MD 변환** — `markdownify` 도입. web_fetch HTML을 구조 보존 Markdown으로 변환하여 토큰 효율 개선
- **Sandbox breadcrumb 3-layer** — tool description 제약 명시 + _check_sandbox hint + non-recoverable recovery skip
- **Insight quality gate** — `_is_valid_insight()` 7개 reject rule. PROJECT.md garbage 방지
- **HITL 3-point diagnostic logging** — thin CLI/server/tool_executor 전체 approval 흐름 진단 로그
- **PR body 필수 4섹션 템플릿** — Summary/Why/Changes/Verification (CANNOT rule)
- **`/auth login` 인터랙티브 플로우** — subprocess로 `claude login`/`codex login` 직접 실행. OAuth 상태 표시

### Changed
- **Anthropic OAuth 비활성화** — Anthropic 2026-01-09 ToS 변경 대응. Claude Code OAuth 재사용은 정책 위반 → API key만 사용. 코드 보존 (정책 변경 시 재활성화 가능)
- **CLAUDE.md → GEODE.md 분리** — scaffold(CLAUDE.md) vs runtime(GEODE.md) 관심사 분리
- **tool_offload_threshold 5000→15000** — offload 빈도 정상화
- **web search timeout 30→60s** — native tool 응답 대기 시간 확대

### Fixed
- **Python 3.14 prompt_toolkit crash** — kqueue OSError. SelectSelector event loop policy 강제로 prompt_toolkit 복원 (한글 입력/history/backspace)
- **_ConsoleProxy context manager** — Rich FileProxy의 `with console:` TypeError. `__enter__`/`__exit__` 명시적 위임
- **HITL approval UI ANSI 깨짐** — spinner raw ANSI escape 제거 → Rich console.print 통일
- **GLM context overflow 감지** — `"Prompt exceeds max length"` (code 1261) 패턴 추가. 즉시 context_overflow 분류 → aggressive recovery
- **OAuth cache thread-safety** — `threading.Lock`으로 _cache dict 동시 접근 보호
- **web search 401** — Codex OAuth 토큰이 web_search 권한 없음. `_openai_search`가 API key 직접 사용
- **ProfileStore 미갱신** — `/auth login` 후 즉시 ProfileStore 반영
- **CLAUDE.md + README.md 메트릭 동기화** — Modules 195, Tests 3525+, Hooks 48, Tools 56 통일
- **Model switch breadcrumb** — `/model` 전환 시 대화에 전환 마커 주입
- **Haiku model switch 3-bug fix** — beta header 조건부 주입 + context guard wire + overhead 실측
- **Haiku native tool 400** — `allowed_callers=["direct"]` 미설정 수정
- **HITL IPC approval 5-bug fix** — buf 미갱신, stale response, tool_name, safety_level, 이중 프롬프트

## [0.45.0] — 2026-04-01

### Added
- **SessionMetrics** — Hook 기반 p50/p95 latency, error rate, tool success rate 실시간 집계. LLM_CALL_END 이벤트에서 per-model 퍼센타일 추적
- **User preferences → 시스템 프롬프트 주입** — Tier 0.5 preferences.json을 `## User Preferences` 섹션으로 LLM context에 주입하여 개인화 강화
- **Scoring weights 설정화** — 하드코딩 weights를 `scoring_weights.yaml`로 외부화. `.geode/scoring_weights.yaml` 프로젝트 override 지원

## [0.44.0] — 2026-04-01

### Changed
- **MCP catalog → Anthropic registry API** — 44개 하드코딩 catalog.py 삭제 → `api.anthropic.com/mcp-registry/v0/servers` fetch + 24h 로컬 캐시. "MCP Available (env missing)" 섹션 제거, config-driven 단순화

## [0.43.0] — 2026-03-31

### Added
- **IPC HITL 릴레이** — thin CLI에서 WRITE/DANGEROUS 도구 승인 양방향 릴레이. serve 데몬이 approval 요청 → IPC → CLI 프롬프트 → 응답 반환

### Fixed
- **SAFE_BASH_PREFIXES HITL bypass** — redirect/pipe 포함 명령어 차단 + symlink 방어
- **tool_error() 마이그레이션 완료** — calendar_tools(5), profile_tools(4), memory_tools(2), registry(1) 총 12개 raw error 구조화
- **Model card 가격 $0.00** — per-token→per-1M 변환 누락 (모든 provider 공통)
- **Transcript total_cost $0** — session_end에 TokenTracker accumulator 비용 전달 누락
- **GLM 비용 추적 누락** — GlmAgenticAdapter에 get_tracker().record() 연결
- **/clear TokenTracker 미초기화** — 대화 초기화 후 stale 비용/토큰 잔존 방지

## [0.42.0] — 2026-03-31

### Added
- **HookSystem audit (42 → 46 events)** — 4 lifecycle event 추가 (SHUTDOWN_STARTED, CONFIG_RELOADED, MCP_SERVER_CONNECTED/FAILED) + 12 table-driven audit logger + S4 비대칭 수정 (memory_tools hook 발화) + 3 trigger site 추가

## [0.41.0] — 2026-03-31

### Fixed
- **모델 전환 mid-call crash** — `switch_model` tool이 agentic loop 내부에서 `loop.update_model()` 직접 호출 → adapter mid-call 교체 → provider 불일치 crash. Deferred model sync로 수정: `_sync_model_from_settings()`가 라운드 경계에서 안전하게 적용. `switch_model` SAFE → WRITE 이동
- **모델 전환 미유지** — `config_watcher`가 `.env` 변경 감지 후 `Settings()` 재생성 시 stale `os.environ`에서 원래 모델 읽어 `settings.model` 복귀. `settings.model`을 hot-reload 대상에서 제외 + `upsert_env()`에 `os.environ` 동기화 추가

## [0.40.0] — 2026-03-31

### Added
- **200K 절대 토큰 가드** — 1M 컨텍스트 모델에서 200K 토큰 초과 시 rate limit pool 분리 방지. 퍼센트 기반 임계값(80%=800K)과 별개로 `ABSOLUTE_TOKEN_CEILING`이 tool result 요약 → compact 2단계 압축 실행
- **LLM 친화적 에러 메시지** — `tool_error()` 헬퍼 + `classify_tool_exception()` 도입. `error_type` (validation/not_found/permission/connection/timeout/dependency/internal), `recoverable` 플래그, `hint`로 구조화. tool_executor, MCP, web_tools, document_tools, analysis tools 적용
- **Graceful serve drain** — SIGTERM/SIGINT 시 3-phase shutdown: `stop_accepting()` (새 연결 차단) → `SessionLane.active_count` 폴링 (30s timeout) → component shutdown. 진행 중 세션 완료 대기

## [0.39.0] — 2026-03-31

### Added
- **IPC pipeline event parity** — thin client now receives all pipeline data that direct CLI renders:
  - Signals (YouTube views, Reddit subscribers, FanArt YoY%) in `pipeline_gather` event
  - PSM causal inference (ATT%, Z-value, Rosenbaum Gamma) in `pipeline_score` event with significance indicators
  - Pipeline warnings/errors in `pipeline_result` event
  - Guardrail failure details in `pipeline_verification` event
- **ToolCallTracker.suspend()** — erases rendered spinner lines and resets cursor position, preventing ANSI cursor-up from corrupting interleaved pipeline/stream output
- **Pipeline ip_name tagging** — `set_pipeline_ip()` thread-local for forward-compatible parallel UI (Option B: IP-sequential queueing)
- **Gateway context overflow recovery** — pre-call context check prevents 400 errors; auto-clear session on context exhaustion; i18n exhaustion messages via Haiku
- **CJK-aware tool tracker** — `_truncate_display()` uses `unicodedata.east_asian_width` for correct CJK character width; spinner moved to left side

### Fixed
- **list_ips spinner duplication** — `stop()` called per stream chunk reprinted spinner each time; now uses `suspend()` with position reset
- **analyze_ip spinner/panel collision** — 9 pipeline event handlers changed from `_clear_activity_line()` to `_suppress_all_spinners()`, stopping tracker before writing
- **Rich Panel cursor-up interference** — stale `_line_count` caused cursor-up to erase interleaved pipeline event output
- **400 error silent swallow** — `call_with_failover` now re-raises context-overflow BadRequestError instead of returning None

### Removed
- **Stub insight generator** — `PIPELINE_END→add_insight` hook removed; generated broken `tier=?/score=0.00` entries because synthesizer input state didn't reliably contain scoring results. Pipeline results are recorded in journal (`runs.jsonl`) via JournalHook.

## [0.38.0] — 2026-03-30

### Added
- **LLM Resilience Hardening** — 14-item 3-phase plan fully implemented across Agentic Loop, Domain DAG, and shared LLM infrastructure:
  - **Backoff jitter** (C1) — full jitter (`random.uniform`) replaces deterministic delay, preventing thundering herd.
  - **Cross-provider failover** (C1-b) — `_cross_provider_dispatch()` in router.py; opt-in via `llm_cross_provider_failover`.
  - **Degraded fallback** (B1) — retry-exhausted analyst/evaluator/scoring nodes return `is_degraded=True` results instead of crashing the pipeline.
  - **Pipeline timeout** (B3) — `invoke_with_timeout()` with `PIPELINE_TIMEOUT` hook event. Config: `pipeline_timeout_s` (default 600s).
  - **Degraded scoring penalty** (B4) — degraded sources proportionally reduce confidence in final score.
  - **Verification enrichment loop** (B5) — guardrails/biasbuster failure triggers gather loopback (before confidence check).
  - **Evaluator partial retry** (B6) — non-degraded evaluators skipped on re-iteration (mirrors analyst pattern).
  - **Iteration history trimming** (B7) — custom reducer caps `iteration_history` at 10 entries.
  - **Fallback cost ratio** (C2) — `llm_max_fallback_cost_ratio` filters expensive fallback models upfront.
  - **Error propagation** (B2) — pipeline `state["errors"]` included in MCP caller output.
  - **Gather retryable** (B8) — gather node added to `_RETRYABLE_NODES`.
  - **Cost budget hardening** (A2) — specific exceptions, 80% proactive warning, hard termination.
  - **Checkpoint resume** (A3) — `SessionCheckpoint` per-round save, auto-checkpoint before failures.
  - **Aggressive context recovery** — continue loop after context exhaustion with summarize + halved-keep prune.
- **Error classification** — `core/llm/errors.py`: typed error hierarchy (rate limit, auth, billing, context overflow) with severity + hint.
- **HookSystem 42 events** — `FALLBACK_CROSS_PROVIDER` + `PIPELINE_TIMEOUT` (40 → 42).
- **Resilience test suite** — 34 new tests covering all resilience scenarios.

### Fixed
- **Sequential tool rendering duplicates** — `ToolCallTracker` accumulated completed entries across batches, causing stale lines (e.g. `sequentialthinking` showing duplicate spinner rows). Now clears previous batch on new batch start.

## [0.37.2] — 2026-03-30

### Added
- **Persistent activity spinner** — thin client shows animated `Working...` spinner from prompt send until result arrives. Thinking/tool spinners override it; resumes between events.
- **Pipeline client-side rendering** — `panels.py` detects IPC mode → emits structured event + returns early (no duplicate raw ANSI stream). Thin client renders all pipeline milestones from structured events.
- **`pipeline_header` / `pipeline_result` events** — 2 new event types (28 → 30 total).

### Fixed
- **Thinking spinner frozen** — `EventRenderer` thinking spinner was rendering 1 frame then freezing until next event. Now uses daemon thread animation (80ms per frame), matching `ToolCallTracker` pattern.
- **Tool duration inaccurate** — `tool_end` event now includes server-measured `duration_s`. Client prefers server duration over client-side measurement (excludes IPC transport latency).
- **`/model` hot-swap (P0)** — `_apply_model()` now calls `loop.update_model()` on the active AgenticLoop. Model changes take effect immediately in the current IPC session without reconnecting.
- **`/quit` session cost (P1)** — `/quit` and `/exit` now relay to serve instead of running locally. Session cost summary renders with real accumulator data from the serve process.

### Added
- **`--continue` / `--resume` (P2)** — IPC resume protocol wired end-to-end. `geode --continue` resumes the most recent session; `geode --resume <id>` resumes a specific session. Checkpoint messages and model are restored into the conversation context.
- **IPC `resume` message type** — CLIPoller handles `{"type": "resume"}` messages, loads checkpoint via `SessionCheckpoint`, and restores conversation context + loop session ID.
- **`IPCClient.request_resume()`** — thin client method to request session resume from serve.
- **Event Schema V2 — 16 new structured IPC events** expanding coverage from 12 → 28 event types:
  - AgenticLoop termination: `model_escalation`, `cost_budget_exceeded`, `time_budget_expired`, `convergence_detected`
  - AgenticLoop strategy: `goal_decomposition`, `tool_backpressure`, `tool_diversity_forced`
  - AgenticLoop lifecycle: `model_switched`, `checkpoint_saved`
  - Pipeline milestones: `pipeline_gather`, `pipeline_analysis`, `pipeline_evaluation`, `pipeline_score`, `pipeline_verification`
  - Pipeline control flow: `feedback_loop`, `node_skipped`
- **EventRenderer V2** — client-side handlers for all 16 new events with ANSI rendering.

## [0.37.1] — 2026-03-30

### Fixed
- **serve auto-start cwd** — `start_serve_if_needed()` resolves GEODE project root via `__file__` path. Works from any directory.
- **sys.executable mismatch** — `shutil.which("geode")` instead of `sys.executable` for subprocess spawn.
- **SessionMode.IPC quiet** — `quiet=True` suppresses AgenticLoop UI on serve terminal; results via IPC JSON only.
- **Thin client UX** — thinking spinner during prompt relay, status line (model/rounds/tools) after response, serve auto-start spinner.
- **tool_calls dict handling** — CLIPoller handles both dict and object tool call formats.
- **auto-start timeout** — 10s → 30s (MCP 13-server startup takes ~20s).

### Known Issues
- `/model` (interactive menu) requires terminal — does not work in thin mode. Use `/model <name>` with explicit arg.

## [0.37.0] — 2026-03-30

### Changed
- **Thin-only architecture** — standalone REPL eliminated (~487 lines deleted). `geode` always connects to serve via IPC; auto-starts serve if not running. Single code path for all execution: CLI, Slack/Discord, Scheduler all route through `acquire_all(key, ["session", "global"])`.
- **SessionMode.IPC** — new session mode for thin CLI client. `hitl=0` (WRITE allowed, DANGEROUS policy-blocked). Replaces `SessionMode.REPL` for IPC connections.
- **CLIPoller hardened** — `acquire_all()` gating, `chmod 0o600` on Unix socket, `command` type in IPC protocol for slash command relay.
- **SessionLane — per-key serialization** — replaced 4-lane system (session/global/gateway/scheduler) with OpenClaw pattern: `SessionLane` (per-session-key `Semaphore(1)`) + `Lane("global", max=8)`. Same session key serializes, different keys parallel. `acquire_all(key, ["session", "global"])` unifies all execution paths. OpenClaw defect fixes: `max_sessions=256` cap, `cleanup_idle()` eviction.
- **Unified bootstrap** — `serve()` no longer calls `bootstrap_geode()`. Uses `setup_contextvars()` + `GeodeRuntime.create()` directly. ONE HookSystem, ONE MCP manager, ONE SkillRegistry across all entry points. Resolves C1/C2/H1/H4/H5 from structural audit.

### Added
- **CLIChannel IPC** — Unix domain socket (`~/.geode/cli.sock`) connects thin CLI client to `geode serve`. `CLIPoller` accepts local connections, creates REPL sessions via SharedServices. `IPCClient` auto-detects serve and delegates agentic execution over line-delimited JSON protocol. Fallback to standalone when serve is not running.
- **Scheduler in serve mode** — `SchedulerService` extracted from REPL into `geode serve`. Scheduled jobs now fire in headless mode. Shared `_drain_scheduler_queue()` helper eliminates duplication between REPL and serve paths.
- **Lane.acquire_timeout()** — blocking-with-timeout acquisition for Lane semaphores.
- **SessionLane class** — per-key `Semaphore(1)`, `max_sessions=256`, idle cleanup at 300s.
- **Serve auto-start** — background daemon spawn with pidfile lock. `geode` thin CLI auto-starts serve if not running.
- **IPC command type** — slash command server-side relay via `command` type in IPC protocol.

### Fixed
- **C3: Dual Scheduler race** — `fcntl.flock(LOCK_EX/LOCK_SH)` on `jobs.json` save/load. REPL and serve can no longer corrupt shared job store via concurrent file access.
- **H2: Scheduler → LaneQueue** — replaced ad-hoc `Semaphore(2)` with `Lane.try_acquire()`/`manual_release()`. Scheduler concurrency now routes through the central LaneQueue system.
- **M2: Scheduler PolicyChain** — `create_session(SCHEDULER/DAEMON)` filters DANGEROUS tools (`run_bash`, `delegate_task`). Headless modes can no longer invoke tools requiring HITL approval.
- **M3: Stuck job detection** — `running_since_ms` field tracks active jobs. `detect_stuck_jobs()` runs each tick, marks jobs exceeding 10min threshold as `stuck`, fires hook.
- **TOCTOU race in start_serve_if_needed** — pidfile lock prevents race between check and spawn.
- **Sub-agent depth guard** — explicit `if depth >= max_depth` check replaces implicit gating.
- **Scheduler drain exception safety** — lane slot leak on `create_session()` failure fixed. `main_loop.run()` exception no longer kills the drain loop. Init failure in serve promoted to `log.warning`.
- **P1 batch (5 fixes)** — C3/C4 regression tests, WorkerRequest `time_budget_s` pass-through, thread-mode `denied_tools` raises (was warn), announce TTL reset (`setdefault` → assignment), subprocess env whitelist +2 vars.

### Removed
- **CoalescingQueue** — 148 lines, no-op callback, 0 trigger rate. Removed entirely.
- **Standalone REPL `_interactive_loop`** — ~487 lines eliminated. All execution routes through serve.
- **Gateway/scheduler named lanes** — replaced by SessionLane per-key serialization.
- **IsolatedRunner internal Semaphore** — replaced by `Lane("global", max=8)`.

### Architecture
- **6-Layer → 4-Layer Stack** — Model → Runtime → Harness → Agent, with orthogonal Domain (`⊥ Domain`). Simplified from previous L0-L5 numbering.
- **M1: Config-driven pollers** — `build_gateway()` reads `[gateway] pollers` from `config.toml`. Dynamic `_POLLER_REGISTRY` replaces hardcoded `register_poller()` calls. Default: all three (slack, discord, telegram).
- **19 legacy docs moved to archive** — outdated architecture and plan documents relocated to `docs/archive/`.

## [0.35.1] — 2026-03-29

### Fixed
- **C1: agentic_ref race** — removed shared mutable `agentic_ref[0]` from SharedServices. Tool handlers now use `_current_loop_ctx` ContextVar (per-thread, no cross-session contamination). Scheduler can no longer corrupt REPL's loop pointer.
- **C2: TaskGraph thread safety** — `threading.Lock` on `get_ready_tasks()`, `mark_running()`, `mark_completed()`, `mark_failed()`, `add_task()`. Prevents double-execution from concurrent state transitions.
- **C3: IsolatedRunner semaphore leak** — semaphore release guarded by `acquired` flag. Timeout on `_acquire_slot` no longer leaks extra permits beyond `MAX_CONCURRENT`.
- **C4: LaneQueue acquire_all()** — tracks acquired semaphores separately from active tracking. Partial failure only releases actually-acquired semaphores.
- **H1: Zombie thread cleanup** — timeout threads removed from `_active`/`_cancel_flags` tracking.
- **H2: Announce double-publish** — atomic check-and-set inside `_announce_lock`.
- **H3: Announce orphan TTL** — 300s auto-expiry for stale queue entries.
- **H4: Subprocess env whitelist** — 10 safe vars only (no full `os.environ` copy).
- **H8: TaskBridge evaluator lock** — `_evaluator_lock` on counter increment.
- **M1: MODEL_SWITCHED duplicate** — removed duplicate C7 handler registration.

### Changed
- **HookEvent count 46→40** — removed 6 orphan events: CONTEXT_WARNING, PROMPT_DRIFT_DETECTED, GATEWAY_MESSAGE/RESPONSE, MCP_SERVER_STARTED/STOPPED.

## [0.35.0] — 2026-03-29

### Added
- **SharedServices Gateway** — single factory for all session modes (REPL/DAEMON/SCHEDULER/FORK). Codex CLI `ThreadManagerState` + OpenClaw Gateway pattern. `create_session(mode)` guarantees identical shared resources across all entry points.
- **SessionMode enum** — `REPL` (hitl=2, interactive), `DAEMON` (hitl=0, Slack/Discord), `SCHEDULER` (hitl=0, 300s cap), `FORK` (hitl=0, 60s cap).

### Changed
- **Time-based constraints** — `DEFAULT_MAX_ROUNDS=0` (unlimited) for all modes. `time_budget_s` is the sole execution constraint. `ChannelBinding.max_rounds` replaced by `time_budget_s` (120s default). Legacy `max_rounds` config auto-converted.
- **GATEWAY → DAEMON** — external channel poller mode renamed to `DAEMON`. "Gateway" now refers to the SharedServices layer.

### Fixed
- **HookSystem wired** — `build_hooks()` called at bootstrap, injected into every `create_session()`. `_fire_hook()` now works (was permanently None).
- **Globals → ContextVar** — `_project_memory`, `_user_profile`, `_readiness` converted from module-level globals to `ContextVar`. Thread-safe across DAEMON/SCHEDULER threads.
- **Scheduler ContextVar propagation** — `propagate_context=True` in `create_session(SCHEDULER)` re-injects domain/memory/profile before job execution.

### Architecture
- **5 Shared Services GAPs resolved** — HookSystem(CRITICAL→fixed), globals(HIGH→fixed), scheduler propagation(HIGH→fixed), _readiness(MEDIUM→fixed), _result_cache(LOW→already had Lock).

## [0.34.0] — 2026-03-29

### Added
- **Sub-Agent Subprocess Isolation** — `WorkerRequest`/`WorkerResult` 데이터 계약 + `core.agent.worker` subprocess worker. IsolatedRunner가 callable(thread) / WorkerRequest(subprocess) 자동 라우팅. 크래시 격리 + SIGKILL timeout.
- **3-Entry-Point 리소스 공유 감사** — REPL/serve/scheduler 전체 리소스 맵 시각화 + 5건 결함 식별.

### Changed
- **Sub-Agent max_depth 2→1** — Claude Code 패턴 정합. 서브에이전트 재귀 금지.
- **IsolatedRunner Semaphore Wait** — 즉시 거부(0s) → 대기(30s). 동시성 제어 개선.

### Changed
- **LLM-consumed documents English conversion** — All 39 files injected into LLM context (GEODE.md, CLAUDE.md, definitions.json, SKILL.md ×30, rules ×4, PROJECT.md, decomposer.md) converted to English. Korean trigger keywords retained for bilingual input matching. Added i18n convention rule to CLAUDE.md (#523).

### Architecture
- **Shared Services GAP 식별** — HookSystem 미연결(CRITICAL), module-level globals 스레드 비안전(HIGH), ContextVar 미전파(HIGH), _readiness 레이스(MEDIUM), _result_cache 충돌(LOW). 다음 버전에서 수정 예정.

## [0.33.0] — 2026-03-29

### Added
- **Skill 2.0** — Agent Skills spec 정합. Progressive Disclosure 3-tier (metadata→body→resources), multi-scope discovery (4-priority dirs), `context: fork` (subagent 실행), `!`cmd`` dynamic context, `$ARGUMENTS` 치환, `user-invocable` 제어. `/skill <name> [args]` 명령어 추가 (#521).
- **런타임 스킬 9종** — deep-researcher, daily-briefing, job-hunter, arxiv-digest, youtube-planner, slack-digest, expense-tracker, pr-reviewer, weekly-retro.
- **워크플로우 Step 7 Rebuild & Restart** — main 머지 후 CLI/serve 재빌드를 필수 단계로 명시.
- **Playwright MCP** — config.toml + Claude Code MCP 활성화.

### Fixed
- **스케줄 잡 중복 생성 방지** — `add_job()` dedup: 동일 schedule+action의 enabled 잡 거부.
- **좀비 MCP subprocess** — isolated 세션이 singleton MCPServerManager 재사용으로 새 subprocess 미스폰.
- **RLIMIT_NPROC fork 실패** — macOS에서 사용자 전체 프로세스 한도 64 설정 제거. CPU/FSIZE 유지.
- **IsolatedRunner._results 메모리 누적** — MAX_RESULTS_CACHE=200 oldest eviction.
- **_announce_queue 세션 종료 정리** — `cleanup_announce_queue()` + `mark_session_completed()` 호출.
- **_run_records 누적** — max 200 eviction.
- **스케줄 잡 action 필수화** — tool_handler에서 action 없이 create 시 에러 반환. 도구 스키마 영어 전환.
- **predefined 잡 자동 등록 제거** — action/callback 없는 게임 IP 전용 잡 8개 매 serve 재시작 시 재등록 차단.
- **Skills 0 표시 생략** — 런타임 스킬 미등록 시 불필요한 혼동 방지.
- **Scheduler/Gateway에 cost_budget + time_budget + hooks 전파** — REPL과 동일 자원 공유.
- **brave-search config.toml 잔류 제거** — v0.31.0 삭제 후 config 미정리.

### Architecture
- **유저 데이터 경로 이동** — session/snapshot/journal/result_cache/transcript를 `{project}/.geode/` → `~/.geode/projects/{slug}/`로 이동. Claude Code/Codex CLI 패턴 정합. 프로젝트 git 오염 방지.

---

## [0.32.1] — 2026-03-29

### Added
- **스케줄 잡 비동기 실행** — REPL drain loop의 isolated 스케줄 잡을 `IsolatedRunner.run_async()`로 전환. 메인 REPL 스레드 블로킹 해소. OpenClaw agentTurn 패턴: 데몬 스레드에서 fresh AgenticLoop 실행, 완료 시 dim 상태줄 콜백 (#519).

### Fixed
- **create_plan goal 경로 UnboundLocalError** — `goal` 파라미터로 범용 계획 생성 시 `template` 변수 미할당 수정 (#515).
- **Scheduler WHEN/WHAT 분리** — NL parser가 `action=original_text`(스케줄 표현식)로 설정 → `action=""`으로 수정. `schedule_job` 도구에 `action` 파라미터 추가. "every monday at 9:00" → AT(1회성) 파싱 → CRON(weekly) 수정. tool handler 이중 파싱 버그 수정 (#516).
- **delegate_task 이중 컨텍스트 주입 제거** — tool_result(전체) + announce(500자 요약) 이중 주입 → `delegate(announce=False)` 파라미터로 동기 호출 시 announce 비활성화. 비동기 경로는 유지 (#517).
- **schedule_job handler quiet mode** — `console.print` 제거로 quiet/isolated 세션에서 UI 오염 방지 (#518).
- **isolated 스케줄 잡 HITL 블로킹** — `hitl_level=0` 추가로 무인 실행 시 MCP/WRITE/EXPENSIVE 도구 승인 프롬프트 억제.
- **MODEL_SWITCHED HookEvent 중복 정의** — main-develop 머지 잔류 제거.

---
## [0.32.0] — 2026-03-28

### Added
- **MODEL_SWITCHED hook** --- `HookEvent.MODEL_SWITCHED` 추가 (45 -> 46). `AgenticLoop.update_model()` 발화, `bootstrap.py`에 `model_switch_logger` 핸들러 등록.
- **Filesystem hook plugin auto-discovery** --- `bootstrap.py`에서 `.geode/hooks/` + `core/hooks/plugins/` 자동 스캔 및 등록. `HookPluginLoader`를 부트스트랩에 통합.
- **README docs-sync** --- 도구(52), Hook(46) 수치를 실측값으로 갱신.
- **Autonomous safety 3조건** — (1) 비용 상한 자동 정지: 세션 비용 budget 초과 시 루프 중단 (Karpathy P3). (2) 런타임 래칫: 동일 에러 3회 수렴 감지 시 모델 에스컬레이션 후 재시도 (Karpathy P4). (3) 다양성 강제: 동일 도구 5회 연속 호출 시 다른 접근 유도 힌트 주입.
- **Plan-first 프롬프트 가이드** — 복잡한 요청(3+ 스텝, 고비용)에 대해 LLM이 자발적으로 `create_plan` 호출 후 사용자 승인 대기. Claude Code 패턴.
- **Plan HITL UI 보강** — 계획 표시 시 승인/수정/거부 안내 표시. plan_id 노출.
- **Provider-aware context compaction** — 장시간 운용을 위한 프로바이더별 컨텍스트 관리. Anthropic: 서버사이드 compaction(`compact_20260112`) + `clear_tool_uses` 결합. OpenAI/GLM: 80%에서 LLM 요약 기반 클라이언트 compaction 발동. `context_action.py` hook이 프로바이더별 전략을 분화.

---
## [0.31.0] — 2026-03-28

### Added
- **Action Summary (Tier 1)** --- AgenticLoop 턴 종료 시 개별 도구 호출 + 결과를 결정론적으로 요약 표시. `AgenticResult.summary` 필드에 저장. 토큰 비용 0.
- **Gateway binding hot-reload** --- `ConfigWatcher` watches `.geode/config.toml` and reloads `ChannelManager` bindings on file change (OpenClaw hot-reload pattern). No restart required.
- **L4 webhook endpoint** --- `geode serve` optionally starts an HTTP POST endpoint (`/webhook`, default port 8765) that triggers AgenticLoop execution from external systems (OpenClaw L4 Gateway Hooks pattern). Controlled by `GEODE_WEBHOOK_ENABLED` / `GEODE_WEBHOOK_PORT` settings.
- **TOOL_APPROVAL hooks** --- `TOOL_APPROVAL_REQUESTED`, `TOOL_APPROVAL_GRANTED`, `TOOL_APPROVAL_DENIED` 3종 HookEvent 추가 (42 -> 45). HITL 승인/거부/Always 패턴 추적. `ToolExecutor`에 hooks 주입, `bootstrap.py`에 `approval_tracker`/`denial_logger` 핸들러 등록.

### Fixed
- **TOOL_APPROVAL 이벤트명 불일치 수정** — `tool_approval_decided` → `tool_approval_granted`/`tool_approval_denied` 분리. 이전 코드에서 `_emit_hook("tool_approval_decided")`가 HookEvent에 없어 ValueError 삼킴 → 실제 발화 안 되는 버그 해소.
- **LLM_CALL_START / LLM_CALL_END hooks** — LLM 호출 전후 발화로 model-level latency/cost observability 제공. `call_llm()`, `call_llm_with_tools()` 계측. 10초 초과 시 slow call 경고 로깅. Hook 42개.
- **SESSION_START / SESSION_END hooks** — REPL 세션 시작/종료 시 발화 (OpenClaw `agent:bootstrap` 패턴).
- **CONTEXT_OVERFLOW_ACTION hook** — 압축 전략을 Hook 핸들러가 결정. `trigger_with_result()`로 핸들러 반환값 피드백. `context_action.py` 기본 핸들러 제공.
- **Scheduler action queue** — `ScheduledJob.action` 필드 추가. 원문 텍스트를 그대로 저장(정규식 추출 제거). `SchedulerService`가 job 발화 시 `action_queue`에 삽입. REPL이 `[scheduled-job:{id}]` 프레이밍으로 AgenticLoop에 위임 — LLM이 자체 판단으로 스케줄 의도를 분리하여 실행.
- **Cron 세션 격리** — `ScheduledJob.isolated` 필드 추가 (기본값 `True`). OpenClaw `agentTurn` 패턴: 스케줄 발화 시 fresh ConversationContext + AgenticLoop에서 독립 실행하여 메인 대화 오염 방지. `isolated=False`(systemEvent)로 메인 세션 주입도 가능.
- **TURN_COMPLETE 자동 메모리** — 37번째 HookEvent. AgenticLoop 매 턴 종료 시 발화, user_input + tool_calls + result 데이터 전달. `turn_auto_memory` 핸들러가 자동으로 project memory에 턴 요약 기록 (OpenClaw `command:new` 패턴).
- **OpenAI Responses API 전환** — `OpenAIAgenticAdapter`를 Chat Completions → Responses API(`client.responses.create`)로 마이그레이션. 네이티브 `web_search` 호스티드 도구 주입. `normalize_openai_responses()` 정규화기 추가.
- **3사 네이티브 웹 검색 fallback** — `GeneralWebSearchTool`/`WebSearchTool`을 Anthropic(Opus) → OpenAI(gpt-5.4) → GLM(glm-5) 순차 fallback으로 전환. 외부 API 키 의존 제로.

### Removed
- **Brave Search MCP 제거** — `brave_adapter.py` 삭제, catalog/registry/mcp_servers.json에서 brave-search 항목 제거. 3사 네이티브 웹 검색으로 대체.
- **Twitter MCP 카탈로그 제거** — $200/월 무료한도 없는 서비스 비추천 → 삭제.

### Infrastructure
- **`openai>=2.26.0`** + **`openai-agents>=0.13.0`** 의존성 추가 (Responses API 지원).

### Architecture
- **ContextVar DI 정리** — 불필요한 ContextVar 8개 제거. 단일 소비자·동일 파일 내 접근인 경우 module-level 변수로 교체. dead code `_llm_text_ctx` 완전 삭제. `set_*/get_*` API 유지로 호출부 변경 없음.
- **`core/fixtures/` 삭제** — 중복 fixture 디렉터리 제거. 소비자 2곳(`core/memory/organization.py`, `core/verification/calibration.py`) import 경로를 `core.domains.game_ip.fixtures`로 갱신. `tests/test_calibration.py` 경로 동기화.
- **Scaffold skills 경로 분리** — `.geode/skills/` 내 Scaffold 21종(SKILL.md 기반)을 `.claude/skills/`로 이동. Runtime skills(`geode-analysts/` 4종) 는 `.geode/skills/`에 유지. CLAUDE.md 경로 갱신.
- **`core/hooks/` 신설** — HookSystem/HookEvent/HookResult + HookPluginLoader + plugins/를 `core/orchestration/`에서 분리. Cross-cutting concern이므로 별도 최상위 모듈로. 26개 소비자 `from core.hooks import HookSystem` 경로 통일. L0~L4가 L3(orchestration)에 의존하던 레이어 위반 해소.
- **single-impl Protocol 제거** — `core/memory/port.py`에서 구현체가 하나뿐인 `ProjectMemoryPort`, `OrganizationMemoryPort`, `UserProfilePort` 삭제. 소비자(runtime.py, context.py, memory_tools.py, profile_tools.py)가 구체 타입(`ProjectMemory`, `MonoLakeOrganizationMemory`, `FileBasedUserProfile`)을 직접 참조. `SessionStorePort`는 다중 구현체(`InMemorySessionStore`, `HybridSessionStore`)가 있으므로 유지.
- **`calendar_bridge.py` 이동** — `core/orchestration/calendar_bridge.py` → `core/automation/calendar_bridge.py`. 스케줄러↔캘린더 동기화는 automation concern.
- **`GeodeRuntime.create()` 분해** — 243줄 팩토리 메서드를 4개 named sub-builder로 분리: `_build_session_store()`, `_build_llm_adapters()`, `_build_config_watcher()`, `_build_plugins()`. create() 70줄로 축소. 파일 1488 → 1477줄.
- **`runtime.py` 5-module 분해** — 1476줄 → 517줄. OpenClaw 플러그인 패턴으로 `core/runtime_wiring/` 4개 모듈 추출: `bootstrap.py`(345줄, hooks/memory/session/config), `infra.py`(228줄, policies/tools/LLM/auth/lanes), `automation.py`(261줄, L4.5 9 components + hook wiring), `adapters.py`(243줄, MCP signal/notification/calendar/gateway). GeodeRuntime 클래스 + dataclass + instance methods만 runtime.py에 잔류. 기존 import 경로 backward compat 유지.

---

## [0.30.0] — 2026-03-27

MCP 카탈로그 단일화 + Proxy Cleanup — registry 삭제 + catalog 축소 + config.toml 통합 + backward-compat stub 제거.

### Architecture
- **`core/agent/adapters/` 삭제** — ClaudeAgenticAdapter/OpenAIAgenticAdapter/GlmAgenticAdapter를 각 provider 파일로 통합. `resolve_agentic_adapter`를 `core.llm.router`로 이동. 모듈 수 195 → 187.
- **`infrastructure/ports/` 삭제** — 8개 Protocol 포트를 주 소비자 모듈 옆으로 co-locate 이동. `infrastructure/` 디렉터리 제거. ~52개 import 경로 갱신.
- **MCPRegistry 삭제** — registry.py(257줄) 제거, MCPServerManager.load_config()가 직접 처리
- **Catalog 검색 전용 축소** — MCPCatalogEntry: package/command/extra_args → install_hint 단일 필드로 통합
- **config.toml 통합** — .geode/config.toml [mcp.servers] 섹션이 MCP 설정 주소 (mcp_servers.json은 fallback 유지)
- **Proxy stub 삭제** — `core/cli/*.pyi` 6개, `infrastructure/ports/*.pyi` 3개, `infrastructure/adapters/llm/` 8개, `ports/{llm_port,agentic_llm_port}.py` 삭제. 소비자 0 확인 후 제거.
- **`core/utils/atomic_io.py`** — `infrastructure/atomic_io.py`를 canonical 위치로 이동. 9개 소비자 갱신.
- **`core/mcp/signal_adapter.py`** — `infrastructure/adapters/signal_adapter.py`를 MCP 레이어로 이동.

### Added
- `MCPServerManager.get_status()` — MCP 상태 조회 (registry.get_mcp_status() 흡수)
- `MCPServerManager._load_dotenv_cache()` — dotenv 캐시 초기화 헬퍼

### Removed
- `core/mcp/registry.py` — MCPRegistry, MCPServerConfig, DEFAULT_SERVERS, AUTO_DISCOVER_SERVERS 삭제
- MCP 자동 발견(env var 기반 auto-discovery) 제거 — 명시적 config.toml 등록으로 대체

### Changed
- `MCPCatalogEntry`: package/command/extra_args → install_hint(str) + env_keys 유지
- `install_mcp_server` 핸들러: install_hint 파싱으로 command/args 도출
- fetch(E404), google-trends(E404) 카탈로그에서 제거

## [0.29.1] — 2026-03-26

Action Display — tool-type 그루핑 + 서브에이전트 progressive counter + 턴 끝 컴팩트 요약.

### Added
- **Action Display** — tool-type 그루핑 (6건+ 동일 타입 그룹 요약), 서브에이전트 progressive counter, 턴 끝 컴팩트 요약
- **OperationLogger** — `_tool_type_counts` 추적 + `finalize()` 그룹 렌더링
- **render_turn_summary()** — rounds · tools · elapsed · cost 한 줄 요약
- **render_subagent_progress()** — completed/total 카운터

## [0.29.0] — 2026-03-26

F안 LLM 분할 + Native Tools + Context Persistence — client.py 1182줄을 Provider Module 패턴으로 분할하고, 3사 네이티브 도구를 통합하고, 프로필 영속성을 보장.

### Added
- **LLM Provider Module** — `core/llm/router.py` + `core/llm/providers/{anthropic,openai,glm}.py` + `core/llm/fallback.py` 분할
- **Anthropic 네이티브 도구** — `web_search_20260209` + `web_fetch_20260209` 자동 주입
- **GLM-5 네이티브 web_search** — 무료 도구 패스스루
- **Agentic adapter 이동** — `core/agent/adapters/` (claude/openai/glm + registry)
- **프로필 영속성** — `geode init` 시 글로벌→프로젝트 자동 시딩 + 로드 상태 표시 + 경고 로그

### Changed
- **client.py 1182줄 → router.py + providers/ 분할** (Provider Module 패턴)
- **infrastructure/adapters/llm/ → core/agent/adapters/ 이동** (agentic) + **core/llm/providers/** (client)
- **BillingError/UserCancelledError → core/llm/errors.py 이동**

### Removed
- **Proxy 47파일 삭제** — cli/extensibility/auth/mcp re-export shims (-710줄)
- **core/nodes/ 빈 디렉토리 삭제**

### Fixed
- **Native tools 테스트** — import 경로 `core.agent.adapters/` 갱신
- **OpenAI adapter** — Responses API TODO 문서화

## [0.28.1] — 2026-03-26

파이프라인 모델 고정 — Analyst/Evaluator/Synthesizer가 유저 REPL 모델을 상속하던 버그 수정.

### Fixed
- **파이프라인 모델 고정** — Analyst/Evaluator/Synthesizer가 유저 REPL 모델(glm-5)을 상속하던 버그 수정. `_PIPELINE_NODE_DEFAULTS`로 `claude-opus-4-6` 고정
- **Tool-augmented LLM paths model= 명시** — analysts/evaluators/synthesizer의 tool-augmented LLM 경로에 `model=` 파라미터 명시 추가

### Added
- **파이프라인 실행 전 유저 안내** — `pipeline_notice` 필드 + `definitions.json` 비용 안내

## [0.28.0] — 2026-03-26

GLM-5 파이프라인 라우팅 수정 + Status line per-turn 리셋 + Signal Tools MCP 라이브 연동.

### Added
- **Signal Tools MCP Live Integration** — 5개 signal stub 도구를 MCP-first + fixture fallback 패턴으로 전환. YouTube(youtube MCP), Reddit(reddit MCP), Twitch(igdb MCP), Steam(steam MCP), Google Trends(google-trends MCP) 서버 연동. `source` 필드로 데이터 출처 추적 (`*_mcp_live` / `*_api_stub`).
- **MCP DEFAULT_SERVERS 확장** — reddit, google-trends를 키 불필요 기본 서버로 등록. youtube-transcript 카탈로그 항목 추가.
- **Signal MCP 테스트 28건** — MCP 라이브 경로, fixture 폴백, 에러 핸들링 검증.
- **Provider-aware LLM routing** — `_get_provider_client()`, `_retry_provider_aware()` — per-provider circuit breaker
- **TokenTracker snapshot/delta** — `UsageSnapshot` + `snapshot()`/`delta_since()` — per-turn 메트릭 계산
- **SessionMeter per-turn** — `mark_turn_start()` + `turn_elapsed_s` — 턴 단위 시간 측정

### Fixed
- **GLM-5 파이프라인 라우팅** — `call_llm_parsed`/`call_llm`/`call_llm_with_tools`가 항상 Anthropic API로 라우팅되던 버그 수정. `_resolve_provider()` 기반 자동 분기
- **Status line per-turn** — 세션 누적(elapsed/tokens/cost/context%) → per-turn 델타 표시

## [0.27.1] — 2026-03-26

모델 스위칭 컨텍스트 가드 — Opus→GLM-5 전환 시 overflow 방지.

### Added
- **모델 스위칭 선제적 적응** — `update_model()` 시 Phase 1(도구 결과 요약) + Phase 2(토큰 기반 adaptive prune) 자동 실행
- **`summarize_tool_results()`** — tool_result 중 5% 초과분을 `[summarized]`로 대체
- **`adaptive_prune()`** — 예산(70%) 내에서 최신 메시지 우선 유지하는 토큰 기반 pruning

### Fixed
- **`usage_pct` 100% 캡 제거** — 240%와 95%는 심각도가 다르므로 실제값 유지

## [0.27.0] — 2026-03-26

GLM-5 컨텍스트 방어 + Gateway 리소스 공유 + UI 스피너 정돈.

### Added
- **GLM-5 컨텍스트 오버플로우 방어** — 모델별 동적 tool result 가드 (max_chars 자동 산출, 컨텍스트 80K 이하 모델 보호)
- **Gateway 리소스 공유** — env cascade + 글로벌 메모리 fallback + User Context 주입 (Slack/Gateway 경로에서 .geode 리소스 접근)

### Fixed
- **서브에이전트 UI 스피너** — 병렬 실행 시 Thinking 스피너 과다 출력 정돈 (stdout isatty 가드 + suppress 컨텍스트)

## [0.26.0] — 2026-03-25

코드 품질 전면 개선 — Thread Safety, Error Handling, DRY, ToolCallProcessor 추출.

### Fixed
- **Thread safety** — HookSystem/ResultCache/Stats Lock 추가 (race condition 방지)
- **Error handling** — synthesizer KeyError 방어, MemoryTools 경고 로그, scoring 가중치 검증
- **DRY** — OpenAI retry_with_backoff_generic 통합 (openai_adapter -63줄)
- **Resource** — httpx client lifecycle 관리 (reset_client close 추가)
- **DAG** — 순환 의존 무성 실행 → strict 모드 ValueError
- **REPL** — detect_api_key + dry-run regex 가로채기 제거 (이메일/간단히 오탐 방지)
- **Flaky test** — SnapshotManager 테스트 격리 (tmp_path)
- **is_glm_key 강화** — @/비ASCII/숫자 필수 조건

### Removed
- **MCP deprecated shims** (base.py, manager.py) 삭제
- **REPL detect_api_key** 자동 감지 (LLM set_api_key 도구로 대체)
- **_text_requests_dry_run** regex (LLM dry_run 파라미터로 대체)

### Changed
- **AgenticLoop → ToolCallProcessor 추출** (agentic_loop -477줄)
- **BillingError** — retry_with_backoff_generic에서 통합 raise

## [0.25.1] — 2026-03-25

MCP REPL 프롬프트 지연 해소.

### Fixed
- **MCP lazy parallel 연결** — `get_all_tools()` 최초 호출 시 `_connect_all()`(ThreadPoolExecutor) 병렬 연결 선행. 기존 10서버 순차 ~100s → 병렬 ~15s

## [0.25.0] — 2026-03-25

메모리 계층 4-tier 시스템 프롬프트 주입 + MCP 부트스트랩 수정.

### Added
- **메모리 계층 시스템 프롬프트** — GEODE.md(G1 정체성) + MEMORY.md(G2 메모리) + LEARNING.md(G3 학습) + 도메인(G4)을 `system_prompt.py`에서 자동 조립하여 LLM에 주입

### Fixed
- **MCP 부트스트랩 경로** — 외부 디렉토리에서 `geode` 실행 시 MCP 서버 0개 로딩되던 이슈 수정 (`load_config` 추가 + 경로 산출 보정)

## [0.24.2] — 2026-03-25

Skills 경로 `.claude/skills` → `.geode/skills` 마이그레이션.

### Fixed
- **Skills 경로 마이그레이션** — `.claude/skills/` 28개 스킬 → `.geode/skills/` 이동 + `skills.py`/`skill_registry.py`/`commands.py` 잔류 참조 4건 수정
- **CWD 독립 해석** — `__file__` 기준 패키지 루트 산출으로 워킹디렉토리 무관하게 스킬 로딩

## [0.24.1] — 2026-03-25

메모리 경로 표시 수정.

### Fixed
- **Startup readiness 메시지** — `.claude/MEMORY.md not found` → `.geode/memory/PROJECT.md not found` (실제 참조 경로와 일치)
- **memory_tools 도구 설명** — rule_create/update/delete/list 5곳의 `.claude/rules/` → `.geode/rules/` 수정

## [0.24.0] — 2026-03-22

Slack Gateway 양방향 소통 + MCPServerManager 싱글턴 + GLM/Failover 안정화.

### Added
- **`geode serve`** 커맨드 — headless Gateway 데몬 모드. REPL 없이 Slack 폴링만 백그라운드 실행 (`nohup geode serve &`)
- **MCPServerManager 싱글턴** — `get_mcp_manager()` 팩토리. 4곳(signal/notification/calendar/gateway)에서 동일 인스턴스 공유, 좀비 MCP 프로세스 근절
- **MCP 병렬 연결** — `_connect_all()` ThreadPoolExecutor 병렬화. 순차 11×10s(110s) → 병렬 ~15s
- **Context Overflow 방지** — `max_tool_result_tokens` 기본 4000 활성화, CRITICAL 시 tool_result 2000자 절삭, `compact_keep_recent` 설정 노출
- **System Prompt 날짜 주입** — `_build_date_context()`로 현재 날짜/연도를 시스템 프롬프트에 동적 주입. LLM knowledge cutoff 연도 오류 방지
- **Gateway System Suffix** — `AgenticLoop`에 `system_suffix` 파라미터 추가. Gateway 모드 전용 시스템 프롬프트 확장
- **@멘션 전용 응답 게이트** — `_is_mentioned()`에 Slack `<@U...>` 포맷 감지 + `_strip_mentions()`로 멘션 태그 정리 + `require_mention=true` 활성화

### Fixed
- **switch_model 퍼지 매칭** — 하이픈/공백/언더스코어 정규화. "GLM5"→`glm-5`, "gpt5"→`gpt-5.4` 등 자연어 힌트 인식
- **Slack 메시지 에코 제거** — Gateway 응답 시 사용자 메시지를 4회 반복 출력하던 문제. `_GATEWAY_SUFFIX`로 에코/반복 금지 지시 주입
- **웹 검색 연도 오류** — `GeneralWebSearchTool` description + 검색 쿼리에 현재 날짜 동적 반영
- **Slack 처리 중 인디케이터** — `_set_reaction()`으로 모래시계 리액션 표시/제거
- **Gateway 양방향 소통** — SlackPoller가 유저 메시지를 수신하지만 응답을 보내지 못하던 5건 수정: 로깅 설정, oldest ts seeding(중복 방지), 메시지별 독립 AgenticLoop, 에러 가시성(debug→warning)
- **Slack MCP tool 이름 정합성** — `get_channel_history` → `slack_get_channel_history`, `send_message` → `slack_post_message`, `channel` → `channel_id` 파라미터명
- **NotificationAdapter kwargs 전달** — 3채널(Slack/Discord/Telegram) `**kwargs`(thread_ts 등) MCP call args에 포함 + `_parse_mcp_result()` content wrapper 파싱
- **GLM base URL** — `api.z.ai/v1` → `open.bigmodel.cn/api/paas/v4/` (nginx 404 해소)
- **httpx keepalive** — 15s → 30s (APIConnectionError 빈도 감소)
- **Failover 로그 노이즈** — retry/fallback 로그 warning→debug/info (유저 콘솔 노출 방지)
- **LLM timeout** — OpenAI/GLM 90s → 120s (ZhipuAI 응답 지연 대응)
- **MCP startup 로그** — warning→debug (서버 연결 실패 메시지 유저 불가시)
- **MCP 테스트 격리** — global .env Path.home() mock으로 환경 독립성 확보

### Infrastructure
- Modules: 184
- Tests: 3055

---

## [0.23.0] — 2026-03-22

P1 Gateway 어댑터 패턴 — 멀티프로바이더 LLM 안정화.

### Architecture
- **P1 Gateway Adapter Pattern** — AgenticLoop 인라인 프로바이더 코드를 `AgenticLLMPort` Protocol + 3개 어댑터(Claude/OpenAI/GLM)로 분리. `agentic_loop.py` 1720→1378줄 (-342줄)
- **Adapter Registry** — `resolve_agentic_adapter()` 동적 임포트. 프로바이더 추가 시 단일 파일로 해결
- **Cross-provider Fallback** — GLM→OpenAI→Anthropic 다단 페일오버 (기존 GLM→OpenAI만)

### Added
- **System Prompt 날짜 주입** — `_build_date_context()`로 현재 날짜/연도를 시스템 프롬프트에 동적 주입. LLM knowledge cutoff(2025)로 인한 검색 연도 오류 방지
- **Gateway System Suffix** — `AgenticLoop`에 `system_suffix` 파라미터 추가. Gateway 모드에서 채널별 시스템 프롬프트 확장 가능

### Fixed
- **Slack Gateway 메시지 에코 제거** — Slack 응답 시 사용자 메시지를 4회 반복 출력하던 문제. `_GATEWAY_SUFFIX`로 에코/반복 금지 지시 주입
- **웹 검색 연도 오류** — `GeneralWebSearchTool` description + 검색 쿼리에 현재 날짜 동적 반영
- **Slack 처리 중 인디케이터** — `_set_reaction()`으로 모래시계 리액션 표시/제거
- GLM Round 2+ `messages[].content[0].type类型错误` — Anthropic→OpenAI 메시지 포맷 변환 누락
- KeyboardInterrupt가 모델 에스컬레이션을 트리거하던 문제 — `UserCancelledError` 분리
- OpenAI/GLM httpx 커넥션 풀 미설정 — Anthropic과 동일 설정 (20conn, 30s keepalive) 적용
- GLM CircuitBreaker 부재 — OpenAI 어댑터에서 상속

### Infrastructure
- Tests: 3058 → 3055 (테스트 리팩토링, 커버리지 동등)
- Modules: 179 → 184 (+5, 어댑터 + 포트 + 레지스트리)

---

## [0.22.0] — 2026-03-21

Sandbox Hardening + REODE 자율 운행 하네스 패턴 역수입 + 품질 스킬 포팅.

### Added

#### Sandbox Hardening
- PolicyChain L1-2 와이어링 — `load_profile_policy()` + `load_org_policy()` → `build_6layer_chain()`으로 Profile/Org/Mode 통합 체인 구성
- SubAgent Tool Scope — `denied_tools` 파라미터 + `SUBAGENT_DENIED_TOOLS` 상수 (6개 민감 도구 서브에이전트 접근 차단)
- Bash Resource Limits — `preexec_fn`으로 `resource.setrlimit` 적용 (CPU 30s, FSIZE 50MB, NPROC 64)
- Secret Redaction — `core/cli/redaction.py` 신규, 8개 API 키 패턴(Anthropic/OpenAI/ZhipuAI/GitHub/Slack) 감지 및 마스킹, BashTool + MCP tool result에 자동 적용

#### Harness Patterns (REODE 역수입)
- Session-level tool approval (A=Always) — HITL 프롬프트에 `[Y/n/A]` 옵션, 세션 동안 카테고리별 자동 승인
- HITL Level (0/1/2) — `GEODE_HITL_LEVEL` 환경변수 (0=자율, 1=WRITE만 묻기, 2=전부 묻기)
- Model Escalation — LLM 연속 2회 실패 시 fallback chain 다음 모델 자동 전환
- Cross-Provider Escalation — provider chain 소진 시 secondary provider로 자동 전환 (anthropic↔openai, glm→openai)
- Backpressure — tool 연속 3회 에러 시 1s 쿨다운 + "다른 접근 고려" 힌트 주입
- Convergence Detection — 동일 에러 4회 반복 → `convergence_detected`로 루프 자동 중단
- Model-first Provider Inference — `_resolve_provider()` 강화 (gpt/o3/o4→openai, gemini→google, deepseek→deepseek, llama→meta, qwen→alibaba)

#### Skills (REODE 역수입)
- `explore-reason-act` — 코드 수정 전 탐색-추론-실행 3단계 워크플로우
- `anti-deception-checklist` — 가짜 성공 방지 5-check 검증
- `code-review-quality` — Python 6-렌즈 코드 품질 리뷰
- `dependency-review` — GEODE 6-Layer 의존성 건전성 리뷰
- `kent-beck-review` — Simple Design 4규칙 코드 리뷰

### Infrastructure
- Tests: 2946 → 3058 (+112)
- Modules: 178 → 179 (+1, `core/cli/redaction.py`)
- Skills: 18 → 25 (+7)

---

## [0.21.0] — 2026-03-19

GAP 7건 해소 — 모델 거버넌스 + 노드 라우팅 + 세션 관리 + 컨텍스트 압축.

### Added
- Model Policy (`.geode/model-policy.toml`) — allowlist/denylist 기반 모델 거버넌스, `call_with_failover()` / `_retry_with_backoff()` 정책 필터 통합
- Routing Config (`.geode/routing.toml`) — 파이프라인 노드별 LLM 모델 라우팅 (`get_node_model()`), analysts/evaluators/synthesizer에 `model=` 전달
- SessionManager + SQLite — `core/memory/session_manager.py` 신규 (WAL 모드, `idx_sessions_updated` 인덱스), `SessionCheckpoint.save()` 자동 동기화
- `/resume` CLI 커맨드 — 중단된 세션 목록 표시 + 복원, REPL 시작 시 활성 세션 자동 탐지
- AgentMemoryStore — `core/memory/agent_memory.py` 신규, 서브에이전트별 task_id 격리 메모리 (파일 스코프 + 24h TTL)
- Context Compaction — `core/orchestration/context_compactor.py` 신규, WARNING(80%) 시 Haiku 기반 LLM 요약 압축, CRITICAL(95%) 시 기존 prune fallback

---

## [0.20.0] — 2026-03-19

Multi-Provider LLM (3사 failover) + .geode Context Hub (5-Layer) + CANNOT 워크플로우 고도화.

### Added
- IP 보고서 상세 섹션 보강 — Analyst Reasoning, Cross-LLM Verification, Rights Risk, Decision Tree Classification 4개 섹션 추가
- 보고서 하위 섹션 — Scoring Breakdown, BiasBuster, Signals, PSM Engine, Evidence Chain, Axis Breakdown
- `.env` 자동 생성 — `.env.example` 기반 atomic write (tmp+rename, chmod 0o600), placeholder 자동 제거
- `/model` 전환 시 프로바이더 키 검증 — 해당 프로바이더 API 키 미설정 시 경고 표시
- Multi-Provider LLM — ZhipuAI GLM-5 (glm-5, glm-5-turbo, glm-4.7-flash) 프로바이더 추가, OpenAI-compatible API 활용
- `.env` Setup Wizard — .env 미존재 시 대화형 API 키 입력 (Anthropic/OpenAI/ZhipuAI, Enter 스킵, Ctrl+C 중단)
- 자연어 API 키 탐지 — REPL 자유 텍스트에 `sk-ant-*`, `sk-*`, `{hex}.{hex}` 패턴 감지 → 자동 키 등록, LLM 전송 방지
- `/key glm <value>` 서브커맨드 + GLM 키 자동 탐지 (`{id}.{secret}` 패턴)
- `_resolve_provider()` 헬퍼 — 모델 ID → 프로바이더 자동 판별 (claude-* → anthropic, glm-* → glm, 그 외 → openai)
- MODEL_PROFILES에 GLM-5, GLM-5 Turbo, GLM-4.7 Flash 추가

### Fixed
- `.env` 파일 보안 — atomic write (tmp+rename) + chmod 0o600 파일 권한 제한
- placeholder 검증 로직 통일 — `_is_placeholder()` 단일 소스로 `_has_any_llm_key()`/`_check_provider_key()` 일관성 확보
- AgenticLoop 모델 캐싱 버그 — `/model` 변경이 `_call_llm()`에 반영되지 않던 문제 수정 (`update_model()` 메서드 추가)
- `check_readiness()` ANY 프로바이더 키 unblock — Anthropic 키 없어도 OpenAI/GLM 키만으로 전체 모드 동작

### Changed
- check_readiness/key_registration_gate 멀티 프로바이더 지원 — 3사 키 상태 표시 및 ANY 키 unblock
- LLM 모델 가격/context window 최신화 (2026-03-19 검증) — gpt-4.1 $2.00/$8.00, o4-mini $1.10/$4.40, claude-opus-4-6 1M ctx 등
- ANTHROPIC_SECONDARY를 `claude-sonnet-4-6` (1M ctx)으로 갱신
- GLM adapter 독립 분리 (`glm_adapter.py`) — 모델 계열별 adapter 확장 용이
- deprecated 모델 제거: gpt-4o, gpt-4o-mini, o3-mini, claude-haiku-3-5
- SubAgent에 부모 model/provider 상속 — GLM 모드에서 자식도 GLM 사용
- `/auth add`에 ZhipuAI 프로바이더 추가
- `_mask_key`/`_upsert_env`/`is_glm_key` 공유 헬퍼 추출 (`_helpers.py`) — DRY

- `.geode` Context Hub — 5-Layer 목적 중심 컨텍스트 계층 (C0 Identity → C1 Project → C2 Journal → C3 Session → C4 Plan)
- `ProjectJournal` (C2) — `.geode/journal/` append-only 실행 기록 (runs.jsonl, costs.jsonl, learned.md, errors.jsonl)
- Journal Hook 자동 기록 — PIPELINE_END/ERROR → runs.jsonl + learned.md 자동 침전
- `SessionCheckpoint` (C3) — `.geode/session/` 세션 체크포인트 저장/복원/정리 (72h auto-cleanup)
- `SessionTranscript` (Tier 1) — `.geode/journal/transcripts/` JSONL 이벤트 스트림 (대화, 도구, 비용, 에러 감사 추적)
- `Vault` (V0) — `.geode/vault/` 목적별 산출물 영속 저장소 (profile/research/applications/general), 자동 분류 + 버전 관리
- ContextAssembler C2 통합 — Journal 이력 + 학습 패턴 시스템 프롬프트 자동 주입
- `geode init` 5-Layer 디렉토리 — project/, journal/, session/, plan/, cache/ 생성
- Multi-Provider AgenticLoop — `AgenticResponse` 정규화 레이어 + Anthropic/OpenAI 이중 경로 (`_call_llm_anthropic`/`_call_llm_openai`)
- Write Fallback — WRITE 거부 시 도구별 대안 제안 메시지 (`_write_denial_with_fallback`)
- `agentic_response.py` (신규) — `normalize_anthropic()`, `normalize_openai()`, `AgenticResponse` 프로바이더 비종속 응답 모델
- Model Failover — `call_with_failover()` async 체인 + circuit breaker + per-model exponential backoff
- MCP Lifecycle — `MCPServerManager.startup()/shutdown()` + SIGTERM/atexit 이중방어 + PID 추적
- Sub-agent Announce — `drain_announced_results()` 큐 기반 비동기 결과 주입 (OpenClaw Spawn+Announce)
- Tiered Batch Approval — 5단계 안전등급 (SAFE→MCP→EXPENSIVE→WRITE→DANGEROUS) 분류 + 배치 비용 승인
- Context Overflow Detection — `check_context()` 80%/95% 임계값 + `prune_oldest_messages()` 비상 압축 (Karpathy P6)
- `/cost` 대시보드 — session/daily/recent/budget 서브커맨드 + 월 예산 설정 + Rich 프로그레스 바
- 6-Layer Policy Chain — ProfilePolicy(Layer 1) + OrgPolicy(Layer 2) + `build_6layer_chain()` (OpenClaw 패턴)
- `HookEvent.MCP_SERVER_STARTED` / `MCP_SERVER_STOPPED` — MCP 라이프사이클 이벤트 (34→36 중 32→34)
- `HookEvent.CONTEXT_WARNING` / `CONTEXT_CRITICAL` — Context Overflow 이벤트 (34→36)
- Stop Hook `check-progress.sh` — develop→main 격차 감지 추가 (블로그 §5.2 스펙)

### Changed
- 워크플로우 REODE 6건 이식: 3-Checkpoint 칸반, .owner 소유권 보호, main-only progress.md, Docs-Sync 2중 구조, PR Body 엄격 규칙, Backlog→Done 직행 금지

### Infrastructure
- Worktree 좀비 3건 + dangling 브랜치 40건 정리 (alloc/free 누수 해소)
- GAP Registry 전체 P1 해소 (gap-multi-provider 포함)

---

## [0.19.1] — 2026-03-18

NL Router 완전 제거, 워크플로우 리서치 + 검증팀 체계화.

### Changed
- NL Router 이중 라우팅 제거 — 모든 자유 텍스트 AgenticLoop 직행. ip_names.py, system_prompt.py 분리 추출
- README NL Router → AgenticLoop 표기 전환 + 도구 수 46개 반영

### Added
- `frontier-harness-research` 스킬 — Claude Code/Codex/OpenClaw/autoresearch 4종 비교 리서치 프로세스
- `verification-team` 스킬 — 4인 페르소나 검증 (Beck/Karpathy/Steinberger/Cherny)
- 워크플로우 Step 1d(리서치 검증) + Step 3v(구현 검증) 검증팀 병렬 배치
- tests/ per-file-ignores에 E501 추가
- `docs/progress.md` — 세션 진척/계획/GAP 기록

### Removed
- `core/cli/nl_router.py` — AgenticLoop 직행으로 불필요. ip_names.py, system_prompt.py로 분리 완료
- `tests/test_nl_router.py` — 1224줄 레거시 테스트 삭제
- `tests/test_report_cli.py` 내 NL Router 의존 테스트 (TestReportNLRouter 클래스)

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
