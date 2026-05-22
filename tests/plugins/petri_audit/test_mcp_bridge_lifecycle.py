"""CSA-2 — lifecycle (prepare / release / mcp_config) invariants."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai", reason="audit extra required")


def _make_tool_info(name: str = "send_message") -> Any:
    from inspect_ai.tool import ToolInfo, ToolParams
    from inspect_ai.util._json import JSONSchema

    return ToolInfo(
        name=name,
        description=f"Tool {name}",
        parameters=ToolParams(
            properties={"body": JSONSchema(type="string")},
            required=["body"],
        ),
    )


# ---------------------------------------------------------------------------
# allowed_tool_names / strip_mcp_prefix round trip
# ---------------------------------------------------------------------------


def test_allowed_tool_names_prefixes_with_server() -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import allowed_tool_names

    out = allowed_tool_names(["send_message", "resume"], server_name="bridge")
    assert out == ["mcp__bridge__send_message", "mcp__bridge__resume"]


def test_strip_mcp_prefix_inverse() -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import allowed_tool_names, strip_mcp_prefix

    decorated = allowed_tool_names(["send_message"], server_name="bridge")
    assert [strip_mcp_prefix(d, server_name="bridge") for d in decorated] == ["send_message"]


def test_strip_mcp_prefix_passthrough_when_no_match() -> None:
    """Bare tool names (no MCP wrapping) should pass through unchanged.

    The auditor's tool dispatcher matches on the bare name; a stripper
    that mangles unrelated names would silently break passthrough
    consumers."""
    from plugins.petri_audit.mcp_bridge.lifecycle import strip_mcp_prefix

    assert strip_mcp_prefix("plain_tool", server_name="bridge") == "plain_tool"
    # Wrong server → passthrough (defensive)
    assert strip_mcp_prefix("mcp__other__send", server_name="bridge") == "mcp__other__send"


# ---------------------------------------------------------------------------
# build_mcp_config shape
# ---------------------------------------------------------------------------


def test_build_mcp_config_default_uses_sys_executable(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import build_mcp_config

    cfg = build_mcp_config(
        server_name="bridge",
        bridge_tools_json=tmp_path / "tools.json",
    )
    bridge = cfg["mcpServers"]["bridge"]  # type: ignore[index]
    assert bridge["command"] == sys.executable
    assert bridge["args"] == ["-m", "plugins.petri_audit.mcp_bridge.bridge_server"]
    assert bridge["env"]["GEODE_AUDIT_BRIDGE_TOOLS_JSON"] == str(tmp_path / "tools.json")


def test_build_mcp_config_python_bin_override(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import build_mcp_config

    cfg = build_mcp_config(
        server_name="bridge",
        bridge_tools_json=tmp_path / "tools.json",
        python_bin="/usr/bin/python3",
    )
    assert cfg["mcpServers"]["bridge"]["command"] == "/usr/bin/python3"  # type: ignore[index]


def test_build_mcp_config_custom_server_name(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import build_mcp_config

    cfg = build_mcp_config(
        server_name="alt",
        bridge_tools_json=tmp_path / "tools.json",
    )
    assert "alt" in cfg["mcpServers"]  # type: ignore[operator]
    assert "bridge" not in cfg["mcpServers"]  # type: ignore[operator]


# ---------------------------------------------------------------------------
# prepare_bridge / release_bridge
# ---------------------------------------------------------------------------


def test_prepare_bridge_creates_tempdir_with_two_files(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import prepare_bridge, release_bridge

    tools = [_make_tool_info(f"t_{i}") for i in range(3)]
    inv = prepare_bridge(tools, base_tmp_dir=tmp_path)
    try:
        assert inv.work_dir.exists()
        assert inv.work_dir.is_dir()
        assert inv.tools_json.is_file()
        assert inv.mcp_config_json.is_file()
        assert inv.allowed_tools == [
            "mcp__bridge__t_0",
            "mcp__bridge__t_1",
            "mcp__bridge__t_2",
        ]
    finally:
        release_bridge(inv)


def test_prepare_bridge_tools_json_round_trips(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import prepare_bridge, release_bridge
    from plugins.petri_audit.mcp_bridge.tool_translator import deserialise_tool_specs

    tools = [_make_tool_info("send_message")]
    inv = prepare_bridge(tools, base_tmp_dir=tmp_path)
    try:
        specs = deserialise_tool_specs(inv.tools_json.read_text(encoding="utf-8"))
        assert specs[0]["name"] == "send_message"
        assert "body" in specs[0]["inputSchema"]["properties"]
    finally:
        release_bridge(inv)


def test_prepare_bridge_mcp_config_points_at_tools_json(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import prepare_bridge, release_bridge

    inv = prepare_bridge([_make_tool_info()], base_tmp_dir=tmp_path)
    try:
        cfg = json.loads(inv.mcp_config_json.read_text(encoding="utf-8"))
        env_path = cfg["mcpServers"]["bridge"]["env"]["GEODE_AUDIT_BRIDGE_TOOLS_JSON"]
        assert Path(env_path) == inv.tools_json
    finally:
        release_bridge(inv)


def test_prepare_bridge_each_call_isolates_to_own_dir(tmp_path: Path) -> None:
    """Parallel inspect_ai samples must not race on shared paths."""
    from plugins.petri_audit.mcp_bridge.lifecycle import prepare_bridge, release_bridge

    inv_a = prepare_bridge([_make_tool_info()], base_tmp_dir=tmp_path)
    inv_b = prepare_bridge([_make_tool_info()], base_tmp_dir=tmp_path)
    try:
        assert inv_a.work_dir != inv_b.work_dir
        assert inv_a.tools_json != inv_b.tools_json
    finally:
        release_bridge(inv_a)
        release_bridge(inv_b)


def test_release_bridge_removes_tempdir(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import prepare_bridge, release_bridge

    inv = prepare_bridge([_make_tool_info()], base_tmp_dir=tmp_path)
    assert inv.work_dir.exists()
    release_bridge(inv)
    assert not inv.work_dir.exists()


def test_release_bridge_tolerates_already_removed(tmp_path: Path) -> None:
    """Double-release must not raise — defensive for finally-block re-entry."""
    import shutil

    from plugins.petri_audit.mcp_bridge.lifecycle import prepare_bridge, release_bridge

    inv = prepare_bridge([_make_tool_info()], base_tmp_dir=tmp_path)
    shutil.rmtree(inv.work_dir, ignore_errors=True)
    # No raise expected.
    release_bridge(inv)


def test_release_bridge_keep_temp_env_preserves_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import (
        BRIDGE_KEEP_TEMP_ENV,
        prepare_bridge,
        release_bridge,
    )

    monkeypatch.setenv(BRIDGE_KEEP_TEMP_ENV, "1")
    inv = prepare_bridge([_make_tool_info()], base_tmp_dir=tmp_path)
    try:
        release_bridge(inv)
        assert inv.work_dir.exists(), "GEODE_AUDIT_BRIDGE_KEEP_TEMP=1 should leave the tempdir"
    finally:
        monkeypatch.delenv(BRIDGE_KEEP_TEMP_ENV, raising=False)
        # Manual cleanup since release was a no-op
        import shutil

        shutil.rmtree(inv.work_dir, ignore_errors=True)


def test_prepare_bridge_empty_tool_list(tmp_path: Path) -> None:
    """Edge case — empty tools is technically valid (text-only path
    should NOT reach here, but defensive coding catches misroutes)."""
    from plugins.petri_audit.mcp_bridge.lifecycle import prepare_bridge, release_bridge

    inv = prepare_bridge([], base_tmp_dir=tmp_path)
    try:
        assert inv.allowed_tools == []
        specs = json.loads(inv.tools_json.read_text(encoding="utf-8"))
        assert specs == []
    finally:
        release_bridge(inv)


def test_prepare_bridge_default_tmpdir_when_none(tmp_path: Path) -> None:
    """When base_tmp_dir is None, prepare_bridge uses the system tempdir."""
    from plugins.petri_audit.mcp_bridge.lifecycle import prepare_bridge, release_bridge

    inv = prepare_bridge([_make_tool_info()])
    try:
        # The path should land under the system tempdir, not under tmp_path
        assert not str(inv.work_dir).startswith(str(tmp_path))
        # And the prefix matches
        assert inv.work_dir.name.startswith("geode-audit-bridge-")
    finally:
        release_bridge(inv)


def test_prepare_bridge_unicode_tool_names(tmp_path: Path) -> None:
    from plugins.petri_audit.mcp_bridge.lifecycle import prepare_bridge, release_bridge

    inv = prepare_bridge([_make_tool_info("시작")], base_tmp_dir=tmp_path)
    try:
        # The decorated names also preserve unicode
        assert inv.allowed_tools == ["mcp__bridge__시작"]
        contents = inv.tools_json.read_text(encoding="utf-8")
        assert "시작" in contents
    finally:
        release_bridge(inv)


def test_lifecycle_does_not_leak_files_on_environ_cleared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity — KEEP_TEMP unset (the default) cleans up."""
    monkeypatch.delenv("GEODE_AUDIT_BRIDGE_KEEP_TEMP", raising=False)
    assert "GEODE_AUDIT_BRIDGE_KEEP_TEMP" not in os.environ

    from plugins.petri_audit.mcp_bridge.lifecycle import prepare_bridge, release_bridge

    inv = prepare_bridge([_make_tool_info()], base_tmp_dir=tmp_path)
    release_bridge(inv)
    assert not inv.work_dir.exists()
