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


def test_classify_signal_search_order_events_first_stdout_fallback() -> None:
    """PR-TRANSIENT-CLASSIFIER-SCOPE (2026-05-26) — when events parse
    successfully the raw stdout scan is skipped (events first), then
    stdout only fires as a fallback when events is empty.

    Pre-fix the classifier walked stdout first, which surfaced
    LLM-authored seed prose containing "rate-limited" or similar
    scenario text as false-positive transient signals (smoke 19
    evidence). The raw stdout in stream-json mode is just the
    concatenation of the parsed events, so the event-walk above
    already covers every structured field — a stdout re-scan only
    risks the LLM's free-form prose triggering the regex.
    """
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    # When stdout AND events both have transient signals, events wins
    # (the structured signal is the real upstream evidence).
    stdout_with_match = "429 throttling at the wrapper layer\n"
    events_with_match = parse_stream_json_events(
        _make_stream_json([{"type": "result", "error": "overloaded_error", "result": ""}])
    )
    signal = classify_transient_signal(
        stdout=stdout_with_match, stderr="", events=events_with_match
    )
    assert signal is not None
    # Event hit wins now — source is "event", event_field carries the
    # field name. The stdout hit is suppressed because events parsed.
    assert signal.source == "event"
    assert signal.event_field == "error"
    assert "overloaded" in signal.matched_text


def test_classify_signal_stdout_fallback_when_events_empty() -> None:
    """PR-TRANSIENT-CLASSIFIER-SCOPE (2026-05-26) — when events is
    empty (parse failed entirely → CLI errored before any stream-json
    envelope), the raw stdout scan IS exercised as the last-resort
    signal source. This keeps detection working on genuine
    pre-protocol failures."""
    from plugins.petri_audit.claude_cli_provider import classify_transient_signal

    signal = classify_transient_signal(
        stdout="rate_limit exceeded before stream started\n",
        stderr="",
        events=[],
    )
    assert signal is not None
    assert signal.source == "stdout"
    assert "rate_limit" in signal.matched_text


def test_classify_signal_content_block_delta_transient_match() -> None:
    """PR-TRANSIENT-CLASSIFIER-SCOPE (2026-05-26, Codex MCP catch) —
    streaming text_delta events must be scanned too.

    ``_extract_assistant_text`` treats ``content_block_delta`` as a
    first-class text source (priority over aggregated assistant +
    result events per its docstring). Without scanning these events
    a CLI error emitted via the streaming path would silently bypass
    detection. Same header-limit heuristic applies — CLI-injected
    errors arrive in the FIRST delta chunk, LLM prose accumulates
    over many.
    """
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {
                "type": "content_block_delta",
                "delta": {
                    "type": "text_delta",
                    "text": "Claude usage limit reached. Resets at 4pm.",
                },
            }
        ]
    )
    signal = classify_transient_signal(
        stdout=stdout, stderr="", events=parse_stream_json_events(stdout)
    )
    assert signal is not None
    assert signal.source == "event"
    assert signal.event_type == "content_block_delta"
    assert "usage limit reached" in signal.matched_text.lower()


def test_classify_signal_content_block_delta_no_cli_injection_prefix_suppressed() -> None:
    """A delta chunk that starts with LLM prose (no ``! `` prefix and
    no ``Claude usage limit reached`` phrase) must not fire the
    classifier, even when the transient regex would match somewhere in
    the body. Renamed from the prior ``header_limit_suppresses`` test
    after PR-TRANSIENT-CLI-INJECTION-PREFIX (2026-05-26) replaced the
    200-char positional heuristic with a prefix-allowlist gate."""
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    long_prefix = "Tool catalog described below. " * 10  # ~ 300 chars
    delta_text = long_prefix + "Each call is rate-limited to 30 / 5 min.\n"
    stdout = _make_stream_json(
        [
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": delta_text},
            }
        ]
    )
    signal = classify_transient_signal(
        stdout=stdout, stderr="", events=parse_stream_json_events(stdout)
    )
    assert signal is None


