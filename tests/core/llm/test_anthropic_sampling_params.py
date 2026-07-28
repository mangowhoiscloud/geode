"""Sampling-param shaping on the LIVE Anthropic adapter path.

Repointed 2026-07-29: previously drove the deleted ``ClaudeAgenticAdapter``;
the production surface is ``build_create_kwargs`` / ``build_stream_kwargs``.
"""

from __future__ import annotations

from core.llm.adapters._anthropic_common import build_create_kwargs, build_stream_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message


def _req(**overrides: object) -> AdapterCallRequest:
    base: dict = {
        "model": "claude-sonnet-5",
        "system_prompt": "static rules",
        "messages": (Message(role="user", content="hi"),),
        "max_tokens": 512,
    }
    base.update(overrides)
    return AdapterCallRequest(**base)


def test_temperature_omitted_when_none() -> None:
    kwargs = build_create_kwargs(_req())
    assert "temperature" not in kwargs


def test_temperature_forwarded_when_set() -> None:
    kwargs = build_create_kwargs(_req(temperature=0.2))
    assert kwargs["temperature"] == 0.2


def test_thinking_budget_maps_to_thinking_block() -> None:
    kwargs = build_create_kwargs(_req(thinking_budget=2048))
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    # Anthropic contract: budget_tokens < max_tokens; extended thinking pins
    # temperature=1 (the first port dropped both — API-invalid payload).
    assert kwargs["max_tokens"] == 512 + 2048
    assert kwargs["temperature"] == 1.0


def test_adaptive_model_omits_sampling_and_sets_display() -> None:
    kwargs = build_create_kwargs(
        _req(model="claude-opus-4-7", temperature=0.3, thinking_budget=2048)
    )
    assert kwargs["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert "temperature" not in kwargs, "adaptive models reject sampling params"
    assert kwargs["output_config"]["effort"]


def test_oauth_identity_composes_with_cache_blocks() -> None:
    from core.llm.adapters.anthropic_oauth import (
        CLAUDE_CODE_IDENTITY,
        _apply_claude_code_identity,
    )

    system = "STATIC\n\n<dynamic_context>\n\nd\n\n</dynamic_context>"
    kwargs = build_create_kwargs(_req(system_prompt=system))
    out = _apply_claude_code_identity(kwargs)
    blocks = out["system"]
    assert blocks[0]["text"] == CLAUDE_CODE_IDENTITY, "identity must stay the EXACT first block"
    assert blocks[1]["cache_control"]["type"] == "ephemeral", "static cache metadata preserved"


def test_stream_kwargs_omit_thinking_and_stops() -> None:
    kwargs = build_stream_kwargs(_req(thinking_budget=2048, stop_sequences=("x",)))
    assert "thinking" not in kwargs
    assert "stop_sequences" not in kwargs
