"""Platform-aware system prompt fragments — Hermes absorption Phase 2.

GEODE is reachable through multiple surfaces — interactive CLI, the
``geode serve`` REPL, Slack gateway, scheduler cron, sandboxed worktree
runs, and the future remote-MCP path. Each surface has different
constraints: Slack truncates long replies, cron must finish in one
turn, the worktree CLI has tool access to the local repo. A
single one-size-fits-all system prompt is leaving capability on the
table.

Hermes' fix (per ``hermes_state.py:1130``) is a ``PLATFORM_HINTS`` dict
keyed by surface, returning a short directive block that gets appended
to the system prompt at assembly time. GEODE Phase 2 absorbs that
pattern with surface labels that match the GEODE entry-points.

**Resolution**:

1. ``$GEODE_SURFACE_TYPE`` env var (operator override) — useful when
   running ad-hoc CLI inside a containerised env that misidentifies
   itself.
2. ContextVar (entry-point-set; Phase 2.5 will wire this). Currently
   unset by default → falls through to step 3.
3. ``"cli"`` default — the most common interactive case.

Missing / unknown surface → no hint block appended (graceful no-op).

**4 frontier comparisons** (why this matters):

* Claude Code prepends an OS / shell / cwd block before every
  conversation.
* Codex CLI's ``<system-reminder>`` surfaces the sandbox + working
  directory.
* OpenClaw gateway injects channel-specific tool-policy reminders.
* Hermes itself routes surface-specific guidance through
  ``BasePromptCustomizer.platform_guidance``.

GEODE's version surfaces all four uses as a single declarative dict
the mutator can later evolve (T-series surface, eventually).
"""

from __future__ import annotations

import contextvars
import logging
import os

log = logging.getLogger(__name__)

__all__ = [
    "GEODE_SURFACE_TYPE_ENV",
    "PLATFORM_HINTS",
    "SURFACE_CLI",
    "SURFACE_CRON",
    "SURFACE_MCP_REMOTE",
    "SURFACE_SERVE_REPL",
    "SURFACE_SLACK",
    "SURFACE_WORKTREE",
    "VALID_SURFACES",
    "get_current_surface",
    "render_platform_hint",
    "set_current_surface",
]

GEODE_SURFACE_TYPE_ENV = "GEODE_SURFACE_TYPE"

# Canonical surface identifiers — keep alphabetised for diff stability.
SURFACE_CLI = "cli"
SURFACE_CRON = "cron"
SURFACE_MCP_REMOTE = "mcp_remote"
SURFACE_SERVE_REPL = "serve_repl"
SURFACE_SLACK = "slack"
SURFACE_WORKTREE = "worktree"

VALID_SURFACES: frozenset[str] = frozenset(
    {
        SURFACE_CLI,
        SURFACE_CRON,
        SURFACE_MCP_REMOTE,
        SURFACE_SERVE_REPL,
        SURFACE_SLACK,
        SURFACE_WORKTREE,
    }
)

PLATFORM_HINTS: dict[str, str] = {
    SURFACE_CLI: (
        "Surface: GEODE interactive CLI in a developer's "
        "terminal. Output is rendered with Rich markdown. Long code blocks "
        "are fine; the user can scroll. Tools include filesystem and shell "
        "access via the local repo's working directory."
    ),
    SURFACE_SERVE_REPL: (
        "Surface: persistent ``geode serve`` REPL. "
        "Conversation state is mirrored to SQLite for cross-session recall "
        "(use ``session_search`` to look up prior turns). The REPL streams "
        "output token-by-token; keep responses cohesive turn-by-turn."
    ),
    SURFACE_SLACK: (
        "Surface: Slack gateway. Replies should be "
        "concise (1–4 paragraphs). Avoid wide tables — Slack mangles them. "
        "Use Slack-flavored mrkdwn (``*bold*`` not ``**bold**``)."
    ),
    SURFACE_CRON: (
        "Surface: non-interactive scheduled job. There is no "
        "human in the loop to answer clarifying questions — make a "
        "reasonable default and document the assumption in the output. "
        "Long-running tools that prompt for input will fail; prefer "
        "non-interactive flags."
    ),
    SURFACE_WORKTREE: (
        "Surface: sandboxed git worktree. Treat the "
        "checkout as ephemeral — anything not committed and pushed before "
        "exit is lost. Filesystem changes outside the worktree are not "
        "permitted. Coordinate with the parent session via the worktree's "
        "``.owner`` file when in doubt about ownership."
    ),
    SURFACE_MCP_REMOTE: (
        "Surface: remote MCP server. The caller may be another "
        "agent; respond with structured JSON when the tool contract asks "
        "for it. Avoid colorised output — the MCP client may not strip ANSI."
    ),
}


_current_surface: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "geode_surface_type", default=None
)


def set_current_surface(surface: str | None) -> contextvars.Token[str | None]:
    """Bind the surface to the current ContextVar scope. Returns the reset token.

    Entry-points (Phase 2.5 follow-up) call this once at startup so every
    LLM call inside that process sees the right surface in
    :func:`get_current_surface`. Passing ``None`` clears the binding.
    """
    return _current_surface.set(surface)


def get_current_surface() -> str:
    """Resolve the active surface, honouring the env override then ContextVar.

    Resolution order:

    1. ``$GEODE_SURFACE_TYPE`` (operator override) — if it's a recognised
       surface name, use it. Unknown values log DEBUG and fall through.
    2. :data:`_current_surface` ContextVar — entry-point-set value.
    3. ``"cli"`` default — the most common interactive case.
    """
    override = os.environ.get(GEODE_SURFACE_TYPE_ENV)
    if override:
        if override in VALID_SURFACES:
            return override
        log.debug(
            "%s=%r is not a recognised surface (valid: %s); ignoring",
            GEODE_SURFACE_TYPE_ENV,
            override,
            sorted(VALID_SURFACES),
        )
    ctx_val = _current_surface.get()
    if ctx_val and ctx_val in VALID_SURFACES:
        return ctx_val
    return SURFACE_CLI


def render_platform_hint(surface: str | None = None) -> str:
    """Return a ``<platform_hint>`` block for the resolved surface, or ``""``.

    Args:
        surface: Explicit surface name; ``None`` triggers
            :func:`get_current_surface`. Useful for tests + future
            multi-surface report renderers.

    Returns:
        ``"<platform_hint>...\\n</platform_hint>"`` formatted block, or
        the empty string when the surface isn't in
        :data:`PLATFORM_HINTS` (graceful — caller's prompt remains
        valid).
    """
    target = surface or get_current_surface()
    body = PLATFORM_HINTS.get(target)
    if not body:
        return ""
    return f"<platform_hint surface={target!r}>\n{body}\n</platform_hint>"