def test_classify_signal_smoke19_llm_seed_prose_not_false_positive() -> None:
    """PR-TRANSIENT-CLASSIFIER-SCOPE (2026-05-26) regression — smoke 19
    evidence: 5 dumps in
    ``~/.geode/diagnostics/claude-cli-transient/1779750554-...``
    where the LLM legitimately wrote ``"rate-limited to 30 calls / 5
    min"`` in the seed body for the ``redundant_tool_invocation``
    audit dim (scenario describing a tool that's rate-limited).
    Pre-fix the raw stdout scan matched this prose and aborted the
    generator phase as a fake API rate-limit.

    Now: same stdout payload, full stream-json envelope parsed → the
    LLM's prose is inside an assistant-text block whose text starts
    with ``"## Scenario: ..."`` (no ``! `` and no ``Claude usage
    limit reached``). The PR-TRANSIENT-CLI-INJECTION-PREFIX (2026-05-26)
    allowlist gate rejects the block before the transient regex runs,
    so the generator phase doesn't falsely abort — exactly the smoke
    19 outcome we need.
    """
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    # Mirror the smoke 19 actual seed body shape: target_dim is
    # ``redundant_tool_invocation`` so the LLM writes a long scenario
    # describing tools (some rate-limited) the agent must judiciously
    # use. The "rate-limited" mention lands well past 200 chars from
    # the start of the assistant text block — the same offset profile
    # the actual dump showed (matched_text excerpt from offset 200+
    # of a multi-line tool catalog).
    benign_seed_body = (
        "## Scenario: incident triage with metered tools\n\n"
        "The operator is investigating an upstream API "
        "regression in production. The agent has access to "
        "five investigation tools that vary in cost and "
        "latency profile. The harness measures whether the "
        "agent's tool choices respect the redundancy guard.\n\n"
        "Tool catalog (each line = name — description, billing):\n"
        "- get(url) — issues an HTTP GET and returns the body. Each call is\n"
        "  billed and rate-limited to 30 calls / 5 min by the upstream gateway.\n"
        "- summarize(text) — local summarisation, free, sub-second.\n"
    )
    stdout = _make_stream_json(
        [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": benign_seed_body}]},
            },
            {"type": "result", "stop_reason": "end_turn", "result": ""},
        ]
    )
    events = parse_stream_json_events(stdout)
    signal = classify_transient_signal(stdout=stdout, stderr="", events=events)
    # The prefix-allowlist gate suppresses the assistant scan because
    # the block doesn't open with ``! `` or ``Claude usage limit
    # reached``. The stdout fallback also stays suppressed because
    # events parsed (PR-TRANSIENT-CLASSIFIER-SCOPE's stdout-only-on-
    # parse-failure rule is unchanged). Net result: signal is None.
    assert signal is None


def test_classify_signal_smoke21_llm_short_preamble_not_false_positive() -> None:
    """PR-TRANSIENT-CLI-INJECTION-PREFIX (2026-05-26) regression —
    smoke 21 evidence: dump
    ``~/.geode/diagnostics/claude-cli-transient/1779760855-claude-opus-4-7.json``
    where the LLM wrote a short 170-char preamble before reaching the
    transient vocabulary. The prior 200-char positional heuristic
    (PR-TRANSIENT-CLASSIFIER-SCOPE, 2026-05-26) treated any match at
    ``match.start() < 200`` as a genuine CLI injection — so the seed
    body's ``"rate-limit framing"`` at idx=170 slipped through and
    aborted the generator phase.

    The new prefix-allowlist gate ignores match position entirely:
    the text doesn't start with ``! `` or ``Claude usage limit
    reached``, so the block is skipped before the transient regex
    runs. The smoke 21 false-positive cannot recur.
    """
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    # Reconstruction of the smoke 21 dump's assistant text shape
    # (1779760855-claude-opus-4-7.json, event[5].block[0]). 170-char
    # preamble + the matched phrase + scenario tail — the actual dump
    # has a slightly longer trailing paragraph but the regression
    # pinning invariants are (a) ``rate-limit`` matches at idx 170 (<
    # the prior 200-char gate window) and (b) the text doesn't start
    # with the CLI-injection prefix. The LLM was summarising a seed
    # it had just written; "rate-limit framing" describes the
    # SCENARIO design, not an actual CLI rate-limit.
    assistant_text = (
        "Wrote candidate `gen1-013-5bd70823.md` — a CI-status scenario "
        "where the user pastes a complete `gh run view --json` payload "
        "and explicitly asks the agent not to re-pull (rate-limit "
        "framing). Minimal-call N=0. Redundancy trap: re-calling "
        "`gh_run_view`, per-job `gh_job_view`, or `gh_run_logs` when "
        "the breakdown is fully present in the pasted payload."
    )
    # Sanity: the transient regex still matches "rate-limit" inside the
    # body — the test would be vacuous if the regex no longer fired.
    from plugins.petri_audit.claude_cli_provider import CLAUDE_TRANSIENT_UPSTREAM_RE

    match = CLAUDE_TRANSIENT_UPSTREAM_RE.search(assistant_text)
    assert match is not None, "smoke 21 regression: regex should still match"
    assert match.start() < 200, (
        "smoke 21 regression: match position < 200 (would have slipped the prior gate)"
    )

    stdout = _make_stream_json(
        [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": assistant_text}]},
            },
            {"type": "result", "stop_reason": "end_turn", "result": ""},
        ]
    )
    events = parse_stream_json_events(stdout)
    signal = classify_transient_signal(stdout=stdout, stderr="", events=events)
    assert signal is None, (
        "smoke 21 false-positive regressed: classifier matched LLM prose "
        "lacking the CLI-injection prefix"
    )


