"""Mid-stream replay-safety boundary — ``retry_with_backoff_generic(_async)``.

Replay-safety rule: a transient failure DURING streaming is safe to
auto-retry (full re-call) only while no visible assistant output (text or
tool-use delta) has been surfaced to a consumer. If visible output HAS
been emitted and the stream then dies, a silent full-call retry would
duplicate the already-shown output — the retry boundary must raise
``StreamInterruptedError`` (chaining the transient cause) so the caller /
session layer decides.

Contract pinned here:

1. ``StreamProgress.note_delta`` flips ``visible_output_emitted`` only for
   ``text`` / ``tool_use`` kinds — ``thinking`` deltas never count.
2. Transient failure BEFORE any visible delta → normal silent retry.
3. Transient failure AFTER a visible delta → ``StreamInterruptedError``,
   no retry, original exception chained via ``__cause__``.
4. Per-attempt semantics: the retry loop resets the progress signal
   before EVERY attempt, so the guard reflects the attempt that just
   failed — stale state from a previous attempt / call never blocks a
   legitimate retry.
5. ``stream_progress=None`` (all current buffered callers) keeps the
   legacy always-retry behavior.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core.llm.errors import StreamInterruptedError, classify_llm_error
from core.llm.fallback import (
    StreamProgress,
    retry_with_backoff_generic,
    retry_with_backoff_generic_async,
)


class _FakeTransientError(Exception):
    """Stands in for a retryable SDK error (connection reset mid-SSE)."""


_FAST_RETRY_KWARGS: dict[str, Any] = {
    "fallback_models": [],
    "retryable_errors": (_FakeTransientError,),
    "max_retries": 3,
    "retry_base_delay": 0.0,
    "retry_max_delay": 0.0,
}


# ---------------------------------------------------------------------------
# StreamProgress contract — what counts as visible output
# ---------------------------------------------------------------------------


def test_text_delta_marks_visible_and_accumulates_chars() -> None:
    progress = StreamProgress()
    assert progress.visible_output_emitted is False
    progress.note_delta("text", 7)
    progress.note_delta("text", 5)
    assert progress.visible_output_emitted is True
    assert progress.partial_chars == 12


def test_tool_use_delta_marks_visible() -> None:
    progress = StreamProgress()
    progress.note_delta("tool_use")
    assert progress.visible_output_emitted is True


def test_thinking_delta_does_not_mark_visible() -> None:
    """Reasoning deltas are not user-visible output — a mid-stream death
    after thinking-only progress is still replay-safe."""
    progress = StreamProgress()
    progress.note_delta("thinking", 999)
    progress.note_delta("usage")
    progress.note_delta("stop")
    assert progress.visible_output_emitted is False
    assert progress.partial_chars == 0


def test_reset_clears_per_attempt_state() -> None:
    progress = StreamProgress()
    progress.note_delta("text", 42)
    progress.reset()
    assert progress.visible_output_emitted is False
    assert progress.partial_chars == 0


# ---------------------------------------------------------------------------
# Sync retry boundary
# ---------------------------------------------------------------------------


def test_sync_transient_before_visible_output_retries() -> None:
    """Death before the first visible delta is replay-safe → silent retry."""
    progress = StreamProgress()
    calls: list[str] = []

    def _fn(*, model: str) -> str:
        calls.append(model)
        if len(calls) == 1:
            raise _FakeTransientError("connection reset before first token")
        return "ok"

    result = retry_with_backoff_generic(
        _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
    )
    assert result == "ok"
    assert len(calls) == 2


def test_sync_transient_after_visible_output_raises_stream_interrupted() -> None:
    """Death after a visible text delta → StreamInterruptedError, no retry."""
    progress = StreamProgress()
    calls: list[str] = []
    original = _FakeTransientError("connection reset mid-stream")

    def _fn(*, model: str) -> str:
        calls.append(model)
        progress.note_delta("text", 17)  # consumer surfaced 17 chars
        raise original

    with pytest.raises(StreamInterruptedError) as exc_info:
        retry_with_backoff_generic(
            _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
        )
    assert len(calls) == 1  # the guard fired before any retry
    assert exc_info.value.__cause__ is original
    assert exc_info.value.visible_output_emitted is True
    assert exc_info.value.partial_chars == 17


def test_sync_transient_after_tool_use_delta_raises_stream_interrupted() -> None:
    progress = StreamProgress()
    calls: list[str] = []

    def _fn(*, model: str) -> str:
        calls.append(model)
        progress.note_delta("tool_use")
        raise _FakeTransientError("stream died after tool_use block")

    with pytest.raises(StreamInterruptedError):
        retry_with_backoff_generic(
            _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
        )
    assert len(calls) == 1


def test_sync_thinking_only_progress_still_retries() -> None:
    """Thinking deltas do not count as visible — death after thinking-only
    progress silently retries like any pre-output transient."""
    progress = StreamProgress()
    calls: list[str] = []

    def _fn(*, model: str) -> str:
        calls.append(model)
        progress.note_delta("thinking", 500)
        if len(calls) == 1:
            raise _FakeTransientError("died during reasoning")
        return "ok"

    result = retry_with_backoff_generic(
        _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
    )
    assert result == "ok"
    assert len(calls) == 2


def test_sync_per_attempt_reset_clears_stale_flag() -> None:
    """A stale flag from a previous call/attempt must not block a
    legitimate retry — the loop resets the signal before every attempt."""
    progress = StreamProgress()
    progress.note_delta("text", 99)  # stale state from an earlier call
    calls: list[str] = []

    def _fn(*, model: str) -> str:
        calls.append(model)
        if len(calls) == 1:
            # No visible output emitted by THIS attempt.
            raise _FakeTransientError("pre-output death")
        return "ok"

    result = retry_with_backoff_generic(
        _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
    )
    assert result == "ok"
    assert len(calls) == 2


def test_sync_guard_applies_to_the_attempt_that_failed() -> None:
    """Attempt 1 fails clean (retried); attempt 2 emits visible output then
    fails → the guard fires for attempt 2 with attempt-2 progress only."""
    progress = StreamProgress()
    calls: list[str] = []

    def _fn(*, model: str) -> str:
        calls.append(model)
        if len(calls) == 1:
            raise _FakeTransientError("pre-output death")
        progress.note_delta("text", 5)
        raise _FakeTransientError("mid-output death")

    with pytest.raises(StreamInterruptedError) as exc_info:
        retry_with_backoff_generic(
            _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
        )
    assert len(calls) == 2
    assert exc_info.value.partial_chars == 5  # attempt 2 only, not accumulated


def test_sync_no_stream_progress_keeps_legacy_retry() -> None:
    """Buffered callers (stream_progress=None) keep the always-retry path."""
    calls: list[str] = []

    def _fn(*, model: str) -> str:
        calls.append(model)
        if len(calls) < 3:
            raise _FakeTransientError("transient")
        return "ok"

    result = retry_with_backoff_generic(_fn, model="m-test", **_FAST_RETRY_KWARGS)
    assert result == "ok"
    assert len(calls) == 3


def test_sync_oauth_refresh_retry_also_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """The OAuth-401 refresh path re-calls the same attempt — it must obey
    the same replay-safety boundary as the transient branch."""
    import core.llm.fallback as fallback_mod

    monkeypatch.setattr(fallback_mod, "_try_oauth_refresh", lambda _label: True)
    progress = StreamProgress()
    calls: list[str] = []
    original = Exception("401 authentication_error mid-stream")

    def _fn(*, model: str) -> str:
        calls.append(model)
        progress.note_delta("text", 3)
        raise original

    with pytest.raises(StreamInterruptedError) as exc_info:
        retry_with_backoff_generic(
            _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
        )
    assert len(calls) == 1
    assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# Async retry boundary — mirrors the sync contract
# ---------------------------------------------------------------------------


def test_async_transient_before_visible_output_retries() -> None:
    progress = StreamProgress()
    calls: list[str] = []

    async def _fn(*, model: str) -> str:
        calls.append(model)
        if len(calls) == 1:
            raise _FakeTransientError("connection reset before first token")
        return "ok"

    result = asyncio.run(
        retry_with_backoff_generic_async(
            _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
        )
    )
    assert result == "ok"
    assert len(calls) == 2


def test_async_transient_after_visible_output_raises_stream_interrupted() -> None:
    progress = StreamProgress()
    calls: list[str] = []
    original = _FakeTransientError("connection reset mid-stream")

    async def _fn(*, model: str) -> str:
        calls.append(model)
        progress.note_delta("text", 23)
        raise original

    with pytest.raises(StreamInterruptedError) as exc_info:
        asyncio.run(
            retry_with_backoff_generic_async(
                _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
            )
        )
    assert len(calls) == 1
    assert exc_info.value.__cause__ is original
    assert exc_info.value.partial_chars == 23


def test_async_thinking_only_progress_still_retries() -> None:
    progress = StreamProgress()
    calls: list[str] = []

    async def _fn(*, model: str) -> str:
        calls.append(model)
        progress.note_delta("thinking", 100)
        if len(calls) == 1:
            raise _FakeTransientError("died during reasoning")
        return "ok"

    result = asyncio.run(
        retry_with_backoff_generic_async(
            _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
        )
    )
    assert result == "ok"
    assert len(calls) == 2


def test_async_per_attempt_reset_clears_stale_flag() -> None:
    progress = StreamProgress()
    progress.note_delta("text", 99)  # stale state from an earlier call
    calls: list[str] = []

    async def _fn(*, model: str) -> str:
        calls.append(model)
        if len(calls) == 1:
            raise _FakeTransientError("pre-output death")
        return "ok"

    result = asyncio.run(
        retry_with_backoff_generic_async(
            _fn, model="m-test", stream_progress=progress, **_FAST_RETRY_KWARGS
        )
    )
    assert result == "ok"
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Classification — the error is a first-class classified category
# ---------------------------------------------------------------------------


def test_stream_interrupted_classifies_as_non_retryable_error() -> None:
    error_type, severity, hint = classify_llm_error(
        StreamInterruptedError("stream died mid-output", partial_chars=10)
    )
    assert error_type == "stream_interrupted"
    assert severity == "error"
    assert "Not auto-retried" in hint
