"""Regression pin for PR-LEGACY-PROVIDER-REMOVAL (2026-05-28).

Backfilled from the deleted ``CodexAgenticAdapter.agentic_call`` (v0.53.3):
the Codex backend at ``chatgpt.com/backend-api/codex`` rejects
``input[i].content == null`` with 400 ``"input[i].content must be array or
string, got null"``. The resulting OpenAI SDK exception is body-less and
the operator has no way to triage which prefix entry misbehaved.

``_log_codex_input_shape`` emits a per-item shape line at WARN whenever
the prefix carries any ``content=None`` entry (and at DEBUG unconditionally)
so the regression is visible in the daemon log.
"""

from __future__ import annotations

import logging

from core.llm.adapters.codex_oauth import _log_codex_input_shape


def test_log_emits_warning_when_any_content_is_null(caplog) -> None:  # type: ignore[no-untyped-def]
    """``content=None`` anywhere in the first 30 entries triggers WARN."""
    resp_input = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": None},  # the offending entry
        {"role": "user", "content": "follow-up"},
    ]
    with caplog.at_level(logging.WARNING, logger="core.llm.adapters.codex_oauth"):
        _log_codex_input_shape(resp_input)
    matching = [r for r in caplog.records if "codex-oauth resp_input shape" in r.message]
    assert matching, "no WARN emitted despite content=None in prefix"
    msg = matching[0].message
    assert "[0]user content=str(5)" in msg
    assert "[1]assistant content=None" in msg
    assert "[2]user content=str(9)" in msg


def test_log_silent_when_all_content_present_and_not_debug(caplog) -> None:  # type: ignore[no-untyped-def]
    """No null content + WARN-only logger → silent (avoids per-call spam)."""
    resp_input = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    with caplog.at_level(logging.WARNING, logger="core.llm.adapters.codex_oauth"):
        _log_codex_input_shape(resp_input)
    matching = [r for r in caplog.records if "codex-oauth resp_input shape" in r.message]
    assert not matching, (
        f"diagnostic logged at WARN despite all content present: {[m.message for m in matching]}"
    )


def test_log_emits_at_debug_when_logger_is_debug(caplog) -> None:  # type: ignore[no-untyped-def]
    """DEBUG logger → emit unconditionally (developer trace mode)."""
    resp_input = [{"role": "user", "content": "hi"}]
    with caplog.at_level(logging.DEBUG, logger="core.llm.adapters.codex_oauth"):
        _log_codex_input_shape(resp_input)
    matching = [r for r in caplog.records if "codex-oauth resp_input shape" in r.message]
    assert matching, "diagnostic not emitted at DEBUG level"


def test_log_handles_function_call_typed_items(caplog) -> None:  # type: ignore[no-untyped-def]
    """Typed items (function_call / function_call_output) have no
    ``content`` key — the diagnostic must still format them."""
    resp_input = [
        {"type": "function_call", "call_id": "c1", "name": "read", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "ok"},
        {"role": "user", "content": None},  # forces WARN
    ]
    with caplog.at_level(logging.WARNING, logger="core.llm.adapters.codex_oauth"):
        _log_codex_input_shape(resp_input)
    matching = [r for r in caplog.records if "codex-oauth resp_input shape" in r.message]
    assert matching
    msg = matching[0].message
    assert "[0]function_call keys=" in msg
    assert "[1]function_call_output output=str(2)" in msg
    assert "[2]user content=None" in msg


def test_log_handles_empty_or_non_list_input() -> None:
    """``None`` / empty / non-list inputs are no-ops (no crash)."""
    # No exception is the assertion — calls return None.
    _log_codex_input_shape(None)
    _log_codex_input_shape([])
    _log_codex_input_shape("not a list")  # type: ignore[arg-type]
