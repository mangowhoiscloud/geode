"""Thin command execution and neutral slash-routing compatibility exports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.cli.ipc_client import IPCClient

from core.slash_routing import (
    COMMAND_REGISTRY,
    CommandSpec,
    RunLocation,
    compose_command_registry,
    is_thin,
    lookup,
)

__all__ = [
    "COMMAND_REGISTRY",
    "CommandSpec",
    "RunLocation",
    "compose_command_registry",
    "is_thin",
    "lookup",
]


def run_thin_command(
    client: IPCClient,
    cmd: str,
    args: str,
    *,
    command_registry: Mapping[str, CommandSpec] | None = None,
) -> None:
    """Collect terminal input here; read and change daemon-owned state through it."""
    from core.cli.dispatcher import _handle_command

    if cmd == "/model":
        from core.cli.commands.model import cmd_model

        cmd_model(args, client=client)
        return
    if cmd == "/login":
        from core.cli.commands.login import DAEMON_LOGIN_SUBCOMMANDS, cmd_login

        sub = args.split(maxsplit=1)[:1]
        if sub == ["source"]:
            cmd_login(args, client=client)
            return
        if not sub or sub[0].lower() in DAEMON_LOGIN_SUBCOMMANDS:
            response = client.send_command("/login", args)
            _render_daemon_result(response)
            if "error" not in (response.get("status"), response.get("type")):
                # Local /model and /login source read this process's copy.
                from core.auth.auth_toml import load_auth_toml

                load_auth_toml()
            return
        if not cmd_login(args):
            return
    else:
        _handle_command(cmd, args, False, command_registry=command_registry)
    if cmd in {"/login", "/key"}:
        response = client.send_command("/login", "refresh")
        if "error" in (response.get("status"), response.get("type")):
            from core.ui.console import console

            console.print(
                f"  [warning]Saved locally; daemon refresh failed: "
                f"{response.get('message')}[/warning]"
            )
        else:
            _render_daemon_result(response)


def _render_daemon_result(response: Mapping[str, object]) -> None:
    from rich.markup import escape
    from rich.text import Text

    from core.ui.console import console

    output = str(response.get("output") or "")
    if output:
        console.print(Text.from_ansi(output), end="")
    if "error" in (response.get("status"), response.get("type")):
        console.print(f"  [warning]{escape(str(response.get('message')))}[/warning]\n")
