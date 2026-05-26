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


# ---------------------------------------------------------------------------
# PR T — observability: structured exception + post-mortem dump
# ---------------------------------------------------------------------------


def test_adapter_transient_carries_signal_dataclass() -> None:
    """Adapter must populate ``ClaudeCliTransientUpstreamError.signal``
    with the matched ``TransientSignal`` so downstream callers
    (AgenticLoop, worker) can act on the actual upstream signature
    instead of guessing from a generic 'transient' string."""
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
    ):
        try:
            asyncio.run(adapter.acomplete(_build_request()))
            raise AssertionError("expected ClaudeCliTransientUpstreamError")
        except ClaudeCliTransientUpstreamError as exc:
            assert exc.signal is not None
            # PR-TRANSIENT-CLASSIFIER-SCOPE (2026-05-26) — classifier
            # now walks stderr → events → stdout-fallback (events
            # first ordering). The raw stream-json stdout scan was
            # demoted to fallback after smoke 19 false positives —
            # LLM-authored seed prose containing "rate-limited tools"
            # was triggering the regex on raw stdout. The
            # ``assistant`` event match now surfaces with
            # ``source="event"`` + ``event_type="assistant"`` (the
            # PR-T quota-leak detection path is preserved).
            assert exc.signal.source == "event"
            assert exc.signal.event_type == "assistant"
            assert "Unexpected error" in exc.signal.matched_text
            # Exception message includes the source/matched_text inline
            # so a single log line is enough for triage.
            msg = str(exc)
            assert "source=event/assistant" in msg
            assert "matched=" in msg


