"""GEODE configuration via Pydantic BaseSettings.

Config Cascade (priority high → low):
  1. CLI arguments
  2. Environment variables / .env
  3. Project TOML: .geode/config.toml
  4. Global TOML: ~/.geode/config.toml
  5. Code defaults

The :class:`Settings` class lives in :mod:`core.config._settings` so the heavy
``pydantic_settings`` import tree only loads when an instance is actually
requested. Module-level constants (``ANTHROPIC_PRIMARY`` etc.) and lightweight
dataclasses (:class:`ModelPolicy`, :class:`RoutingConfig`) stay here so cold
import paths that only need them avoid pydantic entirely.
"""

from __future__ import annotations

import logging
import os
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.paths import GLOBAL_CONFIG_TOML, GLOBAL_ENV_FILE, PROJECT_CONFIG_TOML

if TYPE_CHECKING:
    # Re-export ``Settings`` as a module attribute so ``from core.config
    # import Settings`` type-checks while runtime keeps the heavy import
    # lazy (see ``__getattr__`` below).
    from core.config._settings import Settings as Settings

    # Declare the lazily-resolved ``settings`` singleton for mypy. The actual
    # value is produced by ``__getattr__`` on first access.
    settings: Settings

log = logging.getLogger(__name__)

_settings_lock = threading.Lock()

# ---------------------------------------------------------------------------
# TOML Config Cascade
# ---------------------------------------------------------------------------

GLOBAL_CONFIG_PATH = GLOBAL_CONFIG_TOML
PROJECT_CONFIG_PATH = PROJECT_CONFIG_TOML

# Mapping: TOML dotted key → Settings field name.
# Only mapped keys are applied; unknown TOML keys are silently ignored.
_TOML_TO_SETTINGS: dict[str, str] = {
    "llm.primary_model": "model",
    "llm.learning_extract_model": "learning_extract_model",
    # PR-CL-A6 (2026-05-23) — Plan / Action / Judge model knobs. Empty
    # string falls back to ``llm.primary_model``.
    "llm.plan_model": "plan_model",
    "llm.act_model": "act_model",
    "llm.judge_model": "judge_model",
    # C-2 (2026-06-11) — H7 fix: /login source was writing these toml rows
    # but nothing read them back (dead write); now they are part of the cascade.
    "llm.anthropic_credential_source": "anthropic_credential_source",
    # PR-TOOL-SEARCH-WIRE (2026-06-13) — hosted tool-search defer kill switch.
    "llm.tool_search_defer": "tool_search_defer",
    "llm.tool_search_defer_codex": "tool_search_defer_codex",
    "llm.openai_credential_source": "openai_credential_source",
    # PR-CL-A1 (2026-05-23) — Dynamic Replan knobs.
    "replan.enabled": "replan_enabled",
    "replan.interval": "replan_interval",
    "replan.max_attempts": "replan_max_attempts",
    "cognitive.reflection_enabled": "cognitive_reflection_enabled",
    "cognitive.reflection_model": "cognitive_reflection_model",
    "cognitive.reflection_max_tokens": "cognitive_reflection_max_tokens",
    "cognitive.reflection_interval": "cognitive_reflection_interval",
    "output.verbose": "verbose",
    "agentic.time_budget": "agentic_loop_time_budget",
    "agentic.thinking_budget": "agentic_thinking_budget",
    "agentic.effort": "agentic_effort",
    "sandbox.max_file_size_bytes": "sandbox_max_file_size_bytes",
    "sandbox.max_read_tokens": "sandbox_max_read_tokens",
    "sandbox.max_glob_results": "sandbox_max_glob_results",
    "sandbox.max_grep_results": "sandbox_max_grep_results",
    "sandbox.max_grep_line_chars": "sandbox_max_grep_line_chars",
    # PR-OBS-LOGGING-CONFIG (2026-06-14) — env↔TOML parity. Every non-secret
    # Settings field is now also settable via config.toml (was env-only),
    # completing the documented cascade. Pinned by ``test_toml_settings_map``.
    "llm.write_timeout": "llm_write_timeout",
    "llm.retry_base_delay": "llm_retry_base_delay",
    "llm.retry_max_delay": "llm_retry_max_delay",
    "temperature.agent_loop": "temperature_agent_loop",
    "temperature.reflection": "temperature_reflection",
    "temperature.commentary": "temperature_commentary",
    "temperature.self_improving_mutation": "temperature_self_improving_mutation",
    "subagent.max_depth": "max_subagent_depth",
    "subagent.max_total": "max_total_subagents",
    "subagent.max_tokens": "subagent_max_tokens",
    "subagent.max_tool_result_tokens": "max_tool_result_tokens",
    "observation.mask_keep_rounds": "observation_mask_keep_rounds",
    "plan.auto_execute": "plan_auto_execute",
    "tool_offload.threshold": "tool_offload_threshold",
    "tool_offload.ttl_hours": "tool_offload_ttl_hours",
    "scheduler.interval_s": "scheduler_interval_s",
    "scheduler.auto_start": "scheduler_auto_start",
    "scheduler.jitter_enabled": "scheduler_jitter_enabled",
    "scheduler.max_jitter_ms": "scheduler_max_jitter_ms",
    "scheduler.trigger_interval_s": "trigger_scheduler_interval_s",
    "session.ttl_hours": "session_ttl_hours",
    "session.storage_dir": "session_storage_dir",
    "notification.channel": "notification_channel",
    "notification.recipient": "notification_recipient",
    "webhook.enabled": "webhook_enabled",
    "webhook.port": "webhook_port",
    "persistence.postgres_url": "postgres_url",
    "persistence.redis_url": "redis_url",
    "paths.user_profile_dir": "user_profile_dir",
    "paths.organization_fixture_dir": "organization_fixture_dir",
    "llm.connect_timeout": "llm_connect_timeout",
    "llm.read_timeout": "llm_read_timeout",
    "llm.pool_timeout": "llm_pool_timeout",
    "llm.keepalive_expiry": "llm_keepalive_expiry",
    "llm.max_connections": "llm_max_connections",
    "llm.max_keepalive_connections": "llm_max_keepalive_connections",
    "llm.max_retries": "llm_max_retries",
    "llm.max_fallback_cost_ratio": "llm_max_fallback_cost_ratio",
    "llm.forced_login_method": "forced_login_method",
    "compact.keep_recent": "compact_keep_recent",
    "checkpoint.db": "checkpoint_db",
    "computer_use.enabled": "computer_use_enabled",
    "cost.limit_usd": "cost_limit_usd",
    "ensemble.mode": "ensemble_mode",
    "hitl.level": "hitl_level",
    "gateway.enabled": "gateway_enabled",
    "gateway.max_concurrent": "gateway_max_concurrent",
    "gateway.poll_interval_s": "gateway_poll_interval_s",
}

