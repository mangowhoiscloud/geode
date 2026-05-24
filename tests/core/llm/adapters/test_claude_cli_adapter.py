"""ClaudeCliAdapter — silent-success regression suite.

The adapter previously returned raw ``claude --print --output-format
stream-json`` stdout as ``AdapterCallResult.text``. When claude-cli's
internal retry layer surfaced ``! Unexpected error. Auto-retrying.``
the caller's AgenticLoop treated that error text as the LLM's reply,
terminated with no tool calls, and the parent recorded a ghost
candidate (state.json with metadata but no .md file actually written).

These tests pin:

1. Transient upstream signatures raise ``ClaudeCliTransientUpstreamError``
   instead of being returned as content.
2. The adapter actually parses stream-json events and returns only the
   assistant text — not raw stdout.
3. rc=0 + no events is a hard failure, not silent empty content.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

import pytest


def _make_stream_json(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _build_request() -> Any:
    from core.llm.adapters.base import AdapterCallRequest

    return AdapterCallRequest(model="claude-opus-4-7", messages=())


def _passthrough_lane(*_args: Any, **_kwargs: Any) -> Any:
    """Async context manager stub — yields without touching the
    real LaneQueue / claude_cli_lane semaphore."""

    class _Ctx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_exc: Any) -> None:
            return None

    return _Ctx()


def test_adapter_raises_on_unexpected_error_text() -> None:
    """The smoke run's exact symptom — claude-cli emitted the
    retry-failure phrase as its only assistant text. Before the
    classifier this surfaced as a "successful" empty turn."""
    from core.llm.adapters.claude_cli import ClaudeCliAdapter
    from plugins.petri_audit.claude_cli_provider import ClaudeCliTransientUpstreamError

    adapter = ClaudeCliAdapter()
    stdout = _make_stream_json(
        [
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "! Unexpected error. Auto-retrying."}]
                },
            },
            {"type": "result", "stop_reason": "end_turn", "result": ""},
        ]
    )
    with (
        patch(
            "plugins.petri_audit.claude_cli_provider._resolve_claude_binary",
            return_value="/fake/claude",
        ),
        patch(
            "plugins.petri_audit.claude_cli_provider._run_claude_subprocess",
            return_value=(stdout, "", 0),
        ),
        patch(
            "core.orchestration.claude_cli_lane.acquire_claude_cli_lane_async",
            _passthrough_lane,
        ),
        pytest.raises(ClaudeCliTransientUpstreamError),
    ):
        asyncio.run(adapter.acomplete(_build_request()))


def test_adapter_raises_on_rate_limit_stderr() -> None:
    from core.llm.adapters.claude_cli import ClaudeCliAdapter
    from plugins.petri_audit.claude_cli_provider import ClaudeCliTransientUpstreamError

    adapter = ClaudeCliAdapter()
    stdout = _make_stream_json([{"type": "result", "stop_reason": "end_turn", "result": ""}])
    with (
        patch(
            "plugins.petri_audit.claude_cli_provider._resolve_claude_binary",
            return_value="/fake/claude",
        ),
        patch(
            "plugins.petri_audit.claude_cli_provider._run_claude_subprocess",
            return_value=(stdout, "429 rate_limit_error", 1),
        ),
        patch(
            "core.orchestration.claude_cli_lane.acquire_claude_cli_lane_async",
            _passthrough_lane,
        ),
        pytest.raises(ClaudeCliTransientUpstreamError),
    ):
        asyncio.run(adapter.acomplete(_build_request()))


def test_adapter_returns_parsed_text_not_raw_stdout() -> None:
    """The adapter must extract the assistant text — not pass raw
    stream-json stdout through to AgenticLoop."""
    from core.llm.adapters.claude_cli import ClaudeCliAdapter

    adapter = ClaudeCliAdapter()
    stdout = _make_stream_json(
        [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Hello operator"}]},
            },
            {"type": "result", "stop_reason": "end_turn", "result": "Hello operator"},
        ]
    )
    with (
        patch(
            "plugins.petri_audit.claude_cli_provider._resolve_claude_binary",
            return_value="/fake/claude",
        ),
        patch(
            "plugins.petri_audit.claude_cli_provider._run_claude_subprocess",
            return_value=(stdout, "", 0),
        ),
        patch(
            "core.orchestration.claude_cli_lane.acquire_claude_cli_lane_async",
            _passthrough_lane,
        ),
    ):
        result = asyncio.run(adapter.acomplete(_build_request()))
    assert result.text == "Hello operator"
    assert "stream-json" not in result.text  # not the raw stdout shape
    assert result.stop_reason == "stop"


def test_adapter_raises_when_rc_zero_no_events() -> None:
    """rc=0 + empty stdout is the silent-empty-content path —
    must fail loud rather than return ``text=""`` as a normal reply."""
    from core.llm.adapters.claude_cli import ClaudeCliAdapter
    from plugins.petri_audit.claude_cli_provider import ClaudeCliInvocationError

    adapter = ClaudeCliAdapter()
    with (
        patch(
            "plugins.petri_audit.claude_cli_provider._resolve_claude_binary",
            return_value="/fake/claude",
        ),
        patch(
            "plugins.petri_audit.claude_cli_provider._run_claude_subprocess",
            return_value=("", "", 0),
        ),
        patch(
            "core.orchestration.claude_cli_lane.acquire_claude_cli_lane_async",
            _passthrough_lane,
        ),
        pytest.raises(ClaudeCliInvocationError),
    ):
        asyncio.run(adapter.acomplete(_build_request()))
