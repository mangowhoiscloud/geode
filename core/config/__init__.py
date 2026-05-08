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
    "llm.secondary_model": "default_secondary_model",
    "llm.router_model": "router_model",
    "output.verbose": "verbose",
    "pipeline.confidence_threshold": "confidence_threshold",
    "pipeline.max_iterations": "max_iterations",
    "agentic.time_budget": "agentic_loop_time_budget",
    "agentic.thinking_budget": "agentic_thinking_budget",
    "agentic.effort": "agentic_effort",
    "sandbox.max_file_size_bytes": "sandbox_max_file_size_bytes",
    "sandbox.max_read_tokens": "sandbox_max_read_tokens",
    "sandbox.max_glob_results": "sandbox_max_glob_results",
    "sandbox.max_grep_results": "sandbox_max_grep_results",
    "sandbox.max_grep_line_chars": "sandbox_max_grep_line_chars",
}

DEFAULT_CONFIG_TOML = """\
# GEODE config.toml
# Priority: CLI > env > project .geode/config.toml > global ~/.geode/config.toml > defaults
#
# Uncomment and edit values to override defaults.

[llm]
# primary_model = "claude-opus-4-6"
# secondary_model = "gpt-5.4"
# router_model = "claude-opus-4-6"

[output]
# verbose = false

[pipeline]
# confidence_threshold = 0.7
# max_iterations = 5
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
    gp = global_path or GLOBAL_CONFIG_PATH
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


def _apply_toml_overlay(s: Settings) -> None:
    """Overlay TOML values onto Settings for fields not set by env vars."""
    toml_values = _load_toml_config()
    if not toml_values:
        return

    for field_name, toml_value in toml_values.items():
        # Skip fields that were explicitly set via environment variable.
        # Pydantic Settings loads from GEODE_<FIELD> and .env automatically.
        # We only overlay TOML for fields still at their code default.
        env_key = f"GEODE_{field_name.upper()}"
        if env_key in os.environ:
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

# Anthropic models — verified 2026-04-26 against platform.claude.com.
# v0.53.0 — chain depth reduced to 1 (primary → secondary only) per
# fail-fast governance: deeper chains create cost surprise + unclear
# user attribution. Quota exhaustion now surfaces a panel + stops loop.
ANTHROPIC_PRIMARY = "claude-opus-4-7"
ANTHROPIC_SECONDARY = "claude-sonnet-4-6"
ANTHROPIC_BUDGET = "claude-haiku-4-5-20251001"
ANTHROPIC_FALLBACK_CHAIN: list[str] = [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY]

# OpenAI models — verified 2026-04-26 against developers.openai.com.
# v0.52.4 — gpt-5.5 promoted to primary (Codex's new default model).
# v0.53.0 — chain depth reduced to 1 (primary → next).
OPENAI_PRIMARY = "gpt-5.5"
OPENAI_FALLBACK_CHAIN: list[str] = ["gpt-5.5", "gpt-5.4"]

# OpenAI Codex — Plus quota via chatgpt.com/backend-api/codex (Responses API).
# v0.52.4 — gpt-5.5 OAuth-only (developers.openai.com/codex/models).
# v0.53.0 — chain depth reduced to 1.
CODEX_PRIMARY = "gpt-5.5"
CODEX_FALLBACK_CHAIN: list[str] = ["gpt-5.5", "gpt-5.3-codex"]
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"

# ZhipuAI (GLM) models — OpenAI-compatible API, separate provider.
# v0.53.0 — chain depth reduced to 1 (primary → secondary).
GLM_PRIMARY = "glm-5.1"
GLM_FALLBACK_CHAIN: list[str] = ["glm-5.1", "glm-5"]
# Coding Plan endpoint (subscription-billed). PAYG endpoint is api/paas/v4 — a
# Coding Plan key called against PAYG path silently bypasses the subscription
# quota and incurs metered billing instead.
GLM_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
GLM_PAYG_BASE_URL = "https://api.z.ai/api/paas/v4"


# v0.53.0 — models that are CODEX-ONLY per OpenAI's official Codex
# models page (developers.openai.com/codex/models, verified 2026-04-27).
# These can ONLY be called via chatgpt.com/backend-api/codex (OAuth);
# no API-key path. Pre-fix _resolve_provider returned "openai" for
# gpt-5.5 → static map misled router; resolve_routing's equivalence-
# class scan corrected at runtime, but the user-visible mapping was
# wrong. Listing here makes the OAuth-only constraint explicit.
_CODEX_ONLY_MODELS: frozenset[str] = frozenset(
    {
        "gpt-5.5",
        "gpt-5.5-pro",
    }
)


def _resolve_provider(model: str) -> str:
    """Resolve provider name from model ID.

    Prefix-based inference with broad model coverage:
      claude-*                    → anthropic
      glm-*                       → glm
      gpt-5.5 / gpt-5.5-pro       → openai-codex (OAuth-only models)
      *-codex / *-codex-max/mini  → openai-codex
      gpt-* / o3-* / o4-*         → openai
      gemini-*                    → google
      deepseek-*                  → deepseek
      llama-*                     → meta
      qwen-*/qwen3*               → alibaba
      (fallback)                  → openai
    """
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith("glm-"):
        return "glm"
    if model in _CODEX_ONLY_MODELS:
        return "openai-codex"
    if model.endswith("-codex") or model.endswith("-codex-max") or model.endswith("-codex-mini"):
        return "openai-codex"
    if model.startswith(("gpt-", "o3-", "o4-")):
        return "openai"
    if model.startswith("gemini-"):
        return "google"
    if model.startswith("deepseek-"):
        return "deepseek"
    if model.startswith("llama-"):
        return "meta"
    if model.startswith(("qwen-", "qwen3")):
        return "alibaba"
    return "openai"


# ---------------------------------------------------------------------------
# Model Policy — allowlist / denylist governance (.geode/model-policy.toml)
# ---------------------------------------------------------------------------

MODEL_POLICY_PATH = Path(".geode") / "model-policy.toml"


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

ROUTING_CONFIG_PATH = Path(".geode") / "routing.toml"

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


# Pipeline nodes ALWAYS use these models regardless of user's REPL model.
# When routing.toml has no per-node config, these defaults prevent
# fallback to settings.model (the user's active REPL model like glm-5).
_PIPELINE_NODE_DEFAULTS: dict[str, str] = {
    "analyst": ANTHROPIC_PRIMARY,
    "evaluator": ANTHROPIC_PRIMARY,
    "scoring": ANTHROPIC_PRIMARY,
    "synthesizer": ANTHROPIC_PRIMARY,
}


def get_node_model(node_name: str) -> str | None:
    """Return the model for a pipeline node, or None for default fallback.

    Priority: routing.toml > _PIPELINE_NODE_DEFAULTS > None.
    Pipeline nodes (analyst, evaluator, scoring, synthesizer) always return
    a fixed model so they never inherit the user's REPL model.
    """
    cfg = load_routing_config()
    return cfg.nodes.get(node_name) or _PIPELINE_NODE_DEFAULTS.get(node_name)


def reset_routing_cache() -> None:
    """Clear the routing config cache (for testing)."""
    global _routing_config_cache
    _routing_config_cache = None
