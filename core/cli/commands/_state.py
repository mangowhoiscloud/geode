"""Module-level state, registry, and lookups for the slash-command package.

Hosts the ``ModelProfile`` dataclass + ``get_model_profiles`` factory, the
``COMMAND_MAP`` slash → action lookup, the conversation-state facade, the
generic help renderer, ``resolve_action``, and the small
``_get_profile_store`` accessor. Extracted from the
monolithic ``core/cli/commands.py`` (Tier 3 #9) — every function body is
preserved byte-identical from the legacy module.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any as _Any

from core.agent import conversation as _conversation
from core.auth.profiles import ProfileStore
from core.ui.console import console

_conversation_ctx = _conversation._conversation_ctx
get_conversation_context = _conversation.get_conversation_context
set_conversation_context = _conversation.set_conversation_context

# ---------------------------------------------------------------------------
# Model Registry (OpenClaw Auth Profile Rotation pattern)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelProfile:
    """A selectable LLM model profile."""

    id: str
    provider: str
    label: str
    cost: str  # relative cost indicator


# Model rows expose provider families, not endpoint/auth variants. ChatGPT
# subscription OAuth and PAYG are OpenAI sources selected at call time by
# ``resolve_routing()``; ``openai-codex`` remains the subscription route name.
#
# Label = canonical provider ID + cost ($) tier.
# Every GPT row uses the OpenAI provider family; credential source selects
# ChatGPT subscription versus PAYG.

_OPENROUTER_PICKER_MODELS: tuple[ModelProfile, ...] = (
    ModelProfile(
        "openrouter/openrouter/free",
        "openrouter",
        "OpenRouter Free (smoke)",
        "free*",
    ),
    ModelProfile(
        "openrouter/openrouter/auto",
        "openrouter",
        "OpenRouter Auto (variable)",
        "var",
    ),
)


def get_model_profiles(
    *, configured_model_ids: Iterable[str] = (), openai_source: str | None = None
) -> list[ModelProfile]:
    """The /model picker model list, built fresh per call (H11-tail).

    Pre-PR this was a boot-frozen module-level list, so the routing-constant
    entries (``ANTHROPIC_SECONDARY`` / ``ANTHROPIC_BUDGET`` /
    ``GLM_PRIMARY``) ignored a mid-session ``routing.toml`` reload until
    restart. A function-local import re-reads the live ``core.config`` values
    each call; the hardcoded entries are version-pinned literals.

    ``configured_model_ids`` carries the active per-role selections. Any
    persisted model outside the curated catalog is retained as one deduplicated
    management row, so opening the picker and pressing Enter cannot silently
    replace an existing selection. ``OPENAI_PRIMARY`` receives the same
    treatment because it is an operator-owned routing default. Retired
    subscription models are not offered; an active retired selection stays as
    a labelled, unavailable management row so Enter cannot silently replace it.
    """
    from core.config import (
        ANTHROPIC_BUDGET,
        ANTHROPIC_PRIMARY,
        ANTHROPIC_SECONDARY,
        GLM_PRIMARY,
        OPENAI_PRIMARY,
        _resolve_provider,
    )
    from core.llm.model_catalog import MODEL_OFFERINGS, model_source_unavailable_reason

    def active_profiles(provider: str, source: str | None) -> list[ModelProfile]:
        profiles: list[ModelProfile] = []
        for entry in MODEL_OFFERINGS:
            if entry.provider != provider:
                continue
            selected = source or _selected_openai_source(entry.id) or "payg"
            if selected in entry.sources and not model_source_unavailable_reason(
                entry.id, provider=provider, source=selected
            ):
                profiles.append(ModelProfile(entry.id, entry.provider, entry.label, entry.cost))
        return profiles

    anthropic_profiles = active_profiles("anthropic", "payg")
    openai_profiles = active_profiles("openai", openai_source)
    openrouter_profiles = list(_OPENROUTER_PICKER_MODELS)
    glm_profiles = active_profiles("glm", "payg")
    # Routing defaults are read on every invocation; preserve explicit choices
    # as management rows even when absent from the current public catalogue.
    if any(p.id == GLM_PRIMARY for p in glm_profiles):
        glm_profiles.sort(key=lambda p: p.id != GLM_PRIMARY)

    existing_ids = {
        profile.id
        for profile in (*anthropic_profiles, *openai_profiles, *openrouter_profiles, *glm_profiles)
    }
    configured_profiles: list[ModelProfile] = []
    for raw_model_id in (
        OPENAI_PRIMARY,
        ANTHROPIC_PRIMARY,
        GLM_PRIMARY,
        ANTHROPIC_SECONDARY,
        ANTHROPIC_BUDGET,
        *configured_model_ids,
    ):
        model_id = raw_model_id.strip()
        if not model_id or model_id in existing_ids:
            continue
        existing_ids.add(model_id)
        provider = _resolve_provider(model_id)
        reason = model_unavailable_reason(
            model_id,
            source=openai_source if provider in {"openai", "openai-codex"} else None,
        )
        source_label = "Anthropic API" if provider == "anthropic" else "subscription"
        configured_profiles.append(
            ModelProfile(
                model_id,
                provider,
                (
                    f"{model_id} (Unavailable on {source_label})"
                    if reason
                    else f"{model_id} (Configured)"
                ),
                "$$",
            )
        )

    # Keep configured rows beside their provider family. The final catch-all
    # retains future/custom provider ids without inventing another registry.
    configured_anthropic = [p for p in configured_profiles if p.provider == "anthropic"]
    configured_openai = [p for p in configured_profiles if p.provider in {"openai", "openai-codex"}]
    configured_openrouter = [p for p in configured_profiles if p.provider == "openrouter"]
    configured_glm = [p for p in configured_profiles if p.provider == "glm"]
    configured_other = [
        p
        for p in configured_profiles
        if p.provider not in {"anthropic", "openai", "openai-codex", "openrouter", "glm"}
    ]
    return [
        *anthropic_profiles,
        *configured_anthropic,
        *openai_profiles,
        *configured_openai,
        *openrouter_profiles,
        *configured_openrouter,
        *glm_profiles,
        *configured_glm,
        *configured_other,
    ]


def get_model_index(*, configured_model_ids: Iterable[str] = ()) -> dict[str, ModelProfile]:
    """``{id: ModelProfile}`` over the live picker list (H11-tail)."""
    return {m.id: m for m in get_model_profiles(configured_model_ids=configured_model_ids)}


# ---------------------------------------------------------------------------
# Agent Role Registry — PR-A (2026-05-21)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentRole:
    """One LLM-driven role inside GEODE that owns its own model knob.

    ``/model`` cycles through registered roles via Tab so each role's
    chosen model can be picked through the same UI. Each role maps to:

      * ``settings_field`` — the ``Settings`` attribute that drives the
        runtime (read by the producer, e.g. ``settings.model`` →
        AgenticLoop; ``settings.cognitive_reflection_model`` →
        ``core.agent.loop._reflection.reflect_async``).
      * ``env_var`` — the canonical env var name written by
        ``_upsert_env`` so the picker's choice survives one restart.
      * ``toml_section`` / ``toml_key`` — durable persistence path in
        ``~/.geode/config.toml`` so the picker's choice survives every
        restart.
      * ``description`` — short hint shown next to the role tab.
    """

    name: str
    label: str
    settings_field: str
    env_var: str
    toml_section: str
    toml_key: str
    description: str
    has_effort: bool  # primary uses agentic_effort, reflection doesn't


AGENT_ROLES: list[AgentRole] = [
    AgentRole(
        name="primary",
        label="Primary",
        settings_field="model",
        env_var="GEODE_MODEL",
        toml_section="llm",
        toml_key="primary_model",
        description="Main agentic loop — drives plan / act / observe rounds",
        has_effort=True,
    ),
    AgentRole(
        name="reflection",
        label="Reflection",
        settings_field="cognitive_reflection_model",
        env_var="GEODE_COGNITIVE_REFLECTION_MODEL",
        toml_section="cognitive",
        toml_key="reflection_model",
        description=("Reflection override - empty inherits the main agentic loop model/source"),
        has_effort=False,
    ),
    # PR-G2 (2026-05-21) — self-improving loop mutator role. Unlike
    # primary / reflection (which live on ``Settings``), the mutator's
    # model knob lives in ``MutatorConfig.default_model``
    # (Step J-b.1, 2026-05-23: relocated to
    # ``[self_improving_loop.autoresearch.mutator] default_model`` —
    # autoresearch is the control-layer SoT that owns its in-process
    # engineering LLM). When ``default_model`` is ``None`` (the new
    # G1a default from PR-MINIMAL-2) the runner inherits
    # ``Settings.model``. The ``settings_field=""`` sentinel signals
    # "no Settings attribute to write" — the picker persists via
    # ``upsert_config_toml`` only, which is exactly the SoT path
    # ``_default_llm_call`` reads at dispatch time.
    AgentRole(
        name="mutator",
        label="Mutator",
        settings_field="",
        env_var="GEODE_SELF_IMPROVING_LOOP_MUTATOR_MODEL",
        toml_section="self_improving_loop.autoresearch.mutator",
        toml_key="default_model",
        description=(
            "Self-improving loop mutator — proposes wrapper/policy mutations "
            "(set to '' to inherit Settings.model)"
        ),
        has_effort=False,
    ),
]

_ROLE_INDEX: dict[str, AgentRole] = {r.name: r for r in AGENT_ROLES}


def role_by_name(name: str) -> AgentRole:
    """Return the :class:`AgentRole` matching ``name``.

    Raises :class:`ValueError` on unknown roles so the picker fails
    closed rather than silently writing to an unexpected settings field.
    """
    try:
        return _ROLE_INDEX[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown agent role {name!r}; expected one of {[r.name for r in AGENT_ROLES]!r}"
        ) from exc


# ---------------------------------------------------------------------------
# Command Map (OpenClaw Binding pattern: deterministic routing)
# ---------------------------------------------------------------------------

COMMAND_MAP: dict[str, str] = {
    "/quit": "quit",
    "/exit": "quit",
    "/q": "quit",
    "/help": "help",
    "/verbose": "verbose",
    "/key": "key",
    "/model": "model",
    "/goal": "goal",
    "/plan": "plan",
    "/grill": "grill",
    "/schedule": "schedule",
    "/sched": "schedule",
    "/trigger": "trigger",
    "/status": "status",
    "/fleet": "fleet",
    "/mcp": "mcp",
    "/skills": "skills",
    "/skill": "skill_invoke",
    "/cost": "cost",
    "/resume": "resume",
    "/cognitive": "cognitive",
    "/context": "context",
    "/ctx": "context",
    "/apply": "apply",
    "/compact": "compact",
    "/clear": "clear",
    "/login": "login",
    "/tasks": "tasks",
    "/task": "tasks",
    "/t": "tasks",
}


def show_help(command_registry: _Any = None) -> None:
    """Show interactive mode help."""
    console.print()
    console.print("  [header]Commands[/header]")
    console.print("  [label]/verbose[/label]            — Toggle verbose mode")
    console.print("  [label]/login[/label]              — Plans + credentials dashboard (unified)")
    console.print("  [label]/login openai[/label]       — ChatGPT subscription OAuth")
    console.print("  [label]/login anthropic[/label]    — Explain Anthropic API-key setup")
    console.print("  [label]/login google[/label]       — Google Workspace OAuth (BYO client)")
    console.print("  [label]/login add[/label]          — Interactive plan/key wizard")
    console.print("  [label]/key[/label] <value>        — Quick PAYG API key (legacy alias)")
    console.print("  [label]/model[/label]              — Show & switch LLM model")
    console.print(
        "  [label]/goal[/label] [objective|clear] — Show, set, or clear a persistent goal"
    )
    console.print("  [label]/plan[/label] [objective]    — Show or create an advisory no-tool plan")
    console.print("  [label]/grill[/label] <decision>   — Stress-test a decision tree")
    console.print("  [label]/login source[/label] <p> <t> — Pick credential source per provider")
    console.print("  [label]/schedule[/label]           — Manage scheduled automations")
    console.print("  [label]/trigger[/label]            — Manage event/cron triggers")
    console.print("  [label]/status[/label]             — Show system status")
    console.print("  [label]/fleet[/label]              — Interactive sub-agent fleet view")
    console.print("  [label]/cost[/label]               — LLM cost dashboard")
    console.print("  [label]/mcp[/label]                — MCP server status/tools/add")
    console.print("  [label]/skills[/label]             — List/add/reload skills")
    console.print("  [label]/skill[/label] <name> [args] — Invoke a skill")
    console.print("  [label]/resume[/label]             — Resume interrupted session")
    console.print("  [label]/cognitive[/label] <sid>    — Show cognitive state for a session")
    console.print("  [label]/context[/label]            — Show assembled context tiers")
    console.print("  [label]/apply[/label]              — Manage job applications")
    console.print("  [label]/tasks[/label]              — Show task list")
    console.print(
        "  [label]/compact[/label]            — Summarize context; --prune discards older history"
    )
    console.print("  [label]/clear[/label]              — Clear conversation history")
    console.print("  [label]/help[/label]               — Show this help")
    console.print("  [label]/quit[/label]               — Exit GEODE")

    from core.cli.routing import COMMAND_REGISTRY

    for spec in (COMMAND_REGISTRY if command_registry is None else command_registry).values():
        if spec.name not in COMMAND_MAP:
            console.print(f"  [label]{spec.name}[/label] — {spec.description}")

    console.print()
    console.print("  [muted]Or just type naturally to interact with the agent.[/muted]")
    console.print()


def _get_profile_store() -> ProfileStore:
    """Return the runtime ProfileStore singleton.

    Pre-v0.50.0 the CLI maintained its own parallel store, so credentials
    added through `/login add` were invisible to the LLM dispatch layer.
    Both layers now read from `runtime_wiring.infra` directly.
    """
    from core.wiring.container import ensure_profile_store

    return ensure_profile_store()


def _selected_openai_source(model: str = "") -> str | None:
    """Read the same source choice as adapter dispatch, without changing it."""
    from core.config.runtime_policy_sources import build_policy_source_bundle
    from core.llm.routing import infer_source

    try:
        return infer_source(
            "openai", model=model, sources=build_policy_source_bundle().get("provider_routing")
        )
    except RuntimeError:
        # A disabled provider is handled by the credential availability path.
        return None


def model_unavailable_reason(model_id: str, *, source: str | None = None) -> str | None:
    """Explain source retirement separately from missing credentials."""
    from core.config import _resolve_provider
    from core.llm.model_catalog import model_source_unavailable_reason, normalize_model_provider

    provider = _resolve_provider(model_id)
    if provider == "anthropic":
        return model_source_unavailable_reason(model_id, provider=provider, source="payg")
    if normalize_model_provider(provider) == "glm":
        from core.config.runtime_policy_sources import build_policy_source_bundle
        from core.llm.routing import infer_source

        return model_source_unavailable_reason(
            model_id,
            provider="glm",
            source=source
            if source is not None
            else infer_source(
                "glm", model=model_id, sources=build_policy_source_bundle().get("provider_routing")
            ),
        )
    if normalize_model_provider(provider) != "openai":
        return None
    return model_source_unavailable_reason(
        model_id,
        provider=provider,
        source=source if source is not None else _selected_openai_source(model_id) or "",
    )


def model_available(model_id: str, *, source: str | None = None) -> bool:
    """Return True if `model_id` has a usable credential route.

    Uses admission's model-aware source and the same account selector as SDK
    requests. Bare Settings/environment credentials remain adapter-owned. An
    unavailable explicit plan never falls through to them or another source.

    Used by the ``/model`` picker (M5) to flag entries whose provider
    has no authenticated profile yet — so the user sees *why* a model
    won't switch instead of selecting it and bouncing off the
    ``_check_provider_key`` warning. Returns ``False`` defensively when
    routing raises so a broken plan registry does not lock the picker.
    """
    try:
        from core.config import _resolve_provider
        from core.config.runtime_policy_sources import build_policy_source_bundle
        from core.llm.adapters.base import CredentialDetectionCapable, EnvironmentDiagnosticCapable
        from core.llm.adapters.registry import resolve_for
        from core.llm.routing import infer_source, resolve_routing

        sources = build_policy_source_bundle().get("provider_routing")
        provider = _resolve_provider(model_id)
        source = (
            source
            if source is not None
            else infer_source(provider, model=model_id, sources=sources)
        )
        if model_unavailable_reason(model_id, source=source) is not None:
            return False
        if resolve_routing(model_id, provider=provider, source=source, sources=sources) is not None:
            return True
        adapter = resolve_for(provider, source)
        if isinstance(adapter, CredentialDetectionCapable):
            return adapter.detect_credential() is not None
        return isinstance(adapter, EnvironmentDiagnosticCapable) and adapter.test_environment().ok
    except Exception:
        return False


# v0.99.19 M2 — surface ``settings.forced_login_method`` per provider in
# the ``/model`` picker. Pre-fix the picker silently honoured the user's
# escape hatch (Codex CLI parity) so a user with
# ``forced_login_method = {"openai": "apikey"}`` would pick ``gpt-5.5``
# expecting the ChatGPT subscription and get PAYG instead. The badge below makes the
# override visible at selection time.
_FORCED_METHOD_DEFAULTS: frozenset[str] = frozenset({"subscription", "auto", ""})
_FORCED_METHOD_APIKEY_ALIASES: frozenset[str] = frozenset({"apikey", "api", "api_key", "key"})


def forced_login_method_for(provider: str) -> str | None:
    """Return the user-visible label for `settings.forced_login_method[provider]`.

    ``None`` when the setting is at its default (``"subscription"`` /
    ``"auto"`` / unset) so the picker only renders a badge when the
    user has *explicitly* chosen a non-default routing — that's the
    bit that surprises them.

    Mirrors the aliases accepted by ``core.llm.routing``. This label is
    presentation only; runtime admission validates conflicts and resolves the
    concrete source before account selection.
    """
    try:
        from core.config import settings

        forced = (getattr(settings, "forced_login_method", {}) or {}).get(provider, "")
    except Exception:
        return None
    value = str(forced).strip().lower()
    if value in _FORCED_METHOD_DEFAULTS:
        return None
    if value in _FORCED_METHOD_APIKEY_ALIASES:
        return "apikey"
    return value or None


def resolve_action(cmd: str) -> str | None:
    """Resolve a slash command to its action name. Returns None if unknown."""
    return COMMAND_MAP.get(cmd)
