"""CSA-2 — bridge_server (stdio MCP server) invariants.

Drive the server in-process via mcp.shared.memory's bidirectional
pipe — avoids needing a real subprocess + the system claude CLI.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="audit extra required for bridge_server tests")


# ---------------------------------------------------------------------------
# pure helpers — no MCP wire
# ---------------------------------------------------------------------------


def test_read_tool_specs_round_trips(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.bridge_server import _read_tool_specs

    specs = [{"name": "x", "description": "x", "inputSchema": {"type": "object"}}]
    p = tmp_path / "tools.json"
    p.write_text(json.dumps(specs), encoding="utf-8")
    assert _read_tool_specs(str(p)) == specs


def test_read_tool_specs_missing_file_raises(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.bridge_server import _read_tool_specs

    with pytest.raises(ValueError, match="does not exist"):
        _read_tool_specs(str(tmp_path / "nope.json"))


def test_read_tool_specs_malformed_raises(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.bridge_server import _read_tool_specs

    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        _read_tool_specs(str(p))


# ---------------------------------------------------------------------------
# in-process drive via mcp.shared.memory
# ---------------------------------------------------------------------------


def _drive_server_in_process(specs: list[dict[str, Any]]) -> dict[str, Any]:
    """Spin up the bridge server in a task, talk to it via the in-memory
    bidirectional pipe, return (tools_list, tool_call_result).

    We replicate the inline parts of _serve() rather than refactoring
    the production code just for testability — keeps the server's
    happy path concise.
    """
    from mcp.server import Server
    from mcp.shared.memory import create_connected_server_and_client_session

    from mcp import types as mcp_types

    server: Server = Server("bridge")

    @server.list_tools()  # type: ignore[no-untyped-call, misc, unused-ignore]
    async def _list() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=spec["name"],
                description=spec["description"],
                inputSchema=spec["inputSchema"],
            )
            for spec in specs
        ]

    @server.call_tool()  # type: ignore[no-untyped-call, misc, unused-ignore]
    async def _call(name: str, arguments: dict[str, Any]) -> list[mcp_types.TextContent]:
        return [
            mcp_types.TextContent(
                type="text",
                text=json.dumps({"_bridge_no_exec": True, "tool": name, "arguments": arguments}),
            )
        ]

    async def _run() -> dict[str, Any]:
        async with create_connected_server_and_client_session(server) as client:
            await client.initialize()
            tools_list = await client.list_tools()
            call_result = await client.call_tool(
                specs[0]["name"], arguments={"x": "y"} if specs else None
            )
            return {"tools_list": tools_list, "call_result": call_result}

    return asyncio.run(_run())


def test_server_list_tools_returns_configured_set() -> None:
    specs = [
        {"name": "alpha", "description": "first", "inputSchema": {"type": "object"}},
        {"name": "beta", "description": "second", "inputSchema": {"type": "object"}},
    ]
    out = _drive_server_in_process(specs)
    names = [t.name for t in out["tools_list"].tools]
    assert names == ["alpha", "beta"]


def test_server_call_tool_returns_no_exec_sentinel() -> None:
    specs = [{"name": "alpha", "description": "first", "inputSchema": {"type": "object"}}]
    out = _drive_server_in_process(specs)
    text_content = out["call_result"].content[0]
    payload = json.loads(text_content.text)
    assert payload["_bridge_no_exec"] is True
    assert payload["tool"] == "alpha"


# ---------------------------------------------------------------------------
# main() — subprocess-level smoke for env / exit-code paths
# ---------------------------------------------------------------------------


def _module_invocation() -> list[str]:
    return [sys.executable, "-m", "plugins.petri_audit.mcp_bridge.bridge_server"]


def test_main_missing_env_exits_2(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("GEODE_AUDIT_BRIDGE_TOOLS_JSON", None)
    proc = subprocess.run(  # noqa: S603 — pinned argv via sys.executable
        _module_invocation(),
        env=env,
        capture_output=True,
        timeout=10,
        cwd=str(tmp_path),
        check=False,
    )
    assert proc.returncode == 2
    assert b"missing env GEODE_AUDIT_BRIDGE_TOOLS_JSON" in proc.stderr


def test_main_invalid_tools_path_exits_2(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["GEODE_AUDIT_BRIDGE_TOOLS_JSON"] = str(tmp_path / "does-not-exist.json")
    proc = subprocess.run(  # noqa: S603 — pinned argv via sys.executable
        _module_invocation(),
        env=env,
        capture_output=True,
        timeout=10,
        cwd=str(tmp_path),
        check=False,
    )
    assert proc.returncode == 2
    assert b"could not load tool specs" in proc.stderr


def test_main_malformed_tools_json_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    env = os.environ.copy()
    env["GEODE_AUDIT_BRIDGE_TOOLS_JSON"] = str(bad)
    proc = subprocess.run(  # noqa: S603 — pinned argv via sys.executable
        _module_invocation(),
        env=env,
        capture_output=True,
        timeout=10,
        cwd=str(tmp_path),
        check=False,
    )
    assert proc.returncode == 2


def test_constants_match_documented_contract() -> None:
    """The lifecycle + provider layers reference these constants — keep
    them stable to avoid silent rename drift."""
    from plugins.petri_audit.mcp_bridge.bridge_server import (
        BRIDGE_SERVER_NAME,
        BRIDGE_TOOLS_ENV,
    )

    assert BRIDGE_SERVER_NAME == "bridge"
    assert BRIDGE_TOOLS_ENV == "GEODE_AUDIT_BRIDGE_TOOLS_JSON"