#: Settings fields intentionally NOT in the TOML map — env/CLI-only because
#: putting a secret in a committed/synced ``config.toml`` is the leak we avoid.
#: The parity guard (test_toml_settings_map) allows exactly these.
_TOML_ENV_ONLY_FIELDS: frozenset[str] = frozenset(
    {"anthropic_api_key", "openai_api_key", "zai_api_key"}
)

DEFAULT_CONFIG_TOML = """\
# GEODE config.toml
# Priority: CLI > env > project .geode/config.toml > global ~/.geode/config.toml > defaults
#
# Uncomment and edit values to override defaults.

[llm]
# primary_model = "claude-opus-4-8"

[output]
# verbose = false
"""


def _flatten_toml(
    data: dict[str, Any],
    prefix: str = "",
) -> dict[str, Any]:
    """Flatten nested TOML dict to dotted-key → value mapping.

    Example:
        {"llm": {"primary_model": "x"}} → {"llm.primary_model": "x"}
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{prefix}{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten_toml(value, f"{full_key}."))
        else:
            result[full_key] = value
    return result


def _load_toml_config(
    *,
    global_path: Path | None = None,
    project_path: Path | None = None,
) -> dict[str, Any]:
    """Load and merge TOML configs: project overrides global.

    Returns a dict mapping Settings field names to their values.
    Only keys present in _TOML_TO_SETTINGS are returned.
    """
    # H9 (C-4, 2026-06-11) — ``GEODE_CONFIG_TOML`` redirects the GLOBAL
    # config.toml for the MAIN settings loader too. Pre-fix only the
    # self-improving loop loader honored it
    # (core/config/self_improving.py:_resolve_config_path), so an operator
    # pointing the env var at an alternate file changed loop behavior while
    # the runtime kept reading ~/.geode/config.toml — two meanings for one
    # variable. The project overlay still applies on top.
    env_toml = os.environ.get("GEODE_CONFIG_TOML", "").strip()
    gp = global_path or (Path(env_toml).expanduser() if env_toml else GLOBAL_CONFIG_PATH)
    pp = project_path or PROJECT_CONFIG_PATH
    merged: dict[str, Any] = {}

    for path in (gp, pp):  # global first (lower prio), project second (higher)
        if not path.exists():
            continue
        try:
            with open(path, "rb") as f:
                raw = tomllib.load(f)
            flat = _flatten_toml(raw)
            for toml_key, settings_field in _TOML_TO_SETTINGS.items():
                if toml_key in flat:
                    merged[settings_field] = flat[toml_key]
        except Exception:
            log.warning("Failed to load TOML config %s, skipping", path, exc_info=True)

    return merged


def _apply_toml_overlay(s: Settings, *, env_set_fields: set[str] | None = None) -> None:
    """Overlay TOML values onto Settings for fields NOT already set by env / .env.

    Precedence (documented): CLI > env > project ``.geode/config.toml`` > global
    ``~/.geode/config.toml`` > routing default. The env layer includes BOTH real
    ``GEODE_*`` environment variables AND values pydantic read from a ``.env``
    file — pydantic marks all of them in ``model_fields_set`` (verified: an env
    var and a ``.env`` ``GEODE_MODEL`` both land there). The pre-fix check used
    ``GEODE_<FIELD> in os.environ``, which MISSED ``.env``-file values (pydantic
    loads them into the instance, not ``os.environ``), so a project ``.env``
    ``GEODE_MODEL`` was wrongly overwritten by ``[llm] primary_model`` — inverting
    env > TOML. ``model_fields_set`` closes that gap.

    ``env_set_fields`` overrides which fields count as env/.env-set. Needed by
    :func:`reload_settings_from_disk`, which copies a fresh instance's *values*
    onto the singleton via ``object.__setattr__`` (that bypasses
    ``model_fields_set``), so the caller passes the fresh instance's set.
    """
    toml_values = _load_toml_config()
    if not toml_values:
        return

    env_set = env_set_fields if env_set_fields is not None else s.model_fields_set
    for field_name, toml_value in toml_values.items():
        # Env layer (real env var OR .env file) outranks TOML — don't overlay.
        if field_name in env_set:
            continue
        # Also check special alias env vars for API keys
        if field_name in ("anthropic_api_key", "openai_api_key", "zai_api_key"):
            continue
        if hasattr(s, field_name):
            object.__setattr__(s, field_name, toml_value)


GLOBAL_ENV_PATH = GLOBAL_ENV_FILE


_settings_instance: Settings | None = None


def _get_settings() -> Settings:
    """Get or create the Settings singleton in a thread-safe manner.

    The :class:`Settings` class is imported lazily so that callers requesting
    only constants from :mod:`core.config` (e.g. ``ANTHROPIC_PRIMARY``) avoid
    pulling pydantic_settings into the cold-start tree. After Pydantic loads
    from env/.env, overlays TOML config values for fields not explicitly set
    via environment variables.
    """
    global _settings_instance
    if _settings_instance is not None:
        return _settings_instance
    with _settings_lock:
        # Double-checked locking
        if _settings_instance is None:
            from core.config._settings import Settings as _Settings

            s = _Settings()
            _apply_toml_overlay(s)
            _settings_instance = s
        return _settings_instance


def reload_settings_from_disk() -> None:
    """Re-read ``.env`` + ``config.toml`` + ``GEODE_*`` env vars into the live
    settings singleton.

    **Hermes-style "fresh read at session boundary" fix** for the post-PR-DRIFT-CUT
    incident where CLI and daemon processes diverged on ``settings.model``:
    the CLI process updated disk via ``_apply_model`` after the daemon's
    pydantic Settings had cached its boot-time snapshot, and PR-DRIFT-CUT
    removed the per-turn auto-revert (drift sync) that had been silently
    re-syncing them. Re-reading at session start brings the daemon back in
    sync with disk without re-introducing the auto-revert footgun.

    Why mutate in place instead of replacing the singleton: every module that
    holds a captured reference (``from core.config import settings`` returns
    the current singleton at the moment of import) keeps observing the new
    values. Replacing the binding would leave stale references unfixed.

    Idempotent — calling on a fresh process is a no-op (the new Settings()
    just re-reads the same disk). Cheap: ~ms-scale (pydantic_settings re-init
    + TOML re-parse).
    """
    from core.config._settings import Settings as _Settings

    current = _get_settings()
    fresh = _Settings()  # re-reads .env + GEODE_* env vars
    # Pydantic V2.11 deprecated instance-level ``.model_fields`` access; read
    # the field map off the class. Per-field failures are tolerated (a
    # pydantic validator may refuse certain reassignments, e.g. computed
    # fields) but no longer SILENT (H13, C-4 2026-06-11): pre-fix a field
    # that failed to copy kept its stale value with zero trace, so a reload
    # could half-apply and the operator had no way to tell which half.
    for field_name in type(fresh).model_fields:
        try:
            new_value = getattr(fresh, field_name)
            object.__setattr__(current, field_name, new_value)
        except Exception:
            log.warning(
                "reload_settings_from_disk: field %r kept its previous value "
                "(refresh raised; stale until restart)",
                field_name,
                exc_info=True,
            )
    # ``object.__setattr__`` above copied fresh *values* but not its
    # ``model_fields_set``, so pass the fresh instance's set explicitly — the
    # overlay must skip fields the fresh ``.env`` / env actually set, not what
    # the stale singleton recorded at boot.
    _apply_toml_overlay(current, env_set_fields=set(fresh.model_fields_set))
    reload_routing_constants()
    log.info(
        "reload_settings_from_disk applied: model=%r (pid=%d)",
        getattr(current, "model", "?"),
        os.getpid(),
    )


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute access for ``settings`` and ``Settings``.

    Attribute access here defers the heavy ``pydantic_settings`` import until
    the caller actually uses it. Modules that only need constants such as
    ``ANTHROPIC_PRIMARY`` or ``CODEX_BASE_URL`` therefore avoid the pydantic
    tree entirely. Anything else falls through to the standard
    ``AttributeError`` so typos surface immediately.
    """
    if name == "settings":
        return _get_settings()
    if name == "Settings":
        from core.config._settings import Settings as _Settings

        return _Settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Model constants — single source of truth for model names & pricing
