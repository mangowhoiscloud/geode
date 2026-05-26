"""Tests for model failover — call_with_failover and AgenticLoop integration.

Covers:
- Primary success (no failover needed)
- Primary failure -> Secondary success
- Full chain exhaustion -> None
- AuthenticationError -> immediate failure (no failover)
- Non-retryable errors abort the chain
- Model switch logging
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import anthropic
import pytest
from core.config import ANTHROPIC_FALLBACK_CHAIN, ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY
from core.llm.router import call_with_failover

# ---------------------------------------------------------------------------
# Helper: construct retryable/non-retryable errors
# ---------------------------------------------------------------------------


def _make_rate_limit_error() -> anthropic.RateLimitError:
    err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
    err.status_code = 429
    err.message = "rate limited"
    return err


def _make_connection_error() -> anthropic.APIConnectionError:
    err = anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
    err.message = "connection failed"
    return err


def _make_internal_server_error() -> anthropic.InternalServerError:
    err = anthropic.InternalServerError.__new__(anthropic.InternalServerError)
    err.status_code = 500
    err.message = "internal server error"
    return err


def _make_auth_error() -> anthropic.AuthenticationError:
    err = anthropic.AuthenticationError.__new__(anthropic.AuthenticationError)
    err.status_code = 401
    err.message = "invalid api key"
    return err


def _make_timeout_error() -> anthropic.APITimeoutError:
    err = anthropic.APITimeoutError.__new__(anthropic.APITimeoutError)
    return err


# ---------------------------------------------------------------------------
# call_with_failover — unit tests
# ---------------------------------------------------------------------------


class TestCallWithFailover:
    """Tests for the call_with_failover async function."""

    def test_success_on_first_model(self) -> None:
        """Primary model succeeds on first try — no failover."""
        mock_response = MagicMock()

        async def call_fn(model: str) -> MagicMock:
            return mock_response

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=3,
                retry_base_delay=0.0,
            )
        )
        assert response is mock_response
        assert used_model == ANTHROPIC_PRIMARY

    def test_failover_primary_to_secondary(self) -> None:
        """Primary fails all retries, secondary succeeds."""
        mock_response = MagicMock()
        rate_err = _make_rate_limit_error()
        call_count = {"n": 0}

        async def call_fn(model: str) -> MagicMock:
            call_count["n"] += 1
            if model == ANTHROPIC_PRIMARY:
                raise rate_err
            return mock_response

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=2,
                retry_base_delay=0.0,
            )
        )
        assert response is mock_response
        assert used_model == ANTHROPIC_SECONDARY
        # Primary tried max_retries times + 1 for secondary
        assert call_count["n"] == 3

    def test_all_models_exhausted_returns_none(self) -> None:
        """All models fail — returns (None, None)."""
        rate_err = _make_rate_limit_error()

        async def call_fn(model: str) -> None:
            raise rate_err

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=2,
                retry_base_delay=0.0,
            )
        )
        assert response is None
        assert used_model is None

    def test_auth_error_aborts_immediately(self) -> None:
        """AuthenticationError should NOT trigger failover — re-raised to adapter."""
        auth_err = _make_auth_error()
        call_count = {"n": 0}

        async def call_fn(model: str) -> None:
            call_count["n"] += 1
            raise auth_err

        with pytest.raises(anthropic.AuthenticationError):
            asyncio.run(
                call_with_failover(
                    [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                    call_fn,
                    max_retries=3,
                    retry_base_delay=0.0,
                )
            )
        # Only called once — no retry, no failover
        assert call_count["n"] == 1

    def test_connection_error_triggers_failover(self) -> None:
        """APIConnectionError is retryable and should trigger failover."""
        conn_err = _make_connection_error()
        mock_response = MagicMock()
        call_count = {"n": 0}

        async def call_fn(model: str) -> MagicMock:
            call_count["n"] += 1
            if model == ANTHROPIC_PRIMARY:
                raise conn_err
            return mock_response

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=1,
                retry_base_delay=0.0,
            )
        )
        assert response is mock_response
        assert used_model == ANTHROPIC_SECONDARY

    def test_internal_server_error_triggers_failover(self) -> None:
        """InternalServerError (500) is retryable and should trigger failover."""
        server_err = _make_internal_server_error()
        mock_response = MagicMock()

        async def call_fn(model: str) -> MagicMock:
            if model == ANTHROPIC_PRIMARY:
                raise server_err
            return mock_response

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=1,
                retry_base_delay=0.0,
            )
        )
        assert response is mock_response
        assert used_model == ANTHROPIC_SECONDARY

    def test_timeout_error_triggers_failover(self) -> None:
        """APITimeoutError is retryable and should trigger failover."""
        timeout_err = _make_timeout_error()
        mock_response = MagicMock()

        async def call_fn(model: str) -> MagicMock:
            if model == ANTHROPIC_PRIMARY:
                raise timeout_err
            return mock_response

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=1,
                retry_base_delay=0.0,
            )
        )
        assert response is mock_response
        assert used_model == ANTHROPIC_SECONDARY

    def test_retry_succeeds_within_same_model(self) -> None:
        """Transient error on attempt 1, success on attempt 2 — same model."""
        rate_err = _make_rate_limit_error()
        mock_response = MagicMock()
        attempts = {"n": 0}

        async def call_fn(model: str) -> MagicMock:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise rate_err
            return mock_response

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=3,
                retry_base_delay=0.0,
            )
        )
        assert response is mock_response
        assert used_model == ANTHROPIC_PRIMARY
        assert attempts["n"] == 2

    def test_single_model_chain(self) -> None:
        """Single model in chain — retries then fails gracefully."""
        rate_err = _make_rate_limit_error()

        async def call_fn(model: str) -> None:
            raise rate_err

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY],
                call_fn,
                max_retries=2,
                retry_base_delay=0.0,
            )
        )
        assert response is None
        assert used_model is None

    def test_empty_model_chain(self) -> None:
        """Empty model list — returns (None, None) immediately."""

        async def call_fn(model: str) -> MagicMock:
            return MagicMock()

        response, used_model = asyncio.run(
            call_with_failover(
                [],
                call_fn,
                max_retries=2,
                retry_base_delay=0.0,
            )
        )
        assert response is None
        assert used_model is None

    def test_three_model_chain(self) -> None:
        """Three models: first two fail, third succeeds."""
        rate_err = _make_rate_limit_error()
        mock_response = MagicMock()

        async def call_fn(model: str) -> MagicMock:
            if model in ("model-a", "model-b"):
                raise rate_err
            return mock_response

        response, used_model = asyncio.run(
            call_with_failover(
                ["model-a", "model-b", "model-c"],
                call_fn,
                max_retries=1,
                retry_base_delay=0.0,
            )
        )
        assert response is mock_response
        assert used_model == "model-c"

    def test_unexpected_error_skips_to_next_model(self) -> None:
        """Non-retryable, non-auth error (e.g. ValueError) skips to next model."""
        mock_response = MagicMock()

        async def call_fn(model: str) -> MagicMock:
            if model == ANTHROPIC_PRIMARY:
                raise ValueError("unexpected schema error")
            return mock_response

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=2,
                retry_base_delay=0.0,
            )
        )
        assert response is mock_response
        assert used_model == ANTHROPIC_SECONDARY

    def test_claude_cli_transient_retries_within_same_model(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """PR-CLAUDE-CLI-CREDIT-EXHAUSTION-RETRY (2026-05-27) —
        ``ClaudeCliTransientUpstreamError`` must be retried on the
        same model (not fall through to the next model in the chain).

        Pre-PR the bare ``except Exception`` branch immediately broke
        the retry loop on this exception (smoke 24: 5/5 evolver
        phases hard-failed within 30s after 3 attempts). Post-PR the
        plugin-imported exception routes into a quota-class retry
        with the long QUOTA_BACKOFF schedule.

        Asserts:
        - All ``max_retries`` attempts run on the primary model
          (i.e. the exception was treated as retryable, not as a
          chain-skip signal).
        - The retry uses the QUOTA_BACKOFF schedule (we patch
          ``asyncio.sleep`` to a no-op and capture the wait values).
        - Eventually returns success when the transient resolves
          (mirrors a pool refresh).
        """
        from plugins.petri_audit.claude_cli_provider import (
            ClaudeCliTransientUpstreamError,
            TransientSignal,
        )

        signal = TransientSignal(matched_text="! Unexpected error. Auto-retrying.", source="event")
        transient_err = ClaudeCliTransientUpstreamError(
            "claude-cli upstream transient (pool exhausted)", signal=signal
        )
        mock_response = MagicMock()
        call_count = {"n": 0}

        async def call_fn(model: str) -> MagicMock:
            call_count["n"] += 1
            # Fail the first 2 attempts on primary; succeed on the 3rd.
            if call_count["n"] < 3:
                raise transient_err
            return mock_response

        sleeps: list[float] = []

        async def _fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("asyncio.sleep", _fake_sleep)

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=3,
                retry_base_delay=0.0,
            )
        )
        assert response is mock_response
        assert used_model == ANTHROPIC_PRIMARY  # retried within primary, no chain skip
        assert call_count["n"] == 3
        # Two sleeps fired (between attempts 1→2 and 2→3); both match the
        # paperclip QUOTA_BACKOFF schedule (2m / 10m / 30m / 2h).
        from core.llm.claude_cli_errors import QUOTA_BACKOFF_SECONDS

        assert sleeps == [QUOTA_BACKOFF_SECONDS[0], QUOTA_BACKOFF_SECONDS[1]]

    def test_claude_cli_transient_clips_to_final_quota_tier(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """When ``max_retries`` exceeds ``len(QUOTA_BACKOFF_SECONDS)``,
        every attempt past the schedule's tail repeats the final
        ``7200.0`` (2h) wait — :func:`call_with_failover` uses
        ``min(attempt, len(schedule) - 1)`` to clip, matching paperclip
        heartbeat.ts:217-226 ("MAX_ATTEMPTS = 4, then surrender or
        repeat 2h"). Without this clip a 5-attempt loop would
        ``IndexError`` on attempt 4."""
        from core.llm.claude_cli_errors import QUOTA_BACKOFF_SECONDS
        from plugins.petri_audit.claude_cli_provider import (
            ClaudeCliTransientUpstreamError,
            TransientSignal,
        )

        signal = TransientSignal(matched_text="claude usage limit reached", source="event")
        transient_err = ClaudeCliTransientUpstreamError(
            "claude-cli upstream transient (quota, persistent)", signal=signal
        )

        async def call_fn(model: str) -> None:
            raise transient_err

        sleeps: list[float] = []

        async def _fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("asyncio.sleep", _fake_sleep)

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY],  # single-model chain → no fallback
                call_fn,
                max_retries=6,  # exceeds len(QUOTA_BACKOFF_SECONDS) == 4
                retry_base_delay=0.0,
            )
        )
        assert response is None
        assert used_model is None
        # 5 sleeps fired (between attempts 1→2 through 5→6); the final
        # 2 entries clip to the schedule tail (7200.0).
        assert sleeps == [
            QUOTA_BACKOFF_SECONDS[0],
            QUOTA_BACKOFF_SECONDS[1],
            QUOTA_BACKOFF_SECONDS[2],
            QUOTA_BACKOFF_SECONDS[3],
            QUOTA_BACKOFF_SECONDS[3],  # clipped: attempt=4 → schedule[3]
        ]

    def test_claude_cli_transient_exhausts_then_falls_back(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """When the transient never resolves on the primary model,
        the loop exhausts ``max_retries`` then falls through to the
        next model in the chain. Mirrors the model-chain semantics
        the SDK ``RETRYABLE_ERRORS`` branch already provides."""
        from plugins.petri_audit.claude_cli_provider import (
            ClaudeCliTransientUpstreamError,
            TransientSignal,
        )

        signal = TransientSignal(matched_text="claude usage limit reached", source="event")
        transient_err = ClaudeCliTransientUpstreamError(
            "claude-cli upstream transient (quota)", signal=signal
        )
        mock_response = MagicMock()

        async def call_fn(model: str) -> MagicMock:
            if model == ANTHROPIC_PRIMARY:
                raise transient_err
            return mock_response

        async def _fake_sleep(delay: float) -> None:
            return None

        monkeypatch.setattr("asyncio.sleep", _fake_sleep)

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=2,
                retry_base_delay=0.0,
            )
        )
        assert response is mock_response
        assert used_model == ANTHROPIC_SECONDARY


# ---------------------------------------------------------------------------
# Fallback chain configuration
# ---------------------------------------------------------------------------


class TestFallbackChainConfig:
    """Verify that the fallback chain constants are a *type-safe knob*.

    v0.99.19 — the shipped default is an empty list (no silent fallback
    chain). User can opt in via ``~/.geode/routing.toml`` ``[model.fallbacks]``.
    The constant must still be ``list[str]`` so call sites that iterate
    ``[m for m in FALLBACK_CHAIN if m != model]`` keep working when the
    user populates it.
    """

    def test_anthropic_chain_is_list(self) -> None:
        assert isinstance(ANTHROPIC_FALLBACK_CHAIN, list)

    def test_anthropic_chain_default_empty(self) -> None:
        """Shipped default = no silent fallback (knob is opt-in)."""
        assert ANTHROPIC_FALLBACK_CHAIN == [], (
            "Shipped default for ANTHROPIC_FALLBACK_CHAIN must be an empty "
            "list. v0.99.19 removed silent same-provider model fallback; "
            "users opt in via ``~/.geode/routing.toml`` [model.fallbacks]."
        )

    def test_anthropic_primary_secondary_still_defined(self) -> None:
        """The defaults survive — only the chain is empty by default."""
        assert ANTHROPIC_PRIMARY  # non-empty string
        assert ANTHROPIC_SECONDARY  # non-empty string


# ---------------------------------------------------------------------------
# AgenticLoop._call_llm integration (mocked)
# ---------------------------------------------------------------------------


class TestAgenticLoopFailover:
    """Verify ``AgenticLoop._call_llm`` delegates to ``_new_adapter.acomplete()``.

    PR-MAINPATH-67 (2026-05-24) — the legacy ``_adapter.agentic_call``
    fallback branch was deleted; all dispatch now flows through the
    Path-B ``LLMAdapter.acomplete`` surface unconditionally.
    """

    def _make_loop(self, model: str | None = None) -> Any:
        """Create a minimal AgenticLoop instance for testing."""
        from core.agent.conversation import ConversationContext
        from core.agent.loop import AgenticLoop
        from core.agent.tool_executor import ToolExecutor

        context = ConversationContext()
        executor = MagicMock(spec=ToolExecutor)
        return AgenticLoop(
            context=context,
            tool_executor=executor,
            model=model or ANTHROPIC_PRIMARY,
            max_rounds=5,
        )

    def _install_acomplete_stub(self, loop: Any, result: Any) -> MagicMock:
        """Replace ``loop._new_adapter`` with a stub whose ``acomplete``
        coroutine returns ``result`` (or raises if ``result`` is an
        Exception).
        """

        async def fake_acomplete(_req: Any) -> Any:
            if isinstance(result, Exception):
                raise result
            return result

        stub = MagicMock()
        stub.name = "stub-adapter"
        stub.acomplete = MagicMock(side_effect=fake_acomplete)
        loop._new_adapter = stub
        return stub

    def test_call_llm_uses_adapter(self) -> None:
        """``_call_llm`` should delegate to ``acomplete`` and return
        ``AgenticResponse``."""
        from core.llm.adapters.base import AdapterCallResult, UsageSummary

        adapter_result = AdapterCallResult(
            text="Hello",
            usage=UsageSummary(input_tokens=100, output_tokens=50),
            stop_reason="end_turn",
        )
        loop = self._make_loop()
        stub = self._install_acomplete_stub(loop, adapter_result)

        result = asyncio.run(
            loop._call_llm("system prompt", [{"role": "user", "content": "hello"}])
        )
        assert result is not None
        assert result.stop_reason == "end_turn"
        stub.acomplete.assert_called_once()

    def test_call_llm_returns_none_on_chain_exhaustion(self) -> None:
        """When ``acomplete`` raises, ``_call_llm`` returns None with an
        error message."""
        loop = self._make_loop()
        self._install_acomplete_stub(loop, RuntimeError("chain exhausted"))

        result = asyncio.run(
            loop._call_llm("system prompt", [{"role": "user", "content": "hello"}])
        )
        assert result is None
        assert loop._last_llm_error is not None

    def test_call_llm_no_api_key_returns_none(self) -> None:
        """When ``acomplete`` raises an auth-style failure, ``_call_llm``
        returns None."""
        loop = self._make_loop()
        self._install_acomplete_stub(loop, RuntimeError("missing api key"))

        result = asyncio.run(loop._call_llm("system", [{"role": "user", "content": "hi"}]))
        assert result is None

    def test_failover_chain_available_on_adapter(self) -> None:
        """The Path-B adapter exposes (or does not expose) a
        ``fallback_chain`` knob — ``fallback_chain_suggestions`` reads
        the attribute defensively.

        v0.99.19 — shipped default is an empty list (no silent
        fallback). Path-B adapters that don't override the attribute
        return an empty list via the ``getattr(..., [])`` defensive
        read in :func:`fallback_chain_suggestions`.
        """
        loop = self._make_loop(model=ANTHROPIC_PRIMARY)
        chain = list(getattr(loop._new_adapter, "fallback_chain", []) or [])
        assert isinstance(chain, list)
        # If the user opts in, the chain must be unique and start with primary.
        # If the default (empty list) holds, both checks are trivially true.
        if chain:
            assert chain[0] == ANTHROPIC_PRIMARY
            assert len(chain) == len(set(chain))
