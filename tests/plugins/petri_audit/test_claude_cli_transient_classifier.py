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


# ---------------------------------------------------------------------------
# PR T — classify_transient_signal returns structured TransientSignal
# (replaces the bool-only is_claude_transient_upstream_error so callers
# can act on which signature fired — rate_limit vs overloaded vs quota).
# ---------------------------------------------------------------------------


def test_classify_signal_stdout_source() -> None:
    from plugins.petri_audit.claude_cli_provider import classify_transient_signal

    signal = classify_transient_signal(
        stdout="oops! Unexpected error. Auto-retrying.\n",
        stderr="",
    )
    assert signal is not None
    assert signal.source == "stdout"
    assert "Unexpected error. Auto-retrying" in signal.matched_text
    assert signal.event_type is None
    assert signal.event_field is None


def test_classify_signal_stderr_source() -> None:
    from plugins.petri_audit.claude_cli_provider import classify_transient_signal

    signal = classify_transient_signal(
        stdout="",
        stderr="HTTP 429 rate_limit_error from upstream\n",
    )
    assert signal is not None
    assert signal.source == "stderr"
    # Both '429' and 'rate_limit_error' match — whichever the engine
    # picks first is fine; the assertion is just that the surrounding
    # context made it into the excerpt.
    assert "rate_limit" in signal.matched_text or "429" in signal.matched_text


def test_classify_signal_result_event_with_field() -> None:
    """``result`` event hit must carry the ``event_field`` so the
    operator can tell whether the upstream error landed in
    ``result.error`` vs ``result.message`` vs ``result.stderr``."""
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [{"type": "result", "error": "overloaded_error: upstream busy", "result": ""}]
    )
    signal = classify_transient_signal(
        stdout="", stderr="", events=parse_stream_json_events(stdout)
    )
    assert signal is not None
    assert signal.source == "event"
    assert signal.event_type == "result"
    assert signal.event_field == "error"
    assert "overloaded_error" in signal.matched_text


def test_classify_signal_assistant_event_no_field() -> None:
    """``assistant`` events carry text in ``message.content[].text`` —
    the ``event_field`` is ``None`` because there's only one canonical
    text location."""
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
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
    signal = classify_transient_signal(
        stdout="", stderr="", events=parse_stream_json_events(stdout)
    )
    assert signal is not None
    assert signal.source == "event"
    assert signal.event_type == "assistant"
    assert signal.event_field is None
    assert "usage limit reached" in signal.matched_text


def test_classify_signal_negative_returns_none() -> None:
    """Normal successful output must return ``None`` (not bool ``False``)
    so callers can use ``if signal is not None:`` for clarity."""
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}},
            {"type": "result", "result": "Hello", "stop_reason": "end_turn"},
        ]
    )
    assert (
        classify_transient_signal(stdout=stdout, stderr="", events=parse_stream_json_events(stdout))
        is None
    )


def test_classify_signal_search_order_stdout_first() -> None:
    """Raw stdout match wins over any event match — paperclip's
    ``buildClaudeTransientHaystack`` walks raw fields first because
    they're the rawest evidence (no parser intermediate)."""
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    stdout_with_match = "429 throttling at the wrapper layer\n"
    events_with_match = parse_stream_json_events(
        _make_stream_json([{"type": "result", "error": "overloaded_error", "result": ""}])
    )
    signal = classify_transient_signal(
        stdout=stdout_with_match, stderr="", events=events_with_match
    )
    assert signal is not None
    assert signal.source == "stdout"
    # Verifies stdout hit takes precedence — event hit (overloaded_error)
    # is not the matched_text.
    assert "overloaded" not in signal.matched_text


def test_signal_excerpt_bounded_to_200_chars() -> None:
    """``matched_text`` must stay ≤ 200 chars so log lines remain
    readable even when claude-cli emits multi-KB error blobs."""
    from plugins.petri_audit.claude_cli_provider import classify_transient_signal

    long_pad = "x" * 500
    # PR-TRANSIENT-BARE-HTTP-CODES — was "429" (bare digit run); that
    # alternative is no longer in the regex. Use a phrase-form
    # signal that still matches — the test only cares about the
    # excerpt-length bound, not which alternative fires.
    stdout = f"{long_pad} too many requests {long_pad}"
    signal = classify_transient_signal(stdout=stdout, stderr="")
    assert signal is not None
    assert len(signal.matched_text) <= 200


def test_transient_exception_carries_signal_and_dump_path() -> None:
    """Structured fields on ``ClaudeCliTransientUpstreamError`` —
    these are the diagnostic the bool-only path lost. ``signal`` and
    ``dump_path`` together let downstream callers route on the
    actual upstream signature without re-running the cycle."""
    from plugins.petri_audit.claude_cli_provider import (
        ClaudeCliTransientUpstreamError,
        TransientSignal,
    )

    sig = TransientSignal(matched_text="429 rate_limit", source="stderr")
    fixture_path = "/var/tmp/dump.json"  # noqa: S108 — symbolic fixture path; the file is never opened
    exc = ClaudeCliTransientUpstreamError("test message", signal=sig, dump_path=fixture_path)
    assert exc.signal is sig
    assert exc.dump_path == fixture_path


def test_transient_exception_default_signal_none_for_backwards_compat() -> None:
    """Pre-PR-T callers that raise without keyword args must still
    work — ``signal`` and ``dump_path`` default to ``None``."""
    from plugins.petri_audit.claude_cli_provider import ClaudeCliTransientUpstreamError

    exc = ClaudeCliTransientUpstreamError("legacy")
    assert exc.signal is None
    assert exc.dump_path is None


