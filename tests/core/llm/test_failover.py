"""Tests for LLM failover — retry, backoff, model fallback."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import anthropic
import pytest
from core.config import ANTHROPIC_FALLBACK_CHAIN
from core.llm.fallback import MAX_RETRIES
from core.llm.providers.anthropic import retry_with_backoff_async as _retry_async


class TestRetryWithBackoffAsync:
    """Retry/fallback invariants on the surviving ASYNC path (the sync twin
    was deleted 2026-07-29 with the rest of the sync LLM stack)."""

    def test_success_on_first_try(self):
        fn = AsyncMock(return_value="hello")
        result = asyncio.run(_retry_async(fn, model="test-model"))
        assert result == "hello"
        fn.assert_called_once_with(model="test-model")

    @patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock)
    def test_retry_on_rate_limit(self, mock_sleep):
        fn = AsyncMock(
            side_effect=[anthropic.RateLimitError.__new__(anthropic.RateLimitError), "ok"]
        )
        # Need to properly construct the error
        rate_err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
        rate_err.status_code = 429
        rate_err.message = "rate limited"
        fn.side_effect = [rate_err, "ok"]
        result = asyncio.run(_retry_async(fn, model="test-model"))
        assert result == "ok"
        assert fn.call_count == 2
        # Filter out background spinner sleeps (always exactly 0.08s from
        # ``core.ui.{event_renderer,status,tool_tracker}._animate``) so we
        # only count the genuine retry-backoff sleep emitted by
        # ``retry_with_backoff_async`` itself. ``@patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock)``
        # rebinds the ``time`` module attribute, which is shared across
        # every module that ``import time``, so daemon spinner threads
        # started by a prior test leak into this mock's call_args_list.
        retry_sleeps = [c for c in mock_sleep.call_args_list if c.args[0] != 0.08]
        assert len(retry_sleeps) == 1, retry_sleeps

    @patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock)
    def test_no_silent_fallback_to_other_models(self, mock_sleep):
        """v0.99.19 invariant: shipped default `FALLBACK_MODELS` is empty.

        Pre-fix the loop tried each model in the chain after MAX_RETRIES
        exhausted the primary. With the shipped knob default empty, the
        loop attempts ``MAX_RETRIES`` calls against the supplied model
        and then raises — no silent swap. Users who opt in via
        ``~/.geode/routing.toml`` get the chain behaviour back; the
        invariant here pins the *default* behaviour.
        """
        rate_err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
        rate_err.status_code = 429
        rate_err.message = "rate limited"

        fn = AsyncMock(side_effect=rate_err)
        with pytest.raises(anthropic.RateLimitError):
            asyncio.run(_retry_async(fn, model="primary-model"))

        # Every call must have been against the primary model.
        for call in fn.call_args_list:
            assert call.kwargs["model"] == "primary-model", (
                f"silent fallback to {call.kwargs['model']!r} detected — "
                "shipped knob default forbids same-provider chain."
            )
        assert fn.call_count == MAX_RETRIES

    def test_bad_request_not_retried(self):
        """BadRequestError should not be retried."""
        bad_err = anthropic.BadRequestError.__new__(anthropic.BadRequestError)
        bad_err.status_code = 400
        bad_err.message = "invalid request"
        fn = AsyncMock(side_effect=bad_err)
        with pytest.raises(anthropic.BadRequestError):
            asyncio.run(_retry_async(fn, model="test-model"))
        fn.assert_called_once()

    @patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock)
    def test_all_models_exhausted_raises(self, mock_sleep):
        """When all models and retries fail, should raise last error."""
        rate_err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
        rate_err.status_code = 429
        rate_err.message = "rate limited"

        # All calls fail
        fn = AsyncMock(side_effect=rate_err)
        with pytest.raises(anthropic.RateLimitError):
            asyncio.run(_retry_async(fn, model="primary-model"))


class TestFallbackModels:
    def test_fallback_models_default_empty(self):
        """v0.99.19 — shipped default knob is empty (no silent fallback).

        H11-tail (v0.99.220): asserts against the live SoT
        ``core.config.ANTHROPIC_FALLBACK_CHAIN`` (the per-provider module
        alias ``FALLBACK_MODELS`` was removed; consumers read core.config live)."""
        assert isinstance(ANTHROPIC_FALLBACK_CHAIN, list)
        assert ANTHROPIC_FALLBACK_CHAIN == [], (
            "Shipped anthropic fallback chain must default to empty. "
            "Users opt in via ~/.geode/routing.toml [model.fallbacks]."
        )

    def test_max_retries_positive(self):
        assert MAX_RETRIES >= 1