# All code MUST reference these instead of hardcoding model strings.
# ---------------------------------------------------------------------------

# P2-B (2026-05-17) — model defaults + fallback chains migrated to
# core/config/routing.toml + ~/.geode/routing.toml. The constants below
# retain their public surface (every existing call site keeps working)
# but their values now load from the manifest; users edit routing.toml
# to override rather than monkeypatching this module.
#
# Anthropic / OpenAI / Codex / GLM defaults all come from
# ``[model.defaults]`` and fallback chains from ``[model.fallbacks.<provider>]``.
# Base URLs and any constants the manifest does not yet model stay hardcoded.
from core.config.routing_manifest import (  # noqa: E402
    load_routing_manifest as _load_routing_manifest,
)

_routing = _load_routing_manifest()

ANTHROPIC_PRIMARY: str = _routing.defaults.anthropic
ANTHROPIC_SECONDARY: str = _routing.defaults.anthropic_secondary or ""
ANTHROPIC_BUDGET: str = _routing.defaults.anthropic_budget or ""
ANTHROPIC_FALLBACK_CHAIN: list[str] = list(_routing.fallbacks.anthropic)

OPENAI_PRIMARY: str = _routing.defaults.openai
OPENAI_FALLBACK_CHAIN: list[str] = list(_routing.fallbacks.openai)

