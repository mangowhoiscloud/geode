"""Regression tests for Anthropic sampling-parameter handling.

Anthropic deprecated `temperature`, `top_p`, and `top_k` for Opus 4.7
(and the same constraint applies to Opus 4.6 / Sonnet 4.6 when adaptive
thinking is on). Sending those parameters returns a 400 BadRequest with
"temperature is deprecated for this model."

Source: https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _run_agentic_call(model: str) -> dict[str, Any]:
    """Invoke ClaudeAgenticAdapter.agentic_call once and capture create kwargs."""
    from core.llm.providers.anthropic import ClaudeAgenticAdapter

    adapter = ClaudeAgenticAdapter()

    response = MagicMock()
    response.content = [MagicMock(type="text", text="ok")]
    response.stop_reason = "end_turn"
    response.usage = MagicMock(input_tokens=1, output_tokens=1)
    response.model = model

    captured: dict[str, Any] = {}

    async def fake_create(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return response

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=fake_create)
    adapter._client = client

    async def fake_failover(models: list[str], do_call: Any) -> tuple[Any, str]:
        return await do_call(models[0]), models[0]

    with (
        patch("core.llm.providers.anthropic.settings") as mock_settings,
        patch("core.llm.router.call_with_failover", side_effect=fake_failover),
    ):
        mock_settings.anthropic_api_key = "test-key"
        asyncio.run(
            adapter.agentic_call(
                model=model,
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                tools=[
                    {
                        "name": "noop",
                        "description": "noop",
                        "input_schema": {"type": "object"},
                    }
                ],
                tool_choice={"type": "auto"},
                max_tokens=1024,
                temperature=0.0,
            )
        )

    return captured


@pytest.mark.parametrize(
    "model",
    ["claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6"],
)
def test_adaptive_models_omit_sampling_params(model: str) -> None:
    """Opus 4.6+ / Sonnet 4.6 reject temperature; it must not be sent."""
    kwargs = _run_agentic_call(model)
    assert "temperature" not in kwargs, (
        f"{model} must not receive `temperature` (rejected with 400). "
        f"Got: {sorted(kwargs)}"
    )
    assert kwargs.get("thinking") == {"type": "adaptive"}


def test_opus_4_7_registered_for_context_management() -> None:
    """Opus 4.7 must enable the context-management + compaction beta header."""
    kwargs = _run_agentic_call("claude-opus-4-7")
    headers = kwargs.get("extra_headers") or {}
    beta = headers.get("anthropic-beta", "")
    assert "context-management-2025-06-27" in beta
    assert "compact-2026-01-12" in beta


def test_legacy_model_keeps_temperature() -> None:
    """Older models (no adaptive thinking) still accept temperature."""
    kwargs = _run_agentic_call("claude-haiku-4-5-20251001")
    assert "temperature" in kwargs
    assert kwargs["temperature"] == 0.0
    # Haiku 4.5 must not receive the context-management beta header
    headers = kwargs.get("extra_headers") or {}
    assert "anthropic-beta" not in headers
