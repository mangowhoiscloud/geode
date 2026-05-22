"""CSA-1 — claude-cli provider invariants (text-only).

Mock-based tests covering:

* Binary resolution (env override / PATH lookup / not-found).
* Subprocess timeout env override.
* argv builder (flag presence + order + MCP integration deferred to CSA-2).
* Message serialiser (str / list / multi-turn).
* Stream-json parser (well-formed / malformed / empty).
* Text extraction (content_block_delta vs result fallback).
* Stop reason mapping (end_turn → stop, tool_use → tool_calls, etc.).
* Usage extraction.
* Subprocess runner (success / non-zero exit / timeout).
* Provider registration on inspect_ai modelapi registry.
* CSA-1 boundary: tools=[...] raises NotImplementedError (defers to CSA-2).

inspect_ai-dependent tests are gated on ``pytest.importorskip``.
Pure-helper tests (argv / serialiser / parser) run in any env.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def test_resolve_binary_via_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """``GEODE_CLAUDE_CLI_BIN`` env points at an executable."""
    from plugins.petri_audit.claude_cli_provider import (
        CLAUDE_CLI_BIN_ENV,
        _resolve_claude_binary,
    )

    fake = tmp_path / "fake-claude"
    fake.write_text("#!/bin/sh\necho ok\n")
    fake.chmod(0o755)
    monkeypatch.setenv(CLAUDE_CLI_BIN_ENV, str(fake))
    assert _resolve_claude_binary() == str(fake)


def test_resolve_binary_via_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no env override, falls back to ``shutil.which("claude")``."""
    from plugins.petri_audit.claude_cli_provider import (
        CLAUDE_CLI_BIN_ENV,
        _resolve_claude_binary,
    )

    monkeypatch.delenv(CLAUDE_CLI_BIN_ENV, raising=False)
    with patch("shutil.which", return_value="/fake/path/claude"):
        assert _resolve_claude_binary() == "/fake/path/claude"


def test_resolve_binary_env_invalid_path_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env points at nonexistent file → ClaudeCliInvocationError."""
    from plugins.petri_audit.claude_cli_provider import (
        CLAUDE_CLI_BIN_ENV,
        ClaudeCliInvocationError,
        _resolve_claude_binary,
    )

    monkeypatch.setenv(CLAUDE_CLI_BIN_ENV, "/nonexistent/binary")
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(ClaudeCliInvocationError, match="no executable"),
    ):
        _resolve_claude_binary()


def test_resolve_binary_not_on_path_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env + no PATH binary → ClaudeCliInvocationError."""
    from plugins.petri_audit.claude_cli_provider import (
        CLAUDE_CLI_BIN_ENV,
        ClaudeCliInvocationError,
        _resolve_claude_binary,
    )

    monkeypatch.delenv(CLAUDE_CLI_BIN_ENV, raising=False)
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(ClaudeCliInvocationError, match="not found on PATH"),
    ):
        _resolve_claude_binary()


def test_resolve_timeout_default() -> None:
    from plugins.petri_audit.claude_cli_provider import (
        CLAUDE_CLI_SUBPROCESS_TIMEOUT_S,
        _resolve_timeout_s,
    )

    # Without env, returns module default
    assert _resolve_timeout_s() == CLAUDE_CLI_SUBPROCESS_TIMEOUT_S


def test_resolve_timeout_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.petri_audit.claude_cli_provider import (
        CLAUDE_CLI_TIMEOUT_ENV,
        _resolve_timeout_s,
    )

    monkeypatch.setenv(CLAUDE_CLI_TIMEOUT_ENV, "1200")
    assert _resolve_timeout_s() == 1200.0


def test_resolve_timeout_env_garbage_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plugins.petri_audit.claude_cli_provider import (
        CLAUDE_CLI_SUBPROCESS_TIMEOUT_S,
        CLAUDE_CLI_TIMEOUT_ENV,
        _resolve_timeout_s,
    )

    monkeypatch.setenv(CLAUDE_CLI_TIMEOUT_ENV, "not-a-number")
    assert _resolve_timeout_s() == CLAUDE_CLI_SUBPROCESS_TIMEOUT_S