def test_adapter_transient_writes_postmortem_dump(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Every transient hit must persist a JSON post-mortem under
    ``~/.geode/diagnostics/claude-cli-transient/`` so operators can
    recover the upstream error message claude-cli emitted in its
    stream-json events (otherwise discarded after classification)."""
    import json as _json

    from core.llm.adapters.claude_cli import ClaudeCliAdapter
    from plugins.petri_audit.claude_cli_provider import ClaudeCliTransientUpstreamError

    # ``tmp_path`` is pytest's per-test scratch directory fixture. Alias
    # it to ``diagnostics_root`` at entry so the rest of the test reads
    # in domain terms — we're substituting the operator's real
    # ``~/.geode/diagnostics/`` with a throwaway directory so the dump
    # write doesn't pollute the home tree.
    diagnostics_root = tmp_path
    adapter = ClaudeCliAdapter()
    # PR-TRANSIENT-BARE-HTTP-CODES — was
    # ``"anthropic.RateLimitError: 429"`` which matched the bare
    # ``\b429\b`` alternative. That alternative is now removed; use
    # the phrase-form signal that real claude-cli rate-limit errors
    # carry.
    error_message = "anthropic.RateLimitError: rate_limit_error too many requests"
    stdout = _make_stream_json([{"type": "result", "error": error_message, "result": ""}])
    with (
        patch(
            "plugins.petri_audit.claude_cli_provider._resolve_claude_binary",
            return_value="/fake/claude",
        ),
        patch(
            "plugins.petri_audit.claude_cli_provider._run_claude_subprocess",
            return_value=(stdout, "", 1),
        ),
        patch(
            "core.orchestration.claude_cli_lane.acquire_claude_cli_lane_async",
            _passthrough_lane,
        ),
        # Redirect ``core.paths.GLOBAL_DIAGNOSTICS_DIR`` (the lazy
        # import inside _dump_transient_postmortem reads it at call
        # time, so the monkeypatch propagates to the dump helper).
        patch("core.paths.GLOBAL_DIAGNOSTICS_DIR", diagnostics_root),
    ):
        try:
            asyncio.run(adapter.acomplete(_build_request()))
            raise AssertionError("expected ClaudeCliTransientUpstreamError")
        except ClaudeCliTransientUpstreamError as exc:
            assert exc.dump_path is not None
            # ``postmortem_path`` = the absolute path the adapter wrote
            # the JSON dump to (carried back on the exception so the
            # caller can grep it without scanning the diagnostics dir).
            postmortem_path = exc.dump_path
            assert postmortem_path.startswith(str(diagnostics_root))
            with open(postmortem_path, encoding="utf-8") as fp:
                data = _json.loads(fp.read())
            # Dump must carry the four diagnostic dimensions the
            # bool-only classifier discarded: stdout / parsed events /
            # classifier signal / rc.
            assert set(data.keys()) >= {"signal", "stdout", "stderr", "events", "rc", "model"}
            assert data["signal"]["matched_text"]
            # Source is ``stdout`` (raw stream-json bytes win over parsed
            # events — see classifier search order). The event payload is
            # still persisted in ``events[]`` so post-mortem analysis can
            # walk to the structured event regardless.
            assert data["signal"]["source"] in {"stdout", "event"}
            assert (
                "rate_limit_error" in data["signal"]["matched_text"]
                or "too many requests" in data["signal"]["matched_text"]
            )
            assert len(data["events"]) == 1
            assert data["events"][0]["type"] == "result"
            assert data["events"][0]["payload"]["error"] == error_message


# ────────────────────────── PR-RESUME-NO-PERSIST-FIX (B2) ─────────────────────
# Smoke 10 surfaced --no-session-persistence ↔ --resume conflict:
# pre-fix the adapter unconditionally appended --no-session-persistence
# which broke PR-V's turn-N→turn-N+1 resume path. The B2 fix replaces
# the blunt flag with per-task cwd isolation. These tests pin both
# sides of the contract.


def test_adapter_argv_no_longer_contains_no_session_persistence() -> None:
    """PR-RESUME-NO-PERSIST-FIX — the adapter must NOT inject
    --no-session-persistence into argv. Cross-sub-agent leak is
    prevented by per-task cwd isolation instead (see
    ``test_adapter_passes_task_isolated_cwd_to_subprocess``)."""
    import contextlib

    from core.llm.adapters.claude_cli import ClaudeCliAdapter
    from plugins.petri_audit.claude_cli_provider import ClaudeCliInvocationError

    captured_argv: list[str] = []

    async def _fake_subprocess(argv: list[str], stdin: str, **kwargs: Any) -> tuple[str, str, int]:
        captured_argv.extend(argv)
        # rc=0 + no events → adapter raises ClaudeCliInvocationError;
        # argv is already captured so suppressing is fine.
        return ("", "", 0)

    adapter = ClaudeCliAdapter()
    with (
        patch(
            "plugins.petri_audit.claude_cli_provider._resolve_claude_binary",
            return_value="/fake/claude",
        ),
        patch(
            "plugins.petri_audit.claude_cli_provider._run_claude_subprocess",
            _fake_subprocess,
        ),
        patch(
            "core.orchestration.claude_cli_lane.acquire_claude_cli_lane_async",
            _passthrough_lane,
        ),
        contextlib.suppress(ClaudeCliInvocationError),
    ):
        asyncio.run(adapter.acomplete(_build_request()))

    assert captured_argv, "expected _run_claude_subprocess to be called"
    assert "--no-session-persistence" not in captured_argv


def test_adapter_passes_task_isolated_cwd_to_subprocess() -> None:
    """PR-RESUME-NO-PERSIST-FIX — when the ContextVar is set, the
    adapter forwards the value as the subprocess cwd= kwarg. This is
    the only mechanism by which the per-task cache-pool isolation
    propagates from worker startup down to claude-cli."""
    import contextlib

    from core.agent.task_isolation import set_task_isolated_cwd
    from core.llm.adapters.claude_cli import ClaudeCliAdapter
    from plugins.petri_audit.claude_cli_provider import ClaudeCliInvocationError

    captured_kwargs: dict[str, Any] = {}

    async def _fake_subprocess(
        argv: list[str], stdin: str, *args: Any, **kwargs: Any
    ) -> tuple[str, str, int]:
        captured_kwargs.update(kwargs)
        return ("", "", 0)

    adapter = ClaudeCliAdapter()
    set_task_isolated_cwd("/tmp/per-task-cwd-test")  # noqa: S108 — string probe, not a real dir
    try:
        with (
            patch(
                "plugins.petri_audit.claude_cli_provider._resolve_claude_binary",
                return_value="/fake/claude",
            ),
            patch(
                "plugins.petri_audit.claude_cli_provider._run_claude_subprocess",
                _fake_subprocess,
            ),
            patch(
                "core.orchestration.claude_cli_lane.acquire_claude_cli_lane_async",
                _passthrough_lane,
            ),
            contextlib.suppress(ClaudeCliInvocationError),
        ):
            asyncio.run(adapter.acomplete(_build_request()))
    finally:
        set_task_isolated_cwd(None)

    assert captured_kwargs.get("cwd") == "/tmp/per-task-cwd-test"  # noqa: S108


def test_adapter_passes_none_cwd_when_context_var_unset() -> None:
    """Direct-call path (inspect_ai audit lane, one-shot diagnostic) —
    no sub-agent worker bound the ContextVar, so cwd= should be None
    and the subprocess inherits the caller's cwd."""
    import contextlib

    from core.agent.task_isolation import set_task_isolated_cwd
    from core.llm.adapters.claude_cli import ClaudeCliAdapter
    from plugins.petri_audit.claude_cli_provider import ClaudeCliInvocationError

    captured_kwargs: dict[str, Any] = {}

    async def _fake_subprocess(
        argv: list[str], stdin: str, *args: Any, **kwargs: Any
    ) -> tuple[str, str, int]:
        captured_kwargs.update(kwargs)
        return ("", "", 0)

    set_task_isolated_cwd(None)  # explicit clear for determinism
    adapter = ClaudeCliAdapter()
    with (
        patch(
            "plugins.petri_audit.claude_cli_provider._resolve_claude_binary",
            return_value="/fake/claude",
        ),
        patch(
            "plugins.petri_audit.claude_cli_provider._run_claude_subprocess",
            _fake_subprocess,
        ),
        patch(
            "core.orchestration.claude_cli_lane.acquire_claude_cli_lane_async",
            _passthrough_lane,
        ),
        contextlib.suppress(ClaudeCliInvocationError),
    ):
        asyncio.run(adapter.acomplete(_build_request()))

    assert captured_kwargs.get("cwd") is None
