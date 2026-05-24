"""Pure-helper tests for the claude-cli transient-upstream classifier
and the extended assistant-text extractor.

Separate file (not in ``test_claude_cli_provider.py``) because that
sibling does ``pytest.importorskip("inspect_ai")`` at module top level
— without the ``[audit]`` extra installed the entire file is skipped,
which would mask these pure-Python helper tests.

The classifier and the ``assistant``-event extractor branch DO NOT need
inspect_ai — they only test regex matching and dict-walk logic.
"""

from __future__ import annotations

import json
from typing import Any


def _make_stream_json(events: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


# ---------------------------------------------------------------------------
# Extended _extract_assistant_text — assistant event aggregated shape
# ---------------------------------------------------------------------------


def test_extract_text_from_assistant_event_aggregated() -> None:
    """claude-cli's aggregated ``assistant`` event shape (paperclip
    parse.ts:36) — one event per finished assistant message, with
    text blocks under ``message.content[]``."""
    from plugins.petri_audit.claude_cli_provider import (
        _extract_assistant_text,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "First "},
                        {"type": "text", "text": "second."},
                    ]
                },
            }
        ]
    )
    events = parse_stream_json_events(stdout)
    assert _extract_assistant_text(events) == "First second."


def test_extract_text_delta_wins_over_assistant_and_result() -> None:
    """``content_block_delta`` has highest priority — when all three
    sources are populated the deltas are the freshest stream."""
    from plugins.petri_audit.claude_cli_provider import (
        _extract_assistant_text,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "delta"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "agg"}]}},
            {"type": "result", "result": "fallback"},
        ]
    )
    assert _extract_assistant_text(parse_stream_json_events(stdout)) == "delta"


def test_extract_text_assistant_wins_over_result_when_no_deltas() -> None:
    """``assistant`` event takes precedence over the ``result`` fallback."""
    from plugins.petri_audit.claude_cli_provider import (
        _extract_assistant_text,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "agg"}]}},
            {"type": "result", "result": "fallback"},
        ]
    )
    assert _extract_assistant_text(parse_stream_json_events(stdout)) == "agg"


# ---------------------------------------------------------------------------
# Transient upstream classifier (paperclip parse.ts:370 parity)
# ---------------------------------------------------------------------------


def test_transient_classifier_matches_unexpected_error_text() -> None:
    """The specific phrase claude-cli prints during its internal
    retry storm — this is what the smoke run was returning as the
    assistant's text reply before the classifier was wired in."""
    from plugins.petri_audit.claude_cli_provider import is_claude_transient_upstream_error

    assert is_claude_transient_upstream_error(
        stdout="! Unexpected error. Auto-retrying.\n",
        stderr="",
    )


def test_transient_classifier_matches_rate_limit_in_stderr() -> None:
    from plugins.petri_audit.claude_cli_provider import is_claude_transient_upstream_error

    assert is_claude_transient_upstream_error(
        stdout="",
        stderr="Anthropic API returned 429 rate_limit_error\n",
    )


def test_transient_classifier_matches_overloaded_error() -> None:
    from plugins.petri_audit.claude_cli_provider import is_claude_transient_upstream_error

    assert is_claude_transient_upstream_error(
        stdout="overloaded_error from upstream",
        stderr="",
    )


def test_transient_classifier_matches_usage_limit_in_assistant_event() -> None:
    """Quota text surfaced as the assistant's textual reply — the
    silent-success path the classifier was added to close."""
    from plugins.petri_audit.claude_cli_provider import (
        is_claude_transient_upstream_error,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Claude usage limit reached. Resets at 4pm.",
                        }
                    ]
                },
            }
        ]
    )
    events = parse_stream_json_events(stdout)
    assert is_claude_transient_upstream_error(stdout=stdout, stderr="", events=events)


def test_transient_classifier_matches_result_event_error_field() -> None:
    from plugins.petri_audit.claude_cli_provider import (
        is_claude_transient_upstream_error,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [{"type": "result", "error": "overloaded_error from upstream", "result": ""}]
    )
    events = parse_stream_json_events(stdout)
    assert is_claude_transient_upstream_error(stdout="", stderr="", events=events)


def test_transient_classifier_negative_on_normal_text() -> None:
    """Plain successful output must not trip the classifier."""
    from plugins.petri_audit.claude_cli_provider import (
        is_claude_transient_upstream_error,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello!"}]}},
            {"type": "result", "result": "Hello!", "stop_reason": "end_turn"},
        ]
    )
    events = parse_stream_json_events(stdout)
    assert not is_claude_transient_upstream_error(stdout=stdout, stderr="", events=events)


def test_transient_classifier_negative_empty_inputs() -> None:
    from plugins.petri_audit.claude_cli_provider import is_claude_transient_upstream_error

    assert not is_claude_transient_upstream_error(stdout="", stderr="")
    assert not is_claude_transient_upstream_error(stdout="", stderr="", events=[])


def test_transient_classifier_subclass_caught_by_invocation_error() -> None:
    """``ClaudeCliTransientUpstreamError`` must remain a subclass of
    ``ClaudeCliInvocationError`` so existing call sites don't have
    to be touched to keep catching errors."""
    from plugins.petri_audit.claude_cli_provider import (
        ClaudeCliInvocationError,
        ClaudeCliTransientUpstreamError,
    )

    assert issubclass(ClaudeCliTransientUpstreamError, ClaudeCliInvocationError)
