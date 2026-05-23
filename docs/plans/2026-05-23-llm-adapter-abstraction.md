# LLM Adapter Abstraction — paperclip pattern adoption

**Date**: 2026-05-23
**Branch**: `feature/llm-adapter-abstraction`
**Scope**: Single PR
**Reference**: `~/workspace/paperclip` (`packages/adapter-utils/src/types.ts:349 ServerAdapterModule`, `server/src/adapters/registry.ts`, `adapter-plugin.md` phase-1 notes)

## Why

User-facing requirement: "PAYG, 구독제(OAuth), Adapter(local agent-cli) 세 가지를 UI/UX 에서 선택할 수 있어야 한다. 매번 클로드 코드로만 조작하는 게 아니니까."

Code-grounding verification (2026-05-23, this session):

- `RoleBinding.source` from `plugins/seed_generation/picker.py:262 pick_bindings` is **purely a display/billing label**. It is NEVER threaded through to the LLM call site.
- `cli.py:443 Pipeline(state=state, registry=registry)` drops `picker_result` entirely (binding never enters the pipeline).
- `core/agent/sub_agent.py:497 _build_worker_request` resolves provider via `_resolve_provider(worker_model)` — pure model-id prefix string match.
- `core/llm/providers/anthropic.py:321 _resolve_anthropic_key` → `ProfileRotator.resolve(provider)` uses a global type-priority (OAUTH > TOKEN > API_KEY). Per-role source override is impossible.
- `core/orchestration/claude_cli_lane.py` (LaneQueue) is wired into `core/self_improving_loop/cli_subprocess.py` and `plugins/petri_audit/claude_cli_provider.py`, but NOT into the seed_generation path.

Two cut points:

1. **W1**: `picker_result.bindings` ─/→ `Pipeline` (cli.py:443)
2. **W2**: provider resolution ignores `source` (sub_agent.py:560)

Adopting paperclip's adapter pattern unifies these into a single contract.

## Design — 4-layer + glue

### Layer 4 — `LLMAdapter` Protocol (paperclip `ServerAdapterModule` mirror)

`core/llm/adapters/base.py` (NEW). Protocol (PEP 544 duck typing) — external plugins implement without subclassing.

```python
class LLMAdapter(Protocol):
    name: str            # canonical id e.g. "anthropic-payg" / "claude-cli"
    provider: str        # "anthropic" / "openai" / "glm"
    source: str          # "payg" / "subscription" / "adapter"
    billing_type: AdapterBillingType  # paperclip enum: api / subscription / subscription_included / ...

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult: ...
    def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]: ...

    def test_environment(self) -> EnvironmentReport: ...  # paperclip testEnvironment
    def list_models(self) -> list[ModelSpec]: ...
    def get_quota_windows(self) -> QuotaWindows | None: ...
    def detect_credential(self) -> CredentialDetection | None: ...
```

Companion dataclasses: `AdapterCallRequest` (system + messages + tools + sampling), `AdapterCallResult` (text + usage + stop_reason), `StreamEvent`, `ModelSpec`, `QuotaWindows`, `EnvironmentReport`, `CredentialDetection`. `AdapterBillingType` enum mirrors paperclip 8-value taxonomy.

### Layer 4 — Registry

`core/llm/adapters/registry.py` (NEW). Mutable global registry mirroring paperclip `registerServerAdapter` / `unregisterServerAdapter`.

```python
def register_adapter(adapter: LLMAdapter, *, replace: bool = False) -> None
def unregister_adapter(name: str) -> None
def get_adapter(name: str) -> LLMAdapter  # KeyError if missing
def list_adapters() -> list[LLMAdapter]
def resolve_for(provider: str, source: str) -> LLMAdapter  # "auto" raises — picker resolves first
def bootstrap_builtins() -> None  # called from core/runtime.py
```

### Layer 3 — 6 concrete adapters

| name | provider | source | billing_type | wraps Layer 2 |
|---|---|---|---|---|
| `anthropic-payg` | anthropic | payg | api | `providers/anthropic.py:get_async_anthropic_client(api_key=…)` |
| `anthropic-oauth` | anthropic | subscription | subscription | `providers/anthropic.py` + ProfileRotator force OAUTH-only |
| `claude-cli` | anthropic | adapter | subscription_included | `core/orchestration/claude_cli_lane.py` + `plugins/petri_audit/adapters/claude_cli_backend.py` subprocess |
| `openai-payg` | openai | payg | api | `providers/openai.py` |
| `codex-oauth` | openai | subscription | subscription | `providers/codex.py:_get_async_codex_client` |
| `codex-cli` | openai | adapter | subscription_included | `core/orchestration/codex_cli_lane.py` + codex subprocess |

Files: `core/llm/adapters/anthropic_payg.py`, `anthropic_oauth.py`, `claude_cli.py`, `openai_payg.py`, `codex_oauth.py`, `codex_cli.py`.

