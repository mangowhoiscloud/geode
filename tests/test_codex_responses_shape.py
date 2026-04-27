"""v0.52.7 — Codex Responses API request shape (tools + reasoning + temperature).

Followup to v0.52.6 hotfix. The spec doc (``docs/research/codex-oauth-request-spec.md``)
identified 3 gaps NOT caused by the 400-on-max_output_tokens incident but real:

  1. ``tools`` / ``tool_choice`` / ``parallel_tool_calls`` were never sent.
     Codex agentic loop had no way to invoke any tool — function-calling
     entirely broken on Plus subscription.
  2. ``include=["reasoning.encrypted_content"]`` + ``reasoning={effort, summary}``
     never sent. gpt-5.x-codex returns encrypted reasoning blocks; without
     ``include`` the backend strips them, breaking multi-turn continuity.
  3. ``temperature`` sent unconditionally. Hermes uses
     ``_fixed_temperature_for_model`` which OMITs the field for gpt-5.x-codex.

Reference: 3 codebases agree on the shape (see spec doc):
  - Hermes Agent ``agent/transports/codex.py``
  - OpenClaw ``src/agents/openai-transport-stream.ts``
  - Codex CLI Rust ``codex-rs/codex-api/src/common.rs``

These tests use mocks for the SDK call and inspect the kwargs passed to
``client.responses.stream(...)`` — no live API calls.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core.llm.providers.codex import (
    CodexAgenticAdapter,
    _is_codex_reasoning_model,
)

# ---------------------------------------------------------------------------
# Contract 0 — _is_codex_reasoning_model classifier
# ---------------------------------------------------------------------------


def test_gpt5_models_are_reasoning() -> None:
    """All currently-routed Codex models (gpt-5.5, 5.4, 5.4-mini, 5.3-codex)
    are gpt-5.x and must be classified as reasoning models."""
    for model in ("gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"):
        assert _is_codex_reasoning_model(model) is True, (
            f"{model} must be classified as a Codex reasoning model — "
            "without this, the include + reasoning fields are dropped and "
            "encrypted reasoning is lost across turns."
        )


def test_legacy_models_are_not_reasoning() -> None:
    """Legacy (gpt-4.x and below) models do NOT support the reasoning
    field — sending it would 400."""
    for model in ("gpt-4.1", "gpt-4o", "gpt-3.5-turbo"):
        assert _is_codex_reasoning_model(model) is False


# ---------------------------------------------------------------------------
# Contract 1 — tools / tool_choice / parallel_tool_calls passthrough
# ---------------------------------------------------------------------------


def _capture_codex_kwargs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = "auto",
    model: str = "gpt-5.5",
    temperature: float = 0.7,
    effort: str = "high",
) -> dict[str, Any]:
    """Run agentic_call with mocked SDK + capture the stream() kwargs."""
    captured: dict[str, Any] = {}

    fake_stream_ctx = MagicMock()
    fake_stream_ctx.__enter__ = MagicMock(return_value=iter([]))
    fake_stream_ctx.__exit__ = MagicMock(return_value=False)
    fake_stream_ctx.get_final_response = MagicMock(return_value=MagicMock())

    fake_client = MagicMock()

    def _fake_stream(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        # Build a fresh context each call so iteration / __exit__ work.
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=iter([]))
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.get_final_response = MagicMock(return_value=MagicMock())
        return ctx

    fake_client.responses.stream = _fake_stream

    monkeypatch.setattr("core.llm.providers.codex._get_codex_client", lambda: fake_client)
    # Bypass circuit breaker for the test.
    monkeypatch.setattr(
        "core.llm.providers.codex._codex_circuit_breaker",
        MagicMock(
            can_execute=lambda: True, record_success=lambda: None, record_failure=lambda: None
        ),
    )

    async def _run() -> None:
        adapter = CodexAgenticAdapter()

        # Patch call_with_failover so it just calls _do_call once for `model`
        async def _direct(failover_models: list[str], do_call: Any) -> tuple[Any, str]:
            result = await do_call(failover_models[0])
            return result, failover_models[0]

        with patch("core.llm.providers.codex.call_with_failover", _direct):
            await adapter.agentic_call(
                model=model,
                system="hi",
                messages=[{"role": "user", "content": "test"}],
                tools=tools or [],
                tool_choice=tool_choice,
                max_tokens=4096,
                temperature=temperature,
                effort=effort,
            )

    asyncio.run(_run())
    return captured


def test_tools_are_forwarded_to_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-fix bug: tools list was silently dropped — function calling broken
    on Codex Plus. Post-fix: must appear in stream() kwargs in Responses API
    flat-tool format ({type, name, description, parameters})."""
    tools = [
        {
            "name": "get_weather",
            "description": "Look up weather for a location.",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]
    kwargs = _capture_codex_kwargs(monkeypatch, tools=tools)
    assert "tools" in kwargs, (
        "tools missing from Codex stream() call — function calling is broken on Plus subscription"
    )
    assert kwargs["tools"][0]["name"] == "get_weather"
    assert kwargs["tools"][0]["type"] == "function"
    # Responses API uses flat schema (no nested "function" key).
    assert "function" not in kwargs["tools"][0]


def test_tool_choice_defaults_to_auto_when_tools_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex Rust hardcodes ``tool_choice = "auto"``; Hermes too. Match it."""
    tools = [{"name": "x", "description": "x", "input_schema": {"type": "object"}}]
    kwargs = _capture_codex_kwargs(monkeypatch, tools=tools, tool_choice="auto")
    assert kwargs["tool_choice"] == "auto"


def test_parallel_tool_calls_true_when_tools_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hermes default; Codex Rust forwards. Required by Codex spec."""
    tools = [{"name": "x", "description": "x", "input_schema": {"type": "object"}}]
    kwargs = _capture_codex_kwargs(monkeypatch, tools=tools)
    assert kwargs["parallel_tool_calls"] is True


def test_no_tools_omits_tool_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Don't send tool_choice / parallel_tool_calls when tools list is empty —
    avoids the OpenAI SDK validation that requires tools when tool_choice set."""
    kwargs = _capture_codex_kwargs(monkeypatch, tools=[])
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs
    assert "parallel_tool_calls" not in kwargs


# ---------------------------------------------------------------------------
# Contract 2 — include + reasoning for gpt-5.x reasoning models
# ---------------------------------------------------------------------------


def test_reasoning_model_sends_include_and_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-fix bug: gpt-5.x-codex returns encrypted reasoning blocks the
    backend strips when ``include`` is absent. Multi-turn reasoning
    continuity broken. Spec: Hermes + Codex Rust both send these fields."""
    kwargs = _capture_codex_kwargs(monkeypatch, model="gpt-5.5", effort="high")
    assert kwargs.get("include") == ["reasoning.encrypted_content"], (
        "include=['reasoning.encrypted_content'] must be sent for gpt-5.x — "
        "without it the backend drops encrypted reasoning across turns"
    )
    assert kwargs.get("reasoning") == {"effort": "high", "summary": "auto"}


def test_reasoning_model_omits_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermes ``_fixed_temperature_for_model`` returns OMIT for gpt-5.x-codex.
    Sending ``temperature`` to a reasoning model can return 400 or skew the
    reasoning sampler — match Hermes."""
    kwargs = _capture_codex_kwargs(monkeypatch, model="gpt-5.3-codex", temperature=0.5)
    assert "temperature" not in kwargs, (
        "temperature must be omitted for gpt-5.x-codex per Hermes _fixed_temperature_for_model"
    )


def test_non_reasoning_model_sends_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hypothetical non-reasoning model (e.g. legacy gpt-4) DOES accept
    temperature. The classifier must keep this path open for any future
    non-gpt-5 model that gets added to the Codex chain."""
    kwargs = _capture_codex_kwargs(monkeypatch, model="gpt-4.1-legacy", temperature=0.3)
    assert kwargs.get("temperature") == 0.3
    # And the reasoning fields must NOT appear.
    assert "include" not in kwargs
    assert "reasoning" not in kwargs


# ---------------------------------------------------------------------------
# Contract 3 — invariants from v0.52.6 still hold
# ---------------------------------------------------------------------------


def test_max_output_tokens_still_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.52.6 invariant: max_output_tokens is FORBIDDEN on Codex backend.
    Re-pinned here because v0.52.7 refactored the kwargs construction —
    this test would fail loudly if a regression accidentally re-added it."""
    kwargs = _capture_codex_kwargs(monkeypatch, model="gpt-5.5")
    assert "max_output_tokens" not in kwargs, (
        "max_output_tokens regressed — Codex backend will return 400"
    )
    assert "max_tokens" not in kwargs


def test_store_false_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec: Plus backend has no server-side state; ``store=True`` returns 400."""
    kwargs = _capture_codex_kwargs(monkeypatch, model="gpt-5.5")
    assert kwargs["store"] is False