# OpenAI Codex — subscription quota via chatgpt.com/backend-api/codex (Responses API).
CODEX_PRIMARY: str = _routing.defaults.codex
CODEX_FALLBACK_CHAIN: list[str] = list(_routing.fallbacks.codex)
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"

# ZhipuAI (GLM) — OpenAI-compatible API, separate provider.
GLM_PRIMARY: str = _routing.defaults.glm
GLM_FALLBACK_CHAIN: list[str] = list(_routing.fallbacks.glm)
# Coding Plan endpoint (subscription-billed). PAYG endpoint is api/paas/v4 — a
# Coding Plan key called against PAYG path silently bypasses the subscription
# quota and incurs metered billing instead.
GLM_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
GLM_PAYG_BASE_URL = "https://api.z.ai/api/paas/v4"


def reload_routing_constants() -> None:
    """Re-read routing.toml and rebind this module's routing constants (H11).

    C-4 (2026-06-11). ``_routing`` froze at import, so an edit to
    ``~/.geode/routing.toml`` needed a process restart even though
    :func:`reload_settings_from_disk` claimed to bring the daemon back in
    sync with disk. Called from ``reload_settings_from_disk``; clears the
    manifest lru_cache then rebinds the module globals, so manifest readers
    (``resolve_provider``) and every FUNCTION-LOCAL ``from core.config
    import X`` (which re-resolves the module attribute at call time) see
    fresh values.

    Honest limit: MODULE-LEVEL by-value importers still hold their
    boot-time copies — ``core/llm/providers/{anthropic,openai,codex,glm}.py``
    module aliases (``DEFAULT_*_MODEL`` / ``*_FALLBACK_MODELS``) and
    ``core/skills/agents.py`` dataclass defaults. Defreezing those is a
    separate caller sweep (kanban: H11-tail).
    """
    from core.config import routing_manifest as _rm

    _rm.clear_routing_manifest_cache()
    fresh = _rm.load_routing_manifest()
    module_globals = globals()
    module_globals["ANTHROPIC_PRIMARY"] = fresh.defaults.anthropic
    module_globals["ANTHROPIC_SECONDARY"] = fresh.defaults.anthropic_secondary or ""
    module_globals["ANTHROPIC_BUDGET"] = fresh.defaults.anthropic_budget or ""
    module_globals["ANTHROPIC_FALLBACK_CHAIN"] = list(fresh.fallbacks.anthropic)
    module_globals["OPENAI_PRIMARY"] = fresh.defaults.openai
    module_globals["OPENAI_FALLBACK_CHAIN"] = list(fresh.fallbacks.openai)
    module_globals["CODEX_PRIMARY"] = fresh.defaults.codex
    module_globals["CODEX_FALLBACK_CHAIN"] = list(fresh.fallbacks.codex)
    module_globals["GLM_PRIMARY"] = fresh.defaults.glm
    module_globals["GLM_FALLBACK_CHAIN"] = list(fresh.fallbacks.glm)