### Glue — source threading

| # | Change | Location |
|---|---|---|
| G1 | `SubTask.source: str = "auto"` | `core/agent/sub_agent.py:119` |
| G2 | `WorkerRequest.source: str = ""` + propagate from SubTask | `core/agent/sub_agent.py:497` + `core/agent/worker.py:48` |
| G3 | `AgenticLoop(source=…)` kwarg accepted (consumed by adapter selection at LLM call site) | `core/agent/loop/__init__.py` |
| G4 | Replace direct `client.messages.create / responses.create` in agentic loop with `adapter.acomplete(req)` (resolve_for at call site using worker_request.provider + source) | `core/agent/loop/_reflection.py` etc. |
| G5 | `Pipeline.__init__(state, registry, bindings=None)` accepts `bindings: dict[str, RoleBinding] \| None` | `plugins/seed_generation/orchestrator.py:390` |
| G6 | `cli.py:443` passes `picker_result.bindings` to `Pipeline(...)` | `plugins/seed_generation/cli.py:443` |
| G7 | `_arun_phase` reads `bindings[role].source / model` and builds `SubTask(source=…, model=…)` | `plugins/seed_generation/orchestrator.py` |
| G8 | S11 — `PipelineRegistry` populated with 7 agent instances (generator/critic/pilot/ranker/evolver/meta_reviewer/literature_review) | `plugins/seed_generation/cli.py:436` |

### Config SoT — config.toml unification

