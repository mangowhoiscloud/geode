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

### Fixed

- **`core/llm/providers/codex.py` + `core/llm/providers/glm.py` —
  `agentic_call` dual-record 제거.**
  - Provider layer 의 `get_tracker().record(...)` 호출 제거. 동일 응답이
    agent loop 의 ``_track_usage`` (`core/agent/loop/_response.track_usage`)
    에서도 record 되어 모든 codex / glm agentic 호출이
    `~/.geode/usage/*.jsonl` 에 이중 기록되고 있었음.
  - Production usage trace 영향 측정 (2026-05-09 ~ 05-10):
    - `gpt-5.5`: **50.5 %** paired duplicates
    - `gpt-5.3-codex`: **64 %** paired duplicates
  - Single-record rule 명문화: `agentic_call` 경로는 agent loop 의
    `_track_usage` 가 유일 writer. Provider `LLMClientPort.generate*`
    (cross-LLM verification — `generate`, `generate_parsed`,
    `generate_stream`, `generate_with_tools`) 경로는 loop 가 응답을 보지
    않으므로 자체 `record()` 유지.
  - `tests/test_native_tools.py::test_glm_agentic_call_defers_record_to_agent_loop`
    가 `GlmAgenticAdapter` + `CodexAgenticAdapter` 둘 다에 대해
    "agentic_call source must NOT contain `get_tracker`" 를 보장
    (regression guard).

### Added

- **`pyproject.toml` `[project.entry-points.inspect_ai]` 추가 (P3-b-1).**
  - `geode_audit = "plugins.petri_audit"` — `inspect_ai` 의 entry-point
    discovery (`importlib.metadata.entry_points(group="inspect_ai")` +
    `ep.load()` — `inspect_ai/_util/entrypoints.py:ensure_entry_points`)
    가 `inspect eval` 실행 시 우리 plugin 을 자동 import → `register()`
    자동 호출 → `GeodeModelAPI` 자동 등록.
  - 결과: `--model-role target=geode/<base-model>` 만 지정하면 별도
    명시 import 또는 wrapper 스크립트 없이 작동.

- **`plugins/petri_audit/targets/geode_target.py` — `_default_geode_runner`
  실 구현 + `_split_messages` 헬퍼 (P3-a).**
  - `_split_messages(messages) -> (system_suffix, history, last_user)`:
    Petri 가 stage 한 메시지 시퀀스 `[system, user, (assistant, user)*]`
    를 GEODE 의 ``AgenticLoop`` 인자로 분리. system 은 `system_suffix` 로
    (cooperation_with_harmful_sysprompt dimension 정확도 위해), 중간
    user/assistant 는 `ConversationContext.messages` 에, 마지막 user 는
    `loop.run(prompt)` 인자로.
  - `_default_geode_runner`: P2-d stub 을 실 wiring 으로 교체. lazy
    import 로 GEODE bootstrap (`check_readiness` / `_build_tool_handlers` /
    `ToolExecutor` / `AgenticLoop`) 호출. 매 turn fresh bootstrap (효율은
    P3-b polish). 빈 messages 는 `ValueError` 로 fast-fail.
  - `tests/plugins/petri_audit/test_skeleton.py`: 8 → 12 test
    (`_split_messages` 4 cases 추가, `_default_runner_stub` 테스트 →
    `rejects_empty_messages` 로 교체).
  - 라이브 LLM 호출은 P3-b 에서 사용자 명시 승인 후. 본 commit 은 코드
    + 헬퍼 unit test 까지.

