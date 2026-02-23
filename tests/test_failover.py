"""Tests for LLM failover — retry, backoff, model fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import pytest

from geode.llm.client import (
    FALLBACK_MODELS,
    MAX_RETRIES,
    _retry_with_backoff,
    call_llm,
)


class TestRetryWithBackoff:
    def test_success_on_first_try(self):
        fn = MagicMock(return_value="hello")
        result = _retry_with_backoff(fn, model="test-model")
        assert result == "hello"
        fn.assert_called_once_with(model="test-model")

    @patch("geode.llm.client.time.sleep")
    def test_retry_on_rate_limit(self, mock_sleep):
        fn = MagicMock(
            side_effect=[anthropic.RateLimitError.__new__(anthropic.RateLimitError), "ok"]
        )
        # Need to properly construct the error
        rate_err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
        rate_err.status_code = 429
        rate_err.message = "rate limited"
        fn.side_effect = [rate_err, "ok"]
        result = _retry_with_backoff(fn, model="test-model")
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once()

    @patch("geode.llm.client.time.sleep")
    def test_fallback_model_on_persistent_failure(self, mock_sleep):
        """After MAX_RETRIES on primary, should try fallback models."""
        rate_err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
        rate_err.status_code = 429
        rate_err.message = "rate limited"

        # Fail MAX_RETRIES times on primary, succeed on fallback
        side_effects = [rate_err] * MAX_RETRIES + ["fallback_ok"]
        fn = MagicMock(side_effect=side_effects)
        result = _retry_with_backoff(fn, model="primary-model")
        assert result == "fallback_ok"
        # Should have called with fallback model
        last_call = fn.call_args
        assert last_call.kwargs["model"] in FALLBACK_MODELS

    def test_bad_request_not_retried(self):
        """BadRequestError should not be retried."""
        bad_err = anthropic.BadRequestError.__new__(anthropic.BadRequestError)
        bad_err.status_code = 400
        bad_err.message = "invalid request"
        fn = MagicMock(side_effect=bad_err)
        with pytest.raises(anthropic.BadRequestError):
            _retry_with_backoff(fn, model="test-model")
        fn.assert_called_once()

    @patch("geode.llm.client.time.sleep")
    def test_all_models_exhausted_raises(self, mock_sleep):
        """When all models and retries fail, should raise last error."""
        rate_err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
        rate_err.status_code = 429
        rate_err.message = "rate limited"

        # All calls fail
        fn = MagicMock(side_effect=rate_err)
        with pytest.raises(anthropic.RateLimitError):
            _retry_with_backoff(fn, model="primary-model")


class TestCallLlmFailover:
    @patch("geode.llm.client.get_anthropic_client")
    def test_call_llm_success(self, mock_client_fn):
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "response text"
        mock_response.content = [mock_block]
        mock_client_fn.return_value.messages.create.return_value = mock_response

        result = call_llm("sys", "usr", model="test")
        assert result == "response text"

    @patch("geode.llm.client.time.sleep")
    @patch("geode.llm.client.get_anthropic_client")
    def test_call_llm_retries_on_failure(self, mock_client_fn, mock_sleep):
        rate_err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
        rate_err.status_code = 429
        rate_err.message = "rate limited"

        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "recovered"
        mock_response.content = [mock_block]

        mock_client_fn.return_value.messages.create.side_effect = [rate_err, mock_response]

        result = call_llm("sys", "usr", model="test")
        assert result == "recovered"


class TestFallbackModels:
    def test_fallback_models_defined(self):
        assert len(FALLBACK_MODELS) >= 1

    def test_max_retries_positive(self):
        assert MAX_RETRIES >= 1
