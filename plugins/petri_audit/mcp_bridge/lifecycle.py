"""Per-``generate()`` lifecycle for the CSA-2 MCP bridge.

Owns the temp-file dance that hooks the claude CLI subprocess into our
in-process MCP bridge server. One :class:`BridgeInvocation` per call;
the provider invokes :func:`prepare_bridge` before spawning claude and
:func:`release_bridge` in the ``finally`` block.

Why a tempdir per call
======================

inspect_ai parallelises sample evaluation. Without per-call temp dirs,
concurrent ``generate()`` calls would race on the same
``tools.json`` / ``mcp_config.json`` paths. Each invocation gets its
own ``/tmp/geode-audit-bridge-<random>/`` so the bridge subprocesses
never see each other's tool schemas.

Why ``sys.executable`` for the bridge command
=============================================

The audit extra venv has ``mcp>=1.0.0`` installed; the operator's
system ``python`` does not. Pinning ``sys.executable`` ensures the
spawned bridge subprocess uses the same interpreter (and therefore the
same site-packages) as the parent, even if claude inherits a different
``PATH``.

Operator-visible env
====================

* ``GEODE_AUDIT_BRIDGE_KEEP_TEMP=1`` — skip cleanup so a failed run
  leaves the ``mcp_config.json`` / ``tools.json`` on disk for triage.
  Default is to clean up.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from inspect_ai.tool import ToolInfo

from plugins.petri_audit.mcp_bridge.bridge_server import (
    BRIDGE_SERVER_NAME,
    BRIDGE_TOOLS_ENV,
)
from plugins.petri_audit.mcp_bridge.tool_translator import (
    serialise_tool_infos_for_bridge,
)

log = logging.getLogger(__name__)

__all__ = [
    "BRIDGE_KEEP_TEMP_ENV",
    "BridgeInvocation",
    "allowed_tool_names",
    "build_mcp_config",
    "prepare_bridge",
    "release_bridge",
    "strip_mcp_prefix",
]


BRIDGE_KEEP_TEMP_ENV = "GEODE_AUDIT_BRIDGE_KEEP_TEMP"
"""Operator opt-in to leave the temp dir behind for triage."""

_TEMPDIR_PREFIX = "geode-audit-bridge-"
_TOOLS_FILENAME = "tools.json"
_MCP_CONFIG_FILENAME = "mcp_config.json"


@dataclass(frozen=True, slots=True)
class BridgeInvocation:
    """Per-call MCP bridge resources.

    Construct via :func:`prepare_bridge`. Pass ``mcp_config_json`` to
    :func:`plugins.petri_audit.claude_cli_provider.build_claude_cli_argv`
    as ``mcp_config_path``; pass ``allowed_tools`` as ``allowed_tools``.
    Always release in a ``finally``.
    """

    work_dir: Path
    """``tempfile.mkdtemp`` result. Owns the lifecycle of both files."""

    tools_json: Path
    """Serialised ``list[ToolSpec]`` consumed by the bridge subprocess
    via the ``GEODE_AUDIT_BRIDGE_TOOLS_JSON`` env."""

    mcp_config_json: Path
    """``--mcp-config`` payload — JSON of ``{"mcpServers": {...}}``."""

    allowed_tools: list[str]
    """``--allowed-tools`` whitelist — pre-prefixed with
    ``mcp__<server>__`` per claude CLI's MCP-tool naming convention."""


def allowed_tool_names(
    tool_names: list[str],
    *,
    server_name: str = BRIDGE_SERVER_NAME,
) -> list[str]:
    """Wrap each bare tool name in claude's MCP naming convention.

    Claude prefixes MCP tool names as ``mcp__<server>__<tool>`` —
    e.g. ``mcp__bridge__send_message``. The ``--allowed-tools``
    whitelist on the CLI side uses these decorated names. The parser
    on the response side strips them back via :func:`strip_mcp_prefix`.
    """
    return [f"mcp__{server_name}__{name}" for name in tool_names]