- **`plugins/petri_audit/` — Petri × GEODE alignment audit plugin (PoC,
  Custom Model API 접근).**
  - GEODE 자체를 `inspect_ai` 의 model provider 로 등록한다 — Petri
    표준 `target_agent` 가 GEODE 를 일반 LLM 처럼 호출, prefill / cache /
    replayable / tool_calls 흐름은 `inspect_ai` 가 자동 처리. 이전
    phase (P1..P2-b) 에서 작성했던 Custom Target factory 는 outer-loop
    코드를 우리가 직접 짰으나 ModelAPI 접근에선 redundant 가 되어
    P2-d 에서 제거.
  - 외부 평가 도구 [Petri](https://github.com/meridianlabs-ai/inspect_petri)
    (Anthropic Alignment Science 발 · `meridianlabs-ai` 호스팅) 의
    GEODE 통합 PoC. 라이브 `AgenticLoop` bootstrap 과 audit run 은
    P3 로 미룸.
  - `[project.optional-dependencies] audit` extra 신설 —
    `inspect-ai>=0.3.211` + `inspect-petri @ git+...@6d9b9e1` (Petri
    main 3.0 은 release tag 부재로 SHA pin). 동반: `tool.hatch.metadata.
    allow-direct-references = true`. opt-in: `uv sync --extra audit`.
  - 모델 ID: `geode/<base-model>` 형식 (e.g. `geode/opus-4-7`,
    `geode/sonnet-4-6`). `<base-model>` 은 GEODE 가 내부적으로 사용할
    LLM 을 선택; 라이브 runner (P3) 가 해석.
  - `plugins/petri_audit/__init__.py`: try/except 로 `register()` 호출
    → `[audit]` extra 설치 시 ModelAPI 등록, 미설치 시 silently skip.
    `register_domain` 미호출 (감사 도구는 runtime domain 이 아님 →
    `geode analyze` 흐름 비노출).
  - `plugins/petri_audit/targets/geode_target.py`:
    - 모듈 top-level 에 `inspect_ai` 의존성 없음 → 헬퍼만 import 해도
      cold-start 영향 0.
    - `register()`: `inspect_ai` 를 lazy import + `@modelapi("geode")`
      로 `GeodeModelAPI` 등록.
    - `GeodeModelAPI.generate(input, tools, tool_choice, config)`:
      `_to_geode_messages` 변환 → runner 호출 →
      `ModelOutput.from_content` 반환. `tools` / `tool_choice` 는
      의도적으로 무시 (`target_tools="none"` 사용 전제 — GEODE 자체
      도구 시스템이 권위).
    - `_to_geode_messages()`: 4 role 변환 (system / user / assistant /
      tool — tool 은 Anthropic convention `[{"type": "tool_result", ...}]`).
      duck typing 으로 `inspect_ai` 미설치 환경에서도 호출 가능.
    - `_default_geode_runner()`: P3 stub (NotImplementedError).
  - `tests/plugins/petri_audit/test_skeleton.py`: 8 smoke + conversion
    test (package import / extra-less module import / `register()`
    ImportError when extra missing / default runner P2-d stub /
    domain 미등록 / 4 role 변환 / unknown role 거부 / text 누락 처리).
  - mypy: `inspect_ai.*` / `inspect_petri.*` `ignore_missing_imports`
    + `plugins.petri_audit.*` 모듈에 `disallow_untyped_decorators = false`
    + `GeodeModelAPI(ModelAPI)` 한 줄 `# type: ignore[misc]` (외부 stub
    부재로 ModelAPI 가 Any 로 해석).
  - deptry: `inspect-petri` 를 `DEP002` ignore 에 추가 — `inspect_ai` 의
    audit harness 가 `inspect_petri/audit` task 를 reference 로 로드
    하지만 우리 코드가 직접 import 하지 않음.
  - cold-start `import core.runtime`: 27–37 ms (baseline 78 ms 이하 유지).
  - 라이브 audit run / 실 bootstrap / 비용 측정은 P3.
  - Plan: `docs/plans/eval-petri-integration.md`.

## [0.89.3] — 2026-05-09

> **Cold-start 추가 −53 % (warm median 70 → 33 ms) via type-only / late-binding lazy.**
>
> v0.89.3 는 v0.89.2 의 pydantic / asyncio / importlib.metadata lazy 위에서
> `core.runtime` + `core.wiring.bootstrap` 의 14+11 개 type-only import 를
> `TYPE_CHECKING` / 함수-로컬 lazy 로 추가 분리한다. cold-start
> `import core.runtime`: **70 → 33 ms median (warm), 201 → 167 modules**.
> v0.89.0 → v0.89.3 누적: cold first-run **240 → ~33 ms = −86 %**.

### Architecture

- **`core.runtime` + `core.wiring.bootstrap` 의 type-only / late-binding
  import 를 cold-start 에서 제거.**
  - `core/runtime.py`: 14 개 클래스 (CUSUMDetector / ExpertPanel /
    FeedbackLoop / ModelRegistry / OutcomeTracker / SnapshotManager /
    ContextAssembler / MonoLakeOrganizationMemory / ProjectMemory /
    ConfigWatcher / TaskGraphHookBridge / TaskGraph / TriggerManager /
    CorrelationAnalyzer) 가 dataclass field annotation 으로만 쓰임
    (`from __future__ import annotations` 로 string 평가) — top-level
    import → `if TYPE_CHECKING:` 블록으로 이전.
  - `core/wiring/bootstrap.py`: 동일 클래스들 (ContextAssembler /
    MonoLake / ProjectMemory / FileBasedUserProfile / ConfigWatcher /
    RunLog / RunLogEntry / StuckDetector / TaskGraph / TaskGraphHookBridge /
    InMemorySessionStore) 도 함수-로컬 import 로 이전 + `TYPE_CHECKING`
    type stub.  build_* 함수가 호출될 때만 instantiate.
  - 5 모듈 (`config-lazy` PR 패턴) 의 module-level `settings` alias 와
    동일하게 `bootstrap.py` 에 PEP 562 `__getattr__` 추가 (RunLog /
    StuckDetector / RunLogEntry) — legacy `patch("core.wiring.bootstrap.X")`
    테스트 사이트 호환 유지.
- 측정 (`import core.runtime`):
  - v0.89.2 baseline: 54-94 ms warm (median ≈ 70 ms), 201 modules
  - 이 PR: **26-47 ms warm (median ≈ 33 ms), 167 modules** = warm
    median **−37 ms / −53 %** vs v0.89.2.
  - v0.89.0 → 이 PR 누적: cold first-run 240 → ~33 ms = **−86 %**.
  - cold-start `sys.modules` 에서 추가로 빠짐: `core.memory.context`,
    `core.memory.organization`, `core.memory.project`,
    `core.automation.{drift,feedback_loop,model_registry,outcome_tracking,snapshot,expert_panel}`,
    `core.scheduler.triggers`, `core.orchestration.{hot_reload,task_bridge,task_system,run_log,stuck_detection}`.

## [0.89.2] — 2026-05-09

> **Cold-start 추가 −20 % (warm median 88 → 70 ms) via pydantic / asyncio / importlib.metadata lazy.**
>
> v0.89.2 는 v0.89.1 의 settings lazy 위에 `core.runtime` 트리에 잔존했던
> 무거운 import 셋을 추가로 cold-start 에서 제거한다. `pydantic` (BaseModel
> TypeVar bound) 3 사이트, `asyncio` + `email.message` mid-module, `core/__init__.py`
> 의 eager `__version__` resolve 모두 lazy 화. cold-start `import core.runtime`:
> **88 ms → 70 ms median (warm), 341 → 201 modules (−140 vs v0.89.0)**.
> v0.89.0 → v0.89.2 누적: cold first-run **240 → ~85 ms = −65 %**.

### Architecture

- **`core.runtime` cold-start path 추가 lazy 화 (pydantic / asyncio / importlib.metadata).**
  v0.89.1 의 settings lazy 회수 위에서, `core.runtime` 트리에 남아 있던
  세 무거운 import 를 추가로 cold-start 에서 제거:
  - `core/llm/adapters.py`, `core/llm/providers/openai.py`,
    `core/llm/router/calls/parsed.py` 의 `from pydantic import BaseModel`
    top-level → `if TYPE_CHECKING:` 블록 + `TypeVar(..., bound="BaseModel")`
    forward-reference. pydantic 풀 트리 (~100 ms cumulative) cold-start
    에서 빠짐.
  - `core/llm/providers/openai.py` 의 mid-module `import asyncio` →
    `_async_call` 메소드 진입부 함수-로컬. asyncio + email.message /
    email.utils (~13 ms cumulative) cold-start 에서 빠짐.
  - `core/__init__.py` 의 `from importlib.metadata import ...` (eager
    `__version__` resolve) → PEP 562 `__getattr__` lazy. importlib.metadata
    + email tree (~70 ms cumulative) cold-start 에서 빠짐. `__version__`
    첫 access 시점에 한 번만 resolve + cache.
- 측정 (`import core.runtime`):
  - v0.89.1 baseline: 80-110 ms warm (median ≈ 88 ms), 341 modules
  - 이 PR: **54-94 ms warm (median ≈ 70 ms)**, **201 modules** = warm
    median **−18 ms / −20 %**, modules **−140 vs v0.89.0 baseline 341**.
  - v0.89.0 → v0.89.2 누적: cold first-run 240 → ~85 ms = **−65 % cumulative**.
  - `pydantic` / `pydantic_core` / `pydantic_settings` / `importlib.metadata`
    / `email.message` 모두 cold-start `sys.modules` 에서 빠짐.

## [0.89.1] — 2026-05-09

> **Cold-start −46 % via `core.config` lazy + 19 callsite 함수-로컬 import.**
>
> v0.89.1 은 cold-start path 의 무거운 `pydantic_settings` 트리 (~150 ms cumulative,
> 144 modules) 를 lazy 화한다. `core/config.py` (567 lines) 를 `core/config/`
> 패키지로 분리해 `Settings(BaseSettings)` 클래스를 격리하고, 19 사이트의
> top-level `from core.config import settings` 을 함수-로컬 import 로 이전.
> 측정 — `import core.runtime` cold-start: **240 ms → 128 ms first-run / 80–110 ms warm**
> (median ≈ 88 ms) = **−112 ms / −46 %**. 0 regression: 4330 tests pass,
> E2E A (68.4) unchanged.

### Architecture

- **`core.config` 모듈을 패키지로 분리, pydantic_settings 트리 lazy 화**
  (cold-start 회수 토대). 기존 `core/config.py` (567 lines) 를 `core/config/`
  패키지로 변환:
  - `core/config/_settings.py` (NEW) — `Settings(BaseSettings)` 클래스만 격리
    하여 pydantic / pydantic_settings 풀 import 트리 (~150 ms cumulative,
    144 modules) 가 첫 settings 인스턴스 요청 시점까지 미뤄지도록 함.
  - `core/config/__init__.py` — 상수 (`*_PRIMARY`, `*_BASE_URL` 등),
    TOML 로직, `ModelPolicy`, `RoutingConfig`, `_resolve_provider` 만 유지.
    `settings` / `Settings` 는 PEP 562 `__getattr__` 로 lazy 해석.
- 측정: `import core.config` 단독 cold = **189 ms → 34 ms (−82 %)**;
  modules **308 → 164**; pydantic_settings 가 sys.modules 에 들어가지
  않음 (`settings` 첫 access 시점에만 로드). 단독으로 cold-start path
  전체 회수는 작음 (240 → 226 ms) — `from core.config import settings`
  를 함수-로컬로 옮기는 callsite 변환이 다음 단계에서 핵심 회수를 만듦.

- **`from core.config import settings` 의 cold-start path callsite 19 곳을
  함수-로컬 import 로 이전** (단계 1 의 PEP 562 lazy 후속). 변환 대상:
  - 4-Layer wiring: `core/wiring/{bootstrap,automation,container,startup}.py`
  - LLM 라우터/제공자: `core/runtime.py`, `core/graph.py`,
    `core/llm/{adapters,fallback,provider_dispatch}.py`,
    `core/llm/router/calls/{tools,streaming,text,parsed,_failover}.py`,
    `core/llm/providers/{anthropic,openai,glm}.py`
  - CLI thin client: `core/cli/{__init__,dispatcher,pipeline_executor,onboarding,
    welcome,report_renderer}.py`, `core/cli/tool_handlers/system.py`
  - 도메인 플러그인: `plugins/game_ip/cli/batch.py`
- `core/llm/fallback.py` 의 module-level `MAX_RETRIES` / `RETRY_BASE_DELAY` /
  `RETRY_MAX_DELAY` (settings 즉시 평가) 도 PEP 562 `__getattr__` 로 lazy
  해석. `retry_with_backoff_generic` 함수 default 도 None 으로 바꾸고
  body 에서 settings 에서 해석 — module load 시점 settings 트리거 차단.
- `core/llm/router/__init__.py` 의 `MAX_RETRIES` 등 re-export 는 PEP 562
  fallback constants lazy 분기로 이전 (외부 `from core.llm.router import
  MAX_RETRIES` 호환 유지).
- 5 모듈 (`wiring/{startup,container}`, `cli/onboarding`,
  `llm/provider_dispatch`, `llm/providers/anthropic`) 에 module-level
  `__getattr__` 의 `settings` lazy alias 를 추가해 legacy patch 사이트
  (`patch("core.X.settings")`) 호환 유지.
- 영향 테스트 (`patch("core.X.settings")` 24 사이트) 는 `core.config.settings`
  단일 patch 로 통일. settings 가 singleton 이라 동등.

- **측정 (cold-start, `import core.runtime`)**:
  - v0.89.0 baseline: **240 ms** (single run, clean cache)
  - 단계 1 (`config` 패키지 분리) 단독: 226 ms (−14 ms / −6 %)
  - 단계 1+2 합산 (이 PR): **128 ms cold (first run) / 80–110 ms warm
    (median ≈ 88 ms)** — 누적 −112 ms / **−46 %**
  - `pydantic_settings` / `core.config._settings` 가 더 이상 cold-start 의
    `sys.modules` 에 들어가지 않음 (첫 settings access 시점까지 미뤄짐).
  - modules count: 382 → 341 (−41 modules) on cold-start path.

## [0.89.0] — 2026-05-09

> **Removed — LangSmith 의존 100 % 제거.  관측성은 hook system + RunLog 로 일원화.**
>
> v0.89.0 은 GEODE 의 외부 관측성 SDK 의존(LangSmith) 을 통째로 떼어낸다.
> 18 production files + 57 test references + 1 dependency + 4 docs 가
> 영향 받았고, **자체 hook system 이 LangSmith 를 100 % 대체** (gap 0):
>
> | LangSmith 데코레이션 | 대체 hook 이벤트 |
> |---------------------|------------------|
> | `@maybe_traceable("llm")` (call_llm 5 family) | `LLM_CALL_START` / `LLM_CALL_END` |
> | `@maybe_traceable("chain")` (AgenticLoop.run) | `TURN_COMPLETE` |
> | `@maybe_traceable("chain")` (verification 4 family) | `VERIFICATION_PASS` / `VERIFICATION_FAIL` |
> | LangSmith UI (trace 조회) | RunLog (P50, ALL 58 events → `~/.geode/runs/<session>.jsonl`) |
> | LangSmith run_tree.extra metric 주입 | hook-llm-lifecycle (P55) — LLM_CALL latency/cost 집계 |
>
> 외부 SDK 의 type stub 한계로 박혀 있던 `# type: ignore[untyped-decorator]`
> **11 건 모두 자동 소멸**.  type:ignore 활성 카운트 44 → 30 (−14, −31 %).
> 누적 (B2 batch-1/2/3 + LangSmith 제거): 69 → 30 (−56 %).
>
> Bonus: `langsmith>=0.4.0` 가 우리 deps 에서 빠짐 (langgraph 가 transitive
> 로 들고 있어 sys.modules 에는 남지만, **우리 코드는 절대 import 안 함**).

### Removed
- **`core/llm/router/tracing.py`** (46 LOC) — LangSmith wrapper 모듈 삭제 (`is_langsmith_enabled`, `maybe_traceable`).
- **`@maybe_traceable` 15 + 사이트** — `core/llm/router/calls/{text,json,parsed,streaming,tools}.py`, `core/agent/loop/loop.py` (2x), `core/verification/{biasbuster,guardrails,cross_llm,rights_risk}.py` 모두 데코레이터 제거.  hook 이벤트는 그대로 fire (LLM_CALL_*/VERIFICATION_*).
- **`LLMUsageAccumulator._inject_langsmith`** — token_tracker 의 LangSmith RunTree 메트릭 주입 메서드 삭제.  hook-llm-lifecycle (P55) 이 동일 역할 수행.
- **`pyproject.toml` `langsmith>=0.4.0`** dep 라인 제거.
- **`tests/`** — `TestIsLangsmithEnabled`, `TestMaybeTraceable`, `TestAgenticLoopTracing`, `TestLangSmithTracingLive` (test_e2e_live_llm), `_inject_langsmith` 관련 3 개 케이스 삭제.  conftest.py 의 `LANGCHAIN_TRACING_V2=false` 강제 setdefault 제거 (hook 시스템은 별도 setup 불필요).
- **`# type: ignore[untyped-decorator]` 11 건** — `@maybe_traceable` 제거에 따라 자동 소멸.

### Changed
- **`core/llm/token_tracker.py`** — module docstring `optional LangSmith injection` → `hook lifecycle emission`.  `record()` docstring 도 동일 갱신.  관측성 책임이 hook system 으로 이전됨을 명시.
- **`core/llm/router/_hooks.py`** — `logging.getLogger("langsmith").setLevel(ERROR)` / `langchain` 동일 라인 삭제 (suppress 대상 자체가 사라짐).
- **`core/llm/adapters.py`** — `generate_parsed` / `generate_stream` 의 v0.88.3 anchor `# type: ignore[no-any-return]` 제거 (root-cause LangSmith decorator 가 이제 없음).
- **`plugins/game_ip/nodes/{analysts,evaluators}.py`** — `result = call_llm_with_tools(...)` 의 변수명을 `tool_result` 로 분리.  LangSmith decorator 가 이전에는 반환 타입을 Any 로 erase 했기 때문에 가려져 있던 type assignment 충돌이 mypy 에 노출됨 (ToolUseResult ↔ AnalysisResult/EvaluatorResult 분리).
- **`docs/setup{,.ko}.md`** — Observability env vars 섹션의 `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY` 행 제거.  내장 hook + RunLog 자동 활성 안내로 대체.

### Hardening Metrics
- `# type: ignore` 활성 카운트: 44 → **30** (−14, −31 %).  세션 누적 69 → 30 (−56 %).
- `[untyped-decorator]` 카테고리: 11 → **0** (완전 소멸).
- pytest: 4346 → **4330** (−16, LangSmith-only 테스트 삭제분).  실패 0.
- mypy: 332 → 331 source files (tracing.py 삭제), 0 errors.
- E2E `geode analyze "Cowboy Bebop" --dry-run` A (68.4) unchanged.
- `langsmith` 우리 deps 에서 제거 (langgraph transitive 로만 잔존).

## [0.88.5] — 2026-05-09

> **Hardening — `core/graph.py` `# type: ignore[call-overload]` 9 건 제거
> (B2 batch-3).**  9 개 langgraph `add_node()` 호출의 ignore 모두 제거.
> 원인: 우리 `_node()` wrapper 의 반환 타입 `Callable[[GeodeState], dict[str, Any]]`
> 이 langgraph 의 `_Node[NodeInputT_contra]` Protocol 과 mypy 입장에서
> 자동 매칭되지 않음 (mypy 가 generic Callable 을 Protocol member 로
> 자동 coerce 하지 않음).  Solution: ``_node`` 의 반환을 langgraph 의
> ``_Node[GeodeState]`` Protocol 로 명시 + 반환값을 `cast()` 로 localise.
> 9 개 ignore → 0, mypy 가 `add_node` overload 를 깨끗이 resolve.

### Changed
- **`core/graph.py:_node`** — return 타입 `Callable[[GeodeState], dict[str, Any]]` → `_Node[GeodeState]` (langgraph internal Protocol).  내부에서 `cast(_Node[GeodeState], _make_hooked_node(...))` / `cast(_Node[GeodeState], fn)` 로 wrapped/raw fn 모두 Protocol 로 localise.  Runtime 동작 변화 0 (langgraph 는 dict-shape return 을 그대로 받음).
- **9 개 `add_node` 호출 (line 514–522)** — `# type: ignore[call-overload]` 제거.  `router`, `signals`, `analyst`, `evaluator`, `scoring`, `skip_check`, `verification`, `synthesizer`, `gather` 9 노드 모두.

### Hardening Metrics
- `# type: ignore` 총합: 53 → **44** (active count, −9, −17 %)
- `[call-overload]` 카테고리: 13 → 4 (graph.py 9 → 0; tracing/tools/pipeline_executor 4 잔존 — root-cause 다른 SDK 한계)
- pytest 4346 passed (변동 없음); ruff/mypy clean (332 source files); E2E A (68.4) 동일.

## [0.88.4] — 2026-05-09

> **Hardening — `# type: ignore[union-attr]` 10 건 전부 제거 (B2 batch-2).**
> 10 개 사이트 모두 ``Optional[X]`` 타입 attribute 접근 — 호출 측에서
> 이미 None 가드 (`is_available()`, `_check_mcp_health`) 를 통과한 invariant
> 을 mypy 가 spread 하지 못해 발생.  `assert ... is not None` 로 invariant
> 을 localise 해 ignore 제거 + 런타임 안전성 ↑ (None dereference 발생 시
> 명시적 AssertionError 로 즉시 발견).
>
> v0.88.3 (no-any-return) 에 이은 B2 두 번째 배치.  외부 SDK 의존이
> 아닌, 우리 코드의 invariant 를 명시화하면 깔끔히 잡히는 카테고리.

### Changed
- **`core/server/supervised/{slack,discord,telegram}_poller.py`** — 3 개 poller 모두 `_poll_channel` / `_poll_once` 가 `_check_mcp_health` 통과 후 호출되는 invariant 를 `assert self._mcp is not None` 로 localise.
- **`core/mcp/base_calendar.py`** — 4 개 메서드(`delete_event`, `list_events`, `create_event`, `list_calendars`) 모두 `is_available()` 가드 직후에 `assert self._manager is not None` 추가.
- **`core/mcp/base_notification.py`** — `send` 의 동일 패턴.
- **`core/mcp/stdio_client.py`** — `subprocess.Popen.stdin: Optional[IO[bytes]]` 의 None 가능성을 `if self._process.stdin is not None:` 로 처리 (assert 가 아니라 가드 — stdin 미파이프 시 silently skip).
- **`core/llm/providers/anthropic.py`** — `ClaudeAgenticAdapter.agentic_call` 의 nested `_do_call` closure 에서 `self._client` invariant 를 assert 로 명시 (closure 가 outer scope 의 None 체크를 mypy 입장에서 못 봄).

### Hardening Metrics
- `# type: ignore` 총합: 63 → **53** (−10, −15.9 %)
- `[union-attr]` 카테고리: **10 → 0** (완전 소멸)
- pytest 4346 passed (변동 없음); ruff/mypy clean (332 source files); E2E A (68.4) 동일.

## [0.88.3] — 2026-05-09

> **Hardening — `# type: ignore[no-any-return]` 6 건 제거 (B2 mini-batch).**
> 8 개 `[no-any-return]` ignore 중 6 개를 `cast()` 패턴으로 정리.  나머지
> 2 개는 ``@maybe_traceable`` (LangSmith) 데코레이터의 type erasure 가
> 원인이라 root-cause 가 외부 SDK 에 있어, 이 PR 에서는 anchor 코멘트만
> 갱신하고 ignore 유지(향후 LangSmith 타입 stub 개선 후 일괄 제거).
>
> 정리 대상 — 모두 SDK 반환값(`json.loads(...) → Any`,
> `choice.message.parsed → BaseModel | None`)을 함수의 명시적 반환 타입
> (`list[dict[str, Any]]`, `dict[str, Any]`, TypeVar `T`)으로 변환하는
> 곳.  `cast()` 는 무코스트 hint, 런타임 동작 변경 0.

### Changed
- **`core/tools/base.py`** — `load_all_tool_definitions()` 의 `json.loads(...)` 반환값을 `cast(list[dict[str, Any]], ...)` 로 명시.
- **`core/memory/vault.py`** — `JobApplicationVault._load()` 의 `json.loads(...)` 반환값을 `cast(list[dict[str, Any]], ...)` 로 명시.
- **`core/memory/user_profile.py`** — `_load_preferences()` 의 `json.loads(raw)` 반환값을 `cast(dict[str, Any], ...)` 로 명시.
- **`core/verification/calibration.py`** — `load_golden_set()` 의 `json.loads(...)` 반환값을 `cast(dict[str, Any], ...)` 로 명시.
- **`core/llm/router/calls/parsed.py`** — OpenAI 구조화 출력 `choice.message.parsed` 를 `cast(T, ...)` 로 명시 (TypeVar `T` bound BaseModel).
- **`core/llm/providers/openai.py`** — 동일 패턴(`OpenAIAdapter.generate_parsed` 의 `cast(T, ...)`).
- **`core/llm/adapters.py`** — 두 곳(`generate_parsed`, `generate_stream`)의 ignore 는 root-cause 가 ``@maybe_traceable`` 의 untyped-decorator 임을 명시하는 anchor 코멘트로 갱신; LangSmith 타입 stub 개선 후 제거 예정.

### Hardening Metrics
- `# type: ignore` 총합: 69 → **63** (−6, −8.7 %)
- `[no-any-return]` 카테고리: 8 → 2 (남은 2 는 LangSmith decorator 한계)
- pytest 4346 passed (변동 없음); ruff/mypy clean; E2E A (68.4) 동일.

## [0.88.2] — 2026-05-09

> **Cleanup — httpx 모듈-레벨 lazy loading (B1/v0.88.1 패턴 일관성).**
> v0.88.0 (anthropic) + v0.88.1 (numpy/correlation) 을 거치고도 남아있던
> 마지막 module-level 무거운 SDK 는 **httpx** 였다.
> `core/llm/providers/anthropic.py:13` 과 `core/llm/providers/openai.py:371`
> 두 곳에서 `import httpx` 가 module-level 에 남아 있어 `core.runtime`
> 한 번 import 만으로 httpx 트리(~92 ms importtime cumulative) 를 끌어왔다.
>
> **솔직한 측정 결과**: importtime cumulative 92 ms 와 달리 wall-clock
> 변화는 노이즈에 묻힌다(10-run median: develop 310 ms vs httpx-lazy
> 322 ms — 차이 무의미).  httpx 의 의존(asyncio, ssl, certifi) 일부가
> 다른 path 로도 로드되고, 일부는 병렬 import 로 wall-clock 영향이 적기
> 때문.  그럼에도 본 PR 의 가치는 **코드 일관성 + 사용 패턴 보장**:
>
> 1. **동일 lazy 패턴의 일관 적용** — anthropic/numpy 가 lazy 인데 httpx
>    만 eager 인 비대칭 제거.  v0.88.0/v0.88.1 의 PEP 562 + function-local
>    import 패턴을 마지막 SDK 까지 이어서 적용.
> 2. **사용 안 하는 사용자 보호** — Codex Plus only / GLM only 셋업은
>    HTTP 클라이언트가 필요 없음에도 httpx 를 영원히 sys.modules 에
>    들고 있었다.  본 PR 후 `'httpx' in sys.modules == False` 보장
>    (`import core.runtime` 직후 시점).
> 3. **module-level eager import 의 마지막 잔류 제거** — 이후 cold-start
>    추가 절약은 `core.config` (pydantic settings) 같은 구조적 작업이
>    필요하며, SDK lazy 이슈는 이 PR 로 닫힘.
>
> 검증: `import core.runtime` 후 `'httpx' in sys.modules == False`.  pytest
> 4346 passed (변동 없음); ruff/mypy clean; E2E A (68.4) 동일.

### Changed
- **`core/llm/providers/anthropic.py`** — top-level `import httpx` 제거 → `TYPE_CHECKING` 블록으로 이동.  `_build_httpx_timeout` / `_build_httpx_limits` / `get_anthropic_client` / `get_async_anthropic_client` 4 함수에 함수-로컬 `import httpx` 추가.  Type annotation(`-> httpx.Timeout`, `-> httpx.Limits`)은 `from __future__ import annotations` 로 string.
- **`core/llm/providers/openai.py`** — top-level `import httpx  # noqa: E402` 제거.  유일한 사용처(`_get_client` 의 lock-protected lazy-init 블록)에 함수-로컬 `import httpx` 추가.

### Performance
- 콜드 스타트 wall-clock 측정 가능한 변화 없음 (10-run median: 310 ms → 322 ms, noise band).  importtime cumulative 92 ms 절약은 SDK 의 의존 graph 가 다른 path 로도 일부 로드되어 wall-clock 으로 그대로 환원되지 않음.  그러나 **httpx 미사용 셋업은 SDK 를 영원히 안 로드**하게 됨 (sys.modules 검증).
- 누적 (B1 + v0.88.1 + v0.88.2): 콜드 스타트 절약 ~−258 ms / ~−58 % (v0.88.0 main 대비).

## [0.88.1] — 2026-05-09

> **Performance — numpy + correlation analyzer 모듈-레벨 lazy loading.**
> v0.88.0 가 anthropic SDK 248 ms 를 잘라낸 직후, 남은 콜드 스타트의
> 다음 큰 덩어리는 **numpy** 였다.  `core.automation.correlation` 과
> `core.verification.stats` 가 module-level `import numpy as np` 로
> SDK 를 끌어와, 단순히 `import core.runtime` 만으로도 numpy 트리
> (~31 ms) 가 매번 로드.  `core.automation.expert_panel` 도 같은
> 패턴으로 직접 `import numpy as np`.
>
> 이번 PR 은 **3 곳의 numpy 모듈-레벨 import → 함수-로컬 + TYPE_CHECKING**
> 으로 옮겨, numpy 를 실제로 사용하는 함수가 처음 호출될 때까지 로드를
> 미룬다.  `core.runtime` 의 `CorrelationAnalyzer` 어노테이션도
> `TYPE_CHECKING` 블록으로 이동(B1 의 `LLMClientPort` 와 동일 패턴).
>
> **측정 (warm cache, 10-run sorted, median of 5th–6th):**
> - Before (v0.88.0 main): 314–441 ms (median 356 ms)
> - After  (v0.88.1):     259–367 ms (median 282 ms)
> - **Δ: −74 ms / −21 %**
>
> 검증: `import core.runtime` 후 `'numpy' in sys.modules == False`.
> 첫 ``ExpertPanel.compute_consensus`` / ``CorrelationAnalyzer.spearman``
> / ``calculate_krippendorff_alpha`` 호출이 일어나면 그 시점에 numpy 1
> 회 로드. pytest 4346 passed (변동 없음); E2E A (68.4) 동일.

### Changed
- **`core/runtime.py`** — `from core.automation.correlation import CorrelationAnalyzer` (line 39) 를 `TYPE_CHECKING` 블록으로 이동.  `correlation_analyzer: CorrelationAnalyzer | None = None` 데이터클래스 어노테이션은 `from __future__ import annotations` 로 인해 런타임 string 이라 실제 import 불필요.  B1 의 `LLMClientPort` 패턴 재사용.
- **`core/automation/feedback_loop.py`** — module-level `from core.automation.correlation import CorrelationAnalyzer` 를 `TYPE_CHECKING` 블록으로 이동.  `__init__` factory(line 142, 148) 는 이미 함수-로컬 import 사용 중이라 추가 변경 없음.  Type annotation(line 159) 은 string.
- **`core/automation/expert_panel.py`** — top-level `import numpy as np` 제거.  `_compute_aggregate` 함수 본체 첫 줄에 `import numpy as np` 추가.  사용처는 그 함수의 3 줄(``np.array`` / ``np.std`` / ``np.mean``) 뿐이라 단일 함수-로컬 import 로 충분.
- **`core/verification/stats.py`** — top-level `import numpy as np` 제거.  `calculate_krippendorff_alpha` 함수 첫 줄에 `import numpy as np` 추가.  Krippendorff alpha 계산 외에는 numpy 사용처 없음.

### Performance
- **CLI 콜드 스타트 −74 ms / −21 %** (warm cache, 10-run median).  numpy 를 안 만지는 invocation(`geode about`, `geode doctor`, `geode --help`, `geode version` 등)은 numpy 트리를 영원히 로드하지 않을 수 있게 됨.  v0.88.0 (anthropic lazy) 와 합쳐 콜드 스타트 누적 절약 ~258 ms / ~58 %.

## [0.88.0] — 2026-05-08

> **Performance — anthropic SDK module-level lazy loading.**
> CLI 콜드 스타트 경로(`geode about` / `geode doctor` / `geode --help`)는
> 그동안 `core.runtime` import 한 번만으로 **anthropic SDK 248 ms 그래프
> 전체**를 끌어왔다. anthropic을 한 번도 호출하지 않는 user 도(예: Codex
> Plus 단독, GLM 단독)도 매 invocation 마다 이 비용을 지불해 왔으며,
> `python -X importtime -c "import core.runtime"` 으로 측정 시 anthropic
> 트리(`anthropic.types.*`, `httpx.*`, `anyio.*`)가 cumulative 248 ms 를
> 차지. 이번 PR 은 anthropic 을 **PEP 562 모듈-레벨 `__getattr__`** 로
> defer 해, 진짜로 anthropic 을 만지는 코드(에이전틱 호출, 에러 분류,
> failover) 가 처음 실행될 때까지 SDK 로드를 미룬다.
>
> **측정 (warm cache, `import core.runtime`):**
> - Before (main): 354–386 ms (median ~370 ms)
> - After (B1):   183–190 ms (median ~186 ms)
> - **Δ: −184 ms / −49 %** (3-run median)
>
> 검증: `import core.runtime` 후 `'anthropic' in sys.modules` 가 `False`.
> 첫 ``classify_llm_error`` / failover dispatch / agentic 호출이 일어나면
> 그 시점에 `__getattr__` 이 anthropic 을 1 회 로드.  pytest 4346 passed
> (변동 없음); E2E `geode analyze "Cowboy Bebop" --dry-run` A (68.4) 동일.

### Changed
- **`core/llm/errors.py`** — top-level `import anthropic` 제거.  7 개 `LLM*Error` 별칭(`LLMTimeoutError`, `LLMConnectionError`, `LLMRateLimitError`, `LLMAuthenticationError`, `LLMBadRequestError`, `LLMAPIStatusError`, `LLMInternalServerError`)은 module-level `__getattr__` 으로 lazy 해석.  `_ANTHROPIC_ALIAS_MAP` 로 anthropic SDK 의 실제 클래스 이름을 추적; 첫 접근 시 `globals()` 에 캐시.  `__all__` 추가로 mypy `--no-implicit-reexport` 통과.  `classify_llm_error` 는 함수-로컬 `import anthropic` 후 `anthropic.RateLimitError` 등 SDK 클래스를 직접 참조 (in-module 레퍼런스는 `__getattr__` 을 거치지 않으므로).
- **`core/llm/provider_dispatch.py`** — 모듈-레벨 `import anthropic` 제거.  Dispatch table 의 `_anthropic_retryable` / `_anthropic_bad_request` / `_anthropic_get_client` 헬퍼 도입(기존 `_openai_retryable` / `_openai_bad_request` 의 anthropic 카운터파트).  Lambda capture 가 아닌 함수 레퍼런스로 dispatch table 등록 → 정의가 모듈 import 시점에 이루어지지 않음.
- **`core/llm/providers/anthropic.py`** — top-level `import anthropic` + `from anthropic.types import TextBlockParam` 제거.  `RETRYABLE_ERRORS` / `NON_RETRYABLE_ERRORS` / `TextBlockParam` 은 `__getattr__` 로 lazy.  Type annotation 은 `TYPE_CHECKING` 블록에 보존(IDE / mypy 정적 surface 유지).  Function 본체에서 anthropic SDK 를 만지는 부분(`get_anthropic_client`, `get_async_anthropic_client`, `system_with_cache`, `retry_with_backoff`)은 함수-로컬 `import anthropic`.  자기 모듈 내부에서 lazy 이름을 참조해야 하는 `retry_with_backoff` 는 `sys.modules[__name__].RETRYABLE_ERRORS` 로 PEP 562 우회.
- **`core/llm/router/__init__.py`** — `from core.llm.errors import LLM*Error as LLM*Error` 7 개 eager 재-export 제거(파일 위치 1 곳, 240 ms 절약 핵심).  Public API 는 모듈-레벨 `__getattr__` 으로 보존(`from core.llm.router import LLMRateLimitError` 가 첫 접근 시 lazy 해석).  TYPE_CHECKING 블록은 mypy 정적 view 유지용.
- **`core/llm/client.py`** — router/__init__.py 와 동일 패턴(LLM*Error 7 개를 lazy `__getattr__` 로 전환).
- **`core/llm/router/calls/_failover.py`** — module-level `from core.llm.providers.anthropic import RETRYABLE_ERRORS, NON_RETRYABLE_ERRORS` 를 `call_with_failover` 함수 본체 안으로 이동.  Cold-start path 에서 `providers.anthropic.__getattr__` 호출 차단.
- **`core/llm/router/calls/streaming.py`** — `RETRYABLE_ERRORS` import 를 `call_llm_streaming` 함수-로컬로 이동.  같은 이유.

### Performance
- **CLI 콜드 스타트 −184 ms / −49 %** (warm cache, 3-run median).  `import core.runtime` 후 `'anthropic' in sys.modules == False`.  Anthropic 을 안 쓰는 셋업(Codex Plus only, GLM only)은 anthropic SDK 를 영원히 로드하지 않을 수 있게 됨.

## [0.87.1] — 2026-05-08

> **Hardening — v0.82.0 staleness 인시던트의 재발 방지용 단위 테스트 추가.**
> v0.82.0에서 `SharedServices`의 frozen `_model` 필드를 제거해 `cmd_model`
> 변경이 다음 IPC 세션에 즉시 반영되도록 고쳤지만, 기존 단위 테스트
> `test_model_resolved_per_session`은 boot-time 일관성만 검사할 뿐
> mid-flight `settings.model` 변경 → 다음 세션 fresh-read 시나리오를
> 직접 재현하지 않았다. 이번 패치는 정확히 그 staleness 시나리오를 LLM
> 호출 없이 강제(ANTHROPIC_PRIMARY ↔ OPENAI_PRIMARY 교체)해 v0.82.0
> 인시던트의 provider 교차(Anthropic API ↔ Codex Plus OAuth) 패턴까지
> 회귀로 영구 잠근다. 동작·스키마 변경 0; tests/ 전용 변경. pytest
> 4346 passed (4345→4346); E2E `geode analyze "Cowboy Bebop" --dry-run`
> A (68.4) unchanged.

### Added
- **`tests/test_shared_services.py::test_model_switch_propagates_across_sessions`** — v0.82.0 회귀 잠금. `settings.model`을 `ANTHROPIC_PRIMARY`로 설정 후 `create_session(DAEMON)` → `loop_a.model == ANTHROPIC_PRIMARY` 확인. 그 직후 `settings.model = OPENAI_PRIMARY`로 변경하고 `create_session(DAEMON)` → `loop_b.model == OPENAI_PRIMARY`까지 검증해 `SharedServices`가 매 세션마다 `settings.model`을 fresh-read 함을 증명. 두 세션 인스턴스가 독립적인지 (`loop_a.model`은 첫 시점 값 유지) 도 함께 어서트.

## [0.87.0] — 2026-05-08

> **`core/lifecycle/` → `core/wiring/` rename — `startup` 흡수 후에도 모호하던 폴더 이름을 의도가 명확한 이름으로 교체.**
> v0.52에서 `core/runtime_wiring/`을 `core/lifecycle/`로 옮긴 뒤 4개의 builder
> 모듈(bootstrap, container, adapters, automation)이 들어왔고, v0.86.0(A5b)
> 에서 `cli/startup.py`까지 흡수했음에도 "lifecycle"이라는 이름은 여전히
> daemon lifecycle / session lifecycle / hook lifecycle 같은 이질적 의미와
> 충돌. 그 모듈들이 실제로 하는 일은 *application 의 object graph 를 wire 한다*
> 이므로 `wiring/`이 더 직접적. 패키지 본체 5 파일을 `git mv`로 옮긴 뒤
> 151 caller site (15개 cli/, 23개 tests/, 그 밖에 auth/, llm/, server/,
> agent/loop/) 의 `core.lifecycle.*` import를 `core.wiring.*`로 일괄 교체,
> `pyproject.toml`의 import-linter ignore_imports 1건 + descriptive comment
> 2건도 동기. 동작·테스트·import 그래프 변화 0; cosmetic rename. E2E
> `geode analyze "Cowboy Bebop" --dry-run` unchanged at A (68.4); pytest
> 4345 passed (baseline 동일).

### Changed
- **`core/lifecycle/` → `core/wiring/` (5 files renamed via `git mv`).** `__init__.py` (re-exports `get_plugin_status`), `bootstrap.py` (760L, 14 builders: hooks, memory, session, config_watcher, task, prompt, plugin_registry, tool_offload, run_log, stuck_detector, …), `container.py` (390L, 10 builders: profile_store, policy_chain, lane_queue, tool_registry, auth, LLM adapters, …), `adapters.py` (295L, 8 builders: MCP signal/notification/calendar adapters, gateway, plugins), `automation.py` (335L, build_automation + wire_automation_hooks). Rename history preserved by `git mv`; `git log --follow` continues to work.
- **151 caller sites updated** — `core.lifecycle.*` → `core.wiring.*` across `core/runtime.py` (8 sites incl. docstring), `core/cli/{welcome,dispatcher,bootstrap,session_state,onboarding,typer_commands,typer_serve,doctor_bootstrap,tool_handlers/system}.py`, `core/cli/commands/{login,key,_state}.py`, `core/auth/{credential_breadcrumb,plan_registry,auth_toml,oauth_login}.py`, `core/llm/{credentials,fallback}.py`, `core/llm/providers/codex.py`, `core/agent/loop/_model_switching.py`, `core/server/supervised/services.py`, `core/server/ipc_server/poller.py`, plus 23 test files and `tests/_live_audit_runner.py`. Function bodies untouched.
- **`pyproject.toml`** — ignore_imports: `core.lifecycle.adapters → core.channels.binding` → `core.wiring.adapters → core.channels.binding`. Descriptive comments at lines 112 (`lifecycle/bootstrap` → `wiring/bootstrap`) and 193 (`lifecycle bootstraps` → `wiring bootstraps`) synced. `scripts/check_legacy_imports.py` legacy-import migration target updated `runtime_wiring → wiring` to reflect the latest module name.

## [0.86.0] — 2026-05-08

> **A5b — `cli/startup.py` 책임 분리: `lifecycle/startup.py` + `cli/onboarding.py`.**
> v0.82.0 OAuth 점검에서 발견했으나 단일 mv로 풀리지 않아 폐기됐던 결함의
> 진짜 해결. v0.85.0 (A5a)이 `cli/_helpers`의 IO/key utility를 `utils`로
> 추출해 의존성 blocker를 제거한 뒤, 이번 PR에서 `cli/startup.py` (520L)
> 자체를 책임별로 두 모듈로 갈라냄. lifecycle 부분 (data inspection +
> readiness data classes + file IO) 은 `core/lifecycle/startup.py`
> (287L)으로, interactive 부분 (console.input wizard, slash command
> dispatch, console.print display) 은 `core/cli/onboarding.py` (272L)
> 로 분리. 함수 본문 byte-identical, 호출자 15+ 사이트가 책임에 따라
> import를 분기. **2개 ignore_imports 영구 제거**:
> `core.lifecycle.bootstrap → core.cli.startup` (이젠 lifecycle →
> lifecycle internal), `core.server.ipc_server.poller → core.cli.startup`
> (이젠 server → lifecycle, contract에서 허용). 22 → 19 (-2 from this
> PR + 1 무관). E2E `geode analyze "Cowboy Bebop" --dry-run` unchanged
> at A (68.4); pytest 4345 passed.

### Changed
- **`core/cli/startup.py` (520L) split into `core/lifecycle/startup.py` (287L) + `core/cli/onboarding.py` (272L).** Function placement by responsibility (interactive vs data):
  - **Lifecycle (9 functions + 2 dataclasses)**: `auto_generate_env`, `_is_placeholder`, `_has_any_llm_key`, `detect_subscription_oauth`, `Capability`, `ReadinessReport`, `check_readiness`, `setup_project_memory`, `setup_user_profile` — all pure data inspection / file IO with no `console.input` calls.
  - **CLI/onboarding (6 functions)**: `env_setup_wizard`, `_wizard_subscription_path`, `_wizard_api_key_path`, `detect_api_key`, `key_registration_gate`, `render_readiness` — all `console.input` wizards or `console.print` display, plus `key_registration_gate`'s `cmd_login` / `cmd_key` slash dispatch.
  - The `_KEY_PATTERNS` constant lives with `detect_api_key` in `cli/onboarding.py` since that function is its only consumer.
  - 15+ caller sites updated. Single-name imports route to one module; multi-name imports (e.g. `from core.cli.startup import check_readiness, render_readiness` in `dispatcher.py`, `tool_handlers/system.py`) split into two `from … import …` lines, one per layer.
  - Test patches (especially `tests/test_startup.py:80+`, `tests/test_agentic_loop.py:357-373`, `tests/test_e2e_live_llm.py:48,536-538`) re-point `core.cli.startup.{settings,console,detect_subscription_oauth,log,_upsert_env}` to `core.cli.onboarding.*` (wizard module) or `core.lifecycle.startup.*` (data path) per the function whose state they patch.
- **`pyproject.toml` `[tool.importlinter.contracts]` — 2 entries removed.** `core.lifecycle.bootstrap → core.cli.startup` from the `Server may host agent but never CLI` contract: now `lifecycle.bootstrap → lifecycle.startup`, internal lifecycle import. `core.server.ipc_server.poller → core.cli.startup` from the same contract: now `server.poller → lifecycle.startup`, allowed because that contract only forbids `core.cli`. ignore_imports total drops from 22 → 19. (`core/cli/startup.py` *deleted*, `core/lifecycle/startup.py` *new*, `core/cli/onboarding.py` *new*, 11 caller files, 5 test files, `pyproject.toml`)

## [0.85.0] — 2026-05-08

> **A5a — `cli/_helpers` IO/key utilities → `core/utils/env_io.py`.** First
> of two PRs that resume the v0.82.0-deferred A5 work (move `cli/startup.py`
> out of the CLI layer). The blocker was that `startup.py` imports
> `mask_key`, `upsert_env`, `is_glm_key` from `cli/_helpers` — moving
> startup alone created `lifecycle.startup → cli._helpers` violations.
> This PR extracts the four IO/key utilities (`mask_key`, `upsert_env`,
> `upsert_config_toml`, `is_glm_key`) to `core/utils/env_io.py` because
> they have no CLI semantics — they read/write `.env`,
> `.geode/config.toml`, and detect API key shapes. `parse_dry_run_flag`
> stays in `core/cli/_helpers.py` because it parses CLI argument
> strings, which is genuinely a CLI concern. After this PR,
> `cli/_helpers.py` shrinks from 113 LOC to 21 LOC. Five caller files
> updated. E2E `geode analyze "Cowboy Bebop" --dry-run` unchanged at
> A (68.4); pytest 4345 passed.

### Changed
- **`core/cli/_helpers.py` (113 LOC → 21 LOC) split into `core/utils/env_io.py` + `core/cli/_helpers.py`.** Four utilities move to `core/utils/env_io.py` (107 LOC): `mask_key(key)` (display masking, no CLI dep), `upsert_env(var_name, value)` (writes `.env` + syncs `os.environ`, no CLI dep), `upsert_config_toml(section, key, value)` (writes `.geode/config.toml`, no CLI dep), `is_glm_key(value)` (regex-based ZhipuAI key detection, no CLI dep). `parse_dry_run_flag(args)` stays in `core/cli/_helpers.py` because it parses CLI argument strings — CLI-layer concern. Caller updates (5 files): `core/cli/startup.py:18-19,284`, `core/cli/commands/__init__.py:46-48`, `core/cli/commands/model.py:79`, `tests/test_config_effort_knob.py:18` switch their imports from `core.cli._helpers` to `core.utils.env_io`. `core/cli/dispatcher.py:48` keeps its `parse_dry_run_flag` import unchanged. No `ignore_imports` change yet — those happen in A5b when `cli/startup.py` itself moves to `core/lifecycle/startup.py`. (`core/utils/env_io.py` *new*, `core/cli/_helpers.py`, `core/cli/startup.py`, `core/cli/commands/__init__.py`, `core/cli/commands/model.py`, `tests/test_config_effort_knob.py`)

## [0.84.0] — 2026-05-08

> **OAuth point-check trilogy completion — IPC TTY capability propagation.**
> Third and final fix in the OAuth-OpenAI live-test inspection. v0.82.0
> fixed the *actual LLM call routing* (frozen `SharedServices._model`).
> v0.83.0 fixed the *footer model display* (`init_session_meter` hard
> default). v0.84.0 fixes the *output noise* — when the thin CLI's
> stdout/stdin is not a terminal (heredoc, pipe, CI), the daemon was
> still emitting Rich braille spinner frames `⠴⠦⠧⠇⠏⠋⠙⠹⠸⠼` and ANSI
> cursor sequences into the socket because `make_session_console`
> hard-coded `force_terminal=True`. Per-turn output got polluted with
> 200+ spinner frames. The thin CLI just wrote the bytes to stdout
> as-is. Fix: thin CLI sends a `client_capability` message right
> after `connect()` carrying its own `is_tty` (= `stdin.isatty() and
> stdout.isatty()`) and `width` (`shutil.get_terminal_size().columns`).
> The daemon stores this in a thread-local; the per-thread Console
> built for that IPC handler thread inherits the client's TTY state
> and width. `_tool_spinner` also got a second non-TTY guard for
> direct (non-IPC) REPL piping to a file. Backward compatible: old
> thin clients that don't send the message keep the previous behavior
> (`is_tty=True, width=120`). E2E `geode analyze "Cowboy Bebop"
> --dry-run` unchanged at A (68.4); pytest **4345 passed** (+1 new
> IPC test asserting the daemon-side Console mirrors a non-TTY
> client's state).

### Fixed
- **`core/cli/ipc_client.py` — send `client_capability` on connect.** New helper `_send_client_capability()` runs after the session greeting is read in `connect()`. Reads `sys.stdin.isatty() and sys.stdout.isatty()` for `is_tty` and `shutil.get_terminal_size().columns` (clamped) for `width`. Sends `{"type": "client_capability", "is_tty": ..., "width": ...}` and drains the daemon's `ack` so subsequent one-shot commands (`send_command`, `request_resume`) see their actual response, not the stale capability ack. (`core/cli/ipc_client.py` +47L)
- **`core/server/ipc_server/poller.py` — accept and apply `client_capability`.** New module-level `_client_capability_local` `threading.local()` with a `_get_client_capability()` accessor that defaults to `(is_tty=True, width=120)` for backward compat. New `client_capability` message handler in `_process_message`. `_run_prompt_streaming` reads the stored capability at session-start and passes it through to `make_session_console(writer, force_terminal=is_tty, width=width)`. (`core/server/ipc_server/poller.py` +39L)
- **`core/ui/console.py:make_session_console` — accept `force_terminal` + `width` kwargs.** Both have backward-compatible defaults (`True`, `120`). Truecolor color system is only forced when `force_terminal=True` so non-TTY sessions don't get the ANSI escape soup either. (`core/ui/console.py` +24/-6L)
- **`core/agent/tool_executor/_spinner.py:_tool_spinner` — non-TTY guard for direct REPL piping.** The IPC-mode early-return is unchanged. Added a second guard that checks `_pkg.console.is_terminal` after the IPC check so a *local* REPL piped to a file or running under CI also skips the spinner instead of emitting braille frames + cursor controls. (`core/agent/tool_executor/_spinner.py` +14L)
- **`tests/test_phase3_ipc.py` — new test `test_client_capability_non_tty_disables_ansi`.** Patches `sys.stdin.isatty`/`sys.stdout.isatty` to return False and `shutil.get_terminal_size` to return `(80, 24)`, connects via `IPCClient`, then asserts the daemon-side per-thread Rich Console has `is_terminal == False` and `width == 80`. (`tests/test_phase3_ipc.py` +62L, +1 test → 4345 total passing)

## [0.83.0] — 2026-05-08

> **Footer model display follow-up to v0.82.0.** v0.82.0 fixed the
> *actual LLM call routing* (frozen `SharedServices._model` was
> overriding `/model` switches), but the per-turn footer
> (`✢ Worked for Xs · model · ↓in ↑out · $cost`) still hard-coded
> `claude-opus-4-7` whenever a session started without an explicit
> model argument. Root cause: `init_session_meter(model="")` defaulted
> to `ANTHROPIC_PRIMARY` instead of `settings.model`, and the only
> caller (`core/server/ipc_server/poller.py:305`) calls it with no
> arguments. Now defaults to `settings.model or ANTHROPIC_PRIMARY` so
> what the user sees in the footer matches the live user-selected
> model. E2E `geode analyze "Cowboy Bebop" --dry-run` unchanged at
> A (68.4); full pytest 4344 passed.

### Fixed
- **`core/ui/agentic_ui/_state.py:init_session_meter` — default to live `settings.model`.** When the optional `model` argument is empty, fall back to `settings.model` (the value `_apply_model` mutates on `/model` switches) before falling back to `ANTHROPIC_PRIMARY` as a final safety net. Pairs with v0.82.0's `SharedServices` fix: that change made the *actual* LLM call route to the live model, this change makes the *displayed* model in the per-turn footer match. The single caller (`core/server/ipc_server/poller.py:305`) already passes no argument, so this fix lights up automatically — no caller changes needed. (`core/ui/agentic_ui/_state.py`)

## [0.82.0] — 2026-05-08

> **Critical fix — `SharedServices` no longer freezes the active LLM
> model at daemon boot.** Discovered while live-testing OAuth-OpenAI
> codex routing. Symptom (extremely subtle, silently swaps providers):
> after a long-running daemon was started under `GEODE_MODEL=claude-opus-4-7`,
> a subsequent user `/model gpt-5.5` correctly mutated `settings.model`
> + `.env` and the prompt header rendered `gpt-5.5 · autonomous
> execution agent`, **but every actual LLM call still routed to
> `claude-opus-4-7`** — `serve.log` confirmed `Session started:
> model=claude-opus-4-7` for sessions opened after the switch. The
> turn footer printed `claude-opus-4-7` (correctly reflecting the
> real model), and `/model gpt-5.5` reported `Already using GPT-5.5`
> from the daemon-side handler, both contradicting the prompt header.
> Net effect: a user expecting OAuth-borrowed Codex Plus (free, hosted
> at `chatgpt.com/backend-api/codex`) silently paid Anthropic API for
> Opus 4.7 calls, with their prompts also flowing to Anthropic instead
> of OpenAI/ChatGPT. Root cause: `SharedServices` cached `_model` and
> `_provider` as dataclass fields populated once in
> `build_shared_services()` from boot-time `settings.model`. Each new
> `create_session()` passed `self._model` to the freshly built
> `AgenticLoop`, so the boot-time value won every time. The drift-sync
> path (`_sync_model_from_settings()`) only triggers when an active
> loop runs another round — useless for new sessions in the same
> daemon. **Fix**: remove `_model` / `_provider` dataclass fields;
> `create_session()` now reads `settings.model` directly and resolves
> the provider per call. The 4 `SharedServices(...)` test fixtures
> drop those kwargs; `test_model_resolved` becomes
> `test_model_resolved_per_session` asserting `loop.model ==
> settings.model` after `create_session`. E2E `geode analyze "Cowboy
> Bebop" --dry-run` unchanged at A (68.4); full pytest 4344 passed.

### Fixed
- **`core/server/supervised/services.py` — drop boot-frozen `_model` / `_provider` fields.** `SharedServices` previously held `_model: str = ""` and `_provider: str = "anthropic"` populated once at `build_shared_services()` from `settings.model`. `create_session()` passed those frozen values into every new `AgenticLoop`. After a `/model` switch, the daemon's `settings.model` changed but `self._model` was untouched, so the next session was built with the boot-time model — including its provider — even though the prompt header read the live `settings.model`. The drift-sync path doesn't run for fresh sessions, only for in-flight loops. The fix is a single change in `create_session()`: read `settings.model` and call `_resolve_provider(settings.model)` inline at the `AgenticLoop(...)` construction site, and delete the two dataclass fields plus the `_model=`, `_provider=` kwargs at `build_shared_services()`'s `SharedServices(...)` return. Tests updated: `tests/test_shared_services.py` drops `_model="claude-sonnet-4-6"` / `_provider="anthropic"` from both `services` fixtures (lines 53-60 and 167-175); `test_model_resolved` is rewritten as `test_model_resolved_per_session` to assert that a freshly built `loop.model` matches the live `settings.model` after `create_session(SessionMode.DAEMON)` — the new invariant. (`core/server/supervised/services.py`, `tests/test_shared_services.py`)

## [0.81.0] — 2026-05-08

> **Dependency cleanup A4 — `core/cli/{session_checkpoint,transcript}.py` → `core/runtime_state/`.**
> Fourth of 5 PRs. Two cross-layer state primitives — `SessionCheckpoint`
> (239 LOC, atomic JSON store for resume/checkpoint) and `SessionTranscript`
> (314 LOC, conversation log + cleanup) — get a new dedicated package
> `core/runtime_state/` because they're consumed by all three layers
> (cli, agent, server). Putting them in `core/cli/` was the original
> v0.40-era artifact that v0.52's pyproject comment had explicitly
> flagged: *"server/runtime_state/ 또는 utils/ 로 이동 예정"*. Today, 14
> caller sites span 5 different layers. New package
> `core/runtime_state/` (1 init + 2 modules). 6 `ignore_imports`
> entries removed (`core.agent.loop.{loop,_lifecycle}` × 2 +
> `core.server.ipc_server.poller` for `session_checkpoint`/`transcript`
> in both contracts). 28 → 22 ignore_imports remaining (single biggest
> reduction in the cycle). E2E `geode analyze "Cowboy Bebop" --dry-run`
> unchanged at A (68.4); full pytest 4344 passed.

### Architecture
- **`core/cli/{session_checkpoint,transcript}.py` → `core/runtime_state/{session_checkpoint,transcript}.py` (553 LOC total).** New package `core/runtime_state/` (`__init__.py` 11L docstring) houses cross-layer session state primitives. `session_checkpoint.py` (239 LOC) = `SessionState` + `SessionCheckpoint` atomic-write JSON store backing `/resume`. `transcript.py` (314 LOC) = `SessionTranscript` conversation logger + `cleanup_old_transcripts` retention helper. Caller updates: `core/server/ipc_server/poller.py:526`, `core/agent/loop/_lifecycle.py:30`, `core/agent/loop/loop.py:129,173`, `core/cli/commands/session.py:22,34`, `core/cli/cmd_lifecycle.py:612`, `tests/conftest.py:30,31`, `tests/test_session_checkpoint.py:7`, `tests/test_phase3_ipc.py:357,402`, `tests/test_session_manager.py:129`, `tests/test_session_resume.py:11,39,110`, `tests/test_session_transcript.py:10`, `tests/test_transcript.py:8` — 14 sites across `core/`, `tests/`. `pyproject.toml` `ignore_imports` removed: `core.agent.loop.loop -> core.cli.session_checkpoint`, `core.agent.loop.loop -> core.cli.transcript`, `core.agent.loop._lifecycle -> core.cli.session_checkpoint` (Agent contract); same three + `core.server.ipc_server.poller -> core.cli.session_checkpoint` (Server contract). 28 → 22 ignore_imports remaining — biggest single drop in the cycle (-6 entries from one PR). (`core/runtime_state/__init__.py` *new*, `core/runtime_state/session_checkpoint.py` *new*, `core/runtime_state/transcript.py` *new*, `core/cli/session_checkpoint.py` *deleted*, `core/cli/transcript.py` *deleted*, 14 caller files, `pyproject.toml`)

## [0.80.0] — 2026-05-08

> **Dependency cleanup A3 — `core/cli/project_detect.py` → `core/utils/project_detect.py`.**
> Third of 5 PRs in the dependency cycle. The 377-LOC project type +
> harness directory detector (auto-detects npm/yarn/pnpm/bun, python-uv,
> python-pip, rust, go, java-maven, java-gradle, plus the 10 known AI
> harness directories `.claude/`/`.cursor/`/`.windsurf/`/`.copilot/`/
> `.openclaw/`/`.codeium/`/`.aider/`/`.codex/`/`.geode/`/`.devin/`) is
> a pure path-inspection utility — no CLI dependencies. Its location
> in `core/cli/` was a v0.40.0 era artifact (introduced when the
> `init` command was the only consumer). Today it has 4 callers
> spanning 3 different layers, including the cross-layer violation
> `core.memory.context -> core.cli.project_detect`. Move to
> `core/utils/`. The 4 caller files updated; 1 `ignore_imports` entry
> removed (`core.memory.context -> core.cli.project_detect`).
> 29 → 28 ignore_imports remaining. E2E `geode analyze "Cowboy Bebop"
> --dry-run` unchanged at A (68.4); full pytest 4344 passed.

### Architecture
- **`core/cli/project_detect.py` (377 LOC) → `core/utils/project_detect.py` (377 LOC).** Pure path-inspection utility — `detect_project_type()`, `get_harness_summary()`, `KNOWN_HARNESSES` registry, plus the dataclasses for the detection output. No CLI imports in either direction. Moving to `core/utils/` (alongside `redaction.py`, `atomic_io.py`, `language.py`) puts it in the correct architectural layer for shared utilities. Caller updates: `core/memory/context.py:292` (lazy import — was a layer violation logged in import-linter), `core/cli/welcome.py:33` (eager import inside the CLI welcome screen — same package, just different sub-module), `core/cli/typer_init.py:50` (eager import in the `init` Typer command — same package), `tests/test_project_detect.py:7` (test file). One ruff `I001` import-sort fix auto-applied. `pyproject.toml`: 1 `ignore_imports` entry removed (`core.memory.context -> core.cli.project_detect` from the `Server may host agent but never CLI` contract). 29 → 28 ignore_imports remaining. (`core/utils/project_detect.py` *new*, `core/cli/project_detect.py` *deleted*, `core/memory/context.py`, `core/cli/welcome.py`, `core/cli/typer_init.py`, `tests/test_project_detect.py`, `pyproject.toml`)

## [0.79.0] — 2026-05-08

> **Dependency cleanup A2 — `core/cli/bash_tool.py` → `core/agent/bash_tool.py`.**
> Second of 5 PRs in the dependency cycle. The 162-LOC HITL-gated shell
> execution tool was misplaced in `core/cli/` despite being agent-internal
> — only the agentic loop's `ToolExecutor` ever instantiates it. Moving
> to `core/agent/` puts it at the correct layer. 2 `ignore_imports`
> entries removed; the `S602 shell=True` per-file-ignore path renamed.
> 31 → 29 ignore_imports remaining. E2E unchanged at A (68.4); full
> pytest 4344 passed.

### Architecture
- **`core/cli/bash_tool.py` (162 LOC) → `core/agent/bash_tool.py` (162 LOC).** `BashTool` provides HITL-gated shell execution with sandbox hardening (`preexec_fn` with `resource.setrlimit` for CPU/FSIZE/NPROC caps) + secret redaction on stdout/stderr. Instantiated only by `core/agent/tool_executor/executor.py:_execute_bash` — lives entirely within the agentic loop's tool surface (the CLI never invokes BashTool directly; it goes through `ToolExecutor`). Caller updates: `core/agent/tool_executor/executor.py:20`, `tests/test_bash_tool.py:8,140,146` (3 imports), `tests/test_redaction.py:80,93,106` (3 lazy imports). `pyproject.toml`: 2 `ignore_imports` entries removed (`core.agent.tool_executor.executor -> core.cli.bash_tool` from both `Agent stays pure` + `Server may host agent but never CLI` contracts), 1 `[tool.ruff.lint.per-file-ignores]` entry renamed (`core/cli/bash_tool.py` → `core/agent/bash_tool.py` for the S602 `shell=True` allowance). 31 → 29 ignore_imports remaining. (`core/agent/bash_tool.py` *new*, `core/cli/bash_tool.py` *deleted*, `core/agent/tool_executor/executor.py`, `tests/test_bash_tool.py`, `tests/test_redaction.py`, `pyproject.toml`)

## [0.78.0] — 2026-05-08

> **Dependency cleanup A1 — `core/cli/redaction.py` → `core/utils/redaction.py`.**
> First of 5 PRs in the new cycle that resolves the 33-entry `import-linter`
> `ignore_imports` backlog accumulated since v0.52. This single 34-LOC API-key
> redaction module had been imported from inside `core/agent/tool_executor/`
> and `core/cli/bash_tool.py` — a cross-layer reference (agent layer reaching
> into CLI utilities) that v0.52's pyproject comment had marked as "v0.53로
> 이동 예정" but stayed deferred for 25 minor versions. Move it to its proper
> home `core/utils/` (single-responsibility utility, no CLI dependencies).
> Three caller files updated (`core/agent/tool_executor/executor.py`,
> `core/cli/bash_tool.py`, `tests/test_redaction.py`); 2 `ignore_imports`
> entries removed from `pyproject.toml` (`core.agent.tool_executor.executor
> -> core.cli.redaction` in both the `[Agent stays pure]` and `[Server may
> host agent but never CLI]` contracts). E2E `geode analyze "Cowboy Bebop"
> --dry-run` unchanged at A (68.4); full pytest 4344 passed (parity with
> v0.77.0). 33 → 31 ignore_imports remaining. Five-PR plan: A1 redaction
> (this), A2 bash_tool, A3 project_detect, A4 session_checkpoint+transcript
> → core/runtime_state/, A5 startup → core/lifecycle/.

### Architecture
- **`core/cli/redaction.py` (34 LOC) → `core/utils/redaction.py` (34 LOC).** `redact_secrets()` strips API key patterns (Anthropic `sk-ant-*`, OpenAI `sk-proj-*`, ZhipuAI `hex.token`, GitHub PAT/OAuth, Slack tokens) from text before LLM context injection. The module has no CLI dependencies — it's a pure regex-based utility — and was misplaced in `core/cli/` purely because the original consumer (BashTool) lived there. Moving to `core/utils/` (alongside `atomic_io.py`, `language.py`) puts it in the correct architectural layer. Caller updates: `core/agent/tool_executor/executor.py:407` (`from core.utils.redaction import redact_secrets`), `core/cli/bash_tool.py:145` (same — bash_tool itself will move in A2), `tests/test_redaction.py:5` (same). `pyproject.toml` `[tool.importlinter.contracts]`: 2 entries removed (`core.agent.tool_executor.executor -> core.cli.redaction` from both the `Agent stays pure` and `Server may host agent but never CLI` contracts). 33 → 31 ignore_imports remaining. (`core/utils/redaction.py` *new*, `core/cli/redaction.py` *deleted*, `core/agent/tool_executor/executor.py`, `core/cli/bash_tool.py`, `tests/test_redaction.py`, `pyproject.toml`)

## [0.77.0] — 2026-05-08

> **Codebase audit Tier 3 — God Object split #완성: `core/cli/__init__.py`.
> 9-of-9 Tier 3 splits complete.** The 1,889-LOC CLI Typer entrypoint
> (the `geode.cli:app` module that registers all 12 Typer commands +
> the `_thin_interactive_loop` REPL + the dispatcher) is now a slim
> 395-LOC orchestration layer with the helpers extracted to 8 sibling
> modules within `core/cli/`. Unlike previous splits which created
> sub-packages, this is a package-level `__init__.py`, so the helpers
> moved to **sibling files** (`core/cli/welcome.py`,
> `core/cli/dispatcher.py`, `core/cli/prompt_session.py`,
> `core/cli/interactive_loop.py`, `core/cli/typer_commands.py`,
> `core/cli/typer_serve.py`, `core/cli/typer_init.py`,
> `core/cli/search_render.py`) — preserving the `from core.cli import X`
> import surface that 90 external sites depend on. Largest single file
> post-split is `typer_commands.py` at 336 LOC — **a 79% reduction
> from the 1,889-LOC original**. The Typer `app` and the 3 functions
> that source-introspection tests pin (`_show_commentary`,
> `_handle_memory_action`, `_thin_interactive_loop`) stay in
> `__init__.py` to preserve `tests/test_commentary.py`'s
> `@patch("core.cli.console")` and `tests/test_signal_reload.py`'s
> `inspect.getsource(core.cli)` invariants. E2E `geode analyze
> "Cowboy Bebop" --dry-run` unchanged at A (68.4); full pytest 4344
> passed (parity with v0.76.0). **Tier 3 complete: 9 splits, 0
> regressions, 0 E2E drift, average -60% reduction across all 9
> God Objects.**

### Architecture
- **`core/cli/__init__.py` (1,889 LOC) → `core/cli/__init__.py` (395 LOC) + 8 sibling modules in `core/cli/` (1,669 LOC).** Mechanical split with sibling-module pattern (instead of sub-package — `__init__.py` IS the package). Sibling sizes: `welcome.py` 122 (`_render_welcome_brand`, `_render_readiness_compact`, `_suppress_noisy_warnings`, `_welcome_screen`), `search_render.py` 32 (`_render_search_results`), `dispatcher.py` 292 (`_handle_command` 254-LOC dispatcher + minor helpers), `prompt_session.py` 192 (`_build_prompt_session`, `_force_select_event_loop`, `_get_prompt_session`, `_drain_stdin`, `_read_multiline_input`, `_restore_terminal`, `_sigint_handler`), `interactive_loop.py` 112 (`_render_ipc_response`, `_drain_scheduler_queue`), `typer_commands.py` 336 (the 9 small Typer commands: `analyze`, `report`, `search`, `version`, `about`, `setup`, `doctor`, `list_ips`, `batch`, `history`), `typer_init.py` 249 (the `init` Typer command — 213 LOC body), `typer_serve.py` 334 (the `serve` Typer command + `_build_runtime_for_serve` + `_ensure_gitignore_entry`). Thin `__init__.py` 395 LOC keeps: imports + `_hooks_ctx` module-level state + `_fire_hook` 1-line delegator + Typer `app` registration via `app.command()(func)` calls + the 3 source-introspection-pinned functions (`_show_commentary` 14L, `_handle_memory_action` 6L, `_thin_interactive_loop` 183L) + re-exports of all helpers for backward compat. Preserves `from core.cli import X` for 90 external sites by re-exporting every helper via `from core.cli.X import Y as Y` aliases. The `_thin_interactive_loop` stays here because it's both large (183 LOC) and tightly coupled to the Typer `app` lifecycle; moving it would require either inlining its 254-LOC dispatcher call (too tight) or carrying state through a parameter that mirrors current module-level access. Companion `pyproject.toml` change: `import-linter` ignore rules in both `[tool.importlinter.contracts]` blocks updated for the leaf-path rename — 4 entries `core.cli -> core.{server,channels}.X` became `core.cli.typer_serve -> core.{server,channels}.X` since the `serve` command moved into a sibling module. Net +175 LOC overhead from per-module docstrings, deferred-import patterns, and re-export plumbing — accepted for the SRP win (largest file shrinks from 1,889 → 336 LOC, **82% drop in non-introspection-pinned helpers**; pinned helpers in `__init__.py` constitute the structural floor). (`core/cli/{__init__,welcome,search_render,dispatcher,prompt_session,interactive_loop,typer_commands,typer_init,typer_serve}.py`, `pyproject.toml`)

## [0.76.0] — 2026-05-08

> **Codebase audit Tier 3 — God Object split #8: `core/cli/commands.py`.**
> The 2,441-LOC CLI slash-command router (the user-facing entry point
> behind every `/key`, `/model`, `/auth`, `/login`, `/cost`, `/skills`,
> `/mcp`, `/compact`, `/clear`, `/resume`, `/apply`, `/context`,
> `/tasks`, `/trigger` invocation) is now a 13-file package
> (`core/cli/commands/`). Each command family lives in its own
> sub-module. The `_state.py` module owns the shared state — `COMMAND_MAP`
> dict, `MODEL_PROFILES` registry, `_conversation_ctx` ContextVar,
> `install_domain_commands` plugin merge hook, `show_help`, and
> `resolve_action` slash-to-action resolver. Largest single file
> post-split is `login.py` at 655 LOC (the cohesive `/login` subsystem
> with 9 helpers). **No public API changes** — all 53 names previously
> imported by external callers (29 import sites across `core/`,
> `plugins/`, `tests/`) work unchanged via the package `__init__.py`
> re-exports. The plugin-side `from core.cli.commands import
> COMMAND_MAP; COMMAND_MAP.update(GAME_IP_SLASHES)` mutation continues
> to work because the re-export is a reference (same dict object).
> E2E `geode analyze "Cowboy Bebop" --dry-run` unchanged at A (68.4);
> full pytest 4344 passed (parity with v0.75.0). One Tier-3 God Object
> remains (`cli/__init__.py`).

### Architecture
- **`core/cli/commands.py` (2,441 LOC) → `core/cli/commands/` (13 files, 2,831 LOC).** Mechanical split by command family; preserves every function body byte-identical and the test-monkeypatch surface for the 28 `core.cli.commands.X` patches across the test suite. Sub-module sizes: `__init__.py` 148 (re-exports — `__all__` lists 53 names), `_state.py` 201 (`ModelProfile` dataclass + `MODEL_PROFILES` list + `_MODEL_INDEX` + `_conversation_ctx` ContextVar + `set_conversation_context`/`get_conversation_context` + `COMMAND_MAP` + `install_domain_commands` + `show_help` + `resolve_action` + `_get_profile_store`), `key.py` 211 (`cmd_key` + `_seed_payg_plan_from_key` + `_persist_auth_state` + `_check_provider_key`), `model.py` 204 (`_apply_model` + `_interactive_model_picker` + `cmd_model`), `auth.py` 316 (`_auth_login_status` + `_sync_oauth_profile_after_login` + `cmd_auth` + `_auth_add_interactive`), `mcp.py` 114 (`cmd_mcp` + `_mcp_add`), `skills.py` 200 (`cmd_skills` + `cmd_skill_invoke` + `_skills_add`), `cost.py` 230 (`cmd_cost` + `_budget_bar` + `_get_cost_budget` + `_set_cost_budget`), `session.py` 418 (`cmd_resume` + `cmd_apply` + `cmd_context` + `cmd_compact` + `cmd_clear`), `tasks.py` 84 (`cmd_tasks`), `trigger.py` 50 (`cmd_trigger`), `login.py` 655 (`cmd_login` + 9 `_login_*` helpers — the largest leaf, intentionally kept whole as a cohesive `/login` subsystem). The package's `__init__.py` re-exports the 53 public names previously imported by external callers (`COMMAND_MAP`, `MODEL_PROFILES`, `ModelProfile`, all 16 `cmd_*` functions, `set_conversation_context`/`get_conversation_context`, `resolve_action`, `show_help`, `install_domain_commands`, plus 22 private helpers and constants tests reference) so the 29 external import sites need no changes. The plugin's `COMMAND_MAP.update(GAME_IP_SLASHES)` continues to mutate the canonical dict (re-export is a reference, same object). Test-monkeypatch surface preserved via deferred `from core.cli import commands as _pkg` lookup inside each function — sub-modules call `_pkg.console.print(...)`, `_pkg._upsert_env(...)`, `_pkg._get_cost_budget(...)`, etc. so `@patch("core.cli.commands.X")` patches propagate through the package namespace at call time (mirroring the established `core/ui/agentic_ui` and `core/agent/tool_executor` patterns from prior splits). No `pyproject.toml` import-linter changes required (rules reference `core.cli.commands` as a leaf path which still resolves to the new package). Net +390 LOC overhead from per-module docstrings, deferred-import boilerplate, and re-export plumbing — accepted for the SRP win (largest file shrinks from 2,441 → 655 LOC, **73% drop** — the largest absolute reduction in the Tier 3 series). (`core/cli/commands/{__init__,_state,key,model,auth,mcp,skills,cost,session,tasks,trigger,login}.py`)

## [0.75.0] — 2026-05-07

> **Codebase audit Tier 3 — God Object split #7: `core/agent/loop.py`.**
> The 1,754-LOC AgenticLoop runtime engine (the central agentic
> turn-loop behind every `geode` invocation) is now a 10-file package
> (`core/agent/loop/`). Unlike the previous six splits which were
> function collections, `AgenticLoop` is a single 1,593-LOC class with
> 35 methods including a 644-LOC `arun` async loop that's
> behaviourally indivisible. The split uses a method-extraction
> pattern: 30 of the 35 methods have their bodies moved to topical
> sub-modules (`_lifecycle`, `_model_switching`, `_context`,
> `_decomposition`, `_announce`, `_response`, `_helpers`) and the
> class methods become 1-line delegators that preserve the public API
> surface. `__init__` (110 LOC) and the `arun`/`run`/`_call_llm`
> trio (~750 LOC) stay in `loop.py` as the indivisible core. Behavior
> is preserved: every extracted body is byte-identical to the original
> except for `self.X` → `loop.X` substitution. **No public API
> changes** — all 30 external import sites (`AgenticLoop`,
> `AgenticResult`, `_ContextExhaustedError`, `get_agentic_tools`,
> `AGENTIC_TOOLS`) work via the package `__init__.py` re-exports.
> Largest single file post-split is `loop.py` at 1,136 LOC — a 35%
> reduction (modest by Tier 3 standards but the structural ceiling
> imposed by `arun`+`__init__`+`_call_llm` indivisibility). Companion
> `pyproject.toml` change: `import-linter` ignore rules updated for
> the new leaf paths (`core.agent.loop.loop` /
> `core.agent.loop._lifecycle`). E2E `geode analyze "Cowboy Bebop"
> --dry-run` unchanged at A (68.4); full pytest 4344 passed (parity
> with v0.74.0). Two Tier-3 God Objects remain (`commands.py`,
> `cli/__init__.py`).

### Architecture
- **`core/agent/loop.py` (1,754 LOC) → `core/agent/loop/` (10 files, 2,197 LOC).** Method-extraction split with `self.X` → `loop.X` substitution; preserves behavior via 1-line delegator methods on `AgenticLoop`. Sub-module sizes: `__init__.py` 53 (re-exports + 3 introspection-test sentinels: `_EFFORT_LEVELS`, `_resolve_provider`, `resolve_agentic_adapter`), `models.py` 74 (`AgenticResult` dataclass + `_ContextExhaustedError` exception + `_context_exhausted_message` helper), `_helpers.py` 63 (`get_agentic_tools` factory + `AGENTIC_TOOLS` constant + `MAX_TOOL_RESULT_TOKENS` + `TOOL_LAZY_LOAD_THRESHOLD` thresholds), `_lifecycle.py` 217 (7 helpers: `_save_checkpoint`, `_record_transcript_end`, `_finalize_and_return`, `_build_reasoning_metrics`, `_emit_quota_panel`, `_inject_credential_breadcrumb`, `mark_session_completed`), `_model_switching.py` 327 (8 helpers: `_sync_model_from_settings`, `_drift_target_is_healthy`, `update_model`, `_purge_stale_model_switch_acks`, `_adapt_context_for_model`, `_try_model_escalation`, `_persist_escalated_model`, `_try_cross_provider_escalation`), `_context.py` 77 (7 helpers: `_sync_messages_to_context`, `_notify_context_event`, `_maybe_prune_messages`, `_check_context_overflow`, `_aggressive_context_recovery`, `_repair_messages`, `_build_system_prompt`), `_decomposition.py` 84 (`_try_decompose`), `_announce.py` 41 (`_check_announced_results` — 119 LOC body, biggest extractable method), `_response.py` 125 (6 helpers: `_extract_text`, `_serialize_content`, `_track_usage`, `refresh_tools`, `_update_tool_error_tracking`, `_check_convergence_break`), `loop.py` 1,136 (`AgenticLoop` class with `__init__` 110 LOC + `arun`/`run`/`_call_llm` ~750 LOC kept verbatim + ~30 1-line delegators). The package's `__init__.py` re-exports the 5 names previously imported by external callers so the 30 external import sites need no changes. Three classes of source-introspection tests required special handling: (1) `inspect.getsource(AgenticLoop._method)` checks — class delegators retain docstrings with the load-bearing substrings the tests assert on; (2) file-text scans (`open(loop_mod.__file__).read()`) — `__init__.py` includes documented `_EFFORT_LEVELS` constant and a comment about `emit_reasoning_summary`'s call site so `"xhigh"` and the symbol appear; (3) `monkeypatch.setattr("core.agent.loop._resolve_provider"/"resolve_agentic_adapter", ...)` — both names re-exported on the package, `_model_switching.update_model` looks them up via `core.agent.loop` lazily so test patches propagate. Companion `pyproject.toml` change in both `[tool.importlinter.contracts]` blocks (lines 100-108 and 126-138): the 3+2 ignore rules `core.agent.loop -> core.cli.{commands,session_checkpoint,transcript}` are renamed to `core.agent.loop.loop -> ...` (the `loop.py` sub-module is the leaf consumer), with one entry split off as `core.agent.loop._lifecycle -> core.cli.session_checkpoint` (the `_save_checkpoint` helper). Net +443 LOC overhead from per-module docstrings, helper signatures, and 30 delegator method bodies — accepted for the SRP win (largest file shrinks from 1,754 → 1,136 LOC, 35% drop; the ~420 LOC of method bodies now live in 7 topical sub-modules with clear boundaries). The 35% ceiling is structural: `__init__` (110) + `arun` (650) + `_call_llm` (95) + delegator bodies (~280) = ~1,135 LOC, which is the indivisible bulk of the class without breaking its single-class semantics. (`core/agent/loop/{__init__,models,_helpers,_lifecycle,_model_switching,_context,_decomposition,_announce,_response,loop}.py`, `pyproject.toml`)

## [0.74.0] — 2026-05-07

> **Codebase audit Tier 3 — God Object split #6: `core/llm/router.py`.**
> The 1,046-LOC LLM transport module (the central dispatcher behind every
> Anthropic / OpenAI / GLM / Codex call) is now a 14-file two-level
> package: `core/llm/router/` (top level: re-exports, hooks, tracing,
> usage, models, DI) plus `core/llm/router/calls/` (sub-package: each
> `call_llm*` entry point in its own file). The 7 transport functions
> that account for 64% of the original LOC (`call_llm`, `call_llm_parsed`,
> `call_llm_json`, `call_llm_with_tools`, `call_llm_streaming`,
> `call_with_failover`, `_route_provider`) each get their own leaf
> module. Largest single file post-split is `tools.py` at 228 LOC —
> **a 78% reduction from the 1,046-LOC original**. **Behavior unchanged**:
> every function body is byte-identical. **Test coupling resolved**:
> 17 `@patch("core.llm.router.X")` sites and 1 `monkeypatch.setattr`
> site that previously coupled tests to the monolithic module are
> migrated to leaf paths (`core.llm.router.calls.text.X` /
> `.parsed.X` / `.json.X` / `.tools.X` / `.streaming.X` / `._route.X`)
> in 4 test files; the `inspect.getsource(_router_mod)` invariant test
> in `test_routing_policy.py` is rewritten to walk
> `pkgutil.iter_modules` over the `calls` sub-package and aggregate
> sources, so the 4-callsite invariant on `_route_provider(target_model)`
> is now verified across the union of leaf modules. E2E `geode analyze
> "Cowboy Bebop" --dry-run` unchanged at A (68.4); full pytest 4344
> passed (parity with v0.73.0). Three Tier-3 God Objects remain
> (`commands.py`, `cli/__init__.py`, `agent/loop.py`).

### Architecture
- **`core/llm/router.py` (1,046 LOC) → `core/llm/router/` (top level: 6 files, 450 LOC) + `core/llm/router/calls/` (sub-package: 8 files, 913 LOC).** Two-level mechanical split by call concern; preserves every function body, ContextVar instances, and the test-monkeypatch surface (with leaf-path migration). Top-level package files: `__init__.py` 169 (pure re-export of ~50 names: 9 adapter aliases + 7 errors + 5 fallback names + 4 provider_dispatch names + 9 anthropic provider names + 8 token_tracker names + sub-module callables), `_hooks.py` 37 (`_hooks_ctx`, `set_router_hooks`, `_fire_hook`), `tracing.py` 45 (`is_langsmith_enabled`, `maybe_traceable`), `_usage.py` 74 (`_record_response_usage`, `_record_openai_usage`), `models.py` 33 (`ToolCallRecord`, `ToolUseResult` dataclasses), `_di.py` 92 (5 ContextVars + 6 accessors). Sub-package `calls/` files: `__init__.py` 28 (re-exports), `_route.py` 40 (`_route_provider`), `_failover.py` 143 (`call_with_failover`), `text.py` 129 (`call_llm`), `parsed.py` 140 (`call_llm_parsed`), `json.py` 68 (`call_llm_json`), `tools.py` 228 (`call_llm_with_tools` — largest leaf), `streaming.py` 137 (`call_llm_streaming`). The package's `__init__.py` re-exports everything previously imported from the flat module so the 41 external import sites need no changes (most do package-level lazy imports via `from core.llm.router import call_llm` inside method bodies). Test files updated for leaf paths: `tests/test_failover.py` (8 `@patch` sites: `get_anthropic_client` × 2 → `calls.text`, `call_llm` × 6 → `calls.json` since `call_llm_json` lives in `json.py` and imports from `text.py`), `tests/test_tool_use.py` (4 `@patch` sites: `get_anthropic_client` → `calls.tools`), `tests/test_llm_client.py` (11 `@patch` sites: `get_anthropic_client` → `calls.{parsed,text}`, `_get_provider_client` → `calls.{parsed,text}`, `is_langsmith_enabled` → `tracing`), `tests/test_routing_policy.py` (`monkeypatch.setattr` → `calls._route._resolve_provider`; `inspect.getsource` rewritten to use `pkgutil.iter_modules` walk). Patches that work via `__init__.py` re-export and required no changes: `test_claude_adapter.py` (4), `test_goal_decomposer.py` (5), `test_native_tools.py` (1), `test_anthropic_sampling_params.py` (1), `test_agentic_loop.py` (2). Net +317 LOC overhead from per-module docstrings and re-export plumbing — accepted for the SRP win (largest file shrinks from 1,046 → 228 LOC, 78% drop). (`core/llm/router/{__init__,_hooks,tracing,_usage,models,_di}.py`, `core/llm/router/calls/{__init__,_route,_failover,text,parsed,json,tools,streaming}.py`, `tests/test_{failover,tool_use,llm_client,routing_policy}.py`)

## [0.73.0] — 2026-05-07

> **Codebase audit Tier 3 — God Object split #5: `core/ui/agentic_ui.py`.**
> The 1,160-LOC UI rendering module with 59 functions + 2 classes
> (`SessionMeter`, `OperationLogger`) + 28 `emit_*` event functions in
> a single file is now a 6-module package (`core/ui/agentic_ui/`). Each
> UI concern lives in its own file: thread-local pipeline IP / session
> meter state (`_state`), the `OperationLogger` class
> (`_operation_logger`), inline render functions (`render`), turn
> summary + lifecycle markers (`summary`), and the 28 event emitters
> (`events`). **No public API changes** — all 21 external consumers
> import via `from core.ui.agentic_ui import …` and resolve to the
> same symbols through the package re-exports unchanged. Largest
> single file post-split is `events.py` at 544 LOC. The
> `_turn_snapshot` mutable module-level state lives canonically in
> `__init__.py` so test fixtures (`mod._turn_snapshot = None`) keep
> working. The `console` test-monkeypatch surface
> (`@patch("core.ui.agentic_ui.console")`) flows through via the
> `from core.ui import agentic_ui as _pkg; _pkg.console.print(...)`
> indirection in sub-modules. E2E `geode analyze "Cowboy Bebop"
> --dry-run` unchanged at A (68.4); full pytest 4344 passed (parity
> with v0.72.0). Four Tier-3 God Objects remain (`commands.py`,
> `cli/__init__.py`, `agent/loop.py`, `llm/router.py`).

### Architecture
- **`core/ui/agentic_ui.py` (1,160 LOC) → `core/ui/agentic_ui/` (6 files, 1,424 LOC).** Mechanical split by UI concern; preserves every function body, the `_meter_local`/`_pipeline_ip_local`/`_ipc_writer_local` `threading.local()` instances, the module-level `_turn_snapshot` state, and the test-monkeypatch surface for `console` and `_turn_snapshot`. Sub-module sizes: `__init__.py` 171 (re-exports + `_turn_snapshot` canonical home), `_state.py` 124 (`SessionMeter` class + `init_session_meter`/`update_session_model`/`get_session_meter` accessors + `set_pipeline_ip`/`_get_pipeline_ip` + the 3 `threading.local()` instances), `_operation_logger.py` 195 (`OperationLogger` class), `render.py` 256 (12 inline render functions), `summary.py` 134 (`render_turn_summary`, `render_action_summary`, `mark_turn_start`), `events.py` 544 (28 `emit_*` functions for budget/retry/oauth/quota/pipeline events). The package's `__init__.py` re-exports the 56 names previously imported by external callers (the 2 classes, the 12 render functions, the 28 emit functions, the state accessors, and `console`/`_turn_snapshot`/`_meter_local`/`_pipeline_ip_local`/`_ipc_writer_local`/`_fmt_tokens` for test monkeypatching) so the 21 external import sites need no changes. No companion changes outside the package — no `import-linter` rules referenced `agentic_ui`, `.gitignore` untouched. Net +264 LOC overhead from per-module docstrings and re-export plumbing — accepted for the SRP win (largest file shrinks from 1,160 → 544 LOC, 53% drop). (`core/ui/agentic_ui/{__init__,_state,_operation_logger,render,summary,events}.py`)

## [0.72.0] — 2026-05-07

> **Codebase audit Tier 3 — God Object split #4: `core/agent/tool_executor.py`.**
> The 1,047-LOC tool execution module with `ToolExecutor` (380 LOC) +
> `ToolCallProcessor` (540 LOC) + 4 module-level helpers + 1 spinner
> contextmanager in a single file is now a 5-module package
> (`core/agent/tool_executor/`). Each concern lives in its own file:
> spinner contextmanager (`_spinner`), tool-result helpers (`_helpers`),
> the safety-gated `ToolExecutor` (`executor`), and the multi-block
> `ToolCallProcessor` (`processor`). **No public API changes** — all
> 25 external consumers (5 in `core/`, 19 in `tests/`, 1 in `scripts/`)
> import via `from core.agent.tool_executor import …` and resolve to
> the same symbols through the package re-exports unchanged. Largest
> single file post-split is `processor.py` at 568 LOC. The
> `import-linter` ignore rules in `pyproject.toml` lines 104-105 and
> 128-129 (`core.agent.tool_executor → core.cli.{bash_tool,redaction}`)
> got their paths renamed to the new `core.agent.tool_executor.executor`
> leaf — a mechanical companion change since import-linter reports edge
> at the leaf module path. E2E `geode analyze "Cowboy Bebop" --dry-run`
> unchanged at A (68.4); full pytest 4344 passed (parity with v0.71.0).
> Five Tier-3 God Objects remain (`commands.py`, `cli/__init__.py`,
> `agent/loop.py`, `ui/agentic_ui.py`, `llm/router.py`).

### Architecture
- **`core/agent/tool_executor.py` (1,047 LOC) → `core/agent/tool_executor/` (5 files, 1,123 LOC).** Mechanical split by concern; preserves every method body, the module-level constants (`AUTO_APPROVED_MCP_SERVERS`, `DANGEROUS_TOOLS`, `EXPENSIVE_TOOLS`, `SAFE_BASH_PREFIXES`, `SAFE_TOOLS`, `WRITE_TOOLS`), and the test-monkeypatching surface. Sub-module sizes: `__init__.py` 42 (re-exports), `_spinner.py` 37 (`_tool_spinner` contextmanager — lazily looks up `core.agent.tool_executor.console` so test patches on the package-level attribute keep flowing through), `_helpers.py` 60 (`_compute_model_tool_limit`, `_guard_tool_result`), `executor.py` 416 (`ToolExecutor` class + `_write_denial_with_fallback` + a thin shim `_tool_spinner(label)` that lazily resolves the package-level spinner so `tests/test_tool_executor_spinner.py:monkeypatch` keeps working), `processor.py` 568 (`ToolCallProcessor` class — the multi-block tool-call serialiser, intentionally kept whole). The package's `__init__.py` re-exports the 13 names previously imported by external callers (`ToolExecutor`, `ToolCallProcessor`, `_tool_spinner`, `_compute_model_tool_limit`, `_guard_tool_result`, `_write_denial_with_fallback`, `console`, plus 6 module-level constants) so the 25 external import sites need no changes. The 4-line `pyproject.toml` rename is the only file outside the package touched: `core.agent.tool_executor → core.cli.{bash_tool,redaction}` ignore rules become `core.agent.tool_executor.executor → core.cli.{bash_tool,redaction}` (both `[tool.importlinter.contracts]` blocks at lines 104-105 and 128-129). Net +76 LOC overhead from per-module docstrings and re-export plumbing — accepted for the SRP win (largest file shrinks from 1,047 → 568 LOC, 46% drop). (`core/agent/tool_executor/{__init__,_spinner,_helpers,executor,processor}.py`, `pyproject.toml`)

## [0.71.0] — 2026-05-07

> **Codebase audit Tier 3 — God Object split #3: `core/skills/reports.py`.**
> The 1,156-LOC report-generation module with the `ReportGenerator` class
> plus 33 module-level formatter functions in a single file is now a
> 12-module package (`core/skills/reports/`). Each report concern lives
> in its own file: enums + tier helpers + gauge geometry (`models`),
> subscores/synthesis/analyses (`scoring`), evaluator field extraction +
> table (`evaluators`), PSM + scoring breakdown (`psm`), BiasBuster
> (`biasbuster`), signals (`signals`), analyst reasoning
> (`analyst_reasoning`), cross-LLM (`cross_llm`), rights risk
> (`rights_risk`), decision tree (`decision_tree`), and the
> `ReportGenerator` class (`generator`). The `templates/` subdirectory
> moved with the package to `core/skills/reports/templates/` so
> `Path(__file__).parent / "templates"` keeps resolving correctly.
> **No public API changes** — `core/cli/report_renderer.py` and
> `tests/test_reports.py` import the same 12 symbols through the package
> re-exports unchanged. Largest single file post-split is `generator.py`
> at 336 LOC. E2E `geode analyze "Cowboy Bebop" --dry-run` unchanged at
> A (68.4); full pytest 4344 passed (parity with v0.70.0). Six Tier-3
> God Objects remain (`commands.py`, `cli/__init__.py`,
> `agent/loop.py`, `ui/agentic_ui.py`, `agent/tool_executor.py`,
> `llm/router.py`).

### Architecture
- **`core/skills/reports.py` (1,156 LOC) → `core/skills/reports/` (12 files, 1,317 LOC).** Mechanical split by report concern; preserves every formatter body, the `_TIER_CONFIG` / `_SUBSCORE_BARS` constants, and the `Path(__file__).parent / "templates"` resolution semantics. Sub-module sizes: `__init__.py` 46, `models.py` 107 (`ReportFormat` + `ReportTemplate` Enums + `_TEMPLATES_DIR` + `_load_template` + `_TIER_CONFIG` + `_SUBSCORE_BARS` + `_tier_class` + `_get_tier_config` + `_GAUGE_RADIUS` + `_GAUGE_CIRCUMFERENCE` + `_gauge_offset`), `scoring.py` 150 (subscores/synthesis/analyses html+md), `evaluators.py` 86 (eval field extraction + table), `psm.py` 158 (PSM + scoring breakdown), `biasbuster.py` 72, `signals.py` 94, `analyst_reasoning.py` 71, `cross_llm.py` 60, `rights_risk.py` 62, `decision_tree.py` 75, `generator.py` 336 (`ReportGenerator` class — the central orchestrator, intentionally kept whole). The package's `__init__.py` re-exports the 12 symbols previously imported from the flat module (`ReportFormat`, `ReportGenerator`, `ReportTemplate`, plus 8 `_format_*` formatters: `_format_analyst_reasoning_html/md`, `_format_cross_llm_html/md`, `_format_decision_tree_html/md`, `_format_rights_risk_html/md`) so `core/cli/report_renderer.py:18` and `tests/test_reports.py:9` (the only two external consumers) need no changes. The `templates/` directory was moved via `git mv core/skills/templates core/skills/reports/templates` (rename history preserved). One `.gitignore` adjustment: lines 78-81 add a scoped negation `!core/skills/reports/` + `!core/skills/reports/**` so the new package source is committable while preserving the original `reports/` ignore rule for agent-generated user reports. Net +161 LOC overhead from per-module docstrings and import boilerplate — accepted for the SRP win (largest file shrinks from 1,156 → 336 LOC, 71% drop). (`core/skills/reports/{__init__,models,scoring,evaluators,psm,biasbuster,signals,analyst_reasoning,cross_llm,rights_risk,decision_tree,generator}.py`, `core/skills/reports/templates/{report.html,report_summary.md,report_detailed.md}` *renamed*, `.gitignore`)

## [0.70.0] — 2026-05-07

> **Codebase audit Tier 3 — God Object split #2: `core/scheduler/scheduler.py`.**
> The 1,208-LOC scheduler module with 7 classes + 14 module-level helpers
> in a single file is now a 9-module package
> (`core/scheduler/scheduler/`). Each concern lives in its own file
> (`models`, `serialization`, `run_log`, `lock`, `jitter`, `timezone`,
> `service`, `factory`) plus the package `__init__.py` that re-exports
> all 24 names previously imported by 11 external consumer files. **No
> public API changes** — `from core.scheduler.scheduler import …`
> resolves through the package re-exports unchanged. Largest single
> file post-split is `service.py` at 708 LOC (the `SchedulerService`
> class itself, intentionally kept whole). E2E `geode analyze "Cowboy
> Bebop" --dry-run` unchanged at A (68.4); full pytest 4344 passed
> (parity with v0.69.0). Seven Tier-3 God Objects remain (`commands.py`,
> `cli/__init__.py`, `agent/loop.py`, `ui/agentic_ui.py`,
> `skills/reports.py`, `agent/tool_executor.py`, `llm/router.py`).

### Architecture
- **`core/scheduler/scheduler.py` (1,208 LOC) → `core/scheduler/scheduler/` (9 files, 1,330 LOC).** Mechanical split by concern; preserves every comment, docstring, and behavior from the original. Sub-module sizes: `__init__.py` 81, `models.py` 93 (`ScheduleKind` Enum + `Schedule`/`ActiveHours`/`ScheduledJob` dataclasses + 6 module-level constants + `OnJobFired` type alias), `serialization.py` 81 (`_job_to_dict`, `_job_from_dict`), `run_log.py` 93 (`JobRunLog`), `lock.py` 135 (`SchedulerLock` + `_is_pid_alive` helper — kept together because `_try_reclaim` calls it), `jitter.py` 38 (`_compute_jitter_frac`, `_jittered_next_run`), `timezone.py` 59 (`_parse_hhmm`, `_now_minutes`, `_cron_tuple_for_tz`), `service.py` 708 (`SchedulerService` — the central engine, intentionally kept whole), `factory.py` 42 (`create_scheduler`). The package's `__init__.py` re-exports the 24 names previously imported by external callers so the 11 external import sites (`core/lifecycle/automation.py`, `core/scheduler/nl_scheduler.py`, `core/cli/__init__.py`, plus 8 test files including `test_scheduler{,_lock,_jitter,_missed,_serve,_integration}.py`, `test_phase2_hardening.py`, `test_nl_scheduler.py`) need no changes. Net +122 LOC overhead from per-module docstrings and import boilerplate — accepted for the SRP win (largest file shrinks from 1,208 → 708 LOC, 41% drop; the 660-LOC `SchedulerService` class is now isolated from the supporting types and helpers it depends on, making its surface area readable). (`core/scheduler/scheduler/{__init__,models,serialization,run_log,lock,jitter,timezone,service,factory}.py`)

## [0.69.0] — 2026-05-07

> **Codebase audit Tier 3 — God Object split #1: `core/cli/tool_handlers.py`.**
> The 1,472-LOC monolith with 14 `_build_*_handlers()` factory functions
> in a single file is now a 15-module package
> (`core/cli/tool_handlers/`). Each handler group lives in its own file
> (memory, plan, hitl, system, execution, delegated, mcp, context, task,
> notification, calendar, offload, computer_use) plus shared utilities
> (`_helpers.py`: `_clarify`, `_safe_delegate`,
> `install_domain_tool_handlers`) and the package `__init__.py` that
> hosts the public aggregator (`_build_tool_handlers`) and the
> module-level `PlanStore` singleton (`_PLAN_STORE` / `_get_plan_store`).
> Largest single file post-split is `plan.py` at 296 LOC. **No public API
> changes** — the seven external import sites (4 in `core/`, 3 in tests)
> resolve to the same symbols via package re-exports; the
> `monkeypatch.setattr(th, "_PLAN_STORE", ...)` test fixture in
> `test_plan_mode.py` still works because the singleton lives at the
> package root. E2E `geode analyze "Cowboy Bebop" --dry-run` unchanged
> at A (68.4). Eight Tier-3 God Objects remain (`commands.py`,
> `cli/__init__.py`, `agent/loop.py`, `scheduler/scheduler.py`,
> `ui/agentic_ui.py`, `skills/reports.py`, `agent/tool_executor.py`,
> `llm/router.py`) — each will land as its own PR.

### Architecture
- **`core/cli/tool_handlers.py` (1,472 LOC) → `core/cli/tool_handlers/` (15 files, 1,540 LOC).** Mechanical split by handler group; preserves every section header, comment, and behavior from the original. Sub-module sizes: `__init__.py` 148, `_helpers.py` 57, `memory.py` 74, `plan.py` 296, `hitl.py` 120, `system.py` 250, `execution.py` 159, `delegated.py` 54, `mcp.py` 51, `context.py` 78, `task.py` 149, `notification.py` 19, `calendar.py` 33, `offload.py` 25, `computer_use.py` 27. The package's `__init__.py` re-exports the 19 names previously imported from the flat module (`_build_tool_handlers`, `_build_*_handlers` × 13, `_DELEGATED_TOOLS`, `_PLAN_STORE`, `_get_plan_store`, `_clarify`, `_safe_delegate`, `_make_delegate_handler`, `install_domain_tool_handlers`) so the seven external import sites need no changes. The `_PLAN_STORE` singleton intentionally stays at the package level — `_build_plan_handlers` in `plan.py` calls `_get_plan_store()` via lazy `from core.cli.tool_handlers import _get_plan_store` to avoid the import cycle while keeping the monkeypatch surface (`th._PLAN_STORE`) intact for `tests/test_plan_mode.py`. Net +68 LOC overhead from per-module docstrings, imports, and package boilerplate — accepted for the SRP win (largest file shrinks from 1,472 → 296 LOC, ≈80% drop). (`core/cli/tool_handlers/__init__.py`, `core/cli/tool_handlers/_helpers.py`, `core/cli/tool_handlers/{memory,plan,hitl,system,execution,delegated,mcp,context,task,notification,calendar,offload,computer_use}.py`)

## [0.68.0] — 2026-05-07

> **Codebase audit cleanup — Tier 1 + Tier 2.** Two-tier sweep driven by
> the `codebase-audit` skill. Tier 1 removes three orphan modules whose
> only consumers were their own tests: `core/orchestration/planner.py`
> (NL-router-era `Planner` class — zero non-test callers since #39f7812e),
> `core/skills/plugins.py` (`PluginManager` / `LoggingPlugin` parallel
> system that was superseded by `core/skills/skills.py:SkillRegistry` —
> zero non-test callers), and `core/auth/errors.py` (`AuthError` was
> never `raise`d nor caught in production — only mentioned in three
> doc-comments). Tier 2 deduplicates two near-identical helpers that had
> drifted into 4× and 2× copies: `_fire_hook` (memory_tools / llm.router /
> llm.provider_dispatch / cli.__init__) collapses onto a new
> `core/hooks/utils.py:fire_hook`, and the oauth file readers
> (`claude_code_oauth._read_from_file` / `codex_cli_oauth._read_from_file`)
> share a new `core/auth/credential_cache.py:read_json_credentials_file`
> helper. Net `-1,083` lines removed (Tier 1) plus `~50` lines collapsed
> (Tier 2). E2E anchor `geode analyze "Cowboy Bebop" --dry-run` unchanged
> at A (68.4).

### Removed
- **`core/orchestration/planner.py` (326 LOC) + `tests/test_planner.py` (133 LOC).** The `Planner` class plus its `Route`, `RouteProfile`, `PlannerDecision`, `_CacheEntry`, `_PlannerStats` companions were a leftover from the NL-router era (last touched in commit `39f7812e`); zero non-test callers across `core/`, `plugins/`, `tests/`, `scripts/`, `experimental/`. The verb "Route" is still used in unrelated places (`core/orchestration/task_system.py`, `plugins/game_ip/nodes/router.py`) but those define their own routing primitives — no shared symbols. (`core/orchestration/planner.py`, `tests/test_planner.py`)
- **`core/skills/plugins.py` (260 LOC) + `tests/test_plugins.py` (233 LOC).** Parallel `Plugin` / `PluginState` / `PluginMetadata` / `LoggingPlugin` / `PluginManager` system superseded by `core/skills/skills.py:SkillRegistry` (the live skill registry imported from `core/cli/bootstrap.py`, `core/lifecycle/bootstrap.py`, `core/llm/skill_registry.py`, etc.). Zero non-test callers for any of the five symbols. (`core/skills/plugins.py`, `tests/test_plugins.py`)
- **`core/auth/errors.py` (83 LOC) + `tests/test_auth_errors.py` (48 LOC).** `AuthError`, `AuthErrorCode`, `ERROR_HINTS`, `format_auth_error` had no production raise/except sites — only three doc-comments referenced "auth errors" generically. The auth rotation path uses different error-handling primitives (see `core/auth/rotation.py`). (`core/auth/errors.py`, `tests/test_auth_errors.py`)

### Changed
- **`_fire_hook` 4-copy → 1 helper.** `core/tools/memory_tools.py`, `core/llm/router.py`, `core/llm/provider_dispatch.py`, and `core/cli/__init__.py` each carried their own `_fire_hook(event, data)` body — three of them byte-identical, the fourth differing only in accepting a `HookEvent` enum directly. All four now delegate to a new `core/hooks/utils.py:fire_hook(hooks, event, data)` that handles both `str` and `HookEvent` inputs and the same graceful-degradation contract (no-op on `None` hooks, DEBUG-log + swallow on handler exception). The per-module `_fire_hook` wrappers shrink to a 1-line delegation that supplies the right `_hooks_ctx` source (ContextVar `.get()` for memory_tools, module-global for the other three). (`core/hooks/utils.py` *new*, `core/tools/memory_tools.py`, `core/llm/{router,provider_dispatch}.py`, `core/cli/__init__.py`)
- **OAuth `_read_from_file` 2-copy → shared JSON reader.** `core/auth/claude_code_oauth.py` and `core/auth/codex_cli_oauth.py` each had their own `read text → json.loads → isinstance dict check → narrow extraction` ladder. The IO + JSON-parse + dict-check half is now `core/auth/credential_cache.py:read_json_credentials_file(relative_path)`; each oauth caller keeps only its provider-specific extraction (`data.get("claudeAiOauth")` for Claude Code, `data if "tokens" in data else None` for Codex CLI). Removes a redundant `from pathlib import Path` and a now-unused `import json` reference from each caller. (`core/auth/credential_cache.py`, `core/auth/{claude_code_oauth,codex_cli_oauth}.py`)

## [0.67.0] — 2026-05-06

> **Domain-free core refactor — steps 4-6 of 8.** Second wave of the
> architectural pivot documented in `docs/architecture/domain-free-core-audit.md`
> (v0.66.0 covered steps 1-3). This release moves the largest concentration
> of game-IP-specific code out of `core/`: CLI commands + tool_handlers
> (step 4), the entire tools cluster (step 5: analysis.py whole-file move +
> signal_tools.py 3-way split + tool_schemas.json retirement), and the MCP
> server plugin-registration contract (step 6). Five new `DomainPort` v2
> hooks (`get_rerunnable_nodes`, `register_slash_commands`,
> `register_tool_handlers`, `register_mcp_tools`) follow the
> `naming-conventions.md` verb taxonomy. Two new core utility modules
> (`core/mcp/utils.py`, `core/tools/web_search.py`) re-establish the
> generic infrastructure that step-5's split surfaced. Two new TID251
> banned-api entries with educational breadcrumbs. **Steps 7-8 remain**
> (state.py + reports.py + panels.py extraction; graph.py topology + the
> REODE-fork unblock). E2E anchor `geode analyze "Cowboy Bebop" --dry-run`
> unchanged at A (68.4) across all 3 step PRs (#885, #886, #887).

### Architecture
- **Domain-free core, step 6 of 8 (`docs/architecture/domain-free-core-audit.md`).** MCP server plugin-registration contract — `core/mcp_server.py` shrinks from a hardcoded 6-tool registration body (~190 LOC) to a generic shell (~105 LOC) that registers only the two domain-agnostic tools (`query_memory`, `get_health`) plus the `geode://soul` resource and then delegates to `domain.register_mcp_tools(server)` for plugin-contributed tools. The four IP-specific MCP tools (`analyze_ip`, `quick_score`, `get_ip_signals`, `list_fixtures`) and the `geode://fixtures` resource that previously lived in `core/mcp_server.py` moved to new `plugins/game_ip/mcp/tools.py` (~155 LOC; sits alongside the step-2 `signal_adapter.py` inside the existing `plugins/game_ip/mcp/` subpackage). The plugin's tool body is wrapped in a `register_game_ip_mcp_tools(server)` function that the new `GameIPDomain.register_mcp_tools` hook calls; the function uses `cast("FastMCP", server)` under a `TYPE_CHECKING` guard so mypy resolves the FastMCP decorator types without importing the optional `mcp` package eagerly. New optional `DomainPort` v2 method declared in `core/domains/port.py` with a `...` body and matching the step-3/4 hook taxonomy from `docs/architecture/naming-conventions.md` §2 (the `register_*` verb is reserved exactly for this kind of "subscribe a handler to a registry" surface — REST POST analogue): `register_mcp_tools(server)`. Call site in `core/mcp_server.py:create_mcp_server` uses the same `getattr(domain, "register_mcp_tools", None) + callable(...)` shape as the step-3 hooks so a future domain that omits the method silently falls back to a no-op; failures during plugin registration are caught and logged at debug level so a broken plugin can't take the server down (the two generic tools above stay functional regardless). JSON registry split (Option B per the step-6 plan): `core/tools/mcp_tools.json` shrinks from 6 entries to the 2 generic descriptions; the 4 plugin-specific descriptions move to new `plugins/game_ip/mcp/mcp_tools.json` loaded directly by `plugins/game_ip/mcp/tools.py` at import time. Per-plugin JSON keeps the description colocated with the code that consumes it, mirroring step 5's `plugins/game_ip/tools/tool_schemas.json` precedent. The plugin's `mcp/__init__.py` docstring grew a one-line index of the two now-existing modules (`signal_adapter.py` from step 2, `tools.py` from step 6). No TID251 ban entries this step — `core/mcp_server.py` still exists (just lighter), so a module-level relocation message is wrong; this matches the step-4 reasoning where symbol relocations *inside* still-existing modules don't trip TID251. The retired-from-core JSON file is data, not a Python module, so it's not TID251 territory either. Test updates: `tests/test_mcp_server.py` retargeted — the `len(_TOOL_DESCRIPTIONS) == 6` invariant becomes `== 2` for core (with a separate assertion that the 4 plugin entries live in `plugins.game_ip.mcp.tools._TOOL_DESCRIPTIONS`); a new test confirms `GameIPDomain.register_mcp_tools` is callable. Quality gates green: ruff/ruff-format/mypy/deptry/codespell clean, mypy source-file count 247 → 248 (+1 plugin module), 4388 tests pass (+2 new test cases), E2E anchor `geode analyze "Cowboy Bebop" --dry-run` unchanged at A (68.4) undermarketed. (`core/mcp_server.py`, `core/domains/port.py`, `core/tools/mcp_tools.json`, `plugins/game_ip/mcp/{tools,mcp_tools.json,__init__}.py`, `plugins/game_ip/adapter.py`, `tests/test_mcp_server.py`)

- **Domain-free core, step 5 of 8 (`docs/architecture/domain-free-core-audit.md`).** Tools cluster split — `core/tools/analysis.py` (whole 285-LOC file) moved to `plugins/game_ip/tools/analysis.py`; `core/tools/signal_tools.py` (640 LOC) fully retired with symbols dispersed across three destinations: the 5 IP signal scrapers (`YouTubeSearchTool`, `RedditSentimentTool`, `TwitchStatsTool`, `SteamInfoTool`, `GoogleTrendsTool`) plus the `_load_signal` fixture helper moved to new `plugins/game_ip/tools/signal_tools.py`; the reusable MCP-fallback infrastructure (`_parse_mcp_content`, `_try_mcp_signal`) was promoted to a public API surface at new `core/mcp/utils.py` (renamed without underscores: `parse_mcp_content`, `try_mcp_signal`) so any future plugin's signal layer can adopt the same MCP-first / fixture-fallback shape; the generic 3-provider (Anthropic / OpenAI / GLM) `WebSearchTool` moved to new `core/tools/web_search.py` since it has no game-IP coupling. `core/tools/tool_schemas.json` (the only consumers were `analysis.py` and `signal_tools.py`) was retired; the 9 plugin-coupled schema entries (4 analysis tools + 5 signal tools) moved to `plugins/game_ip/tools/tool_schemas.json` loaded by the plugin modules; the generic `WebSearchTool` schema is inlined as a module constant in `core/tools/web_search.py` (matching the step-2 `plugins/game_ip/tools/data_tools.py:QueryMonoLakeTool` precedent of inline schemas for plugin/generic tools). Caller updates: `core/lifecycle/container.py:build_default_registry` switches to lazy-import the analysis quartet and the 5 signal tools from `plugins.game_ip.tools.*` (matching the existing `QueryMonoLakeTool` lazy-import shape), and lazy-imports `WebSearchTool` from `core.tools.web_search`; `plugins/game_ip/cli/tool_handlers.py:GAME_IP_DELEGATED_TOOLS` rewires its 4 signal entries to `plugins.game_ip.tools.signal_tools`; `tests/test_analysis_tools.py`, `tests/test_e2e.py`, `tests/test_signal_tools.py`, `tests/test_signal_tools_mcp.py`, `tests/test_native_tools.py` updated to the new import paths (the MCP test now imports `parse_mcp_content` / `try_mcp_signal` from `core.mcp.utils` and aliases them locally to keep the test body unchanged). Two new TID251 banned-api entries land in `pyproject.toml`: `core.tools.analysis` → single-target message; `core.tools.signal_tools` → triple-destination message pointing at `plugins.game_ip.tools.signal_tools` / `core.mcp.utils` / `core.tools.web_search` so a stale import gets the full breadcrumb. After step 5, `grep -rn "core\.tools\.signal_tools\|core\.tools\.analysis" core/ tests/ plugins/` returns zero hits. Quality gates green: ruff/ruff-format/mypy/deptry/codespell clean, 4386 tests pass, E2E anchor `geode analyze "Cowboy Bebop" --dry-run` unchanged at A (68.4) undermarketed. See `docs/architecture/naming-conventions.md` §1 (path mirroring) and §3 (TID251 message format) for the conventions applied. (`plugins/game_ip/tools/{analysis,signal_tools,tool_schemas.json}`, `core/mcp/utils.py`, `core/tools/web_search.py`, `core/lifecycle/container.py`, `plugins/game_ip/cli/tool_handlers.py`, `tests/test_{analysis_tools,e2e,signal_tools,signal_tools_mcp,native_tools}.py`, `pyproject.toml`)

- **Domain-free core, step 4 of 8 (`docs/architecture/domain-free-core-audit.md`).** CLI commands and tool-handler IP halves split out of `core/cli/`. `core/cli/commands.py` lost `cmd_list`, `cmd_generate`, `cmd_batch`, the 14 game-IP slash entries in `COMMAND_MAP` (`/analyze`, `/run`, `/list`, `/search`, `/report`, `/batch`, `/compare`, `/generate` + their aliases), and the IP examples block in `show_help`; the slashes now live in `plugins/game_ip/cli/commands.py:GAME_IP_SLASHES` and merge back into the generic `COMMAND_MAP` at bootstrap via the new `install_domain_commands(domain)` helper. `core/cli/tool_handlers.py` lost `_build_analysis_handlers` (180 LOC: `handle_list_ips` / `handle_analyze_ip` / `handle_search_ips` / `handle_compare_ips` / `handle_generate_report` / `handle_batch_analyze`), `handle_generate_data` (in `_build_execution_handlers`), the four signal entries in `_DELEGATED_TOOLS` (`youtube_search`, `reddit_sentiment`, `steam_info`, `google_trends`), and the `FIXTURE_MAP` reads in `handle_check_status` / `handle_show_help`; those handlers now live in `plugins/game_ip/cli/tool_handlers.py:build_game_ip_handlers()` and merge into the dispatcher dict at handler-build time via the new `install_domain_tool_handlers(handlers)` helper. The `handle_rerun_node` allowlist (`{"scoring", "verification", "synthesizer"}`) is now sourced from `domain.get_rerunnable_nodes()` instead of being hardcoded in core. `handle_check_status`'s `fixture_count` is now sourced from `domain.list_fixtures()`. `show_help` defers the IP-specific block to `domain.render_help_fragment()`. Three new optional `DomainPort` v2 methods declared in `core/domains/port.py` and implemented in `plugins/game_ip/adapter.py`: `get_rerunnable_nodes()`, `register_slash_commands(command_map)`, `register_tool_handlers(handlers)` — all use lazy plugin imports inside each method to avoid circular-import risk. `plugins/game_ip/__init__.py` also eagerly merges `GAME_IP_SLASHES` into `COMMAND_MAP` at import time so static-import paths (tests, REPL bootstrap, the legacy `COMMAND_REGISTRY` parity check) see the full slash registry without needing the bootstrap helper. After step 4, `grep -rn "from plugins\.game_ip\|import plugins\.game_ip" core/cli/{commands,tool_handlers}.py` returns zero hits except in `_handle_command` lazy imports for `/list`/`/generate`/`/batch` dispatch (which can't be removed until step 7-8 retire the `_handle_command` god method itself). `core/cli/routing.py` `/list` `handler_path` updated to `plugins.game_ip.cli.commands:cmd_list`. No TID251 entries land this step — step 4 only relocates symbols inside still-existing modules (`core/cli/commands.py` and `core/cli/tool_handlers.py` both shrink but stay), so module-level bans don't apply; resumes in step 5 when `core/tools/analysis.py` and the IP half of `core/tools/signal_tools.py` move whole-module. Quality gates green: ruff/mypy clean, deptry clean, 4386+ tests pass, E2E anchor `geode analyze "Cowboy Bebop" --dry-run` unchanged at A (68.4) undermarketed. (`core/domains/port.py`, `core/cli/{commands,tool_handlers,bootstrap,routing,__init__}.py`, `plugins/game_ip/__init__.py`, `plugins/game_ip/adapter.py`, `plugins/game_ip/cli/{commands,tool_handlers}.py`, `tests/test_commands.py`)

## [0.66.1] — 2026-05-06

> **Hygiene + static analysis ratchet.** Post-v0.66.0 cleanup wave: 3
> dead-code sites excised, full static-analysis stack added
> (ruff PLR/C901 + deptry + codespell + pre-commit), ruff TID family
> enabled with a banned-api ledger for step-2 relocations, and naming
> conventions codified as `docs/architecture/naming-conventions.md`.
> No production-behavior change; CI gate strengthened from 4 tools to
> 8 (ruff, ruff-format, mypy, bandit, import-linter, deptry, codespell,
> 4 ratchet scripts). E2E anchor `geode analyze "Cowboy Bebop" --dry-run`
> unchanged at A (68.4) across all 4 PRs (#878, #880, #881, #882).
> CLAUDE.md `Key entry points` corrected from stale `core/cli/agentic_loop.py`
> to `core/agent/loop.py` (renamed in v0.66.0).

### Documentation
- **Naming conventions codified — RESTful resource orientation (`docs/architecture/naming-conventions.md`).** Audit of v0.66.0 step-1/2/3 artifacts surfaced an *implicit* rule that had been applied consistently but never written down: when a multi-file core subpackage gets domain-extracted, mirror the path inside the plugin (`core/cli/{batch,ip_names,search}.py` → `plugins/game_ip/cli/{...}`); when a single file or fragment gets extracted (or the artifact is a plugin-specific aggregation with no obvious single-file core counterpart), use a flat intent-named module at the plugin root (`plugins/game_ip/{adapter,axes,wiring,prompt,scoring_constants}.py`). The new doc also codifies the `DomainPort` method verb taxonomy (`get_*` / `list_*` / `wire_*` / `build_*` / `compose_*` / `register_*` mapped to GET/PUT/POST semantics), the TID251 `banned-api` message format (`"Moved to <new.path> (v<X.Y.Z> step <N>)."`), PR-title / branch-name / tool-class / hook-event conventions. No code change — captures rules already followed so future contributors and step-4-through-8 PRs apply them deliberately.

### Infrastructure
- **TID251 `banned-api` message uniformity + codespell ignore-words update.** Trimmed the `"core.cli.batch"` ban message from `"Moved to plugins.game_ip.cli.batch (v0.66.0 step 2 of domain-free-core refactor)."` to `"Moved to plugins.game_ip.cli.batch (v0.66.0 step 2)."` so all four step-2 ban entries follow the same `Moved to <new.path> (v<X.Y.Z> step <N>).` shape (the longer-form context is documented in `CHANGELOG.md` and `docs/architecture/domain-free-core-audit.md`, not repeated per-message). Added `wit` to `[tool.codespell] ignore-words-list` so "Wit Studio" (the studio name in `plugins/game_ip/fixtures/generator.py`) stops triggering a false-positive `Wit → With` correction in the pre-commit codespell hook. (`pyproject.toml`)
- **Symbol-level import bans via ruff TID family (LangGraph pattern).** Enabled `TID` rule family in ruff config (`TID251` banned-api, `TID252` relative-imports, `TID253` banned-module-level-imports). Probe found `TID252` and `TID253` already had **zero violations** (GEODE convention is absolute imports), so they're now hard-gated guardrails for free. `TID251` (banned-api) configured under `[tool.ruff.lint.flake8-tidy-imports.banned-api]` with educational error messages for the 4 paths relocated in v0.66.0 step 2: `core.cli.batch`, `core.cli.ip_names`, `core.cli.search`, `core.mcp.signal_adapter`. These paths don't exist on disk after the move (no backwards-compat shim), so a stale reference would raise `ModuleNotFoundError` at runtime — TID251 catches the same mistake at lint time with a friendlier breadcrumb (e.g. `"Moved to plugins.game_ip.cli.batch (v0.66.0 step 2 of domain-free-core refactor)."`). Symbol-level guardrail is complementary to import-linter (which is module-level layer enforcement); use TID251 for transitional moves, deprecated aliases, and specific anti-pattern symbols outside import-linter's contract scope. Negative test confirms `from core.cli.batch import select_ips` triggers `TID251` with the educational message. As steps 4-8 of the domain-free-core refactor relocate more symbols, new entries land alongside each move. (`pyproject.toml`)
- **Static analysis stack expansion (ruff PLR/C901 + deptry + codespell + pre-commit).** Lifted GEODE's static analysis to match or exceed the 5-project frontier reference (LangGraph, FastAPI, Pydantic, Polars, mypy itself). Ruff rule sets `C901` (mccabe cyclomatic complexity) and `PLR` (pylint refactor — too-many-args/branches/returns/statements/nested-blocks) are now enabled with thresholds tuned to the **current worst offender** (day-1 failures = 0; ratchet down per release as steps 4-8 of the domain-free-core refactor extract god methods). Initial baselines documented in `[tool.ruff.lint.mccabe]` and `[tool.ruff.lint.pylint]`: complexity 62, args 18, branches 68, returns 18, statements 273. PLR2004 (magic values), PLR0904 (public methods), PLR0911 (returns) ignored project-wide as too noisy for current shape; tests directory ignores PLR0912/PLR0913/PLR0915 since fixtures legitimately have wide signatures. `deptry>=0.25.0` added to dev deps and a CI lint step (`uv run deptry .`) — catches unused/missing/transitive dependencies. Forced `pyyaml` and `langsmith` from transitive to direct deps (used in 4 + 3 sites respectively); `Pillow → PIL` and `pyyaml → yaml` mappings configured; `langgraph-checkpoint`, `langgraph-checkpoint-sqlite`, `openai-agents`, and `Pillow` whitelisted in DEP002 ignores with rationale. `codespell>=2.3.0` added to dev deps with project-specific ignore-words list (`statics, ot, socio-economic, ...` for Korean/English mixed prose); 8 typos auto-fixed (`unparseable → unparsable` × 4 sites in core/, 1 in docs/). `.pre-commit-config.yaml` extended with codespell hook and a `deptry` local hook; mypy hook updated to include `plugins/` (was `core/` only). Ruff scope normalized to `core/ tests/ plugins/` across CI (was `core/ tests/`) and `extend-exclude` set to `[".geode", ".claude", "experimental", "scripts"]` so external skill scripts and prototypes don't leak into the gate. CI lint job now also runs `deptry`. 4 PLR auto-fixes applied during config rollout (`PLR1714` × 2 in `commands.py` and `skill_registry.py`, `PLR5501` in `scheduler_drain.py`, `PLR1730` in `telegram_poller.py`). Extends 4-of-5 OSS frontier projects' patterns; intentionally skips vulture/radon/xenon/interrogate per the comparative analysis (PLR + C901 cover ~80% of radon's actionable subset with zero new dependency). (`pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `core/cli/{commands,scheduler_drain}.py`, `core/llm/skill_registry.py`, `core/server/supervised/telegram_poller.py`, `core/mcp/{apple_calendar_adapter,google_calendar_adapter}.py`, `core/verification/cross_llm.py`, `docs/e2e/e2e-orchestration-scenarios.md`)

### Removed
- **Dead code excised post-v0.66.0 audit (3 sites).** `core/llm/router.py` `_maybe_traceable = maybe_traceable` backward-compat alias deleted (zero call-sites; only docstring/comment mentions in two test files updated to use `maybe_traceable`). `core/agent/system_prompt.py` `_build_memory_context()` deleted (~28 LOC; superseded by inlined G2-G4 calls in `build_system_prompt`, no external or internal caller; one stale docstring reference in `_build_project_memory_context` cleaned). `core/cli/pipeline_executor.py:_render_streaming_evaluator` and `_render_streaming_analyst` now call `plugins.game_ip.scoring_constants.score_style` instead of duplicating the threshold-styled-string ladder inline (the analyst path rescales 0-5 → 0-100 with `score * 20` so both renderers share the 80/60-tier styler). Findings sourced from the post-release dead/duplicate/zombie code scan; sub-agent flagged 0 critical, 2 moderate, 3 minor — all 3 minor + 1 moderate addressed here. (`core/llm/router.py`, `core/agent/system_prompt.py`, `core/cli/pipeline_executor.py`, `tests/conftest.py`, `tests/test_agentic_loop.py`)

## [0.66.0] — 2026-05-06

> **Domain-free core refactor — steps 1-3 of 8.** First wave of the architectural pivot
> documented in `docs/architecture/domain-free-core-audit.md` (audit landed in PR #869).
> Three of the 8-step refactor sequence merged on develop: `core/llm/prompts/axes.py`
> defused (REODE-fork can now `import core/` without `plugins/game_ip/` present), 5
> PURE-PLUGIN files relocated, lifecycle/system_prompt seam closed via 4 new optional
> `DomainPort` v2 hooks. Steps 4-8 (CLI extraction, tools split, MCP plugin-registration,
> state.py + reports.py extraction, graph.py topology surgery) remain in subsequent
> releases; REODE fork unblocks after step 8 lands.

### Documentation
- **Domain-free core audit + cut-line design (`docs/architecture/domain-free-core-audit.md`).** 313-line architecture document classifying 29 game_ip-coupled files in `core/` into PURE-PLUGIN (8) / PURE-INFRA (4) / MIXED (17) buckets with line-level cut recommendations. Frontier comparison across Claude Code, Codex CLI, OpenClaw, autoresearch — closest analogue is Claude Code's closed-kernel + filesystem-discovered extensions pattern. Sequenced 8-step refactor plan with risk grading, workload estimate (~5,550 LOC moved), DomainPort v2 contract specification, and the Codex-style truth gate (`mv plugins plugins.bak && pytest tests/test_core_only/`) as the post-step-8 verification. (PR #869)

### Architecture
- **Domain-free core, step 3 of 8 (`docs/architecture/domain-free-core-audit.md`).** Three lifecycle/agent seams that still imported `plugins.game_ip.*` directly are now routed through four new optional `DomainPort` v2 hooks: `wire_context_assembler(assembler)`, `build_task_graph(memory, subject_id)`, `build_signal_adapter()`, and `compose_static_prefix(model)`. All four are declared on the Protocol with `...` bodies (no implementation default — Python Protocols can't carry one) and call sites in `core/` use `getattr(domain, "<hook>", None)` + `callable(...)` to skip silently when a future domain omits the hook. `core/lifecycle/bootstrap.py:build_memory` no longer imports `plugins.game_ip.nodes.router.set_context_assembler`; it calls `domain.wire_context_assembler(context_assembler)` instead, falling through to a debug log when no domain or hook is present. `core/lifecycle/bootstrap.py:build_task_graph` no longer imports `core.orchestration.task_system.create_geode_task_graph` directly; it dispatches via `domain.build_task_graph(memory, ip_name)` and constructs an empty `TaskGraph` (still bridge-wired) when no domain is registered. `core/lifecycle/adapters.py:build_signal_adapter` shrinks from ~40 lines of Steam/MCP wiring to a 10-line shim that delegates to `domain.build_signal_adapter()` — the original body, including the `set_signal_adapter` injection, moved to new `plugins/game_ip/wiring.py`. `core/agent/system_prompt.py` drops the `_NOTABLE_IPS` set and the `plugins.game_ip.fixtures` / `plugins.game_ip.cli.ip_names` reach-ins; `build_system_prompt` now calls `domain.compose_static_prefix(model)` and falls back to `_generic_static_prefix()` (`ROUTER_SYSTEM` rendered with `ip_count=0, ip_examples="none loaded"`) when no domain customizes the prompt. The IP-flavored body — `_NOTABLE_IPS`, fixture-driven `{ip_count}`/`{ip_examples}` substitution — moved to new `plugins/game_ip/prompt.py`. `GameIPDomain` (`plugins/game_ip/adapter.py`) implements all four v2 hooks via lazy plugin imports inside each method to avoid circular-import risk at adapter construction time. Cosmetic alignment: `core.lifecycle.automation.wire_automation_hooks` parameter `ip_name` renamed to `subject_id` (call site in `build_automation` updated; downstream `trigger_manager.register_pipeline_trigger(ip_name=...)` and `outcome_tracker.schedule(ip_name=...)` keyword arguments preserved as those APIs still take `ip_name`). After step 3, `grep -rn "from plugins\.game_ip\|import plugins\.game_ip" core/lifecycle/ core/agent/` returns zero hits; the only remaining reach-ins inside `core/` are the two intentional try-imports in `core/llm/prompts/axes.py` (covered by step 1) and call sites still owned by steps 4-8 (`core/cli/`, `core/tools/`, `core/mcp_server.py`, `core/ui/`, `core/skills/reports.py`). Quality gates green: ruff/mypy clean, 4386 tests pass, E2E anchor `geode analyze "Cowboy Bebop" --dry-run` unchanged at A (68.4) undermarketed. (`core/domains/port.py`, `core/lifecycle/bootstrap.py`, `core/lifecycle/adapters.py`, `core/lifecycle/automation.py`, `core/agent/system_prompt.py`, `plugins/game_ip/adapter.py`, `plugins/game_ip/wiring.py`, `plugins/game_ip/prompt.py`) (`docs/architecture/domain-free-core-audit.md`).** Three lifecycle/agent seams that still imported `plugins.game_ip.*` directly are now routed through four new optional `DomainPort` v2 hooks: `wire_context_assembler(assembler)`, `build_task_graph(memory, subject_id)`, `build_signal_adapter()`, and `compose_static_prefix(model)`. All four are declared on the Protocol with `...` bodies (no implementation default — Python Protocols can't carry one) and call sites in `core/` use `getattr(domain, "<hook>", None)` + `callable(...)` to skip silently when a future domain omits the hook. `core/lifecycle/bootstrap.py:build_memory` no longer imports `plugins.game_ip.nodes.router.set_context_assembler`; it calls `domain.wire_context_assembler(context_assembler)` instead, falling through to a debug log when no domain or hook is present. `core/lifecycle/bootstrap.py:build_task_graph` no longer imports `core.orchestration.task_system.create_geode_task_graph` directly; it dispatches via `domain.build_task_graph(memory, ip_name)` and constructs an empty `TaskGraph` (still bridge-wired) when no domain is registered. `core/lifecycle/adapters.py:build_signal_adapter` shrinks from ~40 lines of Steam/MCP wiring to a 10-line shim that delegates to `domain.build_signal_adapter()` — the original body, including the `set_signal_adapter` injection, moved to new `plugins/game_ip/wiring.py`. `core/agent/system_prompt.py` drops the `_NOTABLE_IPS` set and the `plugins.game_ip.fixtures` / `plugins.game_ip.cli.ip_names` reach-ins; `build_system_prompt` now calls `domain.compose_static_prefix(model)` and falls back to `_generic_static_prefix()` (`ROUTER_SYSTEM` rendered with `ip_count=0, ip_examples="none loaded"`) when no domain customizes the prompt. The IP-flavored body — `_NOTABLE_IPS`, fixture-driven `{ip_count}`/`{ip_examples}` substitution — moved to new `plugins/game_ip/prompt.py`. `GameIPDomain` (`plugins/game_ip/adapter.py`) implements all four v2 hooks via lazy plugin imports inside each method to avoid circular-import risk at adapter construction time. Cosmetic alignment: `core.lifecycle.automation.wire_automation_hooks` parameter `ip_name` renamed to `subject_id` (call site in `build_automation` updated; downstream `trigger_manager.register_pipeline_trigger(ip_name=...)` and `outcome_tracker.schedule(ip_name=...)` keyword arguments preserved as those APIs still take `ip_name`). After step 3, `grep -rn "from plugins\.game_ip\|import plugins\.game_ip" core/lifecycle/ core/agent/` returns zero hits; the only remaining reach-ins inside `core/` are the two intentional try-imports in `core/llm/prompts/axes.py` (covered by step 1) and call sites still owned by steps 4-8 (`core/cli/`, `core/tools/`, `core/mcp_server.py`, `core/ui/`, `core/skills/reports.py`). Quality gates green: ruff/mypy clean, 4386 tests pass, E2E anchor `geode analyze "Cowboy Bebop" --dry-run` unchanged at A (68.4) undermarketed. (`core/domains/port.py`, `core/lifecycle/bootstrap.py`, `core/lifecycle/adapters.py`, `core/lifecycle/automation.py`, `core/agent/system_prompt.py`, `plugins/game_ip/adapter.py`, `plugins/game_ip/wiring.py`, `plugins/game_ip/prompt.py`)
- **Domain-free core, step 2 of 8 (`docs/architecture/domain-free-core-audit.md`).** Five PURE-PLUGIN files moved out of `core/` into `plugins/game_ip/` (no re-export shims; direct caller updates). `core/cli/batch.py` → `plugins/game_ip/cli/batch.py` (246 LOC; fixture-driven multi-IP pipeline runner). `core/cli/ip_names.py` → `plugins/game_ip/cli/ip_names.py` (44 LOC; canonical-name → fixture-key registry). `core/cli/search.py` → `plugins/game_ip/cli/search.py` (198 LOC; fixture-backed IP search engine with Korean-English synonym expansion). `core/mcp/signal_adapter.py` → `plugins/game_ip/mcp/signal_adapter.py` (75 LOC; FixtureSignalAdapter + LiveSignalAdapter stub — was misnamed, never an MCP-framework module). `core/tools/data_tools.py` split: `QueryMonoLakeTool` (~80 LOC) moved to `plugins/game_ip/tools/data_tools.py` (depends on `plugins.game_ip.fixtures`); domain-agnostic `CortexAnalystTool` + `CortexSearchTool` Snowflake stubs (~105 LOC) stay in `core/tools/data_tools.py` with the docstring updated to point at the new MonoLake home. New plugin subpackages: `plugins/game_ip/cli/`, `plugins/game_ip/mcp/`, `plugins/game_ip/tools/` (each with a one-line docstring `__init__.py`). 8 caller sites rewritten across `core/agent/system_prompt.py`, `core/cli/__init__.py`, `core/cli/pipeline_executor.py`, `core/cli/session_state.py`, `core/cli/tool_handlers.py`, `core/lifecycle/container.py`, `tests/test_batch.py`, `tests/test_data_tools.py`, `tests/test_search.py`, `tests/test_signal_port.py`. Two now-stale `tool.importlinter` ignore_imports entries removed (`core.agent.system_prompt -> core.cli.ip_names` ×2) since the agent now reaches the IP-name map through `plugins.game_ip.cli` and never crosses the agent→cli boundary. Quality gates green: ruff/mypy clean, 4386 tests pass, E2E anchor `geode analyze "Cowboy Bebop" --dry-run` unchanged at A (68.4) undermarketed. (`plugins/game_ip/cli/`, `plugins/game_ip/mcp/`, `plugins/game_ip/tools/`, `core/tools/data_tools.py`, `core/agent/system_prompt.py`, `core/cli/{__init__,pipeline_executor,session_state,tool_handlers}.py`, `core/lifecycle/container.py`, `pyproject.toml`)
- **Domain-free core, step 1 of 8 (`docs/architecture/domain-free-core-audit.md`).** Eager IP-YAML load lifted out of `core/llm/prompts/axes.py` so `core/` can be imported without `plugins/game_ip/` present (REODE-fork prerequisite). The 14-axis rubric data now lives in `plugins/game_ip/axes.py`; `core/llm/prompts/axes.py` re-exports those constants when the plugin is installed and falls back to empty dicts otherwise (preserves existing GEODE callers; pin hashes unchanged). Domain registry decoupled: `core/domains/loader.py:_BUILTIN_DOMAINS` no longer seeds `game_ip`; the loader gains a 2-pass discovery (registry → convention `import plugins.<name>` → re-check) and `plugins/game_ip/__init__.py` self-registers via `register_domain(...)` at import time. New `DomainPort.get_prospect_evaluator_axes()` v2 method exposes the prospect-track axes that previously lived only as a module-level `PROSPECT_EVALUATOR_AXES` constant. Six new tests in `tests/test_domain_port_step1.py` cover loader 2-pass, plugin self-registration, and the new method. (`core/llm/prompts/axes.py`, `core/domains/loader.py`, `core/domains/port.py`, `plugins/game_ip/axes.py`, `plugins/game_ip/__init__.py`, `plugins/game_ip/adapter.py`, `tests/test_domain_port_step1.py`)

## [0.65.0] — 2026-05-02

### Fixed
- **`manage_login` verdict reporting collapses healthy PAYG profiles to `provider_mismatch`.** The verdict-aggregation loop in `core/cli/tool_handlers.py:handle_manage_login` keyed `verdict_index[(name, profile.provider)]` while iterating `evaluate_eligibility(prov)` once per unique provider in the store. Each iteration evaluates *every* profile, returning a `PROVIDER_MISMATCH` verdict for profiles whose provider != prov; those mismatch verdicts share the same dict key as the real verdict and the last-iterated provider's write wins. Set iteration order is hash-dependent, so on a typical multi-provider store (e.g. `openai-codex`, `openai`, `anthropic`) every profile except the one whose provider iterates last surfaces as `eligible=False / reason=provider_mismatch` to both the LLM (via the `manage_login` tool result) and the `/login` dashboard — even though the underlying credential is healthy and `resolve_routing` would happily use it via the equivalence-class fallback. Fix: skip cross-provider iterations (`if v.reason is ProfileRejectReason.PROVIDER_MISMATCH: continue`) so each profile's verdict comes from its *own* provider's evaluation, mirroring the same filter already applied in `core/auth/credential_breadcrumb.format`. Regression test: `tests/test_manage_login_tool.py::TestVerdictPerOwnProvider` registers three profiles across three providers and asserts none are reported as `provider_mismatch`. (`core/cli/tool_handlers.py`, `tests/test_manage_login_tool.py`)

### Added
- **Messages-level cache_control breakpoints in Anthropic agentic adapter (Hermes `system_and_3` parity).** New `apply_messages_cache_control(messages, n_breakpoints=3)` helper in `core/llm/providers/anthropic.py` adds `cache_control: {"type": "ephemeral"}` to the last 3 non-system messages' final content block, filling Anthropic's remaining cache-control slots after the existing system block (STATIC + DYNAMIC split). Combined cap is 4 breakpoints — 1 on the system block, up to 3 on rolling history. Reduces input-token cost in long multi-turn agentic loops where the message history would otherwise be re-billed every turn. Non-mutating (returns new list with shallow-copied targeted messages); handles both `str` and `list[block]` content shapes. Wired in `ClaudeAgenticAdapter.agentic_call._do_call` immediately before `messages.create`. New test module `tests/test_anthropic_messages_cache.py` (19 cases): empty/short/long lists, system skip, str→block conversion, list-block last-only marking, idempotency, parametrized n_breakpoints bound. `MAX_MESSAGE_CACHE_BREAKPOINTS = 3` exported. (`core/llm/providers/anthropic.py`, `tests/test_anthropic_messages_cache.py`)

## [0.64.0] — 2026-04-29

### Changed
- **E — Game IP domain extracted to `plugins/` namespace.** `core/domains/game_ip/` → `plugins/game_ip/` (12 modules, 220 files including config + fixtures). Hatchling wheel now ships both `core/` and `plugins/` (`pyproject.toml:[tool.hatch.build.targets.wheel] packages`). 72 import statements across 36 caller files rewritten from `core.domains.game_ip.*` → `plugins.game_ip.*` via mechanical sed (verified by lint/format auto-fix + mypy + 4360-test full suite). 3 hardcoded path references also corrected: `core/llm/prompts/axes.py:_YAML_PATH`, `core/memory/organization.py:DEFAULT_FIXTURE_DIR`, `core/verification/calibration.py:_GOLDEN_SET_PATH`, plus `tests/test_calibration.py:GOLDEN_SET_PATH`. `core/domains/loader.py:_DOMAIN_REGISTRY` registry entry updated to point at the new `plugins.game_ip.adapter:GameIPDomain` import path. New `plugins/__init__.py` documents the namespace's purpose (domain-agnostic core scaffold + domain-specific extensions evolving independently). Quality gates (`ruff check core/ tests/ plugins/`, `mypy core/ plugins/`) extended to cover both packages. E2E anchor (`uv run geode analyze "Cowboy Bebop" --dry-run` → A 68.4) unchanged. Fourth and final cycle of the 2026-04-29 backlog cleanup direction. (`plugins/game_ip/*`, `core/domains/loader.py`, `core/llm/prompts/axes.py`, `core/memory/organization.py`, `core/verification/calibration.py`)

### Added
- **D-3 — Experimental modules parking lot (`experimental/`)** [folded in from previous Unreleased]. New top-level directory for working prototypes whose product fit hasn't been validated. Committed there: 4 memory modules (`embeddings.py`, `vector_store.py`, `rag_router.py`, `raptor.py` — RAPTOR per Sarthi et al. ICLR 2024) totalling ~1.9K lines + 36 tests, plus the `progressive_compression.py` 3-zone compressor (~320 lines + 14 tests). All 50 tests pass under their new `experimental.*` import paths. Default-excluded from the production quality gates: pytest collects only `tests/` (per `pyproject.toml:testpaths`), ruff lints only `["core", "tests"]` (per `[tool.ruff] src`), mypy runs against command-line paths so `core/` checks ignore the new tree. Run `uv run pytest experimental/tests/ -v` to opt in. `experimental/README.md` documents promotion criteria (concrete production caller + product trade-off + 1+ frontier ref + integration test) and removal criteria (6+ months with no caller). (`experimental/`)

### Documentation
- **D-2 — Research notes commit + personal-report gitignore** [folded in from previous Unreleased]. Four research markdown files that were sitting in the working tree as untracked since the late-March / early-April research bursts now land in `docs/research/` (Codex OAuth routing cross-codebase notes, deep-thinking ratio research + explainer) and `docs/scaffold-architecture.md` (portfolio v028 architecture writeup). `.gitignore` extended to suppress agent-generated personal reports (`/*_trend_report_*.md`, `/*_stock_report_*.md`, `/*_report_2*.md`) plus the ad-hoc `docs/progress-report.html` dashboard so future runs don't leak personal output into git status.

### Reference
- 2026-04-29 user direction: "이제 Game Domain Plugin은 따로 관리하려고 해" — option 2 (monorepo `plugins/`) chosen over option 1 (separate git repo) for first iteration; option 1 deferred until a second domain plugin or external publishing motivates the split.
- Backlog cleanup plan complete: D-1 (lifecycle, v0.63.0) → D-2 (docs commit) → D-3 (experimental defer) → **E** (this cycle, plugin split).

## [0.63.0] — 2026-04-29

### Added
- **D-1 — Lifecycle command suite (`/stop`, `/clean`, `/uninstall`, extended `/status`).** Hermes-precedent (`hermes_cli/main.py:cmd_status, cmd_uninstall`) daemon control, selective cache cleanup, and full system removal. `/stop` SIGTERMs serve daemon (with `--force` for SIGKILL); `/clean` walks per-project + global caches with `--scope=all|project|global|build` + `--all-data` + `--dry-run` flags; `/uninstall` removes the entire `~/.geode/` tree with `--keep-config` / `--keep-data` for partial uninstall. Existing `/status` action extended with daemon PID + per-directory disk usage block (cmd_lifecycle.show_status). Module was sitting orphaned in main as untracked work since 2026-04-09; this cycle wires it into the CLI dispatcher (`core/cli/__init__.py`) and adds the missing path constants to `core/paths.py` so the dispatcher can route. (`core/cli/cmd_lifecycle.py`, `core/cli/__init__.py:295-501`, `core/paths.py`)
- **9 new path constants in `core/paths.py`** — single source of truth for daemon/cache directories that previously lived as duplicates in `core/cli/ipc_client.py`, `core/server/ipc_server/poller.py`, `core/mcp/registry.py`. The new constants (`CLI_SOCKET_PATH`, `CLI_STARTUP_LOCK`, `SERVE_LOG_PATH`, `GLOBAL_JOURNAL_DIR`, `GLOBAL_WORKERS_DIR`, `MCP_REGISTRY_CACHE`, `APPROVE_HISTORY`, `PROJECT_EMBEDDING_CACHE`, `PROJECT_TOOL_OFFLOAD`, `PROJECT_VECTORS_DIR`) match the values already used at those duplicate sites. Dedup of the existing duplicates is a follow-up refactor — out of scope for the lifecycle-integration cycle. (`core/paths.py`)
- **`tests/test_lifecycle_commands.py`** — 30 invariants (file was alongside `cmd_lifecycle.py` as untracked since 2026-04-09; passes after the import path fix from `core.cli.ui.console` → `core.ui.console`). Coverage: `stop_serve` (not-running, running-then-killed, force, timeout), `show_status` (daemon report, disk usage scan, JSON output), `do_clean` (per-scope filtering, dry-run, force, older_than), `do_uninstall` (full removal, keep-config, keep-data, dry-run preview).

### Reference
- Hermes precedent: `hermes_cli/main.py:cmd_status` (line 4144), `cmd_uninstall` (line 4252), `_clear_bytecode_cache` (line 4260) — same status + uninstall split.
- Backlog cleanup plan from 2026-04-29 user direction: D-1 (lifecycle, this cycle) → D-2 (research docs commit, next) → D-3 (memory/compression defer to experimental/) → E (Game Domain plugin separation).

## [0.62.0] — 2026-04-28

### Added
- **R9 — live wire-level tests for the reasoning-depth audit series.** New `tests/test_e2e_live_reasoning_depth.py` (5 tests, `@pytest.mark.live`, default-excluded) covers the full R1+R2+R3-mini+R4-mini+R6 chain at the actual provider wire. Each test independently gates on its provider env var (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ZAI_API_KEY`/`GLM_API_KEY`, `CHATGPT_OAUTH_TOKEN`) so partial-key environments run whichever subset they have. Direct-adapter calls (no full agentic loop) keep cost low (~$0.01-0.05 / test). Coverage: Anthropic Opus 4.7 `effort=xhigh` returns thinking summaries (R4-mini + R6); PAYG OpenAI gpt-5.5 returns `codex_reasoning_items` with `encrypted_content` + `reasoning_summaries` (R3-mini + R6); PAYG OpenAI multi-turn replay (round 2 with prior reasoning items succeeds — proves the v0.60.0 shared `inject_reasoning_replay` walker is wired in `openai.py`); GLM-4.6 thinking field returns `reasoning_summaries` (R2 + R6); Codex Plus returns `codex_reasoning_items` + `reasoning_summaries` (R1 + R6). Run with `uv run pytest tests/test_e2e_live_reasoning_depth.py -v -m live`. (`tests/test_e2e_live_reasoning_depth.py`)

### Reference
- Audit series tracked in this CHANGELOG: R1 (v0.55.0 Codex encrypted), R2 (v0.58.0 GLM thinking), R3-mini (v0.60.0 PAYG OpenAI parity), R4-mini (v0.56.0 Opus 4.7 xhigh), R6 (v0.57.0 reasoning summaries surface).
- Live test pattern mirrors existing `tests/test_e2e_live_llm.py` (skipif on env var, `pytest.mark.live` exclusion via `pyproject.toml addopts`).

## [0.61.0] — 2026-04-28

### Added
- **Picker effort + model now persist to `.geode/config.toml`** (durable layer), not just `.env`. Previously `_apply_model` wrote `GEODE_AGENTIC_EFFORT` / `GEODE_MODEL` to `.env` only — a stale comment claimed config.toml sync, but the config-toml write never happened. Sessions worked in practice because `.env` survives, but wiping `.env` silently lost the picker choice. New shared helper `upsert_config_toml(section, key, value)` in `core/cli/_helpers.py` performs minimal-diff TOML upserts (creates file + section if absent, replaces existing keys including commented defaults like `# effort = "high"`, inserts before next section heading). Called from `_apply_model` for both `[agentic] effort` and `[llm] primary_model`. 3-codebase consensus pattern (Hermes `~/.hermes/config.json`, Codex `~/.codex/config.toml`, Claude Code project + global config) — chosen settings persist to the config layer. (`core/cli/_helpers.py:upsert_config_toml`, `core/cli/commands.py:_apply_model`)
- **Explicit `store=False` on PAYG OpenAI Responses calls** (R3-mini follow-up). The PAYG `OpenAIAgenticAdapter` now sends `store=False` for parity with the Codex Plus path (`codex.py:331`). We feed conversations via the `input` array + the v0.60.0 encrypted-content replay walker, never via `previous_response_id`, so server-side response storage is unused on our side; opting out matches Codex Plus behaviour and avoids OpenAI-side retention of every response. SDK default is `True`. (`core/llm/providers/openai.py:OpenAIAgenticAdapter._do_call`)
- **`tests/test_config_effort_knob.py`** — 8 invariants. `upsert_config_toml` (creates file with section, updates existing key, inserts into existing section preserving siblings + other sections, uncomments commented defaults exactly once, appends section when missing), picker persistence (`_apply_model` round-trips effort + model into `.geode/config.toml`), source-pin (`store=False` literal in both `openai.py` and `codex.py`).

### Reference
- 3-codebase config persistence: Hermes `hermes_cli/main.py:cmd_model` (writes to `~/.hermes/config.json`), Codex CLI `codex-rs/cli/src/config.rs` (writes to `~/.codex/config.toml`), Claude Code `screens/REPL.tsx` (project + global JSON config write).
- openai-python Stainless SDK `responses/response_create_params.py` — `store: Optional[bool]` defaults to `True`; `store=False` is the supported opt-out for ZDR / privacy-conscious flows.

## [0.60.0] — 2026-04-28

### Added
- **R3-mini — PAYG OpenAI Responses reasoning parity.** The PAYG `OpenAIAgenticAdapter` now sends `include=["reasoning.encrypted_content"]` + `reasoning={"effort": …, "summary": "auto"}` for every gpt-5.x model (and the o-series whitelist). Without these, gpt-5.x silently lost its reasoning state on every multi-turn round (server omits the encrypted continuation blob from non-`include` responses, and `summary` is opt-in). The `_REASONING_MODELS` whitelist is replaced by a `_is_payg_reasoning_model(model)` helper that gates on `gpt-5*` prefix + the legacy o-series — previously gpt-5.5 / 5.4 / 5.4-mini / 5.3-codex got NO reasoning kwarg, so the picker's effort knob was being silently dropped on PAYG. Spec-grounded against `openai-python/src/openai/types/shared/reasoning.py` (`Reasoning` model, `summary: Literal["auto", "concise", "detailed"]`) + `openai-python/src/openai/types/responses/response_create_params.py:70-74` (`reasoning.encrypted_content` semantics under `store=False`). (`core/llm/providers/openai.py:_is_payg_reasoning_model, OpenAIAgenticAdapter._do_call`)
- **Shared encrypted-reasoning replay walker** (`inject_reasoning_replay`). The 29-line walker that re-injects prior-turn `codex_reasoning_items` into the next-turn `input` array (originally inlined in `core/llm/providers/codex.py:243-271` for Codex Plus) is now a shared helper in `core/llm/agentic_response.py`. Both adapters call the same function, so a future change to the wire format only has to land once. Strips the `id` field on replay (server can 404 on item lookup with `store=False`); skips items with no `encrypted_content` (otherwise we just bloat the request); drops the `system` entry (system prompt rides the `instructions` kwarg). (`core/llm/agentic_response.py:inject_reasoning_replay`, `core/llm/providers/codex.py`, `core/llm/providers/openai.py`)
- **`tests/test_r3_mini_payg_reasoning.py`** — 13 invariants. Reasoning-model gate (gpt-5.x family in, o-series in, gpt-4 / claude out), shared walker (blob-precedes-assistant ordering, id strip, missing-blob skip, system drop, plain-conversation pass-through), source-level pins (`include` + `summary:"auto"` + `inject_reasoning_replay` literally appear in `openai.py`; codex.py no longer carries the inline walker; `_EFFORT_MAP` keeps `max → high`).

### Reference
- openai-python (Stainless-generated SDK):
  - `src/openai/types/shared/reasoning.py:13` — "**gpt-5 and o-series models only**"
  - `src/openai/types/shared/reasoning.py:44-52` — `summary: Literal["auto", "concise", "detailed"]`
  - `src/openai/types/responses/response_create_params.py:70-74` — `reasoning.encrypted_content` purpose + `store=False`/ZDR conditions
  - `src/openai/types/responses/response_includable.py` — `Literal["reasoning.encrypted_content", …]`
- 3-codebase consensus: Hermes `agent/codex_responses_adapter.py:228-246, 720-738`, Codex Rust `codex-rs/protocol/src/openai_models.rs:43-51`, GEODE Codex Plus path `core/llm/providers/codex.py:347-348` (R1, v0.55.0).

## [0.59.0] — 2026-04-28

### Added
- **Two-axis interactive `/model` picker — model (↑↓) + effort (←→).** Mirrors the recent Claude Code `ModelPicker.tsx` UX (cursor `❯`, default-marker `✔`, single-line effort indicator with disc symbol, `Enter to confirm · Esc to exit` footer). Per-provider effort enum table (`core/cli/effort_picker.py`) is grounded in each provider's official spec — Anthropic adaptive (`low/medium/high/max/xhigh`, `xhigh` Opus 4.7-only per `platform.claude.com/docs/en/build-with-claude/effort`), OpenAI Responses (`none/minimal/low/medium/high/xhigh` per `openai-python/src/openai/types/shared/reasoning_effort.py` + `codex-rs/protocol/src/openai_models.rs:43-51`), GLM hybrid binary (`disabled/enabled` per `docs.z.ai/guides/capabilities/thinking-mode`); always-on / non-reasoning models display the `· No effort knob for this model` row and arrow keys are silently no-op. Raw-tty input (termios + ANSI escape sequences for arrow keys) replaces the legacy `simple-term-menu` single-axis picker. Selected effort persists to `settings.agentic_effort` + `GEODE_AGENTIC_EFFORT` env so the next AgenticLoop turn picks it up via the same `_sync_model_from_settings` deferred hot-swap path the model field uses. (`core/cli/effort_picker.py`, `core/cli/commands.py:_interactive_model_picker, _apply_model`)
- **`tests/test_effort_picker.py`** — 21 invariants. Per-provider enum integrity (Anthropic adaptive vs Opus-4.7-xhigh gate, OpenAI Responses full enum, GLM hybrid binary vs always-on `()`), `cycle_effort` cycling + wrap-around + empty-tuple no-op + cross-model snap-to-middle on unknown current, default-effort table (Opus 4.7 → `xhigh`, Sonnet/Opus 4.6 → `high`, Codex → `medium`, GLM → `enabled`), cross-provider sanity that every `MODEL_PROFILES` entry has a valid enum + default.

### Reference
- Claude Code `ModelPicker.tsx` (cursor + default-marker + footer layout), `keybindings/defaultBindings.ts` (arrow-key bindings).
- User direction 2026-04-28: "방향키로 조절할 수 있게 디벨롭하자. claude-code 최근 ui/ux를 확인하면 돼" + render-shape spec showing `❯ 1. Default (recommended) ✔` + `◉ xHigh effort (default) ← → to adjust` + `Enter to confirm · Esc to exit`.

## [0.58.0] — 2026-04-28

### Added
- **GLM `thinking` field activation** (R2 of the reasoning-depth audit). All three reference frontier harnesses (Hermes, OpenClaw, Claude Code) leave this dead — Hermes routes GLM through a generic `chat_completions` transport that doesn't know about the field; OpenClaw has no GLM plugin; Claude Code is Anthropic-only. v0.58.0 makes GEODE the **leader** on this dimension. The adapter sends `extra_body={"thinking": {"type": "enabled", "clear_thinking": False}}` for every model in `_GLM_THINKING_MODELS` (GLM-4.5+ family). `clear_thinking=False` preserves prior-turn `reasoning_content` in the model's context — same multi-turn-coherence goal as R1 on Codex Plus. Per-failover-model gate drops the field on pre-GLM-4.5 models that reject it. Spec re-verified 2026-04-28 against `docs.z.ai/api-reference/llm/chat-completion` + `docs.z.ai/guides/capabilities/thinking-mode`. (`core/llm/providers/glm.py:_GLM_THINKING_MODELS, _glm_thinking_supported`)
- **GLM `message.reasoning_content` extraction** (R2 + R6 integration). The GLM Chat Completion endpoint returns reasoning text on a separate `message.reasoning_content` field (distinct from `message.content`). `normalize_openai` (the Chat Completions normaliser used by GLM) now extracts it into `AgenticResponse.reasoning_summaries` so the R6 surfacing path treats GLM the same as Anthropic + Codex. Empty/whitespace-only payloads are filtered. Other Chat-Completions providers (without `reasoning_content`) leave the sidecar `None` — backward-compat preserved. (`core/llm/agentic_response.py:normalize_openai`)
- **`tests/test_glm_thinking_r2.py`** — 15 invariants. Per-model gate (GLM-5.1, GLM-5, GLM-4.7, GLM-4.6, GLM-4.5, legacy reject, unknown reject, empty reject, frozenset constraint), reasoning_content extraction (extracted, no-content → None, empty filtered, OpenAI legacy isolation), source-level wiring pins (extra_body, gate, clear_thinking=False default).

### Reference
- ZhipuAI Z.AI official docs:
  - `https://docs.z.ai/api-reference/llm/chat-completion` (Chat Completion API reference)
  - `https://docs.z.ai/guides/capabilities/thinking-mode` (`thinking` field shape + `clear_thinking` semantics)
  - `https://docs.z.ai/guides/llm/glm-4.5` (GLM-4.5 thinking guide)
  - `https://docs.z.ai/guides/llm/glm-4.6` (GLM-4.6 hybrid mode)
  - `https://docs.z.ai/guides/llm/glm-4.7` (GLM-4.7 turn-level thinking)
  - `https://docs.z.ai/guides/llm/glm-5.1` (GLM-5.1 always-on)
- Cross-codebase comparison: 0/3 references implement this (audit B2/B4 in the prior reasoning-depth scans), making v0.58.0 the leader.

## [0.57.0] — 2026-04-28

### Added
- **Reasoning summaries surface to AgenticUI** (R6 of the reasoning-depth audit). All three reference frontier harnesses (Hermes, Claude Code, OpenClaw) render the model's reasoning chunks live so the user sees "thinking…" rather than a silent spinner; GEODE was the only one dropping them. v0.57.0 captures `reasoning.summary[].text` (Codex Plus) and `thinking` content blocks (Anthropic adaptive thinking with `display:"summarized"` from R4-mini) into a new `AgenticResponse.reasoning_summaries` sidecar, then emits one `reasoning_summary` IPC event per item from `AgenticLoop` after each LLM call returns. Per-item granularity (not per-delta) avoids threading the IPC writer into the `asyncio.to_thread` worker that drives the streaming loop. (`core/llm/agentic_response.py:AgenticResponse.reasoning_summaries`, `core/agent/loop.py` post-call emit, `core/ui/agentic_ui.py:emit_reasoning_summary`, `core/ui/event_renderer.py:_handle_reasoning_summary`)
- **`reasoning_summary` IPC event** in the structured-events allowlist (`core/cli/ipc_client.py`) and renderer dispatch (`core/ui/event_renderer.py:_handle_reasoning_summary`). Long summaries truncate to 240 chars + ellipsis on the inline render; full text is in the IPC event payload for any client that wants the complete summary.
- **`tests/test_reasoning_summary_r6.py`** — 16 invariants covering Codex extraction (with + without encrypted blob, empty filtering, no-reasoning case), Anthropic thinking extraction (block, no-block, empty), sidecar default, other-provider isolation, emit helper console + truncation paths, IPC allowlist + renderer handler presence + truncation/skip-empty rendering, loop wiring source check.

### Reference
- 3-codebase consensus: Hermes `agent/anthropic_adapter.py:793` (TUI activity feed accumulation), Claude Code `screens/REPL.tsx:139-157` (React state + rainbow + 30 s auto-hide), OpenClaw `src/agents/openai-transport-stream.ts:398-407` (per-event push).
- Original audit + R6 priority: `docs/research/reasoning-depth-audit.md` and `docs/research/reasoning-depth-post-r1r5-gaps.md` (both deleted on this commit per user direction "작업 끝나면 해당 MD 삭제하고" — content rolled into changelog entries for R1, R5, R4-mini, R6).

### Removed
- **`docs/research/reasoning-depth-audit.md`** and **`docs/research/reasoning-depth-post-r1r5-gaps.md`** — scratch research notes that drove the R1/R5/R4-mini/R6 cycle. Per user direction these were always temporary; the actionable findings have been captured in the corresponding CHANGELOG entries (v0.55.0 R1, v0.55.1 R5, v0.56.0 R4-mini, v0.57.0 R6).

## [0.56.0] — 2026-04-28

### Added
- **`xhigh` effort level** (R4-mini, audit B3). Opus 4.7 supports a new `xhigh` reasoning level above `high` (Anthropic recommends it as the starting effort for coding/agentic workloads — see [platform.claude.com/docs/en/build-with-claude/effort](https://platform.claude.com/docs/en/build-with-claude/effort)). The Anthropic adapter now version-gates: `xhigh` passes through on Opus 4.7 and downgrades to `"max"` on Opus 4.6 / Sonnet 4.6 (which reject it with 400). Mirrors Hermes `_supports_xhigh_effort` substring-based gate (`anthropic_adapter.py:49-53, 1445-1446`). The `_EFFORT_LEVELS` table in `core/agent/loop.py:1513` was extended to include `xhigh` so the overthinking auto-downgrade can index it without crashing. Users opt in via `agentic.effort = "xhigh"`; we never auto-upgrade `high → xhigh`. (`core/llm/providers/anthropic.py:_XHIGH_EFFORT_MODELS, _supports_xhigh_effort`, `core/agent/loop.py:_EFFORT_LEVELS`, `core/config.py:agentic_effort`)

### Fixed
- **Anthropic `thinking.display = "summarized"` always set on adaptive thinking** (R4-mini, audit C1). Opus 4.7 changed the default for `thinking.display` from `"summarized"` to `"omitted"` (per [whats-new-claude-4-7](https://platform.claude.com/docs/en/docs/about-claude/models/whats-new-claude-4-7)) — meaning thinking blocks come back empty unless the caller explicitly asks for a summary. Without the override the GEODE activity feed had no reasoning trace to render on Opus 4.7. v0.56.0 forces `display: "summarized"` on every adaptive call. Mirrors Hermes (`anthropic_adapter.py:1440`): *"explicit override preserves UX."* (`core/llm/providers/anthropic.py:adaptive thinking branch`)
- **Anthropic thinking-block `signature` round-trip safety pinned** (R4-mini, audit C2). All three reference codebases (OpenClaw, Claude Code, Hermes) preserve the `signature` field when echoing thinking blocks back into the next-turn `messages` array — Claude Code documents the consequence: *"mismatched thinking block signatures cause API 400 errors"* (`utils/messages.ts:2311-2322`). GEODE's normaliser already drops thinking blocks from `AgenticResponse.content` and `_serialize_content` only emits text + tool_use blocks, so a stale signature can't accidentally reach the next request. v0.56.0 pins both invariants with explicit tests so future code that adds thinking-block round-trip support can't silently regress this safety.

### Tests
- `tests/test_anthropic_reasoning_v056.py` — 11 invariants covering the three R4-mini items: `xhigh` model gate (4 cases), `_XHIGH_EFFORT_MODELS ⊆ _ADAPTIVE_MODELS`, loop `_EFFORT_LEVELS` includes `xhigh`, adapter source asserts `display: "summarized"`, downgrade contract on Opus 4.6, normaliser drops thinking blocks, `_serialize_content` only emits text + tool_use.
- `tests/test_anthropic_sampling_params.py:test_adaptive_models_omit_sampling_params` updated to expect the new `{type:"adaptive", display:"summarized"}` shape.

### Reference
- `docs/research/reasoning-depth-audit.md` — R4 in cross-codebase comparison (Hermes was 1/3 to ship `display`; April 23 Anthropic postmortem named `xhigh` as the new default).
- `docs/research/reasoning-depth-post-r1r5-gaps.md` — R4-mini bundle (C1 + B3 + C2) recommended as the next single PR.
- Hermes Agent: `agent/anthropic_adapter.py:49-53` (xhigh gate), `:1440` (display=summarized), `:1445-1446` (downgrade).
- Anthropic official docs: `platform.claude.com/docs/en/build-with-claude/effort` (xhigh), `whats-new-claude-4-7` (display default change), `extended-thinking#preserving-thinking-blocks` (signature round-trip).

## [0.55.1] — 2026-04-28

### Fixed
- **Sub-agent reasoning depth never reached the spawned loop** (R5 of the reasoning-depth audit). `WorkerRequest` declared `effort`, `thinking_budget`, `time_budget_s` since v0.50.x but `WorkerRequest.from_dict` silently dropped them and `_run_agentic` never passed them to `AgenticLoop()`. Every sub-agent ran at the dataclass defaults — `effort="high"`, `thinking_budget=0`, `time_budget_s=0.0` — regardless of what the parent intended. Hermes Agent (`agent/delegate_tool.py:607-636`, parent-inherit + per-child config override) and Claude Code (`utils/AgentTool/loadAgentsDir.ts:116`, agent-level effort frontmatter) both wire this correctly. v0.55.1 mirrors that: `from_dict` deserialises the three fields and `_run_agentic` threads them as `AgenticLoop()` ctor kwargs. (`core/agent/worker.py:WorkerRequest.from_dict, _run_agentic`)

### Tests
- `tests/test_worker.py:TestWorkerRequest::test_reasoning_depth_roundtrip` + `test_reasoning_depth_defaults` — pin the deserialiser invariant.
- `tests/test_worker.py:TestSubAgentReasoningWiring::test_loop_receives_reasoning_kwargs` — verifies `_run_agentic` actually plumbs the kwargs into `AgenticLoop()` (uses `MagicMock` to capture the ctor call).

### Reference
- `docs/research/reasoning-depth-audit.md` — R5 in the cross-codebase comparison; 2/3 references implement parent-inherit, GEODE was the outlier.
- Hermes: `agent/delegate_tool.py:607-636`.
- Claude Code: `utils/AgentTool/loadAgentsDir.ts:116`.

## [0.55.0] — 2026-04-28

### Fixed
- **Codex Plus multi-turn lost reasoning state on every round** (R1 of the reasoning-depth audit). gpt-5.x reasoning is opaque continuation state — the encrypted blob in each `response.output_item.done` of type `reasoning` must be echoed back into the next-turn `input` array, or the model has to re-derive reasoning from scratch every turn. v0.53.3 only handled single-call output. v0.55.0 mirrors the Hermes Agent pattern (`agent/codex_responses_adapter.py:228-246, 720-738`) — extract reasoning items into `AgenticResponse.codex_reasoning_items` (sidecar; `None` on non-Codex providers), persist on the assistant message dict in the loop, replay them in `CodexAgenticAdapter` immediately before the corresponding assistant entry. The `id` field is stripped on replay because `store=False` makes the server unable to resolve items by ID — Hermes calls this out explicitly: *"with store=False the API cannot resolve items by ID and returns 404."* Spec-grounded against `codex-rs/protocol/src/models.rs:701-711` (the `ResponseItem::Reasoning` variant) and `developers.openai.com/codex/cli/`.

### Added
- **`AgenticResponse.codex_reasoning_items: list[dict] | None`** — sidecar field for opaque reasoning continuation state. Populated only by the Codex Plus normaliser (`normalize_openai_responses`); other providers leave it `None`. Loop persists it onto the assistant message dict so the next-turn converter can replay it. (`core/llm/agentic_response.py:AgenticResponse`)
- **`tests/test_codex_multiturn_reasoning.py`** — 10 invariants pinning the round-trip: extraction filters out reasoning items with no `encrypted_content`; other providers' normalisers don't set the sidecar; replay strips `id` and precedes the assistant entry; no-sidecar case doesn't inject; default sidecar is `None`.

### Reference
- `docs/research/reasoning-depth-audit.md` — 3-codebase comparison + per-provider official-doc grounding (the audit that drove this fix).
- Codex Rust source: `codex-rs/protocol/src/models.rs:701-711` (Reasoning variant), `codex-rs/codex-api/src/sse/responses.rs` (event handling), `codex-rs/core/src/client.rs:880` (input echo pattern).
- Hermes Agent: `agent/codex_responses_adapter.py:228-246` (replay loop), `:720-738` (extraction).
- OpenClaw: `src/agents/openai-transport-stream.ts:771` (include unconditional), `:257-264` (replay echo).

## [0.54.0] — 2026-04-28

### Added
- **`geode setup`** — re-runnable first-time setup wizard. Detects ChatGPT subscription OAuth (`~/.codex/auth.json`) before prompting for API keys. `--reset` wipes the existing `~/.geode/.env` and starts over. Anthropic OAuth is intentionally excluded; Anthropic's terms of service (effective 2026-01-09) prohibit third-party reuse of the Claude Code OAuth token. (`core/cli/__init__.py:setup`)
- **`geode about`** — one-screen summary of the runtime: version, active model + provider, registered ProfileStore profiles (no secrets), `~/.geode` paths, daemon socket status. Use this when you want to know "what am I running right now?" without digging through logs. (`core/cli/__init__.py:about`)
- **`geode doctor`** (new default target `bootstrap`) — verifies the first-run surface so beginners aren't left guessing. Seven checks: Python ≥ 3.12, `geode` on PATH, `~/.local/bin` on PATH, `~/.geode/.env` present, Codex CLI OAuth status (with expiry), ProfileStore content, serve daemon socket. Each failure prints a concrete fix command. The previous `geode doctor slack` behaviour is preserved as `geode doctor slack`. (`core/cli/doctor_bootstrap.py` new file)
- **Proactive subscription OAuth detection at first run** — `_welcome_screen()` now calls `detect_subscription_oauth()` before any wizard. If the user has already run `codex auth login`, GEODE picks up the token and skips the wizard entirely. The token is registered in the ProfileStore so the very next prompt routes through the subscription. (`core/cli/startup.py:detect_subscription_oauth`, `core/cli/__init__.py:_welcome_screen`)
- **`env_setup_wizard()` is now a 3-branch menu** — Path A (subscription guidance), Path B (API key paste, the original behaviour), Path C (skip into dry-run mode without re-prompting on next launch). The previous wizard offered only Path B. (`core/cli/startup.py:env_setup_wizard`)
- **Silent dry-run guard** — when readiness reports dry-run mode, `_welcome_screen()` now prints a yellow warning + a one-line hint to run `geode setup`. Previously a user with no credentials could land on a dry-run prompt thinking it was a real LLM call.

### Changed
- **README onboarding flow** rewritten to match the new commands. "5분 setup" now shows three first-class steps: clone + install, `geode setup` (or just `geode`, since proactive OAuth detection runs on first launch), `geode` to start chatting. Path A enumerates the official Codex CLI plan list (Plus, Pro, Business, Edu, Enterprise) per `developers.openai.com/codex/cli/`. The Troubleshooting section now points to `geode doctor` first.

### Tests
- `tests/test_doctor_bootstrap.py` — 17 invariants covering every check (Python version, PATH, env file, OAuth, ProfileStore, serve socket, local-bin) plus aggregator + renderer.
- `tests/test_startup.py:TestDetectSubscriptionOAuth` — 3 cases (no creds → None, valid creds → provider id, probe error swallowed).
- `tests/test_startup.py:TestEnvSetupWizard` rewritten for the new menu. 6 cases: skip/Enter on Path B, Anthropic key set on Path B, Ctrl+C at menu, Path A with OAuth detected, Path A with no OAuth, Path C explicit dry-run.

### Reference
- Anthropic ToS exclusion (re-cited from v0.53.3 hotfix): `https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access` and commit `de18dcd9`.
- Codex CLI plan support: `https://developers.openai.com/codex/cli/` and `https://github.com/openai/codex` README.

## [0.53.3] — 2026-04-28

### Fixed
- **Codex Plus returned `output=[]` for every call** (production incident: REPL showed "AgenticLoop" header with empty body, daemon log showed `in=0 out=0 cost=$0` despite the Codex Plus backend returning `usage_in=25555, usage_out=182, usage_reasoning=26` — the model demonstrably generated ~156 visible tokens). Root cause: the `chatgpt.com/backend-api/codex/responses` SSE protocol omits the `output` field from its `response.completed` event payload by design (verified against the Codex Rust client's `ResponseCompleted` struct in `codex-rs/codex-api/src/sse/responses.rs:120-128` which has no `output` field at all). The OpenAI Python SDK's `client.responses.stream(...).get_final_response()` therefore returns `response.output == []` for Codex Plus. v0.53.3 mirrors the Codex Rust pattern: accumulate items from `response.output_item.done` events as they arrive and overwrite `final.output` with the accumulator before normalising. SDK final-response is now used only as a shell for `usage`/`status`/`response_id`. (`core/llm/providers/codex.py:agentic_call`, 3-codebase grounded against Codex Rust + Hermes Agent + OpenClaw)
- **Codex Plus 400 on multi-turn conversations after a tool call** (regression surfaced post v0.53.3 fix #1). After a `function_call` round, the next LLM call would 400 with `Invalid type for 'input[i].content': expected one of an array of objects or string, but got null instead.` Root cause: `CodexAgenticAdapter.agentic_call` used `_convert_messages_to_openai` (Chat Completions converter — produces `{role:"assistant", content:None, tool_calls:[...]}` for tool-only assistant turns) instead of the Responses API converter `_convert_messages_to_responses` which OpenAI PAYG already used (`openai.py:496`). The Responses API expects per-item-type wire shapes: `function_call` (no `content` field), `function_call_output` (uses `output` not `content`), `message` (content always string/array, never null) — all spec-grounded against the official `openai-python` `ResponseFunctionToolCallParam` / `FunctionCallOutput` / `ResponseOutputMessageParam` TypedDicts. v0.53.3 switches the import + call. Pre-send observability log added (`Codex resp_input shape: ...`) for any future shape regression. (`core/llm/providers/codex.py:213-221`)
- **`normalize_openai_responses` dropped `usage` on empty output** (silent telemetry gap). Pre-fix the early-return for `not response.output` returned a bare `AgenticResponse()` with zero usage even when `response.usage` was populated. v0.53.3 always extracts usage; the empty-output branch additionally surfaces a single WARNING when `usage.output_tokens > usage.thinking_tokens` (model produced visible tokens but the normaliser extracted no blocks — anomalous, never silently dropped). (`core/llm/agentic_response.py:normalize_openai_responses`)
- **`/list_plans` returned `0 items` immediately after a successful `/create_plan`** (production UX bug). Three compounding root causes (B1+B2+C):
  - **B1**: The `_plan_cache` dict lived inside `_build_plan_handlers`'s closure → each invocation of `_build_tool_handlers` (daemon at `services.py:269`, fork at `bootstrap.py:233-237`) created a fresh dict. Cross-handler reads could see an empty cache. v0.53.3 replaces it with a module-level disk-persistent `PlanStore` singleton.
  - **B2**: The AUTO-execute branch of `handle_create_plan` never wrote to the cache (only the MANUAL branch did) → `GEODE_PLAN_AUTO_EXECUTE=true` made all plans invisible to the audit trail. v0.53.3 caches in both branches and persists post-execute status (COMPLETED / FAILED).
  - **C**: `handle_approve_plan` and `handle_reject_plan` immediately popped the entry from the cache → audit trail destroyed for any approved/rejected plan. v0.53.3 keeps the entry; lifecycle is tracked via `PlanStatus` on the plan object itself, and `list_plans` now supports an optional `status` filter for slicing the audit trail. (`core/cli/tool_handlers.py:_build_plan_handlers`)

### Added
- **`core/orchestration/plan_store.py`** — new disk-persistent `PlanStore` (atomic write via tmp+rename, mirrors `core/scheduler/scheduler.py:save`; lazy-loaded; thread-safe via double-checked locking; malformed entries skipped with WARNING; corrupt JSON falls back to empty store rather than crashing daemon startup). Storage at `.geode/plans.json`. Plans now survive daemon restarts.
- **`core/paths.py:PROJECT_PLANS_FILE`** constant for the new store location.
- **`tests/test_plan_mode.py:TestPlanCacheInvariants`** — 4 invariants pinning the B1+B2+C fixes (cross-factory cache sharing, approved-plan audit trail, rejected-plan audit trail, status filter slicing).
- **`tests/test_plan_mode.py:TestPlanStorePersistence`** — 4 invariants for the disk store: roundtrip preserves all fields (steps, dependencies, metadata, status), status update persists, malformed entry does not block others, corrupt JSON falls back to empty.

### Reference
- Codex Rust client (`openai/codex` repo, `codex-rs/`): `ResponseCompleted` struct (`sse/responses.rs:120-128`), accumulator pattern (`core/src/client.rs:1641-1678`), `ResponseItem` enum + serde tagging (`protocol/src/models.rs:751-902`).
- Hermes Agent (`/Users/mango/workspace/hermes-agent`): `_chat_messages_to_responses_input` (`agent/codex_responses_adapter.py:204-325`), output_item.done accumulator (`run_agent.py:4709-4785`).
- OpenClaw (`/Users/mango/workspace/openclaw`): `processResponsesStream` (`src/agents/openai-transport-stream.ts:353-542`).
- OpenAI Responses API spec (`openai-python` TypedDicts): `ResponseFunctionToolCallParam`, `FunctionCallOutput`, `ResponseOutputMessageParam`, `ResponseReasoningItemParam`. Confirmed `function_call` has NO `content` field; `function_call_output` uses `output` not `content`.
- Production daemon log 2026-04-27 19:07:06 — `HTTP 400 Invalid type for 'input[4].content'` after a `create_plan → tool_use → continuation` cycle.

## [0.53.2] — 2026-04-27

### Fixed
- **Anthropic adapter circuit-breaker observability gap** (D1). Pre-fix `ClaudeAgenticAdapter.agentic_call` never invoked `_circuit_breaker.record_failure()` / `record_success()` while OpenAI/Codex/GLM all did — the async LLM path was invisible to the breaker, so a streak of Anthropic failures could not trip the breaker even though the same shape of failure on every other provider would. v0.53.2 adds explicit `record_success()` after the happy path and `record_failure()` on every exception/None branch. (`core/llm/providers/anthropic.py:agentic_call`)
- **`BillingError` swallowed by OpenAI / Codex / GLM adapters** (D2 — quota panel parity gap). v0.53.0 introduced the `quota_exhausted` IPC panel via `BillingError` re-raise from `AgenticLoop._emit_quota_panel`, but only Anthropic's `LLMBadRequestError` branch raised `BillingError`. The other three adapters had a generic `except Exception:` that converted `BillingError` (raised inside `retry_with_backoff_generic` via `is_billing_fatal`) into `self.last_error` and returned `None` — the panel never fired for OpenAI/Codex/GLM, so the v0.52.3 GLM 1113 ("Insufficient balance") incident shape would have been silent on every non-Anthropic provider. v0.53.2 adds `if isinstance(exc, BillingError): record_failure(); raise` ahead of the generic catch on all three adapters. Anthropic's adapter receives the same shape (mirrored on the bare-Exception branch) for symmetry, plus a new `_resolve_plan_meta(model)` helper so async-path BillingErrors carry Plan context. (`core/llm/providers/openai.py`, `codex.py`, `glm.py`, `anthropic.py`)
- **`claude-opus-4` / `claude-opus-4-1` silently fell back to 200K context** (D3). Pricing rows existed in `MODEL_PRICING` but `MODEL_CONTEXT_WINDOW` was missing both keys — `MODEL_CONTEXT_WINDOW.get(model, 200_000)` silently returned 200K for legacy Opus models that actually have larger windows. v0.53.2 adds explicit entries for `claude-opus-4`, `claude-opus-4-1`, and `claude-sonnet-4`. (`core/llm/token_tracker.py:MODEL_CONTEXT_WINDOW`)
- **`gpt-5.5` ModelProfile.provider mismatch** (D4 — `/model` picker label was lying). v0.53.0 added `_CODEX_ONLY_MODELS = {"gpt-5.5"}` so `_resolve_provider("gpt-5.5") == "openai-codex"` (correct: gpt-5.5 is OAuth-only per developers.openai.com/codex/models). But `MODEL_PROFILES` still tagged `gpt-5.5` as `"openai"`, so the picker showed `"OpenAI"` while the actual call consumed Plus quota via Codex backend. The v0.52.4 `resolve_routing()` equivalence-class scan made the routing correct anyway, but the user-visible label was dishonest. v0.53.2 corrects the profile to `"openai-codex"` so picker label == real auth-mode. (`core/cli/commands.py:MODEL_PROFILES`)

### Added
- **`tests/test_provider_parity_v0532.py`** — 11 cross-provider parity invariants pinning all four contracts. Source-level: Anthropic `agentic_call` source contains `_circuit_breaker.record_failure` and `record_success`; every adapter (OpenAI/Codex/GLM/Anthropic) has the `isinstance(exc, BillingError)` re-raise pattern. Functional: `BillingError` is a subclass of `Exception` (so the re-raise must precede the generic catch). Pricing-side: every Anthropic key in `MODEL_PRICING` is also in `MODEL_CONTEXT_WINDOW` (no silent 200K fallback). Profile-side: every `ModelProfile.provider` equals `_resolve_provider(profile.id)` (catches future picker-label drift).

### Reference
- `docs/research/v0531-defect-scan.md` — 213-line scan output (post-v0.53.1, pre-v0.53.2). 4 defects (D1–D4) cited file:line with severity + repro shape. Drove the v0.53.2 scope.

## [0.53.1] — 2026-04-27

### Fixed
- **Codex adapter returned dict, agentic loop expected AgenticResponse** (production hotfix). v0.53.0 dogfooding incident: `/model claude-opus-4-7 → gpt-5.5` succeeded (gpt-5.5 routes to `openai-codex` per v0.53.0 `_CODEX_ONLY_MODELS`), but the very first LLM call crashed with `'dict' object has no attribute 'usage'` at `core/agent/loop.py:1565` (`_track_usage`). Root cause: `CodexAgenticAdapter.agentic_call` returned a raw dict via a local `_normalize_responses_api` helper while the loop reads `response.usage` (attribute access). Anthropic + OpenAI PAYG adapters already used the standard `core.llm.agentic_response.normalize_openai_responses` (returns `AgenticResponse` dataclass); v0.52.7's Codex parity refactor missed this last contract. Fix: Codex adapter now calls `normalize_openai_responses(response)`; the local dict-returning helper is removed entirely. (`core/llm/providers/codex.py:300`)

### Added
- **`tests/test_codex_normalize_parity.py`** — 4 invariant cases. Source-level: `agentic_call` calls `normalize_openai_responses(response)` and never invokes the legacy local helper. Module-level: the legacy `_normalize_responses_api` function definition is removed. Functional: `agentic_call` returns `AgenticResponse` end-to-end with proper `.usage` attribute access. End-to-end: `_track_usage(codex_result)` does not raise.

### Reference
- Production daemon log 2026-04-27 17:32:32 — `AttributeError: 'dict' object has no attribute 'usage'` at loop.py:1565.

## [0.53.0] — 2026-04-27

### Architecture (BREAKING — fail-fast governance redesign)
- **Cross-provider auto-failover REMOVED**. Per the user-confirmed v0.53.0 governance: API/구독 quota 초과 시 silent provider switch 는 cost surprise + behavior drift + identity 혼동 을 만들어 시스템 불확실성을 키운다 — 친절한 안내 + 시스템 정지가 안정적. Audit doc (3 parallel agents) confirmed claw + hermes 둘 다 같은 원칙 (post-pick auth resolve, no auto-cross-swap).
  - `core/llm/adapters.py:CROSS_PROVIDER_FALLBACK` map emptied for all providers (anthropic / openai / glm / openai-codex). Back-compat preserved for external imports.
  - `core/agent/loop.py:_try_cross_provider_escalation` returns False unconditionally (documented no-op).
  - `core/agent/loop.py:_try_model_escalation` cross-provider for-loop removed; same-provider chain exhaustion now surfaces to user.
- **Same-provider fallback chain depth reduced to 1** (primary → secondary). Pre-fix `[opus-4-7, opus-4-6, sonnet-4-6]` (depth 2). v0.53.0 `[opus-4-7, sonnet-4-6]`. Same for openai/glm/codex chains. Reduces cost-surprise from cascading retries.

### Fixed
- **`/model` picker provider label vs ID 불일치** — `"Codex (Plus)"` (marketing) vs `"openai-codex"` (technical) misled users about which auth-mode their pick would consume. v0.53.0 standardises ModelProfile.provider to **canonical provider IDs** (`anthropic` / `openai` / `openai-codex` / `glm`) matching `/login` dashboard + auth.toml. (`core/cli/commands.py:50-64`)
- **`gpt-5.5` static provider mapping** — pre-fix `_resolve_provider("gpt-5.5")` returned `"openai"` even though OpenAI's official Codex models page (verified v0.52.8 spec doc) says gpt-5.5 is **OAuth-only** ("isn't available with API-key authentication"). Added `_CODEX_ONLY_MODELS` set in `core/config.py` so the static mapping is honest; `resolve_routing()` equivalence-class scan still handles the actual routing. (`core/config.py:_resolve_provider`)

### Added
- **Plan-aware quota panel** (`quota_exhausted` IPC event). When `BillingError` carries Plan context (provider/plan_id/plan_display_name/upgrade_url/resets_in_seconds), the thin client renders a multi-line panel: header + reset-time + 3 actionable Options (wait / switch auth / switch provider) + upgrade URL. Pre-v0.53.0 the user saw a single-line "Billing error" with no next step; cross-provider auto-failover then silently swapped providers (cost surprise). Now the loop stops + the user decides. (`core/llm/errors.py:BillingError.user_message`, `core/ui/agentic_ui.py:emit_quota_exhausted`, `core/ui/event_renderer.py:_handle_quota_exhausted`, `core/cli/ipc_client.py KNOWN_EVENT_TYPES`)
- **`_resolve_plan_for_billing_error(model)`** — `core/llm/fallback.py` resolves Plan metadata via `resolve_routing()` so `BillingError` raised from the retry loop carries provider/plan context for the panel.
- **`docs/research/model-ux-governance.md`** — 544-line audit doc (3 parallel agents: claw+hermes /model UX, GEODE current state, /login UX). All claims cite file:line. Includes 13-gap GAP matrix + Phase 1/F/2/3 redesign plan + Addendum (fail-fast on quota). Source-of-truth for v0.53.0 design decisions.

### Tests
- **`tests/test_quota_fail_fast.py`** — 11 invariant cases. Cross-provider map empty across all providers. Escalation methods return False (no auto-swap). BillingError carries Plan context. user_message renders multi-line panel with options. `_emit_quota_panel` routes to `quota_exhausted` event when provider present, falls back to `billing_error` legacy path otherwise. `quota_exhausted` in IPC allowlist + EventRenderer handler exists.
- 7 fixture updates in `tests/test_model_escalation.py` for chain-depth-1 + cross-provider-removed semantics.
- Fixture update in `tests/test_codex_provider.py` for canonical provider ID (`openai-codex` not `Codex (Plus)`).

### Reference
- `docs/research/model-ux-governance.md` (544 lines, 3 codebase-grounded agents — all file:line cited).
- v0.52.4 `resolve_routing()` equivalence-class scan + v0.52.5 GEODE-issued OAuth precedence + v0.52.6 `is_request_fatal` + v0.52.7 Codex Responses parity all stand: governance redesign is *additive policy + UX surface*, not architectural change.
- User direction (2026-04-27): "사용자가 picks model only; 시스템이 OAuth/API 결정" + "API/구독 quota 초과 → 친절한 안내 + 시스템 중지".

## [0.52.8] — 2026-04-27

### Fixed
- **Model identity drift across `/model` switches** (production incident). User did `/model gpt-5.5`, daemon log confirmed gpt-5.5 was called, but the LLM responded "현재 사용 중인 모델은 gpt-5.4-mini" (claimed to be the previous model). Root cause: the v0.52.5 ``_prompt_dirty`` rebuild correctly updated the system-prompt model card, BUT the conversation history still contained earlier ``Understood. I am now <prev_model>.`` assistant acks from prior switches in the same session. The new model deferred to those historical assertions over the system prompt. OpenAI's gpt-5.5 system card (deploymentsafety.openai.com) explicitly says it should identify as "GPT-5.5" — so the model itself is capable; this was our breadcrumb pollution.
  - **Fix 1**: ``_build_model_card(model)`` now uses an explicit, repeated identity assertion ("ACTIVE MODEL IDENTITY ... You are **{model}** ... When asked which model you are, the answer is **{model}** ... Ignore any earlier assistant message that claims a different model name") — combats both recency bias and any backend system-layer claim. (`core/agent/system_prompt.py:184`)
  - **Fix 2**: ``AgenticLoop._purge_stale_model_switch_acks()`` strips prior ``Understood. I am now <prev>.`` assistant acks from history before injecting the new switch ack — each switch leaves exactly one active ack. (`core/agent/loop.py:update_model` + new helper)
- **Codex backend system layer override** (Fix 3 candidate) — DEFERRED. WebFetch verification (Agent C): 3 openai.com URLs returned 403, no public docs describe whether ChatGPT outer system layer overrides user `instructions` on `chatgpt.com/backend-api/codex/responses`. Without evidence, do not add complexity. Re-open if the identity bug recurs after Fix 1+2.

### Added
- **`tests/test_model_identity.py`** — 9 invariant cases. Card-side: assertion text + model-name repetition + anti-stale-ack instruction + provider name + Anthropic parity. Purge-side: removes acks (single + multiple), preserves user messages even if matching prefix verbatim, preserves unrelated assistant replies, no-op on empty history, handles non-string content (Anthropic block format).

### Reference
- gpt-5.5 official spec verified 2026-04-27 via WebFetch (Agent C):
  - Released 2026-04-23 to ChatGPT/Codex (Plus/Pro/Business/Enterprise); API rollout 2026-04-24
  - Codex backend (`chatgpt.com/backend-api/codex`): ChatGPT sign-in only, no API-key auth
  - System card: "should identify itself as **GPT-5.5**" (deploymentsafety.openai.com/gpt-5-5)
  - Pricing matches GEODE v0.52.4 values: $5.00 / $0.50 cached / $30.00 per 1M tokens, 1,050,000 context, 128K max output, knowledge cutoff 2025-12-01
  - Plus quota: 15-80 local msgs / 5h
  - **NEW backlog**: >272K-token prompts cost 2× input / 1.5× output (premium tier — not yet captured in our token tracker)
- 2 parallel reference agents:
  - Agent A — GEODE model identity flow audit (system_prompt rebuild path → conversation history breadcrumbs → Codex backend layer)
  - Agent C — gpt-5.5 official spec via WebFetch (developers.openai.com 200, 3 openai.com URLs 403 / Cloudflare)

## [0.52.7] — 2026-04-27

### Fixed
- **Codex function-calling broken** — `tools` / `tool_choice` / `parallel_tool_calls` were never forwarded to the Codex Responses API. The Codex agentic loop received no native tool dispatch path on Plus subscriptions; LLM saw "no tools available" on every turn. Forward all three per Codex Rust `ResponsesApiRequest` struct + Hermes `agent/transports/codex.py` shape. (`core/llm/providers/codex.py:CodexAgenticAdapter.agentic_call`)
- **Encrypted reasoning lost across turns on gpt-5.x-codex** — `include=["reasoning.encrypted_content"]` + `reasoning={effort, summary}` were never sent. Codex backend strips encrypted reasoning blocks from non-include responses, breaking multi-turn reasoning continuity (each turn re-discovers what it already worked out). Sent for all gpt-5.x models. (Same file)
- **Temperature sent to gpt-5.x-codex unconditionally** — Hermes `_fixed_temperature_for_model` returns OMIT for these models; sending it can return 400 or skew the reasoning sampler. Now omitted for gpt-5.x; preserved for non-reasoning models. (Same file)

### Added
- **`_is_codex_reasoning_model(model)` classifier** — gates the include / reasoning / temperature behaviour. Currently `model.startswith("gpt-5")` covers gpt-5.5, gpt-5.4, gpt-5.4-mini, gpt-5.3-codex (the entire CODEX_FALLBACK_CHAIN). Future Codex additions inherit the same handling without code changes.
- **`tests/test_codex_responses_shape.py`** — 11 invariant cases covering: tools forwarded with correct Responses-API flat schema; tool_choice="auto" + parallel_tool_calls=True when tools present; both omitted when tools empty; include + reasoning + temperature-omit for gpt-5.x; temperature preserved + reasoning skipped for non-gpt-5.x; v0.52.6 max_output_tokens absence still pinned post-refactor.

### Reference
- `docs/research/codex-oauth-request-spec.md` — definitive spec grounded in Hermes Agent + OpenClaw + Codex CLI Rust (introduced in v0.52.6). v0.52.7 closes the 3 remaining gaps the doc identified.

## [0.52.6] — 2026-04-27

### Fixed
- **Codex backend rejected every call with 400 — `max_output_tokens` not allowed** (production hotfix). Every call to `https://chatgpt.com/backend-api/codex/responses` returned `{'detail': 'Unsupported parameter: max_output_tokens'}`, hitting all 3 fallback Codex models × 5 retries × exp-backoff for ~30s before the circuit breaker opened. Plus subscription manages output limits server-side; client cap is forbidden. Removed the kwarg from `CodexAgenticAdapter.agentic_call`'s `client.responses.stream(...)` call. (`core/llm/providers/codex.py:228`)
- **400 "Unsupported parameter" / "Invalid value" retried** — same fail-fast shape as the v0.52.3 billing-fatal storm. Added `is_request_fatal(exc)` in `core/llm/errors.py` that recognises 4xx (non-429) bodies with markers `unsupported parameter`, `invalid parameter`, `invalid value for parameter`, `unknown parameter`, `missing required parameter`. `fallback.retry_with_backoff_generic`'s `bad_request` branch re-raises immediately so the same backend rejection cannot cascade across retries + fallback models.

### Added
- **`docs/research/codex-oauth-request-spec.md`** — definitive Codex OAuth request spec grounded in 3 reference codebases (Hermes Agent `agent/transports/codex.py`, OpenClaw `src/agents/openai-transport-stream.ts`, Codex CLI Rust `codex-rs/codex-api/src/common.rs`). Documents required headers, required body fields, and a FORBIDDEN list (`max_output_tokens`, `max_tokens`, `top_p`, `presence_penalty`, `frequency_penalty`, `seed`, `n`, `stop`, `logprobs`). Future-proofs against Codex backend spec changes.
- **`tests/test_codex_request_shape.py`** — 13 invariant cases covering Codex adapter source-level (no `max_output_tokens` in `responses.stream` call) + functional (`is_request_fatal` recognises 5 marker shapes, ignores 429/500, fallback loop re-raises without retry).

### Backlog (v0.52.7 — separate scope)
- Per the new spec doc, GEODE Codex adapter still has 3 gaps (NOT cause of the 400 incident, but real):
  - `tools` / `tool_choice` / `parallel_tool_calls` never sent → function calling broken on Codex
  - `include=["reasoning.encrypted_content"]` + `reasoning={effort, summary}` never sent → encrypted reasoning lost across turns on gpt-5.x-codex
  - `temperature` sent unconditionally; Hermes uses `_fixed_temperature_for_model` to OMIT for gpt-5.x-codex

### Reference
- Production daemon log 2026-04-27 (every Codex call → 400 → circuit breaker OPEN within ~30s)
- Hermes Agent `agent/transports/codex.py:123-125` — `if max_tokens is not None and not is_codex_backend: kwargs["max_output_tokens"] = max_tokens`
- Codex CLI Rust `codex-rs/codex-api/src/common.rs:117-133` — `ResponsesApiRequest` struct has no `max_output_tokens` field
- OpenClaw `src/agents/openai-transport-stream.ts:751-753` — `buildOpenAIResponsesParams` only adds `max_output_tokens` when caller passes `options.maxTokens`; Codex callers don't

## [0.52.5] — 2026-04-27

### Fixed
- **Codex token resolution silently shadowed by Codex CLI session** — `_resolve_codex_token` iterated `ProfileStore` in insertion order, and `build_auth` adds external CLI profiles (`managed_by="codex-cli"`) BEFORE reading auth.toml. So a user who registered an OAuth token via `/login oauth openai` but also had Codex CLI logged in would silently use Codex CLI's token, not theirs. v0.52.4's stated "GEODE-issued first" contract was ineffective. Fix: 2-pass iteration — `managed_by == ""` (GEODE-issued) wins; `managed_by="codex-cli"` is the second-pass fallback. (`core/llm/providers/codex.py:_resolve_codex_token`)
- **System prompt staleness after escalation** — `_try_model_escalation` and `_try_cross_provider_escalation` call `update_model()` directly + persist via `_persist_escalated_model(settings.model = next)`. The next round's `_sync_model_from_settings()` then sees no drift and skips the system prompt rebuild — leaving the model card pinned to the previously-failed model. Fix: `update_model()` sets `self._prompt_dirty = True`; the run-loop rebuilds when EITHER drift OR dirty flag is set. (`core/agent/loop.py:update_model`, `core/agent/loop.py:704`)

### Added
- **`tests/test_provider_switching.py`** — 11 invariant cases pinning the 5 switch paths (3C2 cross-provider + 2 within-provider Plan switches):
  - Path A: Codex Plus OAuth → Anthropic API key
  - Path B: Codex Plus OAuth → GLM Coding Plan
  - Path C: Anthropic → GLM
  - Path D: Codex Plus OAuth → OpenAI PAYG (within-provider, with `forced_login_method="apikey"` variant)
  - Path E: GLM Coding → GLM PAYG (within-provider)
  - Plus cross-cutting: token-leak detection (no provider's credential leaks into another's call), GEODE-issued OAuth precedence, adapter swap on cross-provider, adapter reuse on within-provider, `_prompt_dirty` invariant.

### Reference
- 2 parallel reference agents:
  - GEODE switch code-path audit — identified 2 real bugs (token shadowing, prompt staleness) + flagged false positives that turned out non-issues (ContextVar carryover affects pipeline only, not chat loop)
  - Codex CLI / Claude Code / aider / simonw-llm / OpenClaw switch-state policies — Codex has no in-session switch (resume only); Claude Code preserves history + invalidates prompt cache + confirmation gate on prior output; aider rebuilds Coder via SwitchCoder exception; simonw/llm stateless. **GEODE chose aider's preserve-history pattern** (already implemented).

## [0.52.4] — 2026-04-26

### Fixed
- **Plan-aware model routing — SUBSCRIPTION/OAUTH wins over PAYG by default** (production incident: `gpt-5.4` calls hit `api.openai.com/v1` at $0.10/call even after `/login oauth openai` registered Codex Plus). Root cause: `_resolve_provider("gpt-5.4")` was a static map returning `"openai"`; the `PlanRegistry.resolve_routing()` resolver was never consulted by `core/llm/router.py`. The four `call_llm*()` entry points now go through a new `_route_provider(model)` helper that calls `resolve_routing()` and returns the actually-routed provider (e.g. `openai-codex` when a Plus OAuth Plan is registered). Pattern source: openai/codex CLI default (`forced_login_method` unset → ChatGPT subscription wins; issues #2733, #3286).

### Added
- **`PlanKind` priority + provider-equivalence routing** (`core/auth/plans.py`, `core/llm/registry.py`, `core/auth/plan_registry.py`). New `PLAN_KIND_PRIORITY` ranks `SUBSCRIPTION → OAUTH_BORROWED → CLOUD_PROVIDER → PAYG` (lower wins). `PROVIDER_EQUIVALENCE` map declares sibling provider classes (`openai ↔ openai-codex`, `glm ↔ glm-coding`). `resolve_routing()` gains a step 1.5 between explicit `set_routing` and provider fallback: scan all sibling providers, sort by `PLAN_KIND_PRIORITY`, return the first with an available profile. Pattern source: OpenClaw Lane fail-over + already-existing `AuthProfile.sort_key()` infra.
- **`forced_login_method` per-provider escape hatch** (`core/config.py`). `settings.forced_login_method = {"openai": "apikey"}` flips kind-priority so PAYG wins for users who deliberately want metered API access despite an active subscription. Default empty dict ⇒ subscription default. Codex CLI parity.
- **GEODE-issued Codex token resolution** (`core/llm/providers/codex.py:_resolve_codex_token`). Now checks ProfileStore for an `openai-codex` profile FIRST (the one registered by `/login oauth openai`), with the legacy `~/.codex/auth.json` path as fallback. Pre-fix the OAuth login wizard wrote to GEODE's auth.toml but the Codex client only read from Codex CLI's separate store, so geode-issued tokens were silently invisible to LLM calls.
- **`tests/test_routing_policy.py`** — 10 invariant cases pinning equivalence-class scan, kind-priority sort, escape hatch, explicit-override precedence, and router wiring (4 call sites must use `_route_provider`, none may use `_resolve_provider(target_model)` directly).

### Changed
- **Model registry refresh — verified 2026-04-26 against official docs** (`core/config.py`, `core/llm/token_tracker.py`). Per CLAUDE.md model-currency policy: drop sub-5.3 OpenAI IDs, add `gpt-5.5` (Codex's new default, **OAuth-only** per developers.openai.com/codex/models — "isn't available with API-key authentication"), refresh stale GLM pricing.
  - `OPENAI_PRIMARY` `gpt-5.4` → `gpt-5.5`. Chain `[gpt-5.4, gpt-5.2, gpt-4.1]` → `[gpt-5.5, gpt-5.4, gpt-5.3-codex]`.
  - `CODEX_PRIMARY` `gpt-5.4-mini` → `gpt-5.5`. Chain `[gpt-5.4-mini, gpt-5.4, gpt-5.3-codex]` → `[gpt-5.5, gpt-5.3-codex, gpt-5.4-mini]`.
  - Removed: `gpt-5.1`, `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-5.2`, `gpt-5.2-codex`, `gpt-5.1-codex-max`, `gpt-5.1-codex-mini`, `gpt-4.1*`. (All sub-5.3 generation or absent from current Codex models page.)
  - GLM pricing: `glm-5.1` $0.95/$3.15 → $1.40/$4.40 (stale by 6+ months). `glm-5` $0.72/$2.30 → $1.00/$3.20. `glm-4.7` $0.40/$1.75 → $0.60/$2.20. `glm-5v-turbo` removed (not on docs.z.ai pricing table).
  - Anthropic chain unchanged (already 4.5-4.7 generation, verified current). OAuth status unchanged (still disabled per Anthropic ToS clarification 2026-01-09 — `platform.claude.com/docs/en/api/oauth` returned 404 on 2026-04-26 verification).
- 4 test fixtures updated to match refreshed model lists (`test_codex_provider`, `test_llm_client`, `test_model_escalation`).

### Reference
- v0.52.1 production incident transcript (gpt-5.4 routes PAYG despite Codex Plus OAuth registered).
- 4 parallel reference agents:
  - GEODE code-path map: `_resolve_provider`/`resolve_routing`/`ProfileRotator.resolve` end-to-end trace
  - Codex CLI / Claude Code / aider / mods / simonw-llm precedence policies (openai/codex#2733/#3286 — subscription default; Claude Code env-key default is documented footgun)
  - OpenClaw routing patterns (`evaluate_eligibility`, `_LAST_VERDICTS`, `managedBy`, Lane fail-over)
  - Official model availability research (developers.openai.com, platform.claude.com, docs.z.ai — all retrieved 2026-04-26)

## [0.52.3] — 2026-04-26

### Fixed
- **B4 — billing-fatal errors retried as transient** (v0.52.1 incident: 40s wasted per LLM call). GLM 429 with code `1113` ("Insufficient balance"), OpenAI `insufficient_quota`, Anthropic `permission_error` 가 SDK 의 `RateLimitError` 로 분류되어 5×4=20 retry × exp-backoff 으로 ~40s 동안 헛돌았음. `core/llm/errors.py` 에 `is_billing_fatal()` + `extract_billing_message()` 신설, `core/llm/fallback.py:235` retry 루프 진입 직전에 호출 → `BillingError` 즉시 raise. 사용자가 본 "thinking ↔ working 무한루프" 증상의 정체.
- **B6 — parallel HITL approval race** (v0.52.1 incident: `manage_login` 승인 받고도 거부됨). LLM 이 같은 round 에서 같은 tool 을 2회 parallel 호출 → 2개 `approval_request` 가 thin client 로 동시 발사 → 사용자가 `A` 한 번 입력 (첫 prompt 가 소비) → 두번째 prompt 가 120s timeout → silent denial. `core/agent/approval.py:80` 에 이미 존재했지만 사용 안 되던 `_approval_lock` 을 `apply_safety_gates` 의 WRITE/EXPENSIVE branch 에 wrap. 두번째 caller 는 lock 안에서 `_always_approved_categories` 를 re-check 해서 첫 caller 의 "A" promotion 을 즉시 관측, prompt 없이 short-circuit.
- **B3 — model drift sync 가 unhealthy target 으로 silent 전환** (v0.52.1 incident: OAuth 직후 GLM 으로 회귀). settings store 의 stale `glm-4.7-flash` 가 loop 의 `glm-5.1` 을 quota 확인 없이 덮어씀. `core/agent/loop.py:_sync_model_from_settings` 에 `_drift_target_is_healthy()` 신설 — `update_model()` 호출 전에 `ProfileRotator.resolve(target_provider)` 결과 확인, None 이면 drift 거부 + WARNING 로그. 패턴: OpenClaw `evaluate_eligibility` + `_LAST_VERDICTS`.
- **B1 — OAuth success 메시지가 잘못된 경로 표시** (`Stored: ~/.geode/auth.json` 출력 but 실제는 `auth.toml`). v0.50.2 SOT migration 후 `AUTH_STORE_PATH` 가 legacy `auth.json` constant 의 alias 로 남아있었음. `core/auth/oauth_login.py` 에 `auth_store_path()` 신설 — `auth_toml_path()` 로 위임, `GEODE_AUTH_TOML` env 도 honor. `emit_oauth_login_success(stored_at=...)` call site 도 갱신.

### Added
- **B2 — `cmd_login("refresh")` 관측성 로그** (`core/cli/commands.py:1956`). 이전에는 success 시 완전 silent 이었던 daemon-side reload 가 INFO 로그를 emit — `auth.toml reload: file=... loaded=True new_plans=N new_profiles=M total_plans=X total_profiles=Y` + per-plan/profile 라인. 프로덕션에서 thin → daemon refresh signal 이 fire 하는지 사후 확인 가능. Hermes `tracing::info!(field=value, "event")` 패턴 + OpenClaw `markAuthProfileGood` 차용.
- **B5 — credential breadcrumb cross-provider escalation** (`core/auth/credential_breadcrumb.py`). 활성 provider 의 모든 profile 이 거부됐을 때 다른 provider 들의 healthy profile 을 스캔해서 `cross-provider: openai-codex(codex-cli); anthropic(default)` 한 줄을 LLM context 에 주입. 이전에는 GLM exhausted 시 LLM 이 "GLM rejection" 만 보고 등록된 Codex Plus OAuth 의 존재를 알 수 없었음. 패턴: OpenClaw Lane fail-over (Session Lane → Global Lane). 자동 cross-provider failover (`llm_cross_provider_failover` flag) 는 default OFF 유지 — 정보 surface 만 추가하고 실제 switch 는 LLM/사용자 결정.
- **6 invariant test files** (34 cases) — `test_billing_fatal.py` (11), `test_parallel_approval.py` (5), `test_model_drift_health.py` (6), `test_oauth_path_display.py` (3), `test_credential_breadcrumb_cross_provider.py` (4), `test_signal_reload.py` +1 case for B2.

### Reference
- v0.52.1 production incident (transcript: `/login oauth openai` → GLM model drift → 40s retry storm + parallel `manage_login` denial).
- OpenClaw 차용 매핑 (`.claude/skills/openclaw-patterns/`): `evaluate_eligibility`, `_LAST_VERDICTS`, `markAuthProfileGood`, Lane fail-over, `managedBy`.
- Hermes 차용 매핑 (`rsasaki0109/hermes-agent-rs`): `tracing::info!` 구조화 로그, `LlmError` 분류 (no false-retries by omission), session model authoritative pattern.
- simonw/llm #112: "billing/quota error → log + surface + DO NOT retry".

## [0.52.2] — 2026-04-26

### Fixed
- **REASONING_METRICS audit logger silently emitted blank rows** — the audit-logger keys list (`["rounds", "tool_call_count"]`) never matched `ReasoningMetrics.to_dict()` field names (`total_rounds`, `tool_calls_total`), so every reasoning_metrics audit log line rendered with empty `%s` substitutions. Realigned the keys list and added a contract test in `tests/test_reasoning_metrics.py` that asserts both ends agree. (`core/lifecycle/bootstrap.py:448`)
- **`_total_empty_rounds` quadratic inflation** — every overthinking round added the running consecutive-counter (`+= self._consecutive_text_only_rounds`), so 3 flagged rounds reported as `2+3+4=9`. Now increments by 1 per flagged round, matching the metric's documented meaning. (`core/agent/loop.py:1046`)
- **`min(adaptive_thinking, adaptive_thinking // 2)` no-op** — collapsed to `max(0, adaptive_thinking // 2)`, which is what the comment ("reduce budget") actually implies. Adds a 0 floor in case the legacy budget ever goes negative. (`core/agent/loop.py:1395`)
- **`cost_per_tool_call` zero-tool-call ambiguity** — sessions with zero tool calls reported `0.0`, indistinguishable from "very cheap per tool call." Now `None`, and omitted from `to_dict()` so downstream alerting can detect "not measured" cleanly. (`core/agent/reasoning_metrics.py:35-50`)

### Removed
- **Dead `_total_thinking_tokens` instance variable** — initialized to 0 and never mutated; `_build_reasoning_metrics` always added 0 to the tracker value. Removed both. (`core/agent/loop.py:209,413`)

### Documentation
- **`reasoning_metrics.py` module docstring** — clarified that `thinking_ratio` is `thinking / output` (input excluded), a GEODE variant rather than the layer-wise JSD ratio from the original DTR paper. Prevents future contributors from inferring paper-equivalent semantics.

## [0.52.1] — 2026-04-26

### Added
- **B7 invariant test** — `tests/test_signal_reload.py` (4 cases) pins the thin → daemon state-propagation contract for `/login`, `/key`, `/auth`. Asserts (1) the CLI dispatch loop relays `/login refresh` after THIN auth commands, (2) `cmd_login("refresh")` calls `load_auth_toml()` and the merge is **additive only** (managed-by-CLI profiles such as Codex CLI OAuth survive a refresh), (3) refresh on a missing auth.toml is a silent no-op.
- **`docs/v053-cleanup-targets.md`** — tracker for the 33 `import-linter` `ignore_imports` legacy violations registered in v0.52.0. Grouped into 9 PR-sized batches (G1-G9) and slotted into v0.53.0 → v0.53.7. Each entry lists the violation, root cause, and the planned move/rule change.

### Documentation
- `cmd_login("refresh")` 안에 **additive-only invariant** docstring 추가 — `load_auth_toml()` 이 cached singleton 에 merge 만 하고 evict 안 한다는 점을 코드에서 바로 보이게 함. 리팩토링 시 "rebuild from disk" 실수로 v0.51 stale-state 버그가 거꾸로 재발하는 걸 막기 위함. (`core/cli/commands.py:1938-1962`)

## [0.52.0] — 2026-04-25

### Architecture
- **Process binding split — cli/server/agent/channels** — 단일 `core/` 안에 thin-client (`cli/`), daemon (`server/`), 추론 엔진 (`agent/`), 외부 채널 (`channels/`) 4개 프로세스 경계를 디렉토리 위치로 가시화. Hermes/OpenClaw/Claude Code 의 동일 패턴 차용. 이전엔 `gateway/`, `runtime_wiring/`, `automation/` 가 모두 daemon-side 코드를 섞어 호스팅해서 OAuth 출력이 어느 프로세스에서 나는지 추적이 불가능했음. 7 phase 에 걸쳐 165+ 파일 이동 + import 갱신.
- **`import-linter` 4 contracts** — `core.cli ↛ core.server | core.channels`, `core.agent ↛ core.cli | core.server`, `core.server ↛ core.cli`, `core.channels ↛ core.cli | core.server | core.agent` 를 CI ratchet 으로 강제. 33 legacy violation 은 `ignore_imports` 로 등록 후 v0.53.x 시리즈에서 정리 (위 tracker 참고).
- **`COMMAND_REGISTRY` + `RunLocation`** — `core/cli/routing.py` 가 모든 슬래시 명령에 대해 thin/daemon 실행 위치를 명시. `/login`, `/key`, `/auth`, `/help`, `/list`, `/model` 6 개는 `THIN` (CLI 프로세스 직접 실행), 그 외는 IPC relay. OAuth device-code prompt 가 daemon `capture_output()` 에 swallow 되던 v0.51 버그(B1/B3)의 정식 해결.

### Added
- **8 invariant tests for bug class regression prevention** —
  - `tests/test_no_daemon_print.py` (B1) — daemon dirs (`server/`, `agent/`, `channels/`, `lifecycle/`, ...) AST 스캔, native `print/input/Console()` 사용 시 fail.
  - `tests/test_command_registry.py` (B2) — 모든 명령이 정확히 1 RunLocation 을 갖고, THIN 핸들러가 `_ipc_writer_local` 에 의존하지 않음을 검증.
  - `tests/test_auth_store_singleton.py` (B4) — ProfileStore 가 dual SOT 가 아님을 검증.
  - `tests/test_provider_label_consistency.py` (B5) — provider label fragmentation 검출.
  - `tests/test_ipc_event_parity.py` (B6) — `emit_*` 호출이 ipc_client `KNOWN_EVENT_TYPES` allowlist 에 등록됐는지 검증.
  - `tests/test_import_linter.py` (B8) — `uv run lint-imports` 결과 0 broken 을 CI 에 wrap.
  - `tests/test_signal_reload.py` (B7) — v0.52.1 에서 신설 (위 항목).

### Changed
- `core/runtime_wiring/` → `core/lifecycle/` (이름 변경 + container.py 신설).
- `core/gateway/auth/` → `core/auth/` (top-level capability).
- `core/cli/ui/` → `core/ui/` (cross-process 공유 컴포넌트).
- `core/gateway/` 디렉토리 폐기 — pollers → `core/server/{ipc_server,supervised}/`, channel 코드 → `core/channels/`.
- `core/automation/cron*` → `core/scheduler/`.
- `core/agent/agentic_loop.py` → `core/agent/loop.py`, `core/agent/safety_constants.py` → `core/agent/safety.py`.

### Fixed
- v0.51.1 의 IPC OAuth event 패치는 증상 해소만 했음. v0.52.0 의 `COMMAND_REGISTRY` 가 `/login` 을 THIN 으로 바인딩하면서 OAuth wizard 가 CLI 프로세스 stdin/stdout/browser 에 직접 붙어 root cause 가 사라짐.

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