Existing surface: `~/.geode/seed-generation.toml` (read by `picker.load_user_overrides`).
New surface: `~/.geode/config.toml` `[seed_generation.role.<role>]` (mirrors `[self_improving_loop.petri.<role>]` consolidation from PR #1496/#1498/#1499, Session 66).

Migration: `picker.load_user_overrides` first reads `~/.geode/config.toml` `[seed_generation.role.*]`. If empty and `~/.geode/seed-generation.toml` exists, emits a one-time deprecation warning and reads the old path until v1.0.0. The old file is NOT auto-migrated (user-driven).

### UI surface

| Surface | NEW |
|---|---|
| `geode adapters list` | typer subcommand — enumerate registered adapters with billing_type + test_environment + list_models |
| `geode adapters detect-model <adapter>` | paperclip `detectModel` equivalent — extract current model from adapter's local config |
| `geode seeds config show` | print 7 role × (model, source) matrix from manifest + config.toml |
| `geode seeds config set <role> source=<mode> [model=<id>]` | config.toml writer |
| REPL `/seed-model <role> <source>` | live override during interactive session |

### Deprecation (scope-out items marked, NOT removed)

Per user directive 2026-05-23 "디자인에서 스코프 넓혀서 벗어난 사안들을 deprecated 로 명시":

| Item | Deprecation reason | Removal target |
|---|---|---|
| `core/llm/providers/anthropic.py:get_async_anthropic_client(api_key=…)` direct callers outside `core/llm/adapters/` | Adapter is the canonical path | v1.0.0 |
| `core/llm/providers/codex.py:_get_async_codex_client` direct callers outside adapters | Adapter is the canonical path | v1.0.0 |
| `core/llm/credentials.py:resolve_provider_key(provider, fallback)` — global type-priority resolution | Per-role source override required, global priority loses information | v1.0.0 (kept until adapters migrate every caller) |
| `~/.geode/seed-generation.toml` | config.toml SoT consolidation | v1.0.0 |
| `core/config/__init__.py:_resolve_provider(model)` — string-prefix only | Adapter resolves provider+source jointly | v1.0.0 |

Each item gets a `.. deprecated:: v0.99.39` Sphinx-style block in the docstring + a CHANGELOG `### Deprecated` entry linked to this plan doc. Runtime `warnings.warn(...)` is intentionally NOT issued — every in-tree caller still uses the legacy path, so a runtime warning would fire on every LLM call until the v1.0.0 migration. The docstring + CHANGELOG signal is sufficient for the new callers' guidance.

## Files (~3,400 LOC)

```
core/llm/adapters/__init__.py           NEW
core/llm/adapters/base.py               NEW   (Protocol + dataclasses + enum)
core/llm/adapters/registry.py           NEW
core/llm/adapters/anthropic_payg.py     NEW
core/llm/adapters/anthropic_oauth.py    NEW
core/llm/adapters/claude_cli.py         NEW
core/llm/adapters/openai_payg.py        NEW
core/llm/adapters/codex_oauth.py        NEW
core/llm/adapters/codex_cli.py          NEW
core/runtime.py                         MOD   (bootstrap_builtins call)
core/agent/sub_agent.py                 MOD   (SubTask.source + WorkerRequest.source thread)
core/agent/worker.py                    MOD   (WorkerRequest.source propagate)
core/agent/loop/__init__.py             MOD   (AgenticLoop source kwarg)
core/agent/loop/_reflection.py          MOD   (adapter.acomplete at call site)
core/llm/credentials.py                 MOD   (DeprecationWarning header)
core/llm/providers/anthropic.py         MOD   (DeprecationWarning on direct caller paths)
core/llm/providers/codex.py             MOD   (DeprecationWarning)
core/config/__init__.py                 MOD   (DeprecationWarning on _resolve_provider)
plugins/seed_generation/picker.py       MOD   (load_user_overrides reads config.toml first)
plugins/seed_generation/orchestrator.py MOD   (Pipeline.bindings + _arun_phase reads)
plugins/seed_generation/cli.py          MOD   (pass bindings + S11 registry populate)
plugins/seed_generation/seed_generation.plugin.toml  MOD  (default_source per role)
core/cli/commands/adapters.py           NEW   (geode adapters list/detect-model)
core/cli/commands/seeds_config.py       NEW   (geode seeds config show/set)
core/cli/repl/slash/seed_model.py       NEW   (/seed-model slash)
tests/core/llm/adapters/test_base.py    NEW
tests/core/llm/adapters/test_registry.py NEW
tests/core/llm/adapters/test_anthropic_payg.py NEW
tests/core/llm/adapters/test_anthropic_oauth.py NEW
tests/core/llm/adapters/test_claude_cli.py NEW
tests/core/llm/adapters/test_openai_payg.py NEW
tests/core/llm/adapters/test_codex_oauth.py NEW
tests/core/llm/adapters/test_codex_cli.py NEW
tests/plugins/seed_generation/test_picker_config_sot.py NEW
tests/plugins/seed_generation/test_orchestrator_bindings.py NEW
tests/core/cli/test_adapters_command.py NEW
tests/core/cli/test_seeds_config_command.py NEW
CHANGELOG.md                            MOD
pyproject.toml                          MOD   (version bump)
CLAUDE.md                               MOD   (version bump)
README.md + README.ko.md                MOD   (version bump)
```

## Quality gates (Single PR)

- `uv run ruff format --check core/ tests/ plugins/`
- `uv run ruff check core/ tests/ plugins/`
- `uv run lint-imports`
- `uv run mypy core/ plugins/`
- `uv run pytest tests/ -m "not live" -q`
- Codex MCP verify on full diff: dedup + slop signals (paperclip-style abstraction redundancy / box-card UI / emoji)

## Scope cut — this single PR vs. follow-ups

**This PR (v0.99.39)** — landing the abstraction without rewriting AgenticLoop:

- Layer 4 (Protocol + registry)
- Layer 3 (6 adapters: anthropic-payg / anthropic-oauth / claude-cli / openai-payg / codex-oauth / codex-cli)
- `core.runtime` registers builtins at bootstrap
- `picker.resolve_binding_to_adapter(binding) -> LLMAdapter` helper so `RoleBinding.source` collapses into a concrete adapter pick
- `picker.load_user_overrides` reads `~/.geode/config.toml` `[seed_generation.role.<role>]` first; falls back to deprecated `~/.geode/seed-generation.toml` with one-time warning
- Deprecation markers on Layer 2 direct callers (``core/llm/providers/*.py``, ``credentials.py``, ``_resolve_provider``) — kept functional, scheduled for v1.0.0 removal
- Tests for Layer 4 + Layer 3 + picker integration
- Codex MCP verify (dedup + slop signals)

**Follow-up PRs** (deferred — each marked deprecated in this PR's diff where applicable):

| Item | Why deferred | Tracking |
|---|---|---|
| AgenticLoop migration to ``adapter.acomplete`` at every LLM call site | ~600 LOC refactor across ``core/agent/loop/`` — touches retry/observability/tool-use plumbing. Must land standalone for bisectability. | follow-up #A |
| ``Pipeline.bindings`` + ``_arun_phase`` reads binding per role | Requires S11 ``PipelineRegistry`` wire-up landed first (seven agent instantiation order matters) | follow-up #B |
| S11 production ``PipelineRegistry`` populate | The seven seed_generation agents (``generator/critic/pilot/ranker/evolver/meta_reviewer/literature_review``) need their constructor contracts aligned before registry boot — current ``cli.py:436`` leaves a TODO from PR-CSP-14 | follow-up #C |
| UI surface — ``geode adapters list``, ``geode adapters detect-model``, ``geode seeds config show/set``, REPL ``/seed-model`` slash | Independent UX work; uses the Layer 4 contract this PR ships | follow-up #D |
| ``~/.geode/seed-generation.toml`` auto-migration to ``~/.geode/config.toml`` | User-initiated only — auto-migration risks silent overwrite of user edits | follow-up #E (CLI assist command) |
| Glm + Google + DeepSeek + Petri audit + Autoresearch adapter wrap | Each is a per-provider follow-up; pattern proven by the 6 in this PR | follow-up #F-J |