def strip_mcp_prefix(tool_name: str, *, server_name: str = BRIDGE_SERVER_NAME) -> str:
    """Inverse of :func:`allowed_tool_names` — for one name.

    ``mcp__bridge__send_message`` → ``send_message``.
    Non-prefixed names pass through unchanged.

    inspect_petri's tool dispatcher matches on the bare name; getting
    this wrong silently breaks every auditor run with "tool not found".
    """
    prefix = f"mcp__{server_name}__"
    if tool_name.startswith(prefix):
        return tool_name[len(prefix) :]
    return tool_name


def build_mcp_config(
    *,
    server_name: str,
    bridge_tools_json: Path,
    python_bin: str | None = None,
) -> dict[str, object]:
    """Construct the ``--mcp-config`` payload for the claude CLI.

    Shape::

        {"mcpServers": {"<server_name>": {
            "command": "<python_bin>",
            "args": ["-m", "plugins.petri_audit.mcp_bridge.bridge_server"],
            "env": {"GEODE_AUDIT_BRIDGE_TOOLS_JSON": "<bridge_tools_json>"}
        }}}

    The bridge subprocess inherits the parent's PATH + venv via
    ``sys.executable``; tool schemas reach it through the
    env-pointed file (NOT inline JSON, to dodge shell env-var size
    limits — see ``serialise_tool_infos_for_bridge``'s docstring).
    """
    binary = python_bin or sys.executable
    return {
        "mcpServers": {
            server_name: {
                "command": binary,
                "args": ["-m", "plugins.petri_audit.mcp_bridge.bridge_server"],
                "env": {BRIDGE_TOOLS_ENV: str(bridge_tools_json)},
            }
        }
    }


def prepare_bridge(
    tools: list[ToolInfo],
    *,
    base_tmp_dir: Path | None = None,
    python_bin: str | None = None,
    server_name: str = BRIDGE_SERVER_NAME,
) -> BridgeInvocation:
    """Materialise the bridge resources for one ``generate()`` call.

    Creates a unique tempdir, writes the tool schemas + MCP config
    files into it, and returns a :class:`BridgeInvocation` the caller
    passes to the provider's argv builder.

    The caller MUST invoke :func:`release_bridge` in a ``finally`` so
    parallel callers don't leak tempdirs.
    """
    work_dir = Path(
        tempfile.mkdtemp(prefix=_TEMPDIR_PREFIX, dir=str(base_tmp_dir) if base_tmp_dir else None)
    )

    tools_json = work_dir / _TOOLS_FILENAME
    tools_json.write_text(serialise_tool_infos_for_bridge(tools), encoding="utf-8")

    mcp_config_json = work_dir / _MCP_CONFIG_FILENAME
    payload = build_mcp_config(
        server_name=server_name,
        bridge_tools_json=tools_json,
        python_bin=python_bin,
    )
    mcp_config_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    bare_names = [tool.name for tool in tools]
    return BridgeInvocation(
        work_dir=work_dir,
        tools_json=tools_json,
        mcp_config_json=mcp_config_json,
        allowed_tools=allowed_tool_names(bare_names, server_name=server_name),
    )


def release_bridge(invocation: BridgeInvocation) -> None:
    """Best-effort cleanup of the bridge tempdir.

    Never raises — cleanup failures must not mask a real
    ``generate()`` error. Logs at WARNING so operators can spot leaks.

    Respects ``GEODE_AUDIT_BRIDGE_KEEP_TEMP=1`` for post-mortem triage.
    """
    if os.environ.get(BRIDGE_KEEP_TEMP_ENV) == "1":
        log.warning(
            "bridge tempdir preserved per %s=1: %s",
            BRIDGE_KEEP_TEMP_ENV,
            invocation.work_dir,
        )
        return
    try:
        shutil.rmtree(invocation.work_dir, ignore_errors=True)
    except Exception:  # pragma: no cover — ignore_errors=True already swallows
        log.warning("bridge tempdir cleanup failed: %s", invocation.work_dir, exc_info=True)