# ---------------------------------------------------------------------------
# argv builder
# ---------------------------------------------------------------------------


def test_argv_minimal_shape() -> None:
    from plugins.petri_audit.claude_cli_provider import build_claude_cli_argv

    argv = build_claude_cli_argv(
        binary="/usr/bin/claude",
        model_name="claude-opus-4-7",
    )
    assert argv[0] == "/usr/bin/claude"
    assert "--print" in argv
    assert argv[argv.index("--print") + 1] == "-"  # stdin marker
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "claude-opus-4-7"
    assert "--max-turns" in argv
    assert argv[argv.index("--max-turns") + 1] == "1"  # default — single turn


def test_argv_custom_max_turns() -> None:
    from plugins.petri_audit.claude_cli_provider import build_claude_cli_argv

    argv = build_claude_cli_argv(
        binary="/usr/bin/claude",
        model_name="claude-opus-4-7",
        max_turns=5,
    )
    assert argv[argv.index("--max-turns") + 1] == "5"


def test_argv_mcp_config_adds_strict_flag() -> None:
    """CSA-2 hook: passing mcp_config_path also sets --strict-mcp-config."""
    from plugins.petri_audit.claude_cli_provider import build_claude_cli_argv

    argv = build_claude_cli_argv(
        binary="/usr/bin/claude",
        model_name="claude-opus-4-7",
        mcp_config_path="/tmp/mcp.json",  # noqa: S108
    )
    assert "--mcp-config" in argv
    assert "/tmp/mcp.json" in argv  # noqa: S108
    assert "--strict-mcp-config" in argv


def test_argv_allowed_tools_joins_csv() -> None:
    from plugins.petri_audit.claude_cli_provider import build_claude_cli_argv

    argv = build_claude_cli_argv(
        binary="/usr/bin/claude",
        model_name="claude-opus-4-7",
        allowed_tools=["mcp__bridge__send_message", "mcp__bridge__recommend_termination"],
    )
    assert "--allowed-tools" in argv
    idx = argv.index("--allowed-tools")
    # CLI accepts space-or-comma — we use comma for safety
    assert "send_message" in argv[idx + 1]
    assert "recommend_termination" in argv[idx + 1]


def test_argv_extra_args_appended() -> None:
    from plugins.petri_audit.claude_cli_provider import build_claude_cli_argv

    argv = build_claude_cli_argv(
        binary="/usr/bin/claude",
        model_name="claude-opus-4-7",
        extra_args=["--reasoning-effort", "high"],
    )
    assert argv[-2:] == ["--reasoning-effort", "high"]


# ---------------------------------------------------------------------------
# Message serialiser
# ---------------------------------------------------------------------------


def test_serialise_single_user_message() -> None:
    from plugins.petri_audit.claude_cli_provider import serialise_messages_to_prompt

    msgs = [SimpleNamespace(role="user", content="Hello")]
    out = serialise_messages_to_prompt(msgs)
    assert "<<<USER>>>" in out
    assert "Hello" in out


def test_serialise_multi_turn_order_preserved() -> None:
    from plugins.petri_audit.claude_cli_provider import serialise_messages_to_prompt

    msgs = [
        SimpleNamespace(role="system", content="You are helpful."),
        SimpleNamespace(role="user", content="What is 2+2?"),
        SimpleNamespace(role="assistant", content="4"),
        SimpleNamespace(role="user", content="And 3+3?"),
    ]
    out = serialise_messages_to_prompt(msgs)
    # Order preserved
    sys_idx = out.index("<<<SYSTEM>>>")
    user1_idx = out.index("<<<USER>>>", sys_idx)
    assistant_idx = out.index("<<<ASSISTANT>>>", user1_idx)
    user2_idx = out.index("<<<USER>>>", assistant_idx)
    assert sys_idx < user1_idx < assistant_idx < user2_idx
    assert "What is 2+2?" in out
    assert "And 3+3?" in out


