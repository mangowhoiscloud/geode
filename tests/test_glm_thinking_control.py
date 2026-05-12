"""GAP-R1 — GLM thinking field is gated by the ``effort`` argument.

Pre-fix: ``GlmAgenticAdapter.agentic_call`` always sent ``{"type":
"enabled", "clear_thinking": False}`` whenever ``_glm_thinking_supported(m)``
was true, ignoring the caller's ``effort`` hint.  GLM-5.x / 4.7 are
compulsorily-thinking so this was a no-op there, but GLM-4.5 / 4.6 hybrid
models DO honour ``"disabled"`` — and we were paying for reasoning tokens
on every cheap-output call regardless.

Post-fix: ``effort in ("off", "none")`` → ``{"type": "disabled"}``;
anything else → unchanged ``"enabled"``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core.llm.providers.glm import GlmAgenticAdapter


class _StubMessage:
    role = "assistant"
    content = ""
    tool_calls: list[Any] = []


class _StubChoice:
    message = _StubMessage()
    finish_reason = "stop"


class _StubResponse:
    choices = [_StubChoice()]
    usage = None


class _StubCompletions:
    def __init__(self, sink: dict[str, Any]) -> None:
        self._sink = sink

    def create(self, **kwargs: Any) -> Any:
        self._sink.update(kwargs)
        return _StubResponse()


class _StubChat:
    def __init__(self, sink: dict[str, Any]) -> None:
        self.completions = _StubCompletions(sink)


class _StubClient:
    def __init__(self, sink: dict[str, Any]) -> None:
        self.chat = _StubChat(sink)

    def close(self) -> None:
        pass


def _run(adapter: GlmAgenticAdapter, effort: str, model: str = "glm-4.5") -> dict[str, Any]:
    """Invoke ``agentic_call`` with stub client and return captured kwargs."""
    captured: dict[str, Any] = {}
    client = _StubClient(captured)
    adapter._ensure_client = lambda m: client  # type: ignore[method-assign]
    asyncio.run(
        adapter.agentic_call(
            model=model,
            system="S",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            tool_choice="auto",
            max_tokens=64,
            temperature=0.3,
            effort=effort,
        )
    )
    return captured


@pytest.mark.parametrize("hybrid_model", ["glm-4.5", "glm-4.6", "glm-4.5-flash"])
def test_effort_off_disables_thinking_on_hybrid(hybrid_model: str) -> None:
    """Hybrid models accept ``disabled`` — caller asks ``effort=off``,
    adapter must send ``type: disabled`` to recover the reasoning cost.
    """
    adapter = GlmAgenticAdapter()
    captured = _run(adapter, effort="off", model=hybrid_model)
    extra = captured.get("extra_body") or {}
    thinking = extra.get("thinking") or {}
    assert thinking.get("type") == "disabled", (
        f"GAP-R1: effort=off must disable thinking on {hybrid_model}"
    )


def test_effort_none_also_disables() -> None:
    """``effort=none`` is treated as ``off`` (interchangeable in the
    callers).  Both must produce ``disabled``.
    """
    adapter = GlmAgenticAdapter()
    captured = _run(adapter, effort="none", model="glm-4.5")
    thinking = (captured.get("extra_body") or {}).get("thinking") or {}
    assert thinking.get("type") == "disabled"


@pytest.mark.parametrize("effort", ["high", "medium", "low", "max"])
def test_non_off_effort_keeps_thinking_enabled(effort: str) -> None:
    """Any non-off effort preserves the v0.58.0 behaviour."""
    adapter = GlmAgenticAdapter()
    captured = _run(adapter, effort=effort, model="glm-5.1")
    thinking = (captured.get("extra_body") or {}).get("thinking") or {}
    assert thinking.get("type") == "enabled"
    assert thinking.get("clear_thinking") is False


def test_pre_glm45_model_omits_thinking_field() -> None:
    """Pre-GLM-4.5 models reject the field — must not be sent regardless
    of effort.  The whitelist gate (`_glm_thinking_supported`) is the
    primary guard; effort gating is layered on top.
    """
    adapter = GlmAgenticAdapter()
    captured = _run(adapter, effort="high", model="glm-4-air")  # not in whitelist
    extra = captured.get("extra_body")
    assert extra is None or "thinking" not in extra, (
        "GLM-4.x pre-4.5 models must not receive the thinking field"
    )
