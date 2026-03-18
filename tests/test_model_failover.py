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
from unittest.mock import MagicMock, patch

import anthropic
from core.config import ANTHROPIC_FALLBACK_CHAIN, ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY, settings
from core.llm.client import call_with_failover

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
        """AuthenticationError should NOT trigger failover — immediate abort."""
        auth_err = _make_auth_error()
        call_count = {"n": 0}

        async def call_fn(model: str) -> None:
            call_count["n"] += 1
            raise auth_err

        response, used_model = asyncio.run(
            call_with_failover(
                [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY],
                call_fn,
                max_retries=3,
                retry_base_delay=0.0,
            )
        )
        assert response is None
        assert used_model is None
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


# ---------------------------------------------------------------------------
# Fallback chain configuration
# ---------------------------------------------------------------------------


class TestFallbackChainConfig:
    """Verify that fallback chain constants are properly defined."""

    def test_anthropic_chain_has_primary(self) -> None:
        assert ANTHROPIC_PRIMARY in ANTHROPIC_FALLBACK_CHAIN

    def test_anthropic_chain_has_secondary(self) -> None:
        assert ANTHROPIC_SECONDARY in ANTHROPIC_FALLBACK_CHAIN

    def test_anthropic_chain_primary_is_first(self) -> None:
        assert ANTHROPIC_FALLBACK_CHAIN[0] == ANTHROPIC_PRIMARY

    def test_anthropic_chain_minimum_length(self) -> None:
        assert len(ANTHROPIC_FALLBACK_CHAIN) >= 2


# ---------------------------------------------------------------------------
# AgenticLoop._call_llm integration (mocked)
# ---------------------------------------------------------------------------


class TestAgenticLoopFailover:
    """Verify AgenticLoop._call_llm uses call_with_failover."""

    def _make_loop(self, model: str | None = None) -> Any:
        """Create a minimal AgenticLoop instance for testing."""
        from core.cli.agentic_loop import AgenticLoop
        from core.cli.conversation import ConversationContext
        from core.cli.tool_executor import ToolExecutor

        context = ConversationContext()
        executor = MagicMock(spec=ToolExecutor)
        return AgenticLoop(
            context=context,
            tool_executor=executor,
            model=model or ANTHROPIC_PRIMARY,
            max_rounds=5,
        )

    @patch("core.cli.agentic_loop.call_with_failover")
    @patch("core.cli.agentic_loop.get_async_anthropic_client")
    def test_call_llm_uses_failover(
        self, mock_get_client: MagicMock, mock_failover: MagicMock
    ) -> None:
        """_call_llm should delegate to call_with_failover."""
        mock_response = MagicMock()
        mock_failover.return_value = (mock_response, ANTHROPIC_PRIMARY)
        mock_get_client.return_value = MagicMock()

        loop = self._make_loop()

        result = asyncio.run(
            loop._call_llm("system prompt", [{"role": "user", "content": "hello"}])
        )
        assert result is mock_response
        mock_failover.assert_called_once()

    @patch("core.cli.agentic_loop.call_with_failover")
    @patch("core.cli.agentic_loop.get_async_anthropic_client")
    def test_call_llm_returns_none_on_chain_exhaustion(
        self, mock_get_client: MagicMock, mock_failover: MagicMock
    ) -> None:
        """When call_with_failover returns (None, None), _call_llm returns None."""
        mock_failover.return_value = (None, None)
        mock_get_client.return_value = MagicMock()

        loop = self._make_loop()

        result = asyncio.run(
            loop._call_llm("system prompt", [{"role": "user", "content": "hello"}])
        )
        assert result is None
        assert loop._last_llm_error is not None

    @patch("core.cli.agentic_loop.call_with_failover")
    @patch("core.cli.agentic_loop.get_async_anthropic_client")
    def test_call_llm_logs_model_switch(
        self, mock_get_client: MagicMock, mock_failover: MagicMock
    ) -> None:
        """When failover switches model, it should be logged."""
        mock_response = MagicMock()
        mock_failover.return_value = (mock_response, ANTHROPIC_SECONDARY)
        mock_get_client.return_value = MagicMock()

        loop = self._make_loop(model=ANTHROPIC_PRIMARY)

        with patch("core.cli.agentic_loop.log") as mock_log:
            result = asyncio.run(
                loop._call_llm("system prompt", [{"role": "user", "content": "hello"}])
            )
            assert result is mock_response
            # Verify warning log about model switch
            mock_log.warning.assert_called()
            warning_args = mock_log.warning.call_args_list
            found_switch_log = any("Model failover" in str(args) for args in warning_args)
            assert found_switch_log, "Expected 'Model failover' warning log"

    def test_call_llm_no_api_key_returns_none(self) -> None:
        """When no API key is set, _call_llm returns None immediately."""
        loop = self._make_loop()

        with patch.object(settings, "anthropic_api_key", ""):
            result = asyncio.run(loop._call_llm("system", [{"role": "user", "content": "hi"}]))
        assert result is None

    @patch("core.cli.agentic_loop.call_with_failover")
    @patch("core.cli.agentic_loop.get_async_anthropic_client")
    def test_failover_chain_includes_current_model_first(
        self, mock_get_client: MagicMock, mock_failover: MagicMock
    ) -> None:
        """The failover chain passed to call_with_failover starts with self.model."""
        mock_failover.return_value = (MagicMock(), ANTHROPIC_PRIMARY)
        mock_get_client.return_value = MagicMock()

        loop = self._make_loop(model=ANTHROPIC_PRIMARY)
        asyncio.run(loop._call_llm("system prompt", [{"role": "user", "content": "hello"}]))

        # Extract the models argument from the call
        call_args = mock_failover.call_args
        models = call_args[0][0]  # first positional arg
        assert models[0] == ANTHROPIC_PRIMARY
        # No duplicates
        assert len(models) == len(set(models))
