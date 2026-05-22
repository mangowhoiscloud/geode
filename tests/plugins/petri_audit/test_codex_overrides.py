"""Tests for plugins.petri_audit.mcp_bridge.codex_overrides (CSA-2c)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from plugins.petri_audit.mcp_bridge.codex_overrides import (
    build_codex_cli_mcp_overrides,
    extract_codex_tool_calls,
)
from plugins.petri_audit.mcp_bridge.lifecycle import BridgeInvocation


def _make_invocation(
    tmp_path: Path, env: dict[str, str] | None = None, server_name: str = "bridge"
) -> BridgeInvocation:
    """Build a real BridgeInvocation by writing the same JSON file
    :func:`prepare_bridge` would produce — so codex_overrides reads the
    actual on-disk payload, not a synthetic dict. Mirrors
    :func:`plugins.petri_audit.mcp_bridge.lifecycle.build_mcp_config`.
    """
    work_dir = tmp_path / "audit-bridge-x"
    work_dir.mkdir()
    tools_json = work_dir / "tools.json"
    tools_json.write_text("[]", encoding="utf-8")
    invocation_env = env or {"GEODE_AUDIT_BRIDGE_TOOLS_JSON": str(tools_json)}
    payload = {
        "mcpServers": {
            server_name: {
                "command": "python",
                "args": ["-m", "plugins.petri_audit.mcp_bridge.bridge_server"],
                "env": invocation_env,
            }
        }
    }
    mcp_config_json = work_dir / "mcp-config.json"
    mcp_config_json.write_text(json.dumps(payload), encoding="utf-8")
    return BridgeInvocation(
        work_dir=work_dir,
        tools_json=tools_json,
        mcp_config_json=mcp_config_json,
        allowed_tools=["mcp__bridge__send_message"],
    )


def test_build_codex_cli_mcp_overrides_renders_command_and_args(tmp_path: Path) -> None:
    """The flat -c overrides must contain command + args entries that
    codex's TOML parser can decode back into the same structure that
    [mcp_servers.bridge] would carry in ~/.codex/config.toml."""
    tokens = build_codex_cli_mcp_overrides(_make_invocation(tmp_path))

    # Always pairs of (-c, key=value), no orphan flags.
    assert len(tokens) % 2 == 0
    assert tokens[::2] == ["-c"] * (len(tokens) // 2)

    # command + args + env entries — order is command, args, then envs.
    bodies = tokens[1::2]
    assert any(b.startswith("mcp_servers.bridge.command=") for b in bodies), bodies
    assert any(b.startswith("mcp_servers.bridge.args=") for b in bodies), bodies


def test_build_codex_cli_mcp_overrides_quotes_strings_as_toml(tmp_path: Path) -> None:
    """Codex parses each ``-c key=value`` value as TOML — strings must
    be JSON-quoted (which TOML also accepts as a string literal)."""
    tokens = build_codex_cli_mcp_overrides(_make_invocation(tmp_path))

    cmd_token = next(t for t in tokens if t.startswith("mcp_servers.bridge.command="))
    _, _, cmd_value = cmd_token.partition("=")
    assert json.loads(cmd_value) == "python", "command value must round-trip as a JSON string"

    args_token = next(t for t in tokens if t.startswith("mcp_servers.bridge.args="))
    _, _, args_value = args_token.partition("=")
    assert json.loads(args_value) == [
        "-m",
        "plugins.petri_audit.mcp_bridge.bridge_server",
    ]


def test_build_codex_cli_mcp_overrides_renders_each_env_key_separately(tmp_path: Path) -> None:
    """Each env var becomes its own dotted -c override so codex's TOML
    parser sees ``mcp_servers.bridge.env.<KEY> = "<VALUE>"`` for each
    key individually (no need to construct a nested dict literal)."""
    tokens = build_codex_cli_mcp_overrides(
        _make_invocation(tmp_path, env={"FOO_VAR": "sandbox://foo.json", "BAR_VAR": "1"})
    )

    bodies = tokens[1::2]
    env_keys = [b for b in bodies if b.startswith("mcp_servers.bridge.env.")]
    assert len(env_keys) == 2
    assert any("mcp_servers.bridge.env.FOO_VAR=" in k for k in env_keys)
    assert any("mcp_servers.bridge.env.BAR_VAR=" in k for k in env_keys)
    # Values stay JSON-quoted (TOML strings).
    foo_token = next(k for k in env_keys if "FOO_VAR" in k)
    _, _, foo_value = foo_token.partition("=")
    assert json.loads(foo_value) == "sandbox://foo.json"


def test_build_codex_cli_mcp_overrides_missing_bridge_key_raises(tmp_path: Path) -> None:
    """Invariant: the bridge server name is pinned to 'bridge'.
    If the lifecycle module ever changes the key, callers must refresh
    the override builder in lockstep — fail loud here so a silent
    rename doesn't quietly break codex tool-use audits."""
    bad_invocation = _make_invocation(tmp_path, server_name="renamed")

    with pytest.raises(ValueError, match="must contain 'bridge' key"):
        build_codex_cli_mcp_overrides(bad_invocation)