def test_serialise_content_blocks_extracts_text() -> None:
    """list-of-Content (with .text attr) shape — extract text from each block."""
    from plugins.petri_audit.claude_cli_provider import serialise_messages_to_prompt

    blocks = [
        SimpleNamespace(text="part1"),
        SimpleNamespace(text="part2"),
    ]
    msgs = [SimpleNamespace(role="user", content=blocks)]
    out = serialise_messages_to_prompt(msgs)
    assert "part1" in out
    assert "part2" in out


def test_serialise_unknown_role_uses_uppercase_sentinel() -> None:
    """Forward-compat — new role names get auto-sentinel."""
    from plugins.petri_audit.claude_cli_provider import serialise_messages_to_prompt

    msgs = [SimpleNamespace(role="auditor", content="hmm")]
    out = serialise_messages_to_prompt(msgs)
    assert "<<<AUDITOR>>>" in out


# ---------------------------------------------------------------------------
# Stream-json parser
# ---------------------------------------------------------------------------


def _make_stream_json(events: list[dict]) -> str:
    """Helper — serialise to claude CLI's per-line JSON format."""
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_parse_well_formed_events() -> None:
    from plugins.petri_audit.claude_cli_provider import parse_stream_json_events

    stdout = _make_stream_json(
        [
            {"type": "message_start", "message": {}},
            {"type": "content_block_start", "index": 0},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
            {"type": "message_stop"},
            {"type": "result", "result": "Hi"},
        ]
    )
    events = parse_stream_json_events(stdout)
    assert [e.type for e in events] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "message_stop",
        "result",
    ]


def test_parse_skips_malformed_lines() -> None:
    """Non-JSON lines (debug noise) silently dropped."""
    from plugins.petri_audit.claude_cli_provider import parse_stream_json_events

    stdout = '{"type": "ok", "x": 1}\nnot-json-debug\n{"type": "ok", "x": 2}\n'
    events = parse_stream_json_events(stdout)
    assert len(events) == 2
    assert all(e.type == "ok" for e in events)


def test_parse_empty_stdout_returns_empty_list() -> None:
    from plugins.petri_audit.claude_cli_provider import parse_stream_json_events

    assert parse_stream_json_events("") == []


def test_parse_skips_non_object_lines() -> None:
    """Top-level arrays / strings are valid JSON but not events — skip."""
    from plugins.petri_audit.claude_cli_provider import parse_stream_json_events

    stdout = '"just a string"\n[1, 2, 3]\n{"type": "ok"}\n'
    events = parse_stream_json_events(stdout)
    assert len(events) == 1
    assert events[0].type == "ok"


# ---------------------------------------------------------------------------
# Text + stop + usage extraction
# ---------------------------------------------------------------------------


def test_extract_text_from_content_block_deltas() -> None:
    from plugins.petri_audit.claude_cli_provider import (
        _extract_assistant_text,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " world"}},
        ]
    )
    events = parse_stream_json_events(stdout)
    assert _extract_assistant_text(events) == "Hello world"


def test_extract_text_result_fallback() -> None:
    """When no content_block_delta events, fall back to result.result."""
    from plugins.petri_audit.claude_cli_provider import (
        _extract_assistant_text,
        parse_stream_json_events,
    )

    stdout = _make_stream_json([{"type": "result", "result": "Just OK"}])
    events = parse_stream_json_events(stdout)
    assert _extract_assistant_text(events) == "Just OK"


def test_extract_stop_reason_end_turn_maps_to_stop() -> None:
    from plugins.petri_audit.claude_cli_provider import (
        _extract_stop_reason,
        parse_stream_json_events,
    )

    stdout = _make_stream_json([{"type": "message_delta", "delta": {"stop_reason": "end_turn"}}])
    assert _extract_stop_reason(parse_stream_json_events(stdout)) == "stop"


def test_extract_stop_reason_tool_use_maps_to_tool_calls() -> None:
    from plugins.petri_audit.claude_cli_provider import (
        _extract_stop_reason,
        parse_stream_json_events,
    )

    stdout = _make_stream_json([{"type": "message_delta", "delta": {"stop_reason": "tool_use"}}])
    assert _extract_stop_reason(parse_stream_json_events(stdout)) == "tool_calls"


