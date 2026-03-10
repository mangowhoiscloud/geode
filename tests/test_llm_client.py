"""Tests for LLM client JSON extraction and token usage tracking."""

from __future__ import annotations

import json
import os
import re
from unittest.mock import MagicMock, patch

import pytest
from core.llm.client import (
    LLMUsage,
    LLMUsageAccumulator,
    calculate_cost,
    get_usage_accumulator,
    is_langsmith_enabled,
    reset_usage_accumulator,
    track_token_usage,
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
        cost = calculate_cost("claude-opus-4-6", 1000, 500)
        expected = 1000 * (15.0 / 1_000_000) + 500 * (75.0 / 1_000_000)
        assert abs(cost - expected) < 1e-10

    def test_known_model_haiku(self):
        cost = calculate_cost("claude-haiku-4-5-20251001", 10_000, 2_000)
        expected = 10_000 * (0.80 / 1_000_000) + 2_000 * (4.0 / 1_000_000)
        assert abs(cost - expected) < 1e-10

    def test_unknown_model_returns_zero(self):
        assert calculate_cost("unknown-model", 5000, 1000) == 0.0

    def test_zero_tokens(self):
        assert calculate_cost("claude-opus-4-6", 0, 0) == 0.0

    def test_gpt_model(self):
        cost = calculate_cost("gpt-5.4", 1000, 1000)
        expected = 1000 * (2.50 / 1_000_000) + 1000 * (15.0 / 1_000_000)
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
# is_langsmith_enabled
# ---------------------------------------------------------------------------


class TestIsLangsmithEnabled:
    def test_disabled_by_default(self):
        env = {"LANGCHAIN_TRACING_V2": "", "LANGCHAIN_API_KEY": ""}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("LANGCHAIN_TRACING_V2", None)
            os.environ.pop("LANGCHAIN_API_KEY", None)
            os.environ.pop("LANGSMITH_API_KEY", None)
            assert is_langsmith_enabled() is False

    def test_enabled_with_both(self):
        env = {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "lsv2_test"}
        with patch.dict(os.environ, env, clear=False):
            assert is_langsmith_enabled() is True

    def test_disabled_without_key(self):
        env = {"LANGCHAIN_TRACING_V2": "true"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("LANGCHAIN_API_KEY", None)
            os.environ.pop("LANGSMITH_API_KEY", None)
            assert is_langsmith_enabled() is False

    def test_disabled_without_tracing_flag(self):
        env = {"LANGCHAIN_TRACING_V2": "false", "LANGCHAIN_API_KEY": "lsv2_test"}
        with patch.dict(os.environ, env, clear=False):
            assert is_langsmith_enabled() is False


# ---------------------------------------------------------------------------
# track_token_usage
# ---------------------------------------------------------------------------


class TestTrackTokenUsage:
    def test_noop_when_disabled(self):
        with patch("core.llm.client.is_langsmith_enabled", return_value=False):
            track_token_usage("opus", 100, 50)

    def test_records_when_enabled(self):
        mock_run_tree = MagicMock()
        mock_run_tree.extra = {}
        with (
            patch("core.llm.client.is_langsmith_enabled", return_value=True),
            patch("langsmith.run_helpers.get_current_run_tree", return_value=mock_run_tree),
        ):
            track_token_usage("claude-opus-4-6", 1000, 500)
            assert "metrics" in mock_run_tree.extra
            assert mock_run_tree.extra["metrics"]["input_tokens"] == 1000
            assert mock_run_tree.extra["metrics"]["output_tokens"] == 500

    def test_handles_no_run_tree(self):
        with (
            patch("core.llm.client.is_langsmith_enabled", return_value=True),
            patch("langsmith.run_helpers.get_current_run_tree", return_value=None),
        ):
            track_token_usage("opus", 100, 50)

    def test_handles_import_error(self):
        with (
            patch("core.llm.client.is_langsmith_enabled", return_value=True),
            patch.dict("sys.modules", {"langsmith.run_helpers": None}),
        ):
            track_token_usage("opus", 100, 50)


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

        with patch("core.llm.client.get_anthropic_client", return_value=mock_client):
            result = call_llm_parsed(
                system="test system",
                user="test user",
                output_model=DummyOutput,
                model="claude-opus-4-6",
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
            patch("core.llm.client.get_anthropic_client", return_value=mock_client),
            pytest.raises(ValueError, match="Structured output parsing returned None"),
        ):
            call_llm_parsed(
                system="test",
                user="test",
                output_model=DummyOutput,
                model="claude-opus-4-6",
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

        with patch("core.llm.client.get_anthropic_client", return_value=mock_client):
            result = call_llm_parsed(
                system="test",
                user="test",
                output_model=DummyOutput,
                model="claude-opus-4-6",
            )
        assert result.ok is True


# ---------------------------------------------------------------------------
# _maybe_traceable
# ---------------------------------------------------------------------------


class TestMaybeTraceable:
    def test_returns_identity_when_disabled(self):
        from core.llm.client import _maybe_traceable

        with patch("core.llm.client.is_langsmith_enabled", return_value=False):
            decorator = _maybe_traceable(run_type="llm", name="test")

            # Should be identity — decorating a function returns same function
            def dummy() -> str:
                return "ok"

            assert decorator(dummy) is dummy

    def test_returns_traceable_when_enabled(self):
        from core.llm.client import _maybe_traceable

        mock_traceable = MagicMock(return_value=lambda fn: fn)
        with (
            patch("core.llm.client.is_langsmith_enabled", return_value=True),
            patch.dict("sys.modules", {"langsmith": MagicMock(traceable=mock_traceable)}),
        ):
            _maybe_traceable(run_type="chain", name="test_fn")

    def test_falls_back_on_import_error(self):
        from core.llm.client import _maybe_traceable

        with (
            patch("core.llm.client.is_langsmith_enabled", return_value=True),
            patch.dict("sys.modules", {"langsmith": None}),
        ):
            decorator = _maybe_traceable(run_type="llm")

            def dummy() -> str:
                return "ok"

            assert decorator(dummy) is dummy


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
            assert cost > 0, f"Cost should be positive for {model_name}"

    def test_langsmith_legacy_key(self):
        env = {"LANGCHAIN_TRACING_V2": "true", "LANGSMITH_API_KEY": "legacy_key"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("LANGCHAIN_API_KEY", None)
            assert is_langsmith_enabled() is True
