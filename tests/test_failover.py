"""Tests for LLM failover — retry, backoff, model fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import pytest
from core.llm.providers.anthropic import retry_with_backoff as _retry_with_backoff
from core.llm.fallback import MAX_RETRIES
from core.llm.providers.anthropic import FALLBACK_MODELS
from core.llm.router import call_llm, call_llm_json


class TestRetryWithBackoff:
    def test_success_on_first_try(self):
        fn = MagicMock(return_value="hello")
        result = _retry_with_backoff(fn, model="test-model")
        assert result == "hello"
        fn.assert_called_once_with(model="test-model")

    @patch("core.llm.fallback.time.sleep")
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
        # Filter out background spinner sleeps (always exactly 0.08s from
        # ``core.ui.{event_renderer,status,tool_tracker}._animate``) so we
        # only count the genuine retry-backoff sleep emitted by
        # ``_retry_with_backoff`` itself. ``@patch("core.llm.fallback.time.sleep")``
        # rebinds the ``time`` module attribute, which is shared across
        # every module that ``import time``, so daemon spinner threads
        # started by a prior test leak into this mock's call_args_list.
        retry_sleeps = [c for c in mock_sleep.call_args_list if c.args[0] != 0.08]
        assert len(retry_sleeps) == 1, retry_sleeps

    @patch("core.llm.fallback.time.sleep")
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

        fn = MagicMock(side_effect=rate_err)
        with pytest.raises(anthropic.RateLimitError):
            _retry_with_backoff(fn, model="primary-model")

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
        fn = MagicMock(side_effect=bad_err)
        with pytest.raises(anthropic.BadRequestError):
            _retry_with_backoff(fn, model="test-model")
        fn.assert_called_once()

    @patch("core.llm.fallback.time.sleep")
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
    @patch("core.llm.router.calls.text.get_anthropic_client")
    def test_call_llm_success(self, mock_client_fn):
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "response text"
        mock_response.content = [mock_block]
        mock_client_fn.return_value.messages.create.return_value = mock_response

        result = call_llm("sys", "usr", model="claude-test")
        assert result == "response text"

    @patch("core.llm.fallback.time.sleep")
    @patch("core.llm.router.calls.text.get_anthropic_client")
    def test_call_llm_retries_on_failure(self, mock_client_fn, mock_sleep):
        rate_err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
        rate_err.status_code = 429
        rate_err.message = "rate limited"

        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "recovered"
        mock_response.content = [mock_block]

        mock_client_fn.return_value.messages.create.side_effect = [rate_err, mock_response]

        result = call_llm("sys", "usr", model="claude-test")
        assert result == "recovered"


class TestFallbackModels:
    def test_fallback_models_default_empty(self):
        """v0.99.19 — shipped default knob is empty (no silent fallback)."""
        assert isinstance(FALLBACK_MODELS, list)
        assert FALLBACK_MODELS == [], (
            "Shipped FALLBACK_MODELS must default to empty. "
            "Users opt in via ~/.geode/routing.toml [model.fallbacks]."
        )

    def test_max_retries_positive(self):
        assert MAX_RETRIES >= 1


class TestCallLlmJsonExtraction:
    """Tests for robust JSON extraction from LLM responses."""

    @patch("core.llm.router.calls.json.call_llm")
    def test_direct_json(self, mock_call):
        mock_call.return_value = '{"key": "value"}'
        result = call_llm_json("sys", "usr")
        assert result == {"key": "value"}

    @patch("core.llm.router.calls.json.call_llm")
    def test_json_with_markdown_fences(self, mock_call):
        mock_call.return_value = '```json\n{"key": "value"}\n```'
        result = call_llm_json("sys", "usr")
        assert result == {"key": "value"}

    @patch("core.llm.router.calls.json.call_llm")
    def test_json_embedded_in_text(self, mock_call):
        """LLM returns prose before/after JSON — extraction finds the object."""
        mock_call.return_value = (
            "Here is the evaluation result:\n\n"
            '{"evaluator_type": "quality_judge", "axes": {"a_score": 4.2}, '
            '"composite_score": 72.0, "rationale": "Good."}\n\n'
            "I hope this helps!"
        )
        result = call_llm_json("sys", "usr")
        assert result["evaluator_type"] == "quality_judge"
        assert result["composite_score"] == 72.0

    @patch("core.llm.router.calls.json.call_llm")
    def test_json_with_nested_braces(self, mock_call):
        mock_call.return_value = (
            'Some text\n{"axes": {"d_score": 4.0, "e_score": 3.0}, "rationale": "test"}\nMore text'
        )
        result = call_llm_json("sys", "usr")
        assert result["axes"]["d_score"] == 4.0

    @patch("core.llm.router.calls.json.call_llm")
    def test_no_json_raises_error(self, mock_call):
        mock_call.return_value = "This is a plain text response with no JSON."
        with pytest.raises(ValueError, match="invalid JSON"):
            call_llm_json("sys", "usr")

    @patch("core.llm.router.calls.json.call_llm")
    def test_whitespace_around_json(self, mock_call):
        mock_call.return_value = '  \n  {"key": 42}  \n  '
        result = call_llm_json("sys", "usr")
        assert result == {"key": 42}
