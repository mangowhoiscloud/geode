"""Pydantic Settings class — isolated module so the heavy pydantic_settings
import tree only loads when a Settings instance is actually requested.

This module is loaded lazily via ``core.config.__getattr__``. Direct callers
should import ``settings`` (not the class) from ``core.config``; the class is
exposed only for type hints and test fixtures.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.config.credential_source import (
    DISABLE_SENTINEL,
    LEGACY_OAUTH_ALIAS,
    CredentialSource,
)
from core.paths import GLOBAL_ENV_FILE

#: Union of every per-provider effort the picker can persist to ``[agentic]
#: effort`` — Anthropic ``low..xhigh``, OpenAI ``none``/``minimal``, GLM
#: ``disabled``/``enabled`` (SoT: ``core.cli.effort_picker.supported_efforts``).
#: ``_validate_effort`` MUST accept the full union: the picker writes the
#: provider-specific value here, so a narrower set would reject a valid config
#: the picker itself produced (e.g. gpt-5.5 + ``none``) and brick the next
#: ``Settings()`` load. Pinned to the picker by
#: ``tests/core/config/test_config_centralization.py``. Defined at module level
#: (not in the class body) so pydantic doesn't treat it as a field and the test
#: can import it directly. ``core.cli`` is a higher layer than ``core.config``,
#: so the constant is duplicated here rather than imported (the test bridges).
AGENTIC_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "max", "xhigh", "disabled", "enabled"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GEODE_",
        # Secrets precedence (2026-06-15, Hermes-aligned; supersedes C-3 for
        # the .env layer). pydantic merges env_file with the LATER file
        # winning, so order (project, global) makes the GLOBAL ~/.geode/.env
        # the authoritative secret store: a project .env can only FILL keys the
        # global lacks, never shadow a global key (the bug an auto-generated
        # project .env with an empty ANTHROPIC_API_KEY= caused under C-3's
        # project-wins). Secrets differ from config: config.toml keeps
        # project>global (per-project tuning), but a credential has one global
        # source. Both loaders (this + env_io.load_env_files) flip together,
        # so the H5 per-process inversion C-3 fixed stays fixed.
        env_file=(".env", str(GLOBAL_ENV_FILE)),
        extra="ignore",
    )

    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("anthropic_api_key", "ANTHROPIC_API_KEY"),
    )
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("openai_api_key", "OPENAI_API_KEY"),
    )
    zai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("zai_api_key", "ZAI_API_KEY"),
    )
    # PR-1 G-E (2026-05-21) bumped 4-6 → 4-7; PR-RUNTIME-OPUS-4-8 (2026-06-05)
    # bumped 4-7 → 4-8 to match routing.toml [model.defaults] anthropic.
    # ANTHROPIC_PRIMARY constant is the source of truth; this default mirrors it.
    model: str = "claude-opus-4-8"
    learning_extract_model: str = Field(
        default="glm-4.7-flash",
        validation_alias=AliasChoices("learning_extract_model", "GEODE_LEARNING_EXTRACT_MODEL"),
        description=(
            "GLM model for the learning-extraction hook "
            "(``core.hooks.llm_extract_learning``) — a cheap budget call run "
            "outside the main loop. The default ``glm-4.7-flash`` is on a "
            "limited-time free tier (see model_pricing.toml); when that promo "
            "ends the call bills at the standard GLM rate, so cost-sensitive "
            "operators should pin a known-priced model here."
        ),
    )
    # PR-3 C-2 (2026-05-21) — Reflection node knobs. The reflection
    # step runs one extra LLM call per tool-use round to populate
    # ``CognitiveState.hypotheses`` / ``confidence``, so operators
    # who want the loop to stay zero-extra-cost can flip the toggle.
    # Default model is Haiku 4.5 — cheapest current Claude that
    # still follows the JSON schema reliably; operators who want
    # higher quality reflection can switch to opus / sonnet.
    cognitive_reflection_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "cognitive_reflection_enabled",
            "GEODE_COGNITIVE_REFLECTION_ENABLED",
        ),
        description=(
            "When True (default) the agentic loop calls the reflection "
            "node after every tool-use round to derive hypotheses + "
            "confidence. When False the cognitive cycle stays "
            "PERCEIVE → PLAN → ACT → OBSERVE → REFLECT (deterministic) "
            "with no extra LLM call. PR-3 C-2."
        ),
    )
    cognitive_reflection_model: str = Field(
        default="claude-haiku-4-5-20251001",
        validation_alias=AliasChoices(
            "cognitive_reflection_model",
            "GEODE_COGNITIVE_REFLECTION_MODEL",
        ),
        description=(
            "Model used by the reflection node. Default is Haiku 4.5 "
            "(cheapest Claude family that still follows the JSON "
            "schema). Operators wanting higher-fidelity reflection can "
            "set this to opus / sonnet. PR-3 C-2."
        ),
    )
    # PR-CL-A6 (2026-05-23) — Plan / Action / Judge model separation
    # (agentic-loop-evolution.md A6). Empty string ("") means "fall back
    # to ``settings.model``" so existing operators see no behaviour change
    # until they set a concrete value. ReWOO (arxiv 2305.18323) showed
    # plan / observation decoupling yields 5x token efficiency; Anthropic
    # Plan / Edit mode pattern (claude-code) splits Opus-class planning
    # from Sonnet-class action.
    plan_model: str = Field(
        default="",
        validation_alias=AliasChoices("plan_model", "GEODE_PLAN_MODEL"),
        description=(
            "Model used by the planning step (goal decomposition before "
            "the main loop). Empty string falls back to ``settings.model``. "
            "Set to ``claude-opus-4-8`` for higher-quality plans, "
            "``claude-haiku-4-5-20251001`` for cheaper. PR-CL-A6."
        ),
    )
    act_model: str = Field(
        default="",
        validation_alias=AliasChoices("act_model", "GEODE_ACT_MODEL"),
        description=(
            "Model used by the action loop (per-round tool calls). Empty "
            "string falls back to ``settings.model``. Set to ``claude-"
            "sonnet-4-6`` to keep planning on Opus while action runs on "
            "Sonnet for cost. PR-CL-A6."
        ),
    )
    judge_model: str = Field(
        default="",
        validation_alias=AliasChoices("judge_model", "GEODE_JUDGE_MODEL"),
        description=(
            "Model used by the per-turn verify LLM-judge mode "
            "(``GEODE_VERIFY_MODE=llm_judge``). Empty string falls back "
            "to ``settings.model``. Cheap models like Haiku 4.5 are "
            "appropriate for binary pass/fail judgement. PR-CL-A6."
        ),
    )
    # PR-CL-A1 (2026-05-23) — Dynamic Replan knobs.
    replan_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("replan_enabled", "GEODE_REPLAN_ENABLED"),
        description=(
            "When True (default) the loop calls the planner LLM on "
            "verify FAIL and every ``replan_interval`` rounds. False "
            "disables the replan feature entirely (the explicit Plan "
            "object still tracks step progress but never revises). PR-CL-A1."
        ),
    )
    replan_interval: int = Field(
        default=5,
        ge=0,
        validation_alias=AliasChoices("replan_interval", "GEODE_REPLAN_INTERVAL"),
        description=(
            "Number of rounds between cadence-based replans. ``0`` "
            "disables cadence (verify FAIL still triggers). Default 5 "
            "balances ReWOO 5x-token-efficiency target with the cost of "
            "an extra plan_model call per N rounds. PR-CL-A1."
        ),
    )
    replan_max_attempts: int = Field(
        default=3,
        ge=1,
        validation_alias=AliasChoices("replan_max_attempts", "GEODE_REPLAN_MAX_ATTEMPTS"),
        description=(
            "Maximum attempts on a single PlanStep before the step is "
            "abandoned and the loop advances to the next step. "
            "Prevents the agent from looping forever on an impossible "
            "step. Default 3. PR-CL-A1."
        ),
    )
    cognitive_reflection_max_tokens: int = Field(
        default=512,
        validation_alias=AliasChoices(
            "cognitive_reflection_max_tokens",
            "GEODE_COGNITIVE_REFLECTION_MAX_TOKENS",
        ),
        description=(
            "Max tokens for the reflection LLM call. The output is a "
            "small JSON object (hypotheses[<=5] + confidence + "
            "next_action_hint); 512 leaves headroom without bloating "
            "cost. PR-3 C-2."
        ),
    )
    cognitive_reflection_interval: int = Field(
        default=1,
        ge=1,
        validation_alias=AliasChoices(
            "cognitive_reflection_interval",
            "GEODE_COGNITIVE_REFLECTION_INTERVAL",
        ),
        description=(
            "Reflection fires every Nth tool-use round. ``1`` (default) "
            "= every round (current PR-3 behaviour, zero regression). "
            "``3`` = round 1, 4, 7, 10... (skip 2 rounds between calls). "
            "Higher values cut the extra-LLM-call overhead at the cost "
            "of staler hypotheses + confidence. The first round always "
            "runs so the loop sees an LLM-derived belief snapshot "
            "before any throttling kicks in. PR-C (2026-05-21)."
        ),
    )
    # Temperature — config-driven sampling (PR-TEMP, 2026-05-23).
    # Replaces six hardcoded literals (agent_loop 0.0 / reflection 0.2 /
    # verification 0.1 / commentary 0.4 / mutation 0.3 / compression 0.0)
    # with operator-tunable knobs. Frontier API grounding:
    #   * Anthropic: default 1.0, range 0.0-1.0. "closer to 0.0 for
    #     analytical / multiple choice, closer to 1.0 for creative and
    #     generative tasks."
    #   * OpenAI: default 1.0, range 0.0-2.0. Reasoning models (o-series,
    #     gpt-5 family) reject non-default sampling — the codex adapter's
    #     ``_is_codex_reasoning_model`` path omits temperature for those.
    #   * Gemini 3: docs strongly recommend keeping temperature at 1.0;
    #     lowering "may lead to unexpected behavior, such as looping or
    #     degraded performance, particularly in complex mathematical or
    #     reasoning tasks."
    # Most defaults sit at 1.0 (= provider default) so each provider's
    # adaptive-sampling logic kicks in unmodified. Verification + budget
    # compression default to 0.0 because their downstream consumers (cross-
    # LLM agreement coefficient + reproducible summaries) are functional
    # invariants where stochastic output is meaningless.
    temperature_agent_loop: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices(
            "temperature_agent_loop",
            "GEODE_TEMPERATURE_AGENT_LOOP",
        ),
        description=(
            "Sampling temperature for the main agentic loop's tool-use "
            "call. Previously hardcoded to 0.0; the new default 1.0 "
            "matches Anthropic / OpenAI / Gemini provider defaults."
        ),
    )
    temperature_reflection: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices(
            "temperature_reflection",
            "GEODE_TEMPERATURE_REFLECTION",
        ),
        description=(
            "Sampling temperature for the reflection node's hypothesis / "
            "confidence call. Previously hardcoded to 0.2."
        ),
    )
    temperature_commentary: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices(
            "temperature_commentary",
            "GEODE_TEMPERATURE_COMMENTARY",
        ),
        description=(
            "Sampling temperature for tool-result commentary generation. "
            "Previously hardcoded to 0.4 (signature default)."
        ),
    )
    temperature_self_improving_mutation: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices(
            "temperature_self_improving_mutation",
            "GEODE_TEMPERATURE_SELF_IMPROVING_MUTATION",
        ),
        description=(
            "Sampling temperature for the self-improving-loop mutator "
            "call. Previously hardcoded to 0.3."
        ),
    )
    verbose: bool = False

    # Trigger Manager
    trigger_scheduler_interval_s: float = 60.0

    # L4.5 Automation — Advanced Scheduler
    scheduler_interval_s: float = 1.0  # 1s check interval (claude-code pattern)
    scheduler_auto_start: bool = True
    scheduler_jitter_enabled: bool = True  # Deterministic per-job jitter
    scheduler_max_jitter_ms: float = 900_000.0  # 15 min cap

    # L2 Memory — Session
    session_ttl_hours: float = 4.0
    session_storage_dir: str = ""  # file-backed persistence dir (empty = in-memory only)

    # L2 Memory — Organization
    organization_fixture_dir: str = ""

    # Tier 0.5 — User Profile
    user_profile_dir: str = ""  # global dir override (default: ~/.geode/user_profile)

    # Tool search — hosted defer_loading on the Anthropic adapter
    # (PR-TOOL-SEARCH-WIRE; reader: core/llm/providers/anthropic.py)
    tool_search_defer: bool = True  # kill switch for deferred tool loading
    # Codex backend acceptance of OpenAI tool_search: live-verified
    # 2026-06-13 — 20 defer_loading defs + {"type": "tool_search"} through
    # chatgpt.com/backend-api/codex/responses on gpt-5.5 returned a normal
    # completion ("DEFER-OK"). Docs cover the platform API only, so the
    # live call was the gate (PR-NO-FALLBACK rule); reader: _openai_common.py.
    tool_search_defer_codex: bool = True

    # Ensemble — Multi-LLM mode
    ensemble_mode: str = "single"  # single | cross

    # Sub-Agent Orchestration (P2)
    max_subagent_depth: int = 1  # 최대 재귀 깊이 (depth=1 강제, Claude Code 패턴)
    # 세션 내 최대 서브에이전트 수 — SubAgentManager.adelegate 에서 per-session
    # 누적 카운터로 강제 (초과분은 거부). reader: core/agent/sub_agent.py
    max_total_subagents: int = 15
    # 서브에이전트 출력 토큰 제한 — WorkerRequest 로 전달돼 spawned AgenticLoop
    # 의 max_tokens 를 설정. reader: core/agent/worker.py
    subagent_max_tokens: int = 32768

    # Token Guard — tool result truncation threshold (0 = unlimited)
    max_tool_result_tokens: int = 25000  # 0 = no limit; clear_tool_uses handles overflow

    # Tool Result Offloading — store large results to filesystem (P0 token optimization)
    tool_offload_threshold: int = 15000  # tokens; 0 = disabled
    tool_offload_ttl_hours: float = 4.0  # TTL for offloaded results
    observation_mask_keep_rounds: int = 3  # keep recent N rounds unmasked

    # Agentic Loop — thinking budget (DTR: Extended Thinking / reasoning tokens)
    agentic_thinking_budget: int = 0  # 0 = disabled; >0 = thinking token budget per call (legacy)

    # Agentic Loop — effort level (replaces thinking_budget for Opus 4.6+ / Sonnet 4.6+)
    # Maps to Anthropic output_config.effort + OpenAI reasoning.effort.
    # v0.56.0 R4-mini — ``xhigh`` added; Opus 4.7+ only (4.7 / 4.8 — the
    # adapter downgrades to ``"max"`` on Opus 4.6 / Sonnet 4.6).
    agentic_effort: str = "high"  # "low" | "medium" | "high" | "max" | "xhigh"

    # Credential source — chosen via the ``/login source`` picker. The picker
    # reads available sources at runtime (local Claude OAuth keychain,
    # Codex auth.json JWT, env-var API key) and persists the user's
    # choice here so :mod:`plugins.petri_audit.models.to_inspect_model`
    # routes ids through the matching provider prefix. ``"auto"`` =
    # legacy behaviour (env / OAuth detection order); explicit values
    # take precedence. No subscription-plan names are hardcoded — the
    # picker labels each source with the plan info pulled from the
    # active credential blob.
    # Valid values: the canonical ``CredentialSource`` members
    # (auto / api_key / claude-cli / openai-codex) plus the legacy provider-
    # agnostic ``oauth`` alias and the ``none`` disable sentinel — validated
    # against the single SoT below (PR-CRED-SOURCE-CENTRALIZE).
    anthropic_credential_source: str = "auto"
    openai_credential_source: str = "auto"

    @field_validator("anthropic_credential_source", "openai_credential_source")
    @classmethod
    def _validate_credential_source(cls, v: str) -> str:
        """Validate against the canonical credential-source set + legacy aliases.

        Keeps these operator-facing settings from drifting from
        :class:`core.config.credential_source.CredentialSource`. ``oauth``
        (legacy agnostic alias, normalised per-provider downstream) and ``none``
        (disable) are accepted in addition to the concrete enum members.
        """
        allowed = {s.value for s in CredentialSource} | {LEGACY_OAUTH_ALIAS, DISABLE_SENTINEL}
        if v not in allowed:
            raise ValueError(f"credential source must be one of {sorted(allowed)}, got {v!r}")
        return v

    # PR-OBS-LOGGING-CONFIG (2026-06-14) — value validators. pydantic's cheap
    # boot-time checks catch a malformed config.toml/.env BEFORE it produces a
    # silent runtime failure (a 0s timeout that busy-loops, an unknown effort
    # the picker can't map). Previously only credential_source was validated.
    # temperature_* already carry native ``Field(ge=0.0, le=2.0)`` constraints
    # (see the field defs above); the timeout / interval / effort fields below
    # were plain scalars accepting any value, so they get explicit guards here.
    @field_validator(
        "llm_connect_timeout",
        "llm_read_timeout",
        "llm_write_timeout",
        "llm_pool_timeout",
        "scheduler_interval_s",
        "trigger_scheduler_interval_s",
        "gateway_poll_interval_s",
    )
    @classmethod
    def _validate_positive_seconds(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"duration must be > 0 seconds, got {v}")
        return v

    @field_validator("agentic_effort")
    @classmethod
    def _validate_effort(cls, v: str) -> str:
        if v not in AGENTIC_EFFORTS:
            raise ValueError(f"agentic_effort must be one of {sorted(AGENTIC_EFFORTS)}, got {v!r}")
        return v

    @field_validator("bash_sandbox")
    @classmethod
    def _validate_bash_sandbox(cls, v: str) -> str:
        normalized = str(v or "").strip().lower()
        if normalized not in {"off", "on", "strict"}:
            raise ValueError(f"bash_sandbox must be 'off', 'on', or 'strict', got {v!r}")
        return normalized

    @field_validator("computer_use_env")
    @classmethod
    def _validate_computer_use_env(cls, v: str) -> str:
        normalized = str(v or "").strip().lower()
        if normalized not in {"host", "sandbox"}:
            raise ValueError(f"computer_use_env must be 'host' or 'sandbox', got {v!r}")
        return normalized

    # Cost guard — session-level cost limit (0 = no limit)
    cost_limit_usd: float = 0.0  # fires COST_WARNING at 80%, COST_LIMIT_EXCEEDED at 100%

    # Computer Use — desktop automation (requires pyautogui)
    computer_use_enabled: bool = True  # default on; pyautogui import guard handles missing dep

    # Computer-use execution environment (Phase E) — "host" (default) | "sandbox".
    # "host": pyautogui drives the operator's real desktop (current behaviour).
    # "sandbox": the harness becomes a thin HTTP client that dispatches each
    # action to an in-container shim (Docker + Xvfb virtual desktop) and gets a
    # screenshot back — the host never touches a display. fail-loud: if the
    # container is unreachable the action errors, NEVER falls back to host.
    computer_use_env: str = "host"
    # Container shim endpoint for computer_use_env="sandbox".
    computer_use_sandbox_url: str = "http://127.0.0.1:8787"

    # run_bash command sandbox (Phase F) — "off" (default, compat) | "on" | "strict".
    # "on": wrap commands in the OS sandbox (macOS sandbox-exec / Linux bwrap) when
    # the binary exists, else warn + run unsandboxed. "strict": fail if unavailable.
    bash_sandbox: str = "off"

    # Context Compaction — overflow prevention
    compact_keep_recent: int = 10  # messages to preserve during compaction/prune

    # Notification — external messaging
    notification_channel: str = "slack"  # default notification channel
    notification_recipient: str = "#geode-alerts"  # default recipient

    # Gateway — inbound messaging
    gateway_enabled: bool = False  # GEODE_GATEWAY_ENABLED=true to enable
    gateway_poll_interval_s: float = 3.0

    # L4 Gateway Hooks — external webhook endpoint
    webhook_enabled: bool = False  # GEODE_WEBHOOK_ENABLED=true to enable
    webhook_port: int = 8765

    # Sandbox — file tool path validation (Claude Code parity)
    sandbox_max_file_size_bytes: int = 262_144  # 256KB pre-read guard
    sandbox_max_read_tokens: int = 25_000  # post-read token estimate guard
    sandbox_max_glob_results: int = 100  # GlobTool max results
    sandbox_max_grep_results: int = 50  # GrepTool max files
    sandbox_max_grep_line_chars: int = 200  # GrepTool match line truncation

    # HITL Level — Human-in-the-loop control
    # 0 = autonomous (skip all prompts), 1 = write-only (prompt only for writes),
    # 2 = all prompts (default, ask everything)
    hitl_level: int = 2

    # Dangerously skip permissions (Claude Code parity, GEODE_DANGEROUSLY_SKIP_PERMISSIONS).
    # When True, EVERY HITL gate is bypassed (write/expensive/bash/MCP approval →
    # hitl_level forced to 0 + auto_approve) AND the plan-approval stop is
    # skipped (plan → action directly, ``plan_auto_execute`` treated as on).
    # For a frictionless autonomous agent experience; the operator opts in with
    # ``geode --dangerously-skip-permissions``. Adopted per IPC connection from
    # the thin CLI's ``client_capability`` handshake (same mechanism as the
    # session model) so a running daemon honours it without a restart.
    dangerously_skip_permissions: bool = False

    # Plan Mode — Autonomous Execution
    plan_auto_execute: bool = False  # GEODE_PLAN_AUTO_EXECUTE=true to enable

    # LLM Connection — httpx pool & timeout tuning
    llm_max_connections: int = 20  # httpx pool: max total connections
    llm_max_keepalive_connections: int = 5  # httpx pool: max idle keep-alive connections
    llm_keepalive_expiry: float = 30.0  # idle conn TTL (match API server timeout)
    llm_connect_timeout: float = 5.0  # TCP connect timeout (fail fast)
    llm_read_timeout: float = 300.0  # response read timeout (5min for 1M context)
    llm_write_timeout: float = 30.0  # request write timeout (seconds)
    llm_pool_timeout: float = 10.0  # wait for available connection from pool (seconds)
    llm_retry_base_delay: float = 2.0  # base delay for exponential backoff (seconds)
    llm_retry_max_delay: float = 30.0  # max delay cap for retries (seconds)
    llm_max_retries: int = 3  # max retry attempts per model

    # v0.52.4 — per-provider auth-mode escape hatch (Codex CLI parity).
    # Default routing prefers SUBSCRIPTION/OAUTH plans over PAYG when both
    # can serve the requested model (matches openai/codex CLI default).
    # Override per provider when the user deliberately wants metered PAYG:
    #   forced_login_method = {"openai": "apikey"}    # use OPENAI_API_KEY even
    #                                                  # if Codex subscription OAuth is registered
    # Valid values: "subscription" (default), "apikey", "auto" (alias).
    # Reference: openai/codex#2733, #3286.
    forced_login_method: dict[str, str] = {}

    # LLM — Fallback cost ratio control (C2: 0 = unlimited)
    llm_max_fallback_cost_ratio: float = 0.0

    # Concurrency — workload lane limits
    gateway_max_concurrent: int = 4  # max simultaneous Gateway messages