def _resolve_provider(model: str) -> str:
    """Resolve provider name from model ID via the routing manifest.

    P2-D (2026-05-17): the legacy 11-branch if/elif chain (with its
    sibling ``_CODEX_ONLY_MODELS`` frozenset) is replaced by a single
    delegation to :func:`core.config.routing_manifest.resolve_provider`.
    The manifest's ``[routing.prefixes]`` table, ``codex_only_models``
    list, and ``codex_suffixes`` list together produce identical output
    for every documented branch (parity verified in
    ``tests/core/config/test_routing_manifest.py::test_resolve_provider_legacy_parity``).
    Users now adjust provider routing by editing
    ``core/config/routing.toml`` (or ``~/.geode/routing.toml``) instead
    of patching code.

    Public surface unchanged — every caller (``core.llm.router``,
    ``core.llm.strategies.plan_registry``, monkeypatched test sites) keeps
    working without modification.

    .. deprecated:: v0.99.39
       Resolves only ``provider`` from a model id string — cannot express
       the source axis (PAYG vs Subscription vs Adapter) that callers
       increasingly need. Use :func:`core.llm.adapters.resolve_for` which
       takes ``(provider, source)`` jointly. Removal target: v1.0.0.
    """
    from core.config.routing_manifest import resolve_provider as _manifest_resolve

    return _manifest_resolve(model)


# ---------------------------------------------------------------------------
# Model Policy — allowlist / denylist governance (.geode/model-policy.toml)
# ---------------------------------------------------------------------------

# P3 (v0.95.x) — single source of truth in `core.paths`; kept as a module-level
# re-export for callers that import `MODEL_POLICY_PATH` from `core.config`.
from core.paths import PROJECT_MODEL_POLICY as MODEL_POLICY_PATH  # noqa: E402


