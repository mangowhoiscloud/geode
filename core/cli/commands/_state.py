"""Module-level state, registry, and lookups for the slash-command package.

Hosts the ``ModelProfile`` dataclass + ``MODEL_PROFILES`` table, the
``COMMAND_MAP`` slash → action lookup, the conversation ContextVar, the
generic help renderer, ``install_domain_commands``, ``resolve_action``,
and the small ``_get_profile_store`` accessor. Extracted from the
monolithic ``core/cli/commands.py`` (Tier 3 #9) — every function body is
preserved byte-identical from the legacy module.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any as _Any

from core.auth.profiles import ProfileStore
from core.config import (
    ANTHROPIC_BUDGET,
    ANTHROPIC_PRIMARY,
    ANTHROPIC_SECONDARY,
    GLM_PRIMARY,
    OPENAI_PRIMARY,
)
from core.ui.console import console

log = logging.getLogger(__name__)

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
# scan when Codex Plus OAuth is registered (v0.52.4 routing policy);
# otherwise to `openai` PAYG. Both paths visible via /login dashboard.
MODEL_PROFILES: list[ModelProfile] = [
    ModelProfile(ANTHROPIC_PRIMARY, "anthropic", "Opus 4.7", "$$$"),
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
    ModelProfile(GLM_PRIMARY, "glm", "GLM-5.1", "$"),
    ModelProfile("glm-5-turbo", "glm", "GLM-5 Turbo", "$"),
    ModelProfile("glm-4.7-flash", "glm", "GLM-4.7 Flash", "$"),
]

_MODEL_INDEX: dict[str, ModelProfile] = {m.id: m for m in MODEL_PROFILES}

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
    "/petri": "petri",
}


def install_domain_commands(domain: _Any) -> None:
    """Merge a domain's slash commands into the generic ``COMMAND_MAP``.

    Domains implement ``DomainPort.register_slash_commands(command_map)``
    (v2, optional). When absent, this is a no-op.
    """
    register = getattr(domain, "register_slash_commands", None)
    if callable(register):
        register(COMMAND_MAP)


def show_help() -> None:
    """Show interactive mode help.

    Renders the generic command list, then asks the active domain (if
    any) to append its own slash-command help fragment via the optional
    ``DomainPort.render_help_fragment()`` hook.
    """
    console.print()
    console.print("  [header]Commands[/header]")
    console.print("  [label]/verbose[/label]            — Toggle verbose mode")
    console.print("  [label]/login[/label]              — Plans + credentials dashboard (unified)")
    console.print("  [label]/login openai[/label]       — Codex OAuth (Plus quota)")
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
    console.print("  [label]/compact[/label]            — Compact conversation context")
    console.print("  [label]/clear[/label]              — Clear conversation history")
    console.print("  [label]/help[/label]               — Show this help")
    console.print("  [label]/quit[/label]               — Exit GEODE")

    # Domain-specific help fragment appended below.
    try:
        from core.domains.port import get_domain_or_none

        domain = get_domain_or_none()
        if domain is not None:
            render_fragment = getattr(domain, "render_help_fragment", None)
            if callable(render_fragment):
                render_fragment()
    except Exception:
        log.debug("Domain help fragment skipped", exc_info=True)
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


def resolve_action(cmd: str) -> str | None:
    """Resolve a slash command to its action name. Returns None if unknown."""
    return COMMAND_MAP.get(cmd)
