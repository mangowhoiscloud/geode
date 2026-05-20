"""PR-3 C-2 — Reflection node invariants.

Pins the structure + behaviour of ``core/agent/loop/_reflection.py``:
prompt assembly, JSON parsing, schema-typed casts, settings knobs,
and AgenticLoop wiring. The actual LLM call is mocked — tests must
not consume provider quota.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from core.agent.cognitive_state import CognitiveState
from core.agent.loop import _reflection

# ---------------------------------------------------------------------------
# Pure-function invariants (no LLM)
# ---------------------------------------------------------------------------


def test_summarise_tool_results_empty() -> None:
    assert _reflection._summarise_tool_results([]) == "(no tool results — text-only round)"


def test_summarise_tool_results_str_content() -> None:
    out = _reflection._summarise_tool_results([{"tool_use_id": "t1", "content": "hello world"}])
    assert "t1" in out
    assert "hello world" in out


def test_summarise_tool_results_list_content() -> None:
    out = _reflection._summarise_tool_results(
        [{"tool_use_id": "t1", "content": [{"type": "text", "text": "deep result"}]}]
    )
    assert "deep result" in out


def test_summarise_tool_results_caps_long_text() -> None:
    long = "x" * 500
    out = _reflection._summarise_tool_results([{"tool_use_id": "t1", "content": long}])
    # 200 head + ellipsis — never the full 500
    assert "x" * 500 not in out
    assert "…" in out


def test_summarise_tool_results_caps_entries() -> None:
    rows = [{"tool_use_id": f"t{i}", "content": f"r{i}"} for i in range(20)]
    out = _reflection._summarise_tool_results(rows, cap=8)
    assert "truncated" in out
    assert "t0" in out and "t7" in out
    assert "t8" not in out


def test_parse_reflection_plain_json() -> None:
    parsed = _reflection._parse_reflection('{"hypotheses": ["a"], "confidence": 0.5}')
    assert parsed == {"hypotheses": ["a"], "confidence": 0.5}


def test_parse_reflection_strips_fence() -> None:
    parsed = _reflection._parse_reflection('```json\n{"hypotheses": ["a"], "confidence": 0.5}\n```')
    assert parsed == {"hypotheses": ["a"], "confidence": 0.5}


def test_parse_reflection_raises_on_non_object() -> None:
    with pytest.raises(ValueError):
        _reflection._parse_reflection('["not", "an", "object"]')


def test_apply_reflection_populates_hypotheses() -> None:
    state = CognitiveState(goal="x")
    _reflection._apply_reflection(state, {"hypotheses": ["h1", "h2"]})
    assert state.hypotheses == ["h1", "h2"]


def test_apply_reflection_caps_hypotheses_at_five() -> None:
    state = CognitiveState()
    _reflection._apply_reflection(state, {"hypotheses": [f"h{i}" for i in range(10)]})
    assert len(state.hypotheses) == 5
    assert state.hypotheses[0] == "h0"
    assert state.hypotheses[-1] == "h4"


def test_apply_reflection_truncates_hypotheses_at_120_chars() -> None:
    state = CognitiveState()
    long = "x" * 500
    _reflection._apply_reflection(state, {"hypotheses": [long]})
    assert len(state.hypotheses[0]) == 120


def test_apply_reflection_clamps_confidence() -> None:
    state = CognitiveState()
    _reflection._apply_reflection(state, {"confidence": 1.5})
    assert state.confidence == 1.0
    _reflection._apply_reflection(state, {"confidence": -0.3})
    assert state.confidence == 0.0


def test_apply_reflection_pushes_hint_into_subgoals() -> None:
    state = CognitiveState()
    _reflection._apply_reflection(state, {"next_action_hint": "try X"})
    _reflection._apply_reflection(state, {"next_action_hint": "try Y"})
    assert state.subgoals == ["try X", "try Y"]


def test_apply_reflection_caps_subgoals_at_five() -> None:
    state = CognitiveState()
    for i in range(8):
        _reflection._apply_reflection(state, {"next_action_hint": f"hint{i}"})
    assert len(state.subgoals) == 5
    assert state.subgoals[0] == "hint3"
    assert state.subgoals[-1] == "hint7"


def test_apply_reflection_ignores_wrong_types() -> None:
    """Schema-typed casts — bad types silently drop the field, not
    poison the whole state."""
    state = CognitiveState(goal="x", confidence=0.5, hypotheses=["keep"])
    _reflection._apply_reflection(
        state,
        {"hypotheses": "not-a-list", "confidence": "high", "next_action_hint": 123},
    )
    # all dropped — original state preserved
    assert state.hypotheses == ["keep"]
    assert state.confidence == 0.5
    assert state.subgoals == []


# ---------------------------------------------------------------------------
# Settings knobs
# ---------------------------------------------------------------------------


def test_settings_carries_cognitive_reflection_fields() -> None:
    from core.config._settings import Settings

    fields = Settings.model_fields
    assert "cognitive_reflection_enabled" in fields
    assert fields["cognitive_reflection_enabled"].default is True
    assert "cognitive_reflection_model" in fields
    assert fields["cognitive_reflection_model"].default == "claude-haiku-4-5-20251001"
    assert "cognitive_reflection_max_tokens" in fields
    assert fields["cognitive_reflection_max_tokens"].default == 512


def test_toml_map_carries_cognitive_reflection_keys() -> None:
    from core.config import _TOML_TO_SETTINGS

    assert _TOML_TO_SETTINGS["cognitive.reflection_enabled"] == "cognitive_reflection_enabled"
    assert _TOML_TO_SETTINGS["cognitive.reflection_model"] == "cognitive_reflection_model"
    assert _TOML_TO_SETTINGS["cognitive.reflection_max_tokens"] == "cognitive_reflection_max_tokens"


# ---------------------------------------------------------------------------
# AgenticLoop wiring
# ---------------------------------------------------------------------------


def test_agentic_loop_has_maybe_reflect() -> None:
    """The AgenticLoop must own the toggle check, not _reflection.py —
    so the LLM module stays pure. Pin the wiring."""
    from core.agent.loop.agent_loop import AgenticLoop

    assert hasattr(AgenticLoop, "_maybe_reflect")
    src = inspect.getsource(AgenticLoop._maybe_reflect)
    assert "cognitive_reflection_enabled" in src
    assert "reflect_async" in src


def test_run_cognitive_act_observe_cycle_calls_maybe_reflect() -> None:
    """The reflection node must fire between ``record_round`` and
    the REFLECT hook event — otherwise downstream listeners see the
    deterministic snapshot, not the LLM-derived belief update."""
    from core.agent.loop.agent_loop import AgenticLoop

    src = inspect.getsource(AgenticLoop._run_cognitive_act_observe_cycle)
    # ordering: record_round → _maybe_reflect → COGNITIVE_REFLECT
    record_pos = src.index("self.cognitive_state.record_round(")
    reflect_call_pos = src.index("self._maybe_reflect(")
    reflect_event_pos = src.index("HookEvent.COGNITIVE_REFLECT")
    assert record_pos < reflect_call_pos < reflect_event_pos, (
        "Cognitive cycle ordering broken: record_round must precede "
        "_maybe_reflect must precede COGNITIVE_REFLECT event emission."
    )


# ---------------------------------------------------------------------------
# reflect_async — error tolerance
# ---------------------------------------------------------------------------


class _StubAdapter:
    def __init__(self, response: Any = None, raise_exc: BaseException | None = None) -> None:
        self._response = response
        self._raise = raise_exc

    async def agentic_call(self, **_kwargs: Any) -> Any:
        if self._raise is not None:
            raise self._raise
        return self._response


class _StubResponse:
    def __init__(self, text: str) -> None:
        from types import SimpleNamespace

        self.content = [SimpleNamespace(text=text)]


def _install_reflection_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    adapter: _StubAdapter,
) -> None:
    """Wire deterministic fakes into the reflection module so tests
    never touch a real LLM provider."""

    async def _fake_call_with_failover(_models: list[str], do_call: Any) -> tuple[Any, str]:
        result = await do_call(_models[0])
        return result, _models[0]

    monkeypatch.setattr(_reflection, "call_with_failover", _fake_call_with_failover, raising=False)
    monkeypatch.setattr(_reflection, "resolve_agentic_adapter", lambda _p: adapter, raising=False)
    monkeypatch.setattr(_reflection, "_resolve_provider", lambda _m: "anthropic", raising=False)


def test_reflect_async_swallows_llm_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the LLM raises, the loop must continue with previous state."""
    state = CognitiveState(hypotheses=["keep"], confidence=0.4)
    _install_reflection_stubs(monkeypatch, adapter=_StubAdapter(raise_exc=RuntimeError("boom")))

    asyncio.run(
        _reflection.reflect_async(
            state, [{"tool_use_id": "t1", "content": "x"}], model="m", max_tokens=128
        )
    )
    assert state.hypotheses == ["keep"]
    assert state.confidence == 0.4


