"""Command location registry — single source of truth for slash routing.

v0.52 phase 3: every slash command is classified into one of three
``RunLocation`` values. The thin-client REPL (``cli/repl.py``) inspects
this registry to decide whether to:

  THIN          → execute locally in the geode CLI process (terminal
                  attached, file/state writes via shared modules)
  DAEMON_RPC    → relay via ``client.send_command`` (≤2s, capture-output
                  RPC). Daemon runs the command, returns stdout buffer.
  DAEMON_STREAM → relay via ``client.send_prompt``-style streaming with
                  IPC events (long-running, interactive progress).

Bug class B2 / B3 / B8 — pre-v0.52 commands were dispatched implicitly:
``cmd_login`` ran in both thin (slash) and daemon (manage_login tool)
paths with different IPC writer availability, so OAuth device-code
prompts were swallowed by ``capture_output()`` on the daemon side.
``COMMAND_REGISTRY`` makes the location explicit, and
``tests/core/cli/test_command_registry.py`` enforces:

  1. Every registered command has exactly one RunLocation
  2. THIN commands do not depend on ``_ipc_writer_local`` (no IPC events)
  3. New commands MUST be added to the registry — REPL refuses unknown
     slash commands rather than silently relaying them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum


class RunLocation(Enum):
    """Where a slash command is executed."""

    #: CLI process. Terminal stdin/stdout/browser available.
    #: Examples: /login (OAuth flow), /key, /help, /model picker.
    THIN = "thin"

    #: Daemon process via ``send_command`` RPC. Capture-output, ≤2s.
    #: Examples: /cost, /status (read-only daemon state).
    DAEMON_RPC = "daemon_rpc"

    #: Daemon process via ``send_command_streaming`` (event channel).
    #: Examples: /analyze, /run, /skill <invoke> (long-running with progress).
    DAEMON_STREAM = "daemon_stream"


@dataclass(frozen=True)
class CommandSpec:
    """Single slash command's contract."""

    name: str  # leading slash, e.g. "/login"
    location: RunLocation
    description: str
    aliases: tuple[str, ...] = ()
    #: Handler imported lazily by repl.py — registry stays cheap to import.
    handler_path: str = ""  # e.g. "core.cli.commands.auth.login:cmd_login"
    #: True if the command requires a TTY (e.g. interactive picker).
    needs_tty: bool = False


# v0.52 phase 3 initial mapping. Phases 4-7 expand DAEMON_* entries as
# handlers move into core/server/.
COMMAND_REGISTRY: dict[str, CommandSpec] = {
    # ────────── THIN — CLI process direct execution ──────────
    "/help": CommandSpec(
        name="/help",
        location=RunLocation.THIN,
        description="Show interactive mode help",
        handler_path="core.cli.commands:show_help",
    ),
    "/login": CommandSpec(
        name="/login",
        location=RunLocation.THIN,
        description="Plans + credentials dashboard (OAuth, API keys, routing)",
        handler_path="core.cli.commands:cmd_login",
        needs_tty=True,  # OAuth device-code flow needs browser + terminal
    ),
    "/key": CommandSpec(
        name="/key",
        location=RunLocation.THIN,
        description="Quick PAYG API key (legacy alias for /login)",
        handler_path="core.cli.commands:cmd_key",
    ),
    "/model": CommandSpec(
        name="/model",
        location=RunLocation.THIN,
        description="Show & switch LLM model (interactive picker)",
        handler_path="core.cli.commands:cmd_model",
        needs_tty=True,
    ),
    "/cognitive": CommandSpec(
        name="/cognitive",
        location=RunLocation.THIN,
        description="Show persisted cognitive state and recent events for a session",
        handler_path="core.cli.commands:cmd_cognitive",
    ),
    # ────────── DAEMON_RPC — short read-only daemon queries ──────────
    # Phase 4에서 core/server/handlers/ 로 이동 후 handler_path 갱신.
    # 현재는 cli/__init__.py:_handle_command 가 IPC RPC로 위임 (호환).
    # ────────── DAEMON_STREAM — long-running with progress events ──────
    # Phase 4에서 추가 (analyze, run, batch, skill_invoke 등).
}


def compose_command_registry(specs: Iterable[CommandSpec] = ()) -> dict[str, CommandSpec]:
    """Return a collision-checked registry for one CLI composition."""
    registry = dict(COMMAND_REGISTRY)
    known = {name for spec in registry.values() for name in (spec.name, *spec.aliases)}
    for spec in specs:
        names = (spec.name, *spec.aliases)
        if any(not name.startswith("/") for name in names):
            raise ValueError(f"slash command names must start with '/': {names!r}")
        collisions = [name for name in names if name in known]
        if collisions:
            raise ValueError(f"duplicate slash command registration: {collisions!r}")
        registry[spec.name] = spec
        known.update(names)
    return registry


def lookup(
    slash_command: str,
    registry: Mapping[str, CommandSpec] | None = None,
) -> CommandSpec | None:
    """Return the registered ``CommandSpec`` for a leading-slash command name.

    Returns None when the command is not registered. The REPL treats
    None as "relay to daemon as legacy DAEMON_RPC" during phases 3-4
    (transitional). Phase 6 + import-linter make unknown commands fail.
    """
    active = COMMAND_REGISTRY if registry is None else registry
    direct = active.get(slash_command)
    if direct is not None:
        return direct
    return next((spec for spec in active.values() if slash_command in spec.aliases), None)


def is_thin(
    slash_command: str,
    registry: Mapping[str, CommandSpec] | None = None,
) -> bool:
    """Quick check: does this command run locally in the CLI process?"""
    spec = lookup(slash_command, registry)
    return spec is not None and spec.location is RunLocation.THIN
