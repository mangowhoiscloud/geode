"""Codex backend payload invariants — Codex MCP review 2026-05-23 BLOCKER pin.

The Codex backend (``chatgpt.com/backend-api/codex``) has 4 mandatory
differences from PAYG OpenAI Responses API. The first follow-up review caught
that the adapter was using the PAYG-style call kwargs. These tests guard
against regression.

References:
- ``docs/research/codex-oauth-request-spec.md``
- ``core/llm/providers/codex.py::CodexAgenticAdapter.agentic_call`` (canonical)
"""

from __future__ import annotations

from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec
from core.llm.adapters.codex_oauth import _build_codex_call_kwargs


def _req(model: str = "gpt-5.5", **kw: object) -> AdapterCallRequest:
    base: dict[str, object] = {
        "model": model,
        "messages": [Message(role="user", content="hello")],
        "system_prompt": "be brief",
        "max_tokens": 1024,
    }
    base.update(kw)
    return AdapterCallRequest(**base)  # type: ignore[arg-type]


def test_codex_kwargs_does_not_send_max_output_tokens() -> None:
    """Codex backend rejects ``max_output_tokens`` with 400 — must not be sent."""
    kwargs = _build_codex_call_kwargs(_req(max_tokens=2048))
    assert "max_output_tokens" not in kwargs
    assert "max_tokens" not in kwargs


def test_codex_kwargs_sets_store_false() -> None:
    """``store = False`` is required on Codex backend (Plus subscription policy)."""
    kwargs = _build_codex_call_kwargs(_req())
    assert kwargs["store"] is False


def test_codex_kwargs_lifts_system_prompt_to_instructions() -> None:
    """System prompt belongs in ``instructions``, not in ``input[].role=system``."""
    kwargs = _build_codex_call_kwargs(_req(system_prompt="audit only"))
    assert kwargs["instructions"] == "audit only"
    roles_in_input = [m.get("role") for m in kwargs["input"]]
    assert "system" not in roles_in_input


def test_codex_kwargs_instructions_default_when_empty() -> None:
    """Empty system_prompt still produces a non-empty instructions string."""
    kwargs = _build_codex_call_kwargs(_req(system_prompt=""))
    assert kwargs["instructions"]  # non-empty fallback


def test_codex_kwargs_gpt5_omits_temperature_adds_reasoning() -> None:
    """gpt-5.x family omits ``temperature`` and adds ``reasoning`` block."""
    kwargs = _build_codex_call_kwargs(_req(model="gpt-5.5", temperature=0.7))
    assert "temperature" not in kwargs
    assert kwargs["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert kwargs["include"] == ["reasoning.encrypted_content"]


def test_codex_kwargs_o_series_also_omits_temperature() -> None:
    """PR-DRIFT-CUT (2026-05-24) — registry-driven reasoning detection.

    Pre-PR the codex branch keyed on ``startswith("gpt-5")``, so o3 /
    o4-mini fell into the "keep temperature" path. The registry now
    treats every model with a ``reasoning_effort_values`` tuple as a
    reasoning model — o3 and o4-mini included — so they correctly
    omit ``temperature`` and add the ``reasoning`` block. Verified
    2026-05-24 against OpenAI reasoning-models guide.
    """
    kwargs = _build_codex_call_kwargs(_req(model="o3", temperature=0.3))
    assert "temperature" not in kwargs
    assert kwargs["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert kwargs["include"] == ["reasoning.encrypted_content"]


def test_codex_kwargs_legacy_model_keeps_temperature() -> None:
    """Models NOT in the registry fall back to legacy gpt-4.x defaults.

    Those defaults accept temperature, so the legacy branch is still
    exercised — we just no longer reach it via prefix-heuristic. An
    unknown model id (e.g. ``gpt-4o`` until it's registered) keeps
    the temperature path.
    """
    kwargs = _build_codex_call_kwargs(_req(model="gpt-4o-legacy", temperature=0.3))
    assert kwargs["temperature"] == 0.3
    assert "reasoning" not in kwargs


def test_codex_kwargs_tools_use_flat_responses_shape() -> None:
    """Codex Responses API requires the FLAT tool shape (not nested ``function``)."""
    tool = ToolSpec(name="search", description="web search", input_schema={"type": "object"})
    kwargs = _build_codex_call_kwargs(_req(tools=[tool]))
    assert kwargs["tools"] == [
        {
            "type": "function",
            "name": "search",
            "description": "web search",
            "parameters": {"type": "object"},
        }
    ]
    assert kwargs["tool_choice"] == "auto"
    assert kwargs["parallel_tool_calls"] is True


def test_codex_kwargs_no_tools_when_none_provided() -> None:
    kwargs = _build_codex_call_kwargs(_req())
    assert "tools" not in kwargs
    assert "parallel_tool_calls" not in kwargs