# ────────────────────────── PR-TRANSIENT-BARE-HTTP-CODES ──────────────────────
# Smoke 7 (v0.99.53) pilot phase surfaced a fresh false-positive in
# the bare ``\b429\b`` / ``\b503\b`` / ``\b529\b`` alternatives —
# claude-cli completed successfully but its stdout serialised the
# LLM's narrative that quoted a Python source-code comment with the
# digit run ``# instant 429``. Dropping the bare digits removes the
# whole class of false-positives. Real signals always carry a
# phrase (named alternatives below still match them).


def test_bare_429_in_source_code_comment_does_not_match() -> None:
    """Smoke 7 pilot regression — the literal stdout substring that
    misfired previously. Bare digit alone must not classify as a
    transient signal."""
    from plugins.petri_audit.claude_cli_provider import (
        CLAUDE_TRANSIENT_UPSTREAM_RE,
        classify_transient_signal,
    )

    pilot_stdout_excerpt = (
        "current\n252\t # POST /v1/messages (auditor + judge + target × 10) → "
        "instant 429\n253\t # storm → 769s retry-after backoff → 17-min timeout "
        "with 0 samples.\n"
    )
    # Direct regex search — no match.
    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search(pilot_stdout_excerpt) is None
    # Classifier helper — None means "no signal, ok to ship as success".
    assert classify_transient_signal(stdout=pilot_stdout_excerpt, stderr="") is None


def test_bare_503_in_code_does_not_match() -> None:
    from plugins.petri_audit.claude_cli_provider import CLAUDE_TRANSIENT_UPSTREAM_RE

    payload = "if response.status == 503:  # service unavailable on upstream"
    # The named phrase 'service unavailable' WILL match — verify the
    # bare 503 alone (without the phrase) does not.
    bare_only = "if response.status == 503:  # upstream gave us this code"
    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search(bare_only) is None
    # And confirm the phrase form (which is what real signals carry)
    # still matches.
    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search(payload) is not None


def test_bare_529_in_code_does_not_match() -> None:
    from plugins.petri_audit.claude_cli_provider import CLAUDE_TRANSIENT_UPSTREAM_RE

    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search("retry_codes = {429, 503, 529}") is None


def test_real_rate_limit_signal_still_matches_after_bare_removal() -> None:
    """Regression — the canonical Anthropic-API rate-limit signal
    must still classify. The named ``rate_limit_error`` alternative
    catches this even without the bare ``\\b429\\b`` fallback."""
    from plugins.petri_audit.claude_cli_provider import (
        is_claude_transient_upstream_error,
    )

    assert is_claude_transient_upstream_error(
        stdout="",
        stderr="Anthropic API returned 429 rate_limit_error\n",
    )


def test_overloaded_error_still_matches_after_bare_removal() -> None:
    from plugins.petri_audit.claude_cli_provider import (
        is_claude_transient_upstream_error,
    )

    assert is_claude_transient_upstream_error(
        stdout="overloaded_error from upstream",
        stderr="",
    )


def test_too_many_requests_phrase_still_matches() -> None:
    from plugins.petri_audit.claude_cli_provider import CLAUDE_TRANSIENT_UPSTREAM_RE

    # The HTTP 429 status text is the phrase-form equivalent of the
    # bare-digit alternative we removed — must still match.
    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search("HTTP 429 Too Many Requests") is not None


# ────────────────────────── PR-TRANSIENT-WORD-BOUNDARIES ──────────────────────
# Smoke 8 (v0.99.53, post-PR-TRANSIENT-BARE-HTTP-CODES) pilot
# sub-agent surfaced single-word alternatives matching inside
# identifiers (e.g. ``CODEX_CLI_LANE_THROTTLED_MSG`` — a Python
# constant the LLM was quoting from a stack-trace fragment).
# Anchoring on ``\b`` keeps real phrases matching while excluding
# identifier-internal hits.


def test_throttled_inside_identifier_does_not_match() -> None:
    """Smoke 8 pilot regression — the literal stack-trace fragment
    that misfired previously."""
    from plugins.petri_audit.claude_cli_provider import CLAUDE_TRANSIENT_UPSTREAM_RE

    stack_trace = (
        "│ ❱ 171 │ │ raise TimeoutError(CODEX_CLI_LANE_THROTTLED_MSG) │\n"
        "│ 172 │ lane = get_codex_cli_lane()"
    )
    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search(stack_trace) is None


def test_throttled_real_phrase_still_matches() -> None:
    """Real signal — phrase form with whitespace boundary."""
    from plugins.petri_audit.claude_cli_provider import CLAUDE_TRANSIENT_UPSTREAM_RE

    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search("request was throttled") is not None
    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search("Throttling exception thrown") is not None


def test_overloaded_inside_identifier_does_not_match() -> None:
    from plugins.petri_audit.claude_cli_provider import CLAUDE_TRANSIENT_UPSTREAM_RE

    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search("OVERLOADED_ERROR_MSG = '...'") is None


def test_overloaded_error_real_phrase_still_matches() -> None:
    from plugins.petri_audit.claude_cli_provider import CLAUDE_TRANSIENT_UPSTREAM_RE

    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search("upstream returned overloaded_error\n") is not None
    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search("status: overloaded") is not None


def test_throttling_exception_inside_identifier_does_not_match() -> None:
    from plugins.petri_audit.claude_cli_provider import CLAUDE_TRANSIENT_UPSTREAM_RE

    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search("THROTTLINGEXCEPTION_DEFAULT_MSG") is None


def test_throttling_exception_real_phrase_still_matches() -> None:
    from plugins.petri_audit.claude_cli_provider import CLAUDE_TRANSIENT_UPSTREAM_RE

    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search("ThrottlingException ") is not None
    assert CLAUDE_TRANSIENT_UPSTREAM_RE.search('"errorCode": "ThrottlingException"') is not None