# ---------------------------------------------------------------------------
# extract_codex_tool_calls
# ---------------------------------------------------------------------------


def _function_call_event(
    name: str = "mcp__bridge__send_message",
    arguments: str = '{"text": "hello"}',
    call_id: str = "call_123",
) -> dict[str, Any]:
    return {
        "type": "item.completed",
        "item": {
            "type": "function_call",
            "name": name,
            "arguments": arguments,
            "call_id": call_id,
        },
    }


def test_extract_codex_tool_calls_strips_mcp_prefix() -> None:
    """inspect_petri's solver dispatches against the bare tool name
    (e.g. ``send_message``), not the MCP-prefixed wire form
    (``mcp__bridge__send_message``). Parity with the claude side."""
    calls = extract_codex_tool_calls([_function_call_event()])

    assert len(calls) == 1
    call = calls[0]
    function_name = call.function if hasattr(call, "function") else call["function"]
    assert function_name == "send_message", (
        "mcp__bridge__ prefix must be stripped before reaching inspect_petri"
    )


def test_extract_codex_tool_calls_parses_arguments_json() -> None:
    calls = extract_codex_tool_calls([_function_call_event(arguments='{"text": "hi", "n": 3}')])

    call = calls[0]
    arguments = call.arguments if hasattr(call, "arguments") else call["arguments"]
    assert arguments == {"text": "hi", "n": 3}


def test_extract_codex_tool_calls_surfaces_parse_error_on_bad_json() -> None:
    """Bad JSON in arguments → parse_error field set, arguments default
    to {}. Caller (inspect_petri's solver) decides what to do with the
    parse_error; we surface rather than raise so a single mal-formed
    tool call doesn't kill the whole audit."""
    calls = extract_codex_tool_calls([_function_call_event(arguments="{not json")])

    call = calls[0]
    parse_error = call.parse_error if hasattr(call, "parse_error") else call["parse_error"]
    arguments = call.arguments if hasattr(call, "arguments") else call["arguments"]
    assert parse_error is not None
    assert "JSON decode failed" in parse_error
    assert arguments == {}


def test_extract_codex_tool_calls_ignores_non_function_call_items() -> None:
    """The codex JSONL stream interleaves agent_message / thread / turn
    events — only function_call items become ToolCall entries."""
    calls = extract_codex_tool_calls(
        [
            {"type": "thread.started", "thread": {"thread_id": "T1"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}},
            _function_call_event(),
            {"type": "turn.completed"},
        ]
    )

    assert len(calls) == 1, "only the single function_call item should produce a tool call"


def test_extract_codex_tool_calls_empty_stream_returns_no_calls() -> None:
    """Text-only response → no tool calls → caller falls through to the
    regular stop_reason path."""
    calls = extract_codex_tool_calls(
        [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "no tools"}},
            {"type": "turn.completed"},
        ]
    )

    assert calls == []


def test_extract_codex_tool_calls_handles_multiple_calls_in_one_turn() -> None:
    """A single codex turn can emit multiple function_call items —
    inspect_petri's parallel-tools mode relies on every call being
    surfaced in order."""
    calls = extract_codex_tool_calls(
        [
            _function_call_event(name="mcp__bridge__send_message", call_id="c1"),
            _function_call_event(
                name="mcp__bridge__resume", arguments='{"session": "abc"}', call_id="c2"
            ),
        ]
    )

    assert len(calls) == 2
    names = [c.function if hasattr(c, "function") else c["function"] for c in calls]
    assert names == ["send_message", "resume"]
    ids = [c.id if hasattr(c, "id") else c["id"] for c in calls]
    assert ids == ["c1", "c2"]