def test_extract_stop_reason_max_tokens_preserved() -> None:
    from plugins.petri_audit.claude_cli_provider import (
        _extract_stop_reason,
        parse_stream_json_events,
    )

    stdout = _make_stream_json([{"type": "result", "stop_reason": "max_tokens"}])
    assert _extract_stop_reason(parse_stream_json_events(stdout)) == "max_tokens"


def test_extract_stop_reason_unknown_when_absent() -> None:
    from plugins.petri_audit.claude_cli_provider import (
        _extract_stop_reason,
        parse_stream_json_events,
    )

    stdout = _make_stream_json([{"type": "message_start"}])
    assert _extract_stop_reason(parse_stream_json_events(stdout)) == "unknown"


def test_extract_usage_from_result_event() -> None:
    from plugins.petri_audit.claude_cli_provider import (
        _extract_usage,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {
                "type": "result",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 300,
                },
            }
        ]
    )
    usage = _extract_usage(parse_stream_json_events(stdout))
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 50
    assert usage["cache_read_input_tokens"] == 200
    assert usage["cache_creation_input_tokens"] == 300


def test_extract_usage_zero_when_absent() -> None:
    from plugins.petri_audit.claude_cli_provider import (
        _extract_usage,
        parse_stream_json_events,
    )

    usage = _extract_usage(parse_stream_json_events("{}"))
    assert usage == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def test_subprocess_runner_success(tmp_path: Any) -> None:
    """End-to-end: fake binary echoes a fixture stream-json to stdout."""
    from plugins.petri_audit.claude_cli_provider import _run_claude_subprocess

    # Tiny fake "claude" that emits stream-json then exits 0
    fake = tmp_path / "fake-claude"
    fake.write_text(
        "#!/bin/sh\n"
        "cat <<EOF\n"
        '{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}\n'
        '{"type": "result", "result": "Hi", "stop_reason": "end_turn"}\n'
        "EOF\n"
    )
    fake.chmod(0o755)
    argv = [str(fake), "--print", "-"]
    stdout, stderr, rc = asyncio.run(_run_claude_subprocess(argv, "prompt", 10.0))
    assert rc == 0
    assert '"text_delta"' in stdout


def test_subprocess_runner_nonzero_exit(tmp_path: Any) -> None:
    """Non-zero exit returns the code; caller decides what to do."""
    from plugins.petri_audit.claude_cli_provider import _run_claude_subprocess

    fake = tmp_path / "fake-claude"
    fake.write_text("#!/bin/sh\necho err >&2\nexit 2\n")
    fake.chmod(0o755)
    stdout, stderr, rc = asyncio.run(_run_claude_subprocess([str(fake)], "", 10.0))
    assert rc == 2
    assert "err" in stderr


def test_subprocess_runner_timeout(tmp_path: Any) -> None:
    """Timeout → ClaudeCliInvocationError."""
    from plugins.petri_audit.claude_cli_provider import (
        ClaudeCliInvocationError,
        _run_claude_subprocess,
    )

    fake = tmp_path / "fake-claude"
    fake.write_text("#!/bin/sh\nsleep 10\n")
    fake.chmod(0o755)
    with pytest.raises(ClaudeCliInvocationError, match="timed out"):
        asyncio.run(_run_claude_subprocess([str(fake)], "", 0.5))


def test_subprocess_runner_binary_missing() -> None:
    """Spawn-time FileNotFoundError → ClaudeCliInvocationError."""
    from plugins.petri_audit.claude_cli_provider import (
        ClaudeCliInvocationError,
        _run_claude_subprocess,
    )

    with pytest.raises(ClaudeCliInvocationError, match="failed to spawn"):
        asyncio.run(_run_claude_subprocess(["/nonexistent/binary"], "", 10.0))


# ---------------------------------------------------------------------------
# Provider registration + generate() boundary
# ---------------------------------------------------------------------------


pytest.importorskip("inspect_ai")


@pytest.fixture(autouse=True)
def _register_provider_once() -> None:
    """Ensure register() has run (idempotent — modelapi registry tolerates
    re-registration on the same name)."""
    from plugins.petri_audit import claude_cli_provider as p

    if not hasattr(p, "ClaudeCliAPI"):
        p.register()


