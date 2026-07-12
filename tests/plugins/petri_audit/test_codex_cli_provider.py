"""CSA-1b — codex-cli provider invariants (text-only).

Mock-based tests covering the codex side of the paperclip-pattern
adapter. Mirror of ``test_claude_cli_provider.py`` with codex-specific
event shapes (``thread.started`` / ``item.completed`` / ``turn.completed``
/ ``turn.failed``) and argv (``codex exec --json``).

inspect_ai-dependent tests gated on ``pytest.importorskip``.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_mock_cli_from_live_oauth_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.llm.codex_oauth_usage import CODEX_OAUTH_POLL_DISABLED_ENV

    monkeypatch.setenv(CODEX_OAUTH_POLL_DISABLED_ENV, "1")


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def test_resolve_binary_via_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from plugins.petri_audit.codex_cli_provider import (
        CODEX_CLI_BIN_ENV,
        _resolve_codex_binary,
    )

    fake = tmp_path / "fake-codex"
    fake.write_text("#!/bin/sh\necho ok\n")
    fake.chmod(0o755)
    monkeypatch.setenv(CODEX_CLI_BIN_ENV, str(fake))
    assert _resolve_codex_binary() == str(fake)


def test_resolve_binary_via_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.petri_audit.codex_cli_provider import (
        CODEX_CLI_BIN_ENV,
        _resolve_codex_binary,
    )

    monkeypatch.delenv(CODEX_CLI_BIN_ENV, raising=False)
    with patch("shutil.which", return_value="/fake/codex"):
        assert _resolve_codex_binary() == "/fake/codex"


def test_resolve_binary_env_invalid_path_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plugins.petri_audit.codex_cli_provider import (
        CODEX_CLI_BIN_ENV,
        CodexCliInvocationError,
        _resolve_codex_binary,
    )

    monkeypatch.setenv(CODEX_CLI_BIN_ENV, "/nonexistent")
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(CodexCliInvocationError, match="no executable"),
    ):
        _resolve_codex_binary()


def test_resolve_binary_not_on_path_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.petri_audit.codex_cli_provider import (
        CODEX_CLI_BIN_ENV,
        CodexCliInvocationError,
        _resolve_codex_binary,
    )

    monkeypatch.delenv(CODEX_CLI_BIN_ENV, raising=False)
    with (
        patch("shutil.which", return_value=None),
        pytest.raises(CodexCliInvocationError, match="not found on PATH"),
    ):
        _resolve_codex_binary()


def test_resolve_timeout_default() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        CODEX_CLI_SUBPROCESS_TIMEOUT_S,
        _resolve_timeout_s,
    )

    assert _resolve_timeout_s() == CODEX_CLI_SUBPROCESS_TIMEOUT_S


def test_resolve_timeout_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.petri_audit.codex_cli_provider import (
        CODEX_CLI_TIMEOUT_ENV,
        _resolve_timeout_s,
    )

    monkeypatch.setenv(CODEX_CLI_TIMEOUT_ENV, "1500")
    assert _resolve_timeout_s() == 1500.0


def test_resolve_timeout_env_garbage_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plugins.petri_audit.codex_cli_provider import (
        CODEX_CLI_SUBPROCESS_TIMEOUT_S,
        CODEX_CLI_TIMEOUT_ENV,
        _resolve_timeout_s,
    )

    monkeypatch.setenv(CODEX_CLI_TIMEOUT_ENV, "garbage")
    assert _resolve_timeout_s() == CODEX_CLI_SUBPROCESS_TIMEOUT_S


# ---------------------------------------------------------------------------
# argv builder
# ---------------------------------------------------------------------------


def test_argv_minimal_shape() -> None:
    from plugins.petri_audit.codex_cli_provider import build_codex_cli_argv

    argv = build_codex_cli_argv(binary="/usr/bin/codex", model_name="gpt-5.5")
    assert argv[0] == "/usr/bin/codex"
    assert "exec" in argv
    assert "--json" in argv
    assert "--skip-git-repo-check" in argv  # default True
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "gpt-5.5"
    assert argv[-1] == "-"  # stdin marker last


def test_argv_skip_git_repo_check_can_disable() -> None:
    from plugins.petri_audit.codex_cli_provider import build_codex_cli_argv

    argv = build_codex_cli_argv(
        binary="/usr/bin/codex",
        model_name="gpt-5.5",
        skip_git_repo_check=False,
    )
    assert "--skip-git-repo-check" not in argv


def test_argv_bypass_sandbox_adds_flag() -> None:
    from plugins.petri_audit.codex_cli_provider import build_codex_cli_argv

    argv = build_codex_cli_argv(
        binary="/usr/bin/codex",
        model_name="gpt-5.5",
        bypass_sandbox=True,
    )
    assert "--dangerously-bypass-approvals-and-sandbox" in argv


def test_argv_resume_session_uses_subcommand_form() -> None:
    """``codex exec resume <id> -`` — paperclip pattern (codex-args.ts:65)."""
    from plugins.petri_audit.codex_cli_provider import build_codex_cli_argv

    argv = build_codex_cli_argv(
        binary="/usr/bin/codex",
        model_name="gpt-5.5",
        resume_session_id="abc123",
    )
    # `resume abc123` must appear after `--json` (subcommand position)
    json_idx = argv.index("--json")
    assert "resume" in argv[json_idx:]
    resume_idx = argv.index("resume", json_idx)
    assert argv[resume_idx + 1] == "abc123"
    assert argv[-1] == "-"


def test_argv_reasoning_effort_emits_config_override() -> None:
    from plugins.petri_audit.codex_cli_provider import build_codex_cli_argv

    argv = build_codex_cli_argv(
        binary="/usr/bin/codex",
        model_name="gpt-5.5",
        reasoning_effort="high",
    )
    assert "-c" in argv
    # The value is JSON-encoded so "high" → `"high"`
    overrides = [a for a in argv if "model_reasoning_effort" in a]
    assert overrides
    assert '"high"' in overrides[0]


def test_argv_extra_args_appended_before_stdin_marker() -> None:
    from plugins.petri_audit.codex_cli_provider import build_codex_cli_argv

    argv = build_codex_cli_argv(
        binary="/usr/bin/codex",
        model_name="gpt-5.5",
        extra_args=["--enable", "fast_mode"],
    )
    assert "--enable" in argv
    assert "fast_mode" in argv
    # `-` should still be last
    assert argv[-1] == "-"


# ---------------------------------------------------------------------------
# Message serialiser (parity with CSA-1)
# ---------------------------------------------------------------------------


def test_serialise_single_user_message() -> None:
    from plugins.petri_audit.codex_cli_provider import serialise_messages_to_prompt

    msgs = [SimpleNamespace(role="user", content="Hello")]
    out = serialise_messages_to_prompt(msgs)
    assert "<<<USER>>>" in out
    assert "Hello" in out


def test_serialise_multi_turn_preserves_order() -> None:
    from plugins.petri_audit.codex_cli_provider import serialise_messages_to_prompt

    msgs = [
        SimpleNamespace(role="system", content="be brief"),
        SimpleNamespace(role="user", content="hi"),
        SimpleNamespace(role="assistant", content="hello"),
    ]
    out = serialise_messages_to_prompt(msgs)
    assert out.index("<<<SYSTEM>>>") < out.index("<<<USER>>>") < out.index("<<<ASSISTANT>>>")


def test_serialise_content_blocks_extract_text() -> None:
    from plugins.petri_audit.codex_cli_provider import serialise_messages_to_prompt

    blocks = [SimpleNamespace(text="a"), SimpleNamespace(text="b")]
    msgs = [SimpleNamespace(role="user", content=blocks)]
    out = serialise_messages_to_prompt(msgs)
    assert "a" in out
    assert "b" in out


# ---------------------------------------------------------------------------
# Codex JSONL parser
# ---------------------------------------------------------------------------


def _make_jsonl(events: list[dict]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_parse_well_formed_events() -> None:
    from plugins.petri_audit.codex_cli_provider import parse_codex_jsonl_events

    stdout = _make_jsonl(
        [
            {"type": "thread.started", "thread_id": "t_abc"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}},
            {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 2}},
        ]
    )
    events = parse_codex_jsonl_events(stdout)
    assert [e.type for e in events] == [
        "thread.started",
        "item.completed",
        "turn.completed",
    ]


def test_parse_skips_malformed_lines() -> None:
    from plugins.petri_audit.codex_cli_provider import parse_codex_jsonl_events

    stdout = '{"type": "ok", "x": 1}\njunk-debug-line\n{"type": "ok", "x": 2}\n'
    events = parse_codex_jsonl_events(stdout)
    assert len(events) == 2


def test_parse_empty_returns_empty_list() -> None:
    from plugins.petri_audit.codex_cli_provider import parse_codex_jsonl_events

    assert parse_codex_jsonl_events("") == []


# ---------------------------------------------------------------------------
# Event extractors
# ---------------------------------------------------------------------------


def test_extract_agent_message_single_completion() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_agent_message,
        parse_codex_jsonl_events,
    )

    stdout = _make_jsonl(
        [{"type": "item.completed", "item": {"type": "agent_message", "text": "result"}}]
    )
    assert _extract_agent_message(parse_codex_jsonl_events(stdout)) == "result"


def test_extract_agent_message_concatenates_multiple() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_agent_message,
        parse_codex_jsonl_events,
    )

    stdout = _make_jsonl(
        [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "part1"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "part2"}},
        ]
    )
    out = _extract_agent_message(parse_codex_jsonl_events(stdout))
    assert "part1" in out and "part2" in out


def test_extract_agent_message_ignores_non_agent_items() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_agent_message,
        parse_codex_jsonl_events,
    )

    stdout = _make_jsonl(
        [
            {"type": "item.completed", "item": {"type": "tool_call", "text": "ignored"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "kept"}},
        ]
    )
    assert _extract_agent_message(parse_codex_jsonl_events(stdout)) == "kept"


def test_extract_session_id_from_thread_started() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_session_id,
        parse_codex_jsonl_events,
    )

    stdout = _make_jsonl([{"type": "thread.started", "thread_id": "t_xyz"}])
    assert _extract_session_id(parse_codex_jsonl_events(stdout)) == "t_xyz"


def test_extract_session_id_none_when_absent() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_session_id,
        parse_codex_jsonl_events,
    )

    assert _extract_session_id(parse_codex_jsonl_events("{}\n")) is None


def test_extract_stop_reason_turn_completed_maps_to_stop() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_stop_reason,
        parse_codex_jsonl_events,
    )

    stdout = _make_jsonl([{"type": "turn.completed", "usage": {}}])
    assert _extract_stop_reason(parse_codex_jsonl_events(stdout)) == "stop"


def test_extract_stop_reason_turn_failed_maps_to_stop() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_stop_reason,
        parse_codex_jsonl_events,
    )

    stdout = _make_jsonl([{"type": "turn.failed", "error": {"message": "boom"}}])
    assert _extract_stop_reason(parse_codex_jsonl_events(stdout)) == "stop"


def test_extract_stop_reason_unknown_when_absent() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_stop_reason,
        parse_codex_jsonl_events,
    )

    assert _extract_stop_reason(parse_codex_jsonl_events("{}\n")) == "unknown"


def test_extract_usage_from_turn_completed() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_usage,
        parse_codex_jsonl_events,
    )

    stdout = _make_jsonl(
        [
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cached_input_tokens": 200,
                },
            }
        ]
    )
    usage = _extract_usage(parse_codex_jsonl_events(stdout))
    assert usage == {
        "input_tokens": 100,
        "output_tokens": 50,
        "cached_input_tokens": 200,
    }


def test_extract_usage_zero_when_absent() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_usage,
        parse_codex_jsonl_events,
    )

    assert _extract_usage(parse_codex_jsonl_events("{}\n")) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
    }


def test_extract_error_from_error_event() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_error,
        parse_codex_jsonl_events,
    )

    stdout = _make_jsonl([{"type": "error", "message": "rate limit"}])
    assert _extract_error(parse_codex_jsonl_events(stdout)) == "rate limit"


def test_extract_error_from_turn_failed_event() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_error,
        parse_codex_jsonl_events,
    )

    stdout = _make_jsonl([{"type": "turn.failed", "error": {"message": "model unavailable"}}])
    assert _extract_error(parse_codex_jsonl_events(stdout)) == "model unavailable"


def test_extract_error_none_when_success() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        _extract_error,
        parse_codex_jsonl_events,
    )

    stdout = _make_jsonl([{"type": "turn.completed", "usage": {}}])
    assert _extract_error(parse_codex_jsonl_events(stdout)) is None


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def test_subprocess_runner_success(tmp_path: Any) -> None:
    from plugins.petri_audit.codex_cli_provider import _run_codex_subprocess

    fake = tmp_path / "fake-codex"
    fake.write_text(
        "#!/bin/sh\n"
        "cat <<EOF\n"
        '{"type":"thread.started","thread_id":"t_test"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"Hi"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":1,"cached_input_tokens":0}}\n'
        "EOF\n"
    )
    fake.chmod(0o755)
    stdout, _stderr, rc = asyncio.run(_run_codex_subprocess([str(fake)], "prompt", 10.0))
    assert rc == 0
    assert "thread.started" in stdout


def test_subprocess_runner_nonzero_exit(tmp_path: Any) -> None:
    from plugins.petri_audit.codex_cli_provider import _run_codex_subprocess

    fake = tmp_path / "fake-codex"
    fake.write_text("#!/bin/sh\necho err >&2\nexit 3\n")
    fake.chmod(0o755)
    _stdout, stderr, rc = asyncio.run(_run_codex_subprocess([str(fake)], "", 10.0))
    assert rc == 3
    assert "err" in stderr


def test_subprocess_runner_timeout(tmp_path: Any) -> None:
    from plugins.petri_audit.codex_cli_provider import (
        CodexCliInvocationError,
        _run_codex_subprocess,
    )

    fake = tmp_path / "fake-codex"
    fake.write_text("#!/bin/sh\nsleep 10\n")
    fake.chmod(0o755)
    with pytest.raises(CodexCliInvocationError, match="timed out"):
        asyncio.run(_run_codex_subprocess([str(fake)], "", 0.5))


def test_subprocess_runner_binary_missing() -> None:
    from plugins.petri_audit.codex_cli_provider import (
        CodexCliInvocationError,
        _run_codex_subprocess,
    )

    with pytest.raises(CodexCliInvocationError, match="failed to spawn"):
        asyncio.run(_run_codex_subprocess(["/nonexistent"], "", 10.0))


# ---------------------------------------------------------------------------
# Provider registration + boundary
# ---------------------------------------------------------------------------


pytest.importorskip("inspect_ai")


@pytest.fixture(autouse=True)
def _register_provider_once() -> None:
    from plugins.petri_audit import codex_cli_provider as p

    if not hasattr(p, "CodexCliAPI"):
        p.register()


def test_provider_registers_modelapi() -> None:
    from plugins.petri_audit import codex_cli_provider as p

    assert hasattr(p, "CodexCliAPI")


def test_generate_with_tools_dispatches_to_tools_path(tmp_path: Any) -> None:
    """CSA-2c (2026-05-22) — the CSA-1b boundary
    (``NotImplementedError("tool_use deferred to CSA-2b MCP bridge")``)
    was lifted. ``generate()`` with a non-empty ``tools`` argument now
    routes through ``_generate_with_tools`` which calls into the MCP
    bridge. Pin the routing: mock ``_generate_with_tools`` and confirm
    it is what gets called when tools are present. The bridge internals
    have their own contract tests in ``test_codex_overrides.py``."""
    pytest.importorskip("inspect_ai")
    from plugins.petri_audit import codex_cli_provider as p

    fake = tmp_path / "fake-codex"
    fake.write_text("#!/bin/sh\necho ok\n")
    fake.chmod(0o755)

    async def _fake_with_tools(_inp: Any, _tools: Any) -> str:
        return "sentinel-tools"

    with patch(
        "plugins.petri_audit.codex_cli_provider._resolve_codex_binary",
        return_value=str(fake),
    ):
        api = p.CodexCliAPI(model_name="gpt-5.5")
        with patch.object(api, "_generate_with_tools", side_effect=_fake_with_tools) as mocked:
            result = asyncio.run(api.generate([], tools=["t"], tool_choice="auto", config=None))
        assert result == "sentinel-tools"
        mocked.assert_called_once()


def test_generate_text_only_round_trip(tmp_path: Any) -> None:
    from inspect_ai.model._model_output import ModelOutput
    from plugins.petri_audit import codex_cli_provider as p

    fake = tmp_path / "fake-codex"
    fake.write_text(
        "#!/bin/sh\n"
        "cat <<EOF\n"
        '{"type":"thread.started","thread_id":"t_test"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"Hello"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2,"cached_input_tokens":5}}\n'
        "EOF\n"
    )
    fake.chmod(0o755)
    with patch(
        "plugins.petri_audit.codex_cli_provider._resolve_codex_binary",
        return_value=str(fake),
    ):
        api = p.CodexCliAPI(model_name="gpt-5.5")
        msgs = [SimpleNamespace(role="user", content="hi")]
        output = asyncio.run(api.generate(msgs, tools=[], tool_choice="auto", config=None))
    assert isinstance(output, ModelOutput)
    assert output.completion == "Hello"
    assert output.usage is not None
    assert output.usage.input_tokens == 10
    assert output.usage.output_tokens == 2
    assert output.usage.input_tokens_cache_read == 5
    assert output.choices[0].stop_reason == "stop"


def test_generate_nonzero_exit_raises(tmp_path: Any) -> None:
    from plugins.petri_audit import codex_cli_provider as p

    fake = tmp_path / "fake-codex"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    with patch(
        "plugins.petri_audit.codex_cli_provider._resolve_codex_binary",
        return_value=str(fake),
    ):
        api = p.CodexCliAPI(model_name="gpt-5.5")
        with pytest.raises(p.CodexCliInvocationError, match="exited 1"):
            asyncio.run(
                api.generate(
                    [SimpleNamespace(role="user", content="hi")],
                    tools=[],
                    tool_choice="auto",
                    config=None,
                )
            )


def test_generate_empty_stdout_raises(tmp_path: Any) -> None:
    from plugins.petri_audit import codex_cli_provider as p

    fake = tmp_path / "fake-codex"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    with patch(
        "plugins.petri_audit.codex_cli_provider._resolve_codex_binary",
        return_value=str(fake),
    ):
        api = p.CodexCliAPI(model_name="gpt-5.5")
        with pytest.raises(p.CodexCliInvocationError, match="no JSONL"):
            asyncio.run(
                api.generate(
                    [SimpleNamespace(role="user", content="hi")],
                    tools=[],
                    tool_choice="auto",
                    config=None,
                )
            )


def test_generate_surfaces_error_event_in_model_output(tmp_path: Any) -> None:
    """When codex emits an error event but exits 0, surface error string
    via ModelOutput.error so inspect_ai can render it."""
    from plugins.petri_audit import codex_cli_provider as p

    fake = tmp_path / "fake-codex"
    fake.write_text(
        "#!/bin/sh\n"
        "cat <<EOF\n"
        '{"type":"thread.started","thread_id":"t"}\n'
        '{"type":"error","message":"upstream timeout"}\n'
        '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":0,"cached_input_tokens":0}}\n'
        "EOF\n"
    )
    fake.chmod(0o755)
    with patch(
        "plugins.petri_audit.codex_cli_provider._resolve_codex_binary",
        return_value=str(fake),
    ):
        api = p.CodexCliAPI(model_name="gpt-5.5")
        output = asyncio.run(
            api.generate(
                [SimpleNamespace(role="user", content="hi")],
                tools=[],
                tool_choice="auto",
                config=None,
            )
        )
    assert output.error == "upstream timeout"
