"""Module-level state, registry, and lookups for the slash-command package.

Hosts the ``ModelProfile`` dataclass + ``get_model_profiles`` factory, the
``COMMAND_MAP`` slash → action lookup, the conversation ContextVar, the
generic help renderer, ``resolve_action``, and the small
``_get_profile_store`` accessor. Extracted from the
monolithic ``core/cli/commands.py`` (Tier 3 #9) — every function body is
preserved byte-identical from the legacy module.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any as _Any

from core.auth.profiles import ProfileStore
from core.ui.console import console

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


# v0.53.0 — provider labels are CANONICAL provider IDs (matching
# /login dashboard + auth.toml), not marketing names. Pre-fix:
# "Codex (Plus)" label vs "openai-codex" provider ID mismatch caused
# user confusion. Auth-mode (OAuth vs PAYG) is NOT in the picker —
# the system auto-resolves at LLM call time via resolve_routing()
# based on the user's active /login state.
#
# Label = canonical provider ID + cost ($) tier.
# `gpt-5.5` default routes to `openai-codex` per equivalence-class
# scan when ChatGPT subscription OAuth is registered (v0.52.4 routing policy);
# otherwise to `openai` PAYG. Both paths visible via /login dashboard.

# GLM picker rows: id → display label. The live default (GLM_PRIMARY) leads the
# GLM block and the rest follow, with the default skipped from the tail so an
# operator override never duplicates a row. A label falls back to the id for an
# unknown override value.
_GLM_MODELS: tuple[tuple[str, str], ...] = (
    ("glm-5.2", "GLM-5.2"),
    ("glm-5.1", "GLM-5.1"),
    ("glm-5-turbo", "GLM-5 Turbo"),
    ("glm-4.7-flash", "GLM-4.7 Flash"),
)
_GLM_LABELS: dict[str, str] = dict(_GLM_MODELS)


def _glm_label(model_id: str) -> str:
    return _GLM_LABELS.get(model_id, model_id)


def get_model_profiles() -> list[ModelProfile]:
    """The /model picker model list, built fresh per call (H11-tail).

    Pre-PR this was a boot-frozen module-level list, so the routing-constant
    entries (``ANTHROPIC_SECONDARY`` / ``ANTHROPIC_BUDGET`` / ``OPENAI_PRIMARY``
    / ``GLM_PRIMARY``) ignored a mid-session ``routing.toml`` reload until
    restart. A function-local import re-reads the live ``core.config`` values
    each call; the hardcoded entries are version-pinned literals.
    """
    from core.config import ANTHROPIC_BUDGET, ANTHROPIC_SECONDARY, GLM_PRIMARY, OPENAI_PRIMARY

    return [
        # Fable 5 — Anthropic's most capable widely released model ($10/$50,
        # 1M ctx, adaptive-only thinking, refusal stop_reason). GA 2026-06-09.
        # ref: https://platform.claude.com/docs/en/about-claude/models/overview
        ModelProfile("claude-fable-5", "anthropic", "Fable 5", "$$$$"),
        ModelProfile("claude-opus-4-8", "anthropic", "Opus 4.8", "$$$"),
        ModelProfile("claude-opus-4-7", "anthropic", "Opus 4.7", "$$$"),
        ModelProfile("claude-opus-4-6", "anthropic", "Opus 4.6", "$$$"),
        ModelProfile(ANTHROPIC_SECONDARY, "anthropic", "Sonnet 4.6", "$$"),
        ModelProfile(ANTHROPIC_BUDGET, "anthropic", "Haiku 4.5", "$"),
        # v0.53.2 — gpt-5.5 is OAuth-only (Codex backend per
        # developers.openai.com/codex/models). _resolve_provider returns
        # "openai-codex" for it via _CODEX_ONLY_MODELS; ModelProfile.provider
        # must match so the /model picker label is honest about which
        # auth-mode the user's pick will actually consume.
        ModelProfile(OPENAI_PRIMARY, "openai-codex", "GPT-5.5", "$$"),
        ModelProfile("gpt-5.4", "openai", "GPT-5.4", "$$"),
        ModelProfile("gpt-5.4-mini", "openai", "GPT-5.4 Mini", "$"),
        ModelProfile("gpt-5.3-codex", "openai-codex", "GPT-5.3 Codex", "$$"),
        # GLM — the live default (GLM_PRIMARY, glm-5.2 as shipped) leads so a
        # routing.toml reload is reflected mid-session (H11-tail), labelled via
        # the id→label map; the rest follow with the default skipped so an
        # operator override of the default never duplicates a row.
        ModelProfile(GLM_PRIMARY, "glm", _glm_label(GLM_PRIMARY), "$"),
        *[ModelProfile(mid, "glm", lbl, "$") for mid, lbl in _GLM_MODELS if mid != GLM_PRIMARY],
    ]


def get_model_index() -> dict[str, ModelProfile]:
    """``{id: ModelProfile}`` over the live picker list (H11-tail)."""
    return {m.id: m for m in get_model_profiles()}


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
        description="Reviews and refines the agent's reasoning after each tool batch",
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
# Conversation Context ContextVar (shared with tool handlers)
# ---------------------------------------------------------------------------

_conversation_ctx: ContextVar[_Any] = ContextVar("conversation_ctx", default=None)


def set_conversation_context(ctx: _Any) -> None:
    """Inject the active ConversationContext for command handlers."""
    _conversation_ctx.set(ctx)


def get_conversation_context() -> _Any:
    """Retrieve the active ConversationContext (None if not set)."""
    return _conversation_ctx.get(None)


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
    "/schedule": "schedule",
    "/sched": "schedule",
    "/trigger": "trigger",
    "/status": "status",
    "/mcp": "mcp",
    "/skills": "skills",
    "/skill": "skill_invoke",
    "/cost": "cost",
    "/resume": "resume",
    "/context": "context",
    "/ctx": "context",
    "/apply": "apply",
    "/compact": "compact",
    "/clear": "clear",
    "/login": "login",
    "/tasks": "tasks",
    "/task": "tasks",
    "/t": "tasks",
    "/audit": "audit",
    "/audit-seeds": "audit-seeds",
    "/petri": "petri",
    "/self-improving": "self-improving",
    "/sil": "self-improving",
    "/recall": "recall",
}


def show_help() -> None:
    """Show interactive mode help."""
    console.print()
    console.print("  [header]Commands[/header]")
    console.print("  [label]/verbose[/label]            — Toggle verbose mode")
    console.print("  [label]/login[/label]              — Plans + credentials dashboard (unified)")
    console.print("  [label]/login openai[/label]       — ChatGPT subscription OAuth")
    console.print("  [label]/login anthropic[/label]    — Claude subscription OAuth")
    console.print("  [label]/login add[/label]          — Interactive plan/key wizard")
    console.print("  [label]/key[/label] <value>        — Quick PAYG API key (legacy alias)")
    console.print("  [label]/model[/label]              — Show & switch LLM model")
    console.print(
        "  [label]/petri[/label]              — Show & switch Petri role × model × source"
    )
    console.print("  [label]/login source[/label] <p> <t> — Pick credential source per provider")
    console.print("  [label]/schedule[/label]           — Manage scheduled automations")
    console.print("  [label]/trigger[/label]            — Manage event/cron triggers")
    console.print("  [label]/status[/label]             — Show system status")
    console.print("  [label]/cost[/label]               — LLM cost dashboard")
    console.print("  [label]/mcp[/label]                — MCP server status/tools/add")
    console.print("  [label]/skills[/label]             — List/add/reload skills")
    console.print("  [label]/skill[/label] <name> [args] — Invoke a skill")
    console.print("  [label]/resume[/label]             — Resume interrupted session")
    console.print("  [label]/context[/label]            — Show assembled context tiers")
    console.print("  [label]/apply[/label]              — Manage job applications")
    console.print("  [label]/tasks[/label]              — Show task list")
    console.print("  [label]/recall[/label]             — Memory-recall pool (list/show/save)")
    console.print("  [label]/compact[/label]            — Compact conversation context")
    console.print("  [label]/clear[/label]              — Clear conversation history")
    console.print("  [label]/help[/label]               — Show this help")
    console.print("  [label]/quit[/label]               — Exit GEODE")

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


def model_available(model_id: str) -> bool:
    """Return True if `model_id` has a usable credential route.

    Mirrors what ``AgenticLoop`` would resolve at the next LLM call:
    delegates to ``resolve_routing(model_id)`` (which walks per-model
    routing → equivalence-class scan → single-provider fallback → PAYG
    synthesis) and treats a non-None ``RoutingTarget`` as "available".

    Used by the ``/model`` picker (M5) to flag entries whose provider
    has no authenticated profile yet — so the user sees *why* a model
    won't switch instead of selecting it and bouncing off the
    ``_check_provider_key`` warning. Returns ``False`` defensively when
    routing raises so a broken plan registry does not lock the picker.
    """
    try:
        from core.llm.strategies.plan_registry import resolve_routing

        return resolve_routing(model_id) is not None
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

    Mirrors the normalisation in
    ``core.llm.strategies.plan_registry._apply_forced_login_method`` so the
    badge stays in lockstep with the actual sort behaviour: any of
    ``apikey`` / ``api`` / ``api_key`` / ``key`` collapse to the
    ``"apikey"`` label that the underlying sort uses.
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
