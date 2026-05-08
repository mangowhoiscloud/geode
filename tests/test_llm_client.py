"""Tests for LLM client JSON extraction and token usage tracking."""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

import pytest
from core.config import ANTHROPIC_BUDGET, ANTHROPIC_PRIMARY, OPENAI_PRIMARY
from core.llm.client import (
    LLMUsage,
    LLMUsageAccumulator,
    calculate_cost,
    get_usage_accumulator,
    reset_usage_accumulator,
)


def _strip_fences(raw: str) -> str:
    """Reproduce the fence-stripping logic from client.py for testing."""
    text = raw.strip()
    text = re.sub(r"^```\w*\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    return text


class TestStripFences:
    def test_no_fences(self):
        raw = '{"key": "value"}'
        assert json.loads(_strip_fences(raw)) == {"key": "value"}

    def test_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        assert json.loads(_strip_fences(raw)) == {"key": "value"}

    def test_fence_with_trailing_spaces(self):
        raw = '```json  \n{"key": "value"}\n```  '
        assert json.loads(_strip_fences(raw)) == {"key": "value"}

    def test_plain_fence(self):
        raw = '```\n{"key": "value"}\n```'
        assert json.loads(_strip_fences(raw)) == {"key": "value"}

    def test_multiline_json(self):
        raw = '```json\n{\n  "score": 4.2,\n  "finding": "test"\n}\n```'
        result = json.loads(_strip_fences(raw))
        assert result["score"] == 4.2
        assert result["finding"] == "test"

    def test_no_trailing_newline_fence(self):
        raw = '{"key": "value"}'
        assert json.loads(_strip_fences(raw)) == {"key": "value"}

    def test_fence_with_language_tag(self):
        raw = '```javascript\n{"key": "value"}\n```'
        assert json.loads(_strip_fences(raw)) == {"key": "value"}


# ---------------------------------------------------------------------------
# calculate_cost
# ---------------------------------------------------------------------------


class TestCalculateCost:
    def test_known_model_opus(self):
        cost = calculate_cost(ANTHROPIC_PRIMARY, 1000, 500)
        expected = 1000 * (5.0 / 1_000_000) + 500 * (25.0 / 1_000_000)
        assert abs(cost - expected) < 1e-10

    def test_known_model_haiku(self):
        cost = calculate_cost(ANTHROPIC_BUDGET, 10_000, 2_000)
        expected = 10_000 * (1.0 / 1_000_000) + 2_000 * (5.0 / 1_000_000)
        assert abs(cost - expected) < 1e-10

    def test_unknown_model_returns_zero(self):
        assert calculate_cost("unknown-model", 5000, 1000) == 0.0

    def test_zero_tokens(self):
        assert calculate_cost(ANTHROPIC_PRIMARY, 0, 0) == 0.0

    def test_gpt_model(self):
        # v0.52.4 — OPENAI_PRIMARY is now gpt-5.5 (input $5/1M, output $30/1M)
        cost = calculate_cost(OPENAI_PRIMARY, 1000, 1000)
        expected = 1000 * (5.00 / 1_000_000) + 1000 * (30.0 / 1_000_000)
        assert abs(cost - expected) < 1e-10


# ---------------------------------------------------------------------------
# LLMUsage + LLMUsageAccumulator
# ---------------------------------------------------------------------------


class TestLLMUsage:
    def test_defaults(self):
        usage = LLMUsage()
        assert usage.model == ""
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cost_usd == 0.0

    def test_to_dict(self):
        usage = LLMUsage(model="opus", input_tokens=100, output_tokens=50, cost_usd=0.005)
        d = usage.to_dict()
        assert d == {
            "model": "opus",
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": 0.005,
        }


class TestLLMUsageAccumulator:
    def test_empty(self):
        acc = LLMUsageAccumulator()
        assert acc.total_input_tokens == 0
        assert acc.total_output_tokens == 0
        assert acc.total_cost_usd == 0.0
        assert acc.to_dict()["call_count"] == 0

    def test_record_and_aggregate(self):
        acc = LLMUsageAccumulator()
        acc.record(LLMUsage(model="a", input_tokens=100, output_tokens=50, cost_usd=0.01))
        acc.record(LLMUsage(model="b", input_tokens=200, output_tokens=100, cost_usd=0.02))
        assert acc.total_input_tokens == 300
        assert acc.total_output_tokens == 150
        assert abs(acc.total_cost_usd - 0.03) < 1e-10
        assert acc.to_dict()["call_count"] == 2

    def test_to_dict(self):
        acc = LLMUsageAccumulator()
        acc.record(LLMUsage(input_tokens=10, output_tokens=5, cost_usd=0.001))
        d = acc.to_dict()
        assert set(d.keys()) == {
            "total_input_tokens",
            "total_output_tokens",
            "total_cost_usd",
            "call_count",
        }


# ---------------------------------------------------------------------------
# get_usage_accumulator / reset_usage_accumulator
# ---------------------------------------------------------------------------


class TestUsageAccumulatorContext:
    def test_get_creates_default(self):
        reset_usage_accumulator()
        acc = get_usage_accumulator()
        assert isinstance(acc, LLMUsageAccumulator)
        assert len(acc.calls) == 0

    def test_same_instance_in_same_context(self):
        reset_usage_accumulator()
        a = get_usage_accumulator()
        b = get_usage_accumulator()
        assert a is b

    def test_reset_clears(self):
        acc = get_usage_accumulator()
        acc.record(LLMUsage(input_tokens=100))
        reset_usage_accumulator()
        assert len(get_usage_accumulator().calls) == 0


# ---------------------------------------------------------------------------
# call_llm_parsed (mocked)
# ---------------------------------------------------------------------------


class TestCallLLMParsed:
    def test_parsed_output_success(self):
        from core.llm.client import call_llm_parsed
        from pydantic import BaseModel

        class DummyOutput(BaseModel):
            score: float = 0.0

        mock_response = MagicMock()
        mock_response.parsed_output = DummyOutput(score=4.2)
        mock_response.usage = MagicMock(
            input_tokens=500,
            output_tokens=200,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        mock_client = MagicMock()
        mock_client.messages.parse.return_value = mock_response

        with patch("core.llm.router.calls.parsed.get_anthropic_client", return_value=mock_client):
            result = call_llm_parsed(
                system="test system",
                user="test user",
                output_model=DummyOutput,
                model=ANTHROPIC_PRIMARY,
            )
        assert result.score == 4.2

    def test_parsed_output_none_raises(self):
        from core.llm.client import call_llm_parsed
        from pydantic import BaseModel

        class DummyOutput(BaseModel):
            value: str = ""

        mock_response = MagicMock()
        mock_response.parsed_output = None
        mock_response.usage = MagicMock(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        mock_client = MagicMock()
        mock_client.messages.parse.return_value = mock_response

        with (
            patch("core.llm.router.calls.parsed.get_anthropic_client", return_value=mock_client),
            pytest.raises(ValueError, match="LLM returned no structured output"),
        ):
            call_llm_parsed(
                system="test",
                user="test",
                output_model=DummyOutput,
                model=ANTHROPIC_PRIMARY,
            )

    def test_parsed_output_with_cache(self):
        from core.llm.client import call_llm_parsed
        from pydantic import BaseModel

        class DummyOutput(BaseModel):
            ok: bool = True

        mock_response = MagicMock()
        mock_response.parsed_output = DummyOutput(ok=True)
        mock_response.usage = MagicMock(
            input_tokens=500,
            output_tokens=200,
            cache_creation_input_tokens=100,
            cache_read_input_tokens=50,
        )

        mock_client = MagicMock()
        mock_client.messages.parse.return_value = mock_response

        with patch("core.llm.router.calls.parsed.get_anthropic_client", return_value=mock_client):
            result = call_llm_parsed(
                system="test",
                user="test",
                output_model=DummyOutput,
                model=ANTHROPIC_PRIMARY,
            )
        assert result.ok is True


# ---------------------------------------------------------------------------
# LLMUsage edge cases
# ---------------------------------------------------------------------------


class TestLLMUsageEdgeCases:
    def test_large_token_counts(self):
        usage = LLMUsage(model="opus", input_tokens=1_000_000, output_tokens=500_000, cost_usd=52.5)
        d = usage.to_dict()
        assert d["input_tokens"] == 1_000_000

    def test_accumulator_single_call(self):
        acc = LLMUsageAccumulator()
        u = LLMUsage(model="opus", input_tokens=100, output_tokens=50, cost_usd=0.005)
        acc.record(u)
        assert acc.total_input_tokens == 100
        assert acc.total_output_tokens == 50
        d = acc.to_dict()
        assert d["call_count"] == 1

    def test_calculate_cost_all_models(self):
        from core.llm.client import MODEL_PRICING

        for model_name in MODEL_PRICING:
            cost = calculate_cost(model_name, 1000, 1000)
            # Free-tier models (e.g. glm-4.7-flash) have $0 pricing
            assert cost >= 0, f"Cost should be non-negative for {model_name}"


class TestProviderRouting:
    """Verify call_llm_parsed / call_llm route to correct SDK based on model."""

    def test_call_llm_parsed_routes_to_anthropic_for_claude(self):
        """call_llm_parsed should use Anthropic SDK when model is claude-*."""
        from pydantic import BaseModel

        class _DummyOutput(BaseModel):
            value: str

        mock_response = MagicMock()
        mock_response.parsed_output = _DummyOutput(value="test")
        mock_response.usage = MagicMock(
            input_tokens=10,
            output_tokens=5,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        with patch("core.llm.router.calls.parsed.get_anthropic_client") as mock_get:
            mock_client = MagicMock()
            mock_client.messages.parse.return_value = mock_response
            mock_get.return_value = mock_client

            from core.llm.client import call_llm_parsed

            result = call_llm_parsed(
                "system",
                "user",
                output_model=_DummyOutput,
                model="claude-opus-4-6",
            )

            assert result.value == "test"
            mock_client.messages.parse.assert_called_once()

    def test_call_llm_parsed_routes_to_openai_for_glm(self):
        """call_llm_parsed should use OpenAI-compatible SDK when model is glm-*."""
        from pydantic import BaseModel

        class _DummyOutput(BaseModel):
            value: str

        mock_parsed = _DummyOutput(value="glm-result")
        mock_choice = MagicMock()
        mock_choice.message.parsed = mock_parsed

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

        mock_glm_client = MagicMock()
        mock_glm_client.beta.chat.completions.parse.return_value = mock_response

        with patch(
            "core.llm.router.calls.parsed._get_provider_client", return_value=mock_glm_client
        ):
            from core.llm.client import call_llm_parsed

            result = call_llm_parsed(
                "system",
                "user",
                output_model=_DummyOutput,
                model="glm-5",
            )

            assert result.value == "glm-result"
            mock_glm_client.beta.chat.completions.parse.assert_called_once()

    def test_call_llm_parsed_routes_to_openai_for_gpt(self):
        """call_llm_parsed should use OpenAI SDK when model is gpt-*."""
        from pydantic import BaseModel

        class _DummyOutput(BaseModel):
            value: str

        mock_parsed = _DummyOutput(value="gpt-result")
        mock_choice = MagicMock()
        mock_choice.message.parsed = mock_parsed

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

        mock_openai_client = MagicMock()
        mock_openai_client.beta.chat.completions.parse.return_value = mock_response

        with patch(
            "core.llm.router.calls.parsed._get_provider_client", return_value=mock_openai_client
        ):
            from core.llm.client import call_llm_parsed

            result = call_llm_parsed(
                "system",
                "user",
                output_model=_DummyOutput,
                model="gpt-5.4",
            )

            assert result.value == "gpt-result"
            mock_openai_client.beta.chat.completions.parse.assert_called_once()

    def test_call_llm_routes_to_openai_for_glm(self):
        """call_llm should use OpenAI-compatible SDK when model is glm-*."""
        mock_choice = MagicMock()
        mock_choice.message.content = "glm text response"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

        mock_glm_client = MagicMock()
        mock_glm_client.chat.completions.create.return_value = mock_response

        with patch("core.llm.router.calls.text._get_provider_client", return_value=mock_glm_client):
            from core.llm.client import call_llm

            result = call_llm("system", "user", model="glm-5")

            assert result == "glm text response"
            mock_glm_client.chat.completions.create.assert_called_once()

    def test_call_llm_routes_to_anthropic_for_claude(self):
        """call_llm should use Anthropic SDK when model is claude-*."""
        mock_block = MagicMock()
        mock_block.text = "anthropic response"

        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_response.usage = MagicMock(
            input_tokens=10,
            output_tokens=5,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        with patch("core.llm.router.calls.text.get_anthropic_client") as mock_get:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_get.return_value = mock_client

            from core.llm.client import call_llm

            result = call_llm("system", "user", model="claude-opus-4-6")

            assert result == "anthropic response"
            mock_client.messages.create.assert_called_once()
