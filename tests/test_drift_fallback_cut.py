"""Tests for PR-DRIFT-CUT (2026-05-24).

Covers the five surfaces hardened in the v0.99.52 post-merge smoke
incident:

  1. OpenAI per-model spec registry replaces the ``startswith`` prefix
     check (and warns on unknown models).
  2. ``cap_tools`` truncates the 128-cap overflow with an actionable log.
  3. ``summarize_error_detail`` strips raw SDK exception JSON down to
     the underlying ``error.message``.
  4. ``_looks_like_context_overflow`` is strict — never matches a
     ``max_tokens`` parameter error.
  5. Drift sync + provider fallback chains are dead no-ops.

These tests pin the contracts the PR introduces so a future cleanup
cannot silently revive the deprecated paths.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

# ─────────────────────────────────────────────────────────────────────
# 1. OpenAI per-model spec registry
# ─────────────────────────────────────────────────────────────────────


def test_get_openai_model_spec_known_gpt5_family() -> None:
    """GPT-5.x models route to the reasoning branch (max_completion_tokens, no temperature)."""
    from core.llm.adapters._openai_common import get_openai_model_spec

    for model_id in ("gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"):
        spec = get_openai_model_spec(model_id)
        assert spec.uses_max_completion_tokens is True, model_id
        assert spec.accepts_temperature is False, model_id
        assert spec.reasoning_effort_values is not None, model_id
        assert "none" in spec.reasoning_effort_values, model_id


def test_get_openai_model_spec_o_series() -> None:
    """o3 / o4-mini are reasoning models (no 'none' effort — always reasoning)."""
    from core.llm.adapters._openai_common import get_openai_model_spec

    for model_id in ("o3", "o4-mini"):
        spec = get_openai_model_spec(model_id)
        assert spec.uses_max_completion_tokens is True, model_id
        assert spec.accepts_temperature is False, model_id
        assert spec.reasoning_effort_values is not None, model_id
        assert "none" not in spec.reasoning_effort_values, model_id


def test_get_openai_model_spec_unknown_model_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown model id → legacy gpt-4.x fallback + one-shot WARNING."""
    from core.llm.adapters import _openai_common

    # Clear the dedup set so the test sees a fresh warning.
    _openai_common._UNKNOWN_MODEL_WARNED.discard("gpt-future-9.9")

    caplog.set_level(logging.WARNING, logger="core.llm.adapters._openai_common")
    spec = _openai_common.get_openai_model_spec("gpt-future-9.9")

    assert spec.uses_max_completion_tokens is False  # legacy default
    assert spec.accepts_temperature is True
    assert any(
        "gpt-future-9.9" in rec.message and "not in" in rec.message for rec in caplog.records
    )

    # Second call must not emit a duplicate warning.
    caplog.clear()
    _openai_common.get_openai_model_spec("gpt-future-9.9")
    assert all("gpt-future-9.9" not in rec.message for rec in caplog.records)


# ─────────────────────────────────────────────────────────────────────
# 2. cap_tools — 128 cap enforcement
# ─────────────────────────────────────────────────────────────────────


def test_cap_tools_passthrough_under_limit() -> None:
    from core.llm.adapters._openai_common import OPENAI_TOOLS_MAX, cap_tools

    tools = [{"name": f"t{i}"} for i in range(OPENAI_TOOLS_MAX)]
    result = cap_tools(tools, model="gpt-5.5", adapter_name="openai-payg")
    assert result is tools  # untouched when at the cap


def test_cap_tools_truncates_over_limit(caplog: pytest.LogCaptureFixture) -> None:
    from core.llm.adapters._openai_common import OPENAI_TOOLS_MAX, cap_tools

    tools = [{"name": f"t{i}"} for i in range(OPENAI_TOOLS_MAX + 48)]
    caplog.set_level(logging.WARNING, logger="core.llm.adapters._openai_common")
    result = cap_tools(tools, model="gpt-5.5", adapter_name="openai-payg")

    assert len(result) == OPENAI_TOOLS_MAX
    assert result[0]["name"] == "t0"
    assert result[-1]["name"] == f"t{OPENAI_TOOLS_MAX - 1}"
    assert any(
        "tools array length" in rec.message and "gpt-5.5" in rec.message for rec in caplog.records
    )


# ─────────────────────────────────────────────────────────────────────
# 3. summarize_error_detail
# ─────────────────────────────────────────────────────────────────────


