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
    """Keep terminal collection and persistence in the caller process."""
    from core.cli.dispatcher import _handle_command

    if cmd == "/model":
        from core.cli.commands.model import cmd_model

        cmd_model(args, client=client)
        return
    _handle_command(cmd, args, False, command_registry=command_registry)
    if cmd in {"/login", "/key"}:
        response = client.send_command("/login", "refresh")
        if response.get("status") == "error":
            from core.ui.console import console

            console.print(
                f"  [warning]Saved locally; daemon refresh failed: "
                f"{response.get('message')}[/warning]"
            )