def test_reflect_async_swallows_empty_text(monkeypatch: pytest.MonkeyPatch) -> None:
    state = CognitiveState(hypotheses=["keep"])
    _install_reflection_stubs(monkeypatch, adapter=_StubAdapter(response=_StubResponse("")))

    asyncio.run(_reflection.reflect_async(state, [], model="m", max_tokens=128))
    assert state.hypotheses == ["keep"]


def test_reflect_async_applies_valid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    state = CognitiveState(goal="x")
    _install_reflection_stubs(
        monkeypatch,
        adapter=_StubAdapter(
            response=_StubResponse(
                '{"hypotheses": ["h1", "h2"], "confidence": 0.7, "next_action_hint": "do it"}'
            )
        ),
    )

    asyncio.run(_reflection.reflect_async(state, [], model="m", max_tokens=128))
    assert state.hypotheses == ["h1", "h2"]
    assert state.confidence == 0.7
    assert state.subgoals == ["do it"]


def test_reflect_async_swallows_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    state = CognitiveState(hypotheses=["keep"])
    _install_reflection_stubs(
        monkeypatch, adapter=_StubAdapter(response=_StubResponse("definitely not json"))
    )
    asyncio.run(_reflection.reflect_async(state, [], model="m", max_tokens=128))
    assert state.hypotheses == ["keep"]