def test_summarize_error_detail_extracts_message_field() -> None:
    from core.llm.errors import summarize_error_detail

    raw = (
        "Error code: 400 - {'error': {'message': "
        "\"Unsupported parameter: 'max_tokens' is not supported with this model. "
        "Use 'max_completion_tokens' instead.\", "
        "'type': 'invalid_request_error', 'code': 'unsupported_parameter'}}"
    )
    cleaned = summarize_error_detail(raw)

    assert cleaned.startswith("Unsupported parameter")
    assert "max_completion_tokens" in cleaned
    assert "Error code:" not in cleaned
    assert "{" not in cleaned


def test_summarize_error_detail_handles_exception_with_body() -> None:
    from core.llm.errors import summarize_error_detail

    exc: Any = Exception("legacy stringy")
    exc.body = {"error": {"message": "Prompt is too long: 1234567 tokens."}}
    assert summarize_error_detail(exc) == "Prompt is too long: 1234567 tokens."


def test_summarize_error_detail_passthrough_when_unstructured() -> None:
    """No extraction pattern matches → return input untouched (never drop info)."""
    from core.llm.errors import summarize_error_detail

    raw = "Just a plain string with no JSON inside"
    assert summarize_error_detail(raw) == raw


# ─────────────────────────────────────────────────────────────────────
# 4. _looks_like_context_overflow — strict matching
# ─────────────────────────────────────────────────────────────────────


def _fake_exc(message: str, code: str = "") -> Exception:
    exc: Any = Exception("Error code: 400 - <body>")
    exc.body = (
        {"error": {"message": message, "code": code}} if code else {"error": {"message": message}}
    )
    return exc


def test_context_overflow_matches_structured_code() -> None:
    from core.llm.errors import _looks_like_context_overflow

    assert _looks_like_context_overflow(_fake_exc("anything", code="context_length_exceeded"))
    assert _looks_like_context_overflow(_fake_exc("anything", code="prompt_too_long"))


def test_context_overflow_does_not_match_max_tokens_parameter_error() -> None:
    """Regression for the v0.99.52 smoke: 'max_tokens' must not trigger overflow."""
    from core.llm.errors import _looks_like_context_overflow

    msg = (
        "Unsupported parameter: 'max_tokens' is not supported with this model. "
        "Use 'max_completion_tokens' instead."
    )
    exc = _fake_exc(msg, code="unsupported_parameter")
    assert _looks_like_context_overflow(exc) is False


def test_context_overflow_matches_word_anchored_phrases() -> None:
    from core.llm.errors import _looks_like_context_overflow

    for msg in (
        "Your prompt is too long, please shorten it.",
        "context length exceeded: 350000 tokens.",
        "The input is too long for the context window.",
        "Too many tokens in this request",
    ):
        assert _looks_like_context_overflow(_fake_exc(msg)), msg


# ─────────────────────────────────────────────────────────────────────
# 5. Drift sync + fallback chains are no-ops
# ─────────────────────────────────────────────────────────────────────


def test_settings_model_target_always_none() -> None:
    """Per PR-DRIFT-CUT, the drift target is unconditionally absent."""
    from core.agent.loop._model_switching import _settings_model_target

    fake_loop = SimpleNamespace(model="gpt-5.5", _disable_settings_drift=False)
    assert _settings_model_target(fake_loop) is None


def test_sync_model_from_settings_async_returns_false() -> None:
    """Ditto for the per-turn async wrapper."""
    import asyncio

    from core.agent.loop._model_switching import sync_model_from_settings_async

    fake_loop = SimpleNamespace(model="gpt-5.5")
    assert asyncio.run(sync_model_from_settings_async(fake_loop)) is False


def test_get_fallback_chain_returns_empty_for_every_provider() -> None:
    """Cross-provider + same-provider fallback alike is dead."""
    from core.llm.provider_dispatch import _get_fallback_chain

    for provider in ("anthropic", "openai", "glm", "openai-codex"):
        assert _get_fallback_chain(provider) == []


def test_provider_fallback_chain_property_is_empty() -> None:
    """Per-provider ``fallback_chain`` property is also deprecated to []."""
    from core.llm.providers.codex import CodexAgenticAdapter
    from core.llm.providers.glm import GlmAgenticAdapter
    from core.llm.providers.openai import OpenAIAgenticAdapter

    for cls in (OpenAIAgenticAdapter, GlmAgenticAdapter, CodexAgenticAdapter):
        # ``fallback_chain`` is a property — read it off a bare instance
        # without driving full provider init.
        instance = cls.__new__(cls)  # type: ignore[call-arg]
        assert instance.fallback_chain == []
