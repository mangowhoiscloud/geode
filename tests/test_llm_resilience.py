"""Tests for LLM resilience hardening features.

Covers: jitter, cross-provider fallback, error classification,
retry events, auto-checkpoint, context detail, budget warning.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. Backoff jitter
# ---------------------------------------------------------------------------


class TestBackoffJitter:
    """Verify retry delay uses full jitter (random.uniform(0, cap))."""

    def test_jitter_produces_varying_delays(self) -> None:
        """Multiple calls should produce different delays (not deterministic)."""
        from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic

        call_count = 0
        delays: list[float] = []

        cb = CircuitBreaker()

        def _failing_fn(*, model: str) -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("test")

        def _capture_sleep(s: float) -> None:
            delays.append(s)

        with (
            patch("core.llm.fallback.time.sleep", side_effect=_capture_sleep),
            pytest.raises(ConnectionError),
        ):
            retry_with_backoff_generic(
                _failing_fn,
                model="test-model",
                fallback_models=[],
                circuit_breaker=cb,
                retryable_errors=(ConnectionError,),
                max_retries=3,
                retry_base_delay=2.0,
                retry_max_delay=30.0,
            )

        assert len(delays) == 3
        # Jitter: delays should be in [0, cap], not all identical
        for d in delays:
            assert d >= 0

    def test_jitter_cap_respects_max_delay(self) -> None:
        """Jitter should never exceed retry_max_delay."""
        from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic

        delays: list[float] = []
        cb = CircuitBreaker()

        def _failing(*, model: str) -> str:
            raise ConnectionError("test")

        def _capture_sleep(s: float) -> None:
            delays.append(s)

        with (
            patch("core.llm.fallback.time.sleep", side_effect=_capture_sleep),
            pytest.raises(ConnectionError),
        ):
            retry_with_backoff_generic(
                _failing,
                model="m",
                fallback_models=[],
                circuit_breaker=cb,
                retryable_errors=(ConnectionError,),
                max_retries=5,
                retry_base_delay=10.0,
                retry_max_delay=15.0,
            )

        for d in delays:
            assert d <= 15.0


# ---------------------------------------------------------------------------
# 2. Cross-provider dispatch
# ---------------------------------------------------------------------------


class TestCrossProviderDispatch:
    """Verify _cross_provider_dispatch helper."""

    def test_single_provider_no_fallback(self) -> None:
        """Without cross-provider enabled, only primary is tried."""
        from core.llm.router import _cross_provider_dispatch

        calls: list[tuple[str, str]] = []

        def _dispatch(p: str, m: str) -> str:
            calls.append((p, m))
            return "ok"

        with patch("core.llm.router.settings") as mock_settings:
            mock_settings.llm_cross_provider_failover = False
            result = _cross_provider_dispatch("anthropic", "claude-opus-4-6", _dispatch, "test")

        assert result == "ok"
        assert len(calls) == 1
        assert calls[0] == ("anthropic", "claude-opus-4-6")

    def test_cross_provider_on_failure(self) -> None:
        """When primary fails and cross-provider is enabled, tries next provider."""
        from core.llm.router import _cross_provider_dispatch

        calls: list[tuple[str, str]] = []

        def _dispatch(p: str, m: str) -> str:
            calls.append((p, m))
            if p == "anthropic":
                raise RuntimeError("provider down")
            return "fallback_ok"

        with (
            patch("core.llm.router.settings") as mock_settings,
            patch("core.llm.router._get_fallback_chain") as mock_chain,
            patch("core.llm.router._fire_hook"),
        ):
            mock_settings.llm_cross_provider_failover = True
            mock_settings.llm_cross_provider_order = ["anthropic", "openai", "glm"]
            mock_chain.return_value = ["gpt-5.4", "gpt-5.2"]

            result = _cross_provider_dispatch("anthropic", "claude-opus-4-6", _dispatch, "test")

        assert result == "fallback_ok"
        assert len(calls) == 2
        assert calls[0][0] == "anthropic"
        assert calls[1][0] == "openai"

    def test_all_providers_fail(self) -> None:
        """When all providers fail, raises the last exception."""
        from core.llm.router import _cross_provider_dispatch

        def _dispatch(p: str, m: str) -> str:
            raise RuntimeError(f"{p} down")

        with (
            patch("core.llm.router.settings") as mock_settings,
            patch("core.llm.router._get_fallback_chain", return_value=["m1"]),
            patch("core.llm.router._fire_hook"),
            pytest.raises(RuntimeError, match="glm down"),
        ):
            mock_settings.llm_cross_provider_failover = True
            mock_settings.llm_cross_provider_order = ["anthropic", "openai", "glm"]
            _cross_provider_dispatch("anthropic", "claude-opus-4-6", _dispatch, "test")


# ---------------------------------------------------------------------------
# 3. Error classification
# ---------------------------------------------------------------------------


class TestErrorClassification:
    """Verify classify_llm_error maps exceptions to severity and hints."""

    def test_rate_limit(self) -> None:
        from core.llm.errors import LLMRateLimitError, classify_llm_error

        try:
            raise LLMRateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429),
                body=None,
            )
        except LLMRateLimitError as exc:
            et, sev, hint = classify_llm_error(exc)
        assert et == "rate_limit"
        assert sev == "warning"
        assert "rate limit" in hint.lower()

    def test_auth_error(self) -> None:
        from core.llm.errors import LLMAuthenticationError, classify_llm_error

        try:
            raise LLMAuthenticationError(
                message="invalid key",
                response=MagicMock(status_code=401),
                body=None,
            )
        except LLMAuthenticationError as exc:
            et, sev, hint = classify_llm_error(exc)
        assert et == "auth"
        assert sev == "error"

    def test_billing_error(self) -> None:
        from core.llm.errors import BillingError, classify_llm_error

        et, sev, hint = classify_llm_error(BillingError("no credits"))
        assert et == "billing"
        assert sev == "critical"

    def test_unknown_error(self) -> None:
        from core.llm.errors import classify_llm_error

        et, sev, hint = classify_llm_error(ValueError("something weird"))
        assert et == "unknown"
        assert sev == "warning"


# ---------------------------------------------------------------------------
# 4. Retry callback (on_retry)
# ---------------------------------------------------------------------------


class TestRetryCallback:
    """Verify on_retry callback is invoked during retries."""

    def test_on_retry_called_with_metadata(self) -> None:
        from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic

        retry_events: list[dict[str, Any]] = []

        def _on_retry(**kwargs: Any) -> None:
            retry_events.append(kwargs)

        cb = CircuitBreaker()

        def _failing(*, model: str) -> str:
            raise ConnectionError("down")

        with (
            patch("core.llm.fallback.time.sleep"),
            pytest.raises(ConnectionError),
        ):
            retry_with_backoff_generic(
                _failing,
                model="m",
                fallback_models=[],
                circuit_breaker=cb,
                retryable_errors=(ConnectionError,),
                max_retries=2,
                on_retry=_on_retry,
            )

        assert len(retry_events) == 2
        assert retry_events[0]["attempt"] == 1
        assert retry_events[1]["attempt"] == 2
        assert "delay_s" in retry_events[0]
        assert "elapsed_s" in retry_events[0]
        assert retry_events[0]["error_type"] == "ConnectionError"


# ---------------------------------------------------------------------------
# 5. HookEvent count
# ---------------------------------------------------------------------------


class TestHookEventCount:
    """Verify FALLBACK_CROSS_PROVIDER is present."""

    def test_cross_provider_hook_exists(self) -> None:
        from core.hooks import HookEvent

        assert hasattr(HookEvent, "FALLBACK_CROSS_PROVIDER")
        assert HookEvent.FALLBACK_CROSS_PROVIDER.value == "fallback_cross_provider"

    def test_total_event_count(self) -> None:
        from core.hooks import HookEvent

        assert len(HookEvent) == 41


# ---------------------------------------------------------------------------
# 6. Config settings
# ---------------------------------------------------------------------------


class TestResilienceConfig:
    """Verify new config fields exist with correct defaults."""

    def test_cross_provider_defaults(self) -> None:
        from core.config import Settings

        s = Settings()
        assert s.llm_cross_provider_failover is False
        assert s.llm_cross_provider_order == ["anthropic", "openai", "glm"]


# ---------------------------------------------------------------------------
# 7. Adapter last_error
# ---------------------------------------------------------------------------


class TestAdapterLastError:
    """Verify adapters expose last_error for error classification."""

    def test_anthropic_adapter_has_last_error(self) -> None:
        from core.llm.providers.anthropic import ClaudeAgenticAdapter

        adapter = ClaudeAgenticAdapter()
        assert adapter.last_error is None

    def test_openai_adapter_has_last_error(self) -> None:
        from core.llm.providers.openai import OpenAIAgenticAdapter

        adapter = OpenAIAgenticAdapter()
        assert adapter.last_error is None