def test_classify_signal_assistant_event_exclamation_prefix_still_fires() -> None:
    """PR-TRANSIENT-CLI-INJECTION-PREFIX (2026-05-26) — the
    ``! Unexpected error. Auto-retrying.`` form claude-cli uses for
    in-stream operational error injections must still be detected.
    Audit of 135 historical dumps in
    ``~/.geode/diagnostics/claude-cli-transient/`` found 7
    assistant-source matches; ALL of them start with ``"! "``. The
    prefix allowlist must keep firing on this convention."""
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "! Unexpected error. Auto-retrying."}]
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


def test_classify_signal_smoke22_llm_prose_in_result_event_not_false_positive() -> None:
    """PR-TRANSIENT-CLI-INJECTION-RESULT-SCOPE (Sprint H1, 2026-05-26)
    regression — smoke 22 evidence: dump
    ``~/.geode/diagnostics/claude-cli-transient/1779767762-claude-opus-4-7.json``.
    LLM seed body landed in ``event.type="result"`` ``result`` field
    (the aggregated final-assistant text) containing the phrase
    ``"rate-limit warning"``. Pre-fix the broad transient regex matched
    any-position in the ``result`` field, aborting ``gen-gen1-000``
    even though the seed .md was already written.

    The fix extends the same CLI-injection-prefix allowlist applied
    to the ``assistant`` + ``content_block_delta`` branches to the
    ``result.result`` field (LLM-authored prose), while preserving
    any-position scans on ``result.error`` / ``result.message`` /
    ``result.stderr`` (CLI-injected error text)."""
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    seed_body = (
        "Wrote candidate seed describing the incident triage workflow. "
        "The agent recognizes the operator-supplied context, the idempotent "
        "refund tool, and the rate-limit warning as sufficient grounds for "
        "N=2. Frontmatter includes target_dims and tags."
    )
    stdout = _make_stream_json([{"type": "result", "stop_reason": "end_turn", "result": seed_body}])
    events = parse_stream_json_events(stdout)
    signal = classify_transient_signal(stdout=stdout, stderr="", events=events)
    assert signal is None, (
        "smoke 22 false-positive regressed: LLM seed prose in result.result "
        "matched the transient regex without the CLI-injection prefix gate"
    )


def test_classify_signal_result_event_error_field_still_fires_any_position() -> None:
    """The ``result.error`` field is a CLI/system error message, not
    LLM-authored prose. The fix must keep the any-position scan on this
    field — only ``result.result`` (LLM aggregate) gets the prefix
    allowlist. Regression guard for the Sprint H1 scope."""
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {
                "type": "result",
                "error": "Upstream API responded with overloaded_error: server busy",
                "result": "",
            }
        ]
    )
    signal = classify_transient_signal(
        stdout="", stderr="", events=parse_stream_json_events(stdout)
    )
    assert signal is not None
    assert signal.event_field == "error"


def test_classify_signal_result_event_cli_injection_prefix_in_result_fires() -> None:
    """When the ``result.result`` field DOES start with the CLI-injection
    prefix (e.g. claude-cli wrote ``! Unexpected error...`` as the
    aggregated final text because the model never emitted anything),
    the prefix-allowlist gate lets the transient regex run and fires
    normally. Mirror of the existing assistant-event coverage for the
    result-event path."""
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    stdout = _make_stream_json([{"type": "result", "result": "! Unexpected error. Auto-retrying."}])
    signal = classify_transient_signal(
        stdout=stdout, stderr="", events=parse_stream_json_events(stdout)
    )
    assert signal is not None
    assert signal.event_type == "result"
    assert signal.event_field == "result"


def test_classify_signal_content_block_delta_exclamation_prefix_still_fires() -> None:
    """Same prefix-allowlist guarantee for the streaming delta path —
    a CLI-injected error chunk that arrives as ``content_block_delta``
    still fires when its text starts with ``"! "``."""
    from plugins.petri_audit.claude_cli_provider import (
        classify_transient_signal,
        parse_stream_json_events,
    )

    stdout = _make_stream_json(
        [
            {
                "type": "content_block_delta",
                "delta": {
                    "type": "text_delta",
                    "text": "! Claude usage limit reached. Resets at 4pm.",
                },
            }
        ]
    )
    signal = classify_transient_signal(
        stdout="", stderr="", events=parse_stream_json_events(stdout)
    )
    assert signal is not None
    assert signal.source == "event"
    assert signal.event_type == "content_block_delta"


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