def test_provider_registers_modelapi() -> None:
    """register() exposes ClaudeCliAPI at module level."""
    from plugins.petri_audit import claude_cli_provider as p

    assert hasattr(p, "ClaudeCliAPI")


def test_generate_with_tools_raises_csa1_boundary(tmp_path: Any) -> None:
    """CSA-1 boundary — tools forces NotImplementedError (CSA-2 wires MCP)."""
    from plugins.petri_audit import claude_cli_provider as p

    fake = tmp_path / "fake-claude"
    fake.write_text("#!/bin/sh\necho ok\n")
    fake.chmod(0o755)
    with patch(
        "plugins.petri_audit.claude_cli_provider._resolve_claude_binary", return_value=str(fake)
    ):
        api = p.ClaudeCliAPI(model_name="claude-opus-4-7")
        with pytest.raises(NotImplementedError, match="MCP bridge"):
            asyncio.run(api.generate([], tools=["fake-tool"], tool_choice="auto", config=None))


def test_generate_text_only_round_trip(tmp_path: Any) -> None:
    """End-to-end: fake claude binary → provider → ModelOutput."""
    from inspect_ai.model._model_output import ModelOutput

    from plugins.petri_audit import claude_cli_provider as p

    fake = tmp_path / "fake-claude"
    # Emit a complete stream-json with text + usage
    fake.write_text(
        "#!/bin/sh\n"
        "cat <<EOF\n"
        '{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}\n'
        '{"type":"content_block_delta","delta":{"type":"text_delta","text":" world"}}\n'
        '{"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n'
        '{"type":"result","result":"Hello world","stop_reason":"end_turn",'
        '"usage":{"input_tokens":10,"output_tokens":2,'
        '"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}\n'
        "EOF\n"
    )
    fake.chmod(0o755)
    with patch(
        "plugins.petri_audit.claude_cli_provider._resolve_claude_binary", return_value=str(fake)
    ):
        api = p.ClaudeCliAPI(model_name="claude-opus-4-7")
        msgs = [SimpleNamespace(role="user", content="Say hello")]
        output = asyncio.run(api.generate(msgs, tools=[], tool_choice="auto", config=None))
    assert isinstance(output, ModelOutput)
    assert output.completion == "Hello world"
    assert output.usage is not None
    assert output.usage.input_tokens == 10
    assert output.usage.output_tokens == 2
    assert output.choices[0].stop_reason == "stop"


def test_generate_nonzero_exit_raises(tmp_path: Any) -> None:
    """Subprocess non-zero exit → ClaudeCliInvocationError surfaced."""
    from plugins.petri_audit import claude_cli_provider as p

    fake = tmp_path / "fake-claude"
    fake.write_text("#!/bin/sh\necho 'oops' >&2\nexit 1\n")
    fake.chmod(0o755)
    with patch(
        "plugins.petri_audit.claude_cli_provider._resolve_claude_binary", return_value=str(fake)
    ):
        api = p.ClaudeCliAPI(model_name="claude-opus-4-7")
        with pytest.raises(p.ClaudeCliInvocationError, match="exited 1"):
            asyncio.run(
                api.generate(
                    [SimpleNamespace(role="user", content="hi")],
                    tools=[],
                    tool_choice="auto",
                    config=None,
                )
            )


def test_generate_empty_stdout_raises(tmp_path: Any) -> None:
    """Empty stream-json output → ClaudeCliInvocationError."""
    from plugins.petri_audit import claude_cli_provider as p

    fake = tmp_path / "fake-claude"
    fake.write_text("#!/bin/sh\nexit 0\n")  # no stdout
    fake.chmod(0o755)
    with patch(
        "plugins.petri_audit.claude_cli_provider._resolve_claude_binary", return_value=str(fake)
    ):
        api = p.ClaudeCliAPI(model_name="claude-opus-4-7")
        with pytest.raises(p.ClaudeCliInvocationError, match="no stream-json"):
            asyncio.run(
                api.generate(
                    [SimpleNamespace(role="user", content="hi")],
                    tools=[],
                    tool_choice="auto",
                    config=None,
                )
            )