@dataclass
class ModelPolicy:
    """Model governance policy loaded from .geode/model-policy.toml."""

    allowlist: list[str] = field(default_factory=list)
    denylist: list[str] = field(default_factory=list)
    default_model: str = ""


def load_model_policy(policy_path: Path | None = None) -> ModelPolicy:
    """Load .geode/model-policy.toml. Returns empty policy (all allowed) if missing."""
    path = policy_path or MODEL_POLICY_PATH
    if not path.exists():
        return ModelPolicy()
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        section = raw.get("policy", {})
        return ModelPolicy(
            allowlist=section.get("allowlist", []),
            denylist=section.get("denylist", []),
            default_model=section.get("default_model", ""),
        )
    except Exception:
        log.warning("Failed to load model policy from %s, using empty policy", path, exc_info=True)
        return ModelPolicy()


def is_model_allowed(model: str, policy: ModelPolicy | None = None) -> bool:
    """Check if a model is allowed by the policy. Empty policy = all allowed."""
    if policy is None:
        policy = load_model_policy()
    # allowlist takes precedence: if set, only listed models are allowed
    if policy.allowlist:
        return model in policy.allowlist
    # denylist: if set, listed models are blocked
    if policy.denylist:
        return model not in policy.denylist
    return True


# ---------------------------------------------------------------------------
# Routing Config — per-node model routing (.geode/routing.toml)
# ---------------------------------------------------------------------------

# P3 (v0.95.x) — re-export from `core.paths` (SoT).
from core.paths import PROJECT_ROUTING_CONFIG as ROUTING_CONFIG_PATH  # noqa: E402

_routing_config_cache: RoutingConfig | None = None


@dataclass
class RoutingConfig:
    """Per-node model routing loaded from .geode/routing.toml."""

    nodes: dict[str, str] = field(default_factory=dict)
    agentic: dict[str, str] = field(default_factory=dict)


def load_routing_config(path: Path | None = None) -> RoutingConfig:
    """Load .geode/routing.toml. Returns empty config (default model) if missing."""
    global _routing_config_cache
    if _routing_config_cache is not None:
        return _routing_config_cache
    cfg_path = path or ROUTING_CONFIG_PATH
    if not cfg_path.exists():
        _routing_config_cache = RoutingConfig()
        return _routing_config_cache
    try:
        with open(cfg_path, "rb") as f:
            raw = tomllib.load(f)
        _routing_config_cache = RoutingConfig(
            nodes=raw.get("nodes", {}),
            agentic=raw.get("agentic", {}),
        )
        return _routing_config_cache
    except Exception:
        log.warning("Failed to load routing config from %s", cfg_path, exc_info=True)
        _routing_config_cache = RoutingConfig()
        return _routing_config_cache


def get_node_model(node_name: str) -> str | None:
    """Return the model for a pipeline node, or None for default fallback.

    Priority (post-P2-E):
      1. Project routing.toml (``<project>/.geode/routing.toml`` —
         legacy per-project override, loaded by :func:`load_routing_config`).
      2. Global routing manifest (``core/config/routing.toml`` +
         ``~/.geode/routing.toml`` user override, loaded by
         :func:`core.config.routing_manifest.load_routing_manifest`).
      3. ``None`` — caller falls back to ``settings.model``.

    Pipeline nodes (analyst, evaluator, scoring, synthesizer) always
    return a fixed model so they never inherit the user's REPL model.
    The shipped manifest pins all four to the Anthropic primary; users
    customise per-node by editing either routing.toml.
    """
    cfg = load_routing_config()
    if node_name in cfg.nodes:
        return cfg.nodes[node_name]
    try:
        from core.config.routing_manifest import load_routing_manifest

        manifest = load_routing_manifest()
    except Exception:
        return None
    return manifest.nodes.get(node_name)


def reset_routing_cache() -> None:
    """Clear the routing config cache (for testing)."""
    global _routing_config_cache
    _routing_config_cache = None


# Context-block char budget (hardcoding sweep, 2026-06-11) — the 8000-char
# cap was independently hardcoded at 4 sites (isolated_execution, skills
# context block, skill_catalog_policy, web_tools); one drift-prone policy,
# one anchor.
CONTEXT_BLOCK_MAX_CHARS = 8000
