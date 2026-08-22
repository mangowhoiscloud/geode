"""R3.2 characterization for the explicit AgenticLoop phase boundary."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from core.agent.loop import _guards, _phases
from core.agent.loop.agent_loop import AgenticLoop
from core.agent.loop.models import AgenticResult, TerminationReason, TurnState
from core.llm.agentic_response import AgenticResponse
from core.ui.status import TextSpinner


@pytest.mark.parametrize(
    "phase",
    [
        _phases.prepare_input,
        _phases.prepare_model_call,
        _phases.call_provider,
        _phases.process_tool_calls,
        _phases.observe_and_compact,
        _phases.assemble_termination,
    ],
)
def test_phase_collaborators_are_explicit_coroutines(phase: Any) -> None:
    assert inspect.iscoroutinefunction(phase)


def test_arun_once_runs_the_six_phases_in_order() -> None:
    source = inspect.getsource(AgenticLoop._arun_once)
    names = [
        "prepare_input",
        "prepare_model_call",
        "call_provider",
        "process_tool_calls",
        "observe_and_compact",
        "assemble_termination",
    ]
    offsets = [source.index(f"_phases.{name}(") for name in names]
    assert offsets == sorted(offsets)


def test_arun_once_returns_the_observation_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    turn = _phases.PreparedTurn(
        user_input="task",
        messages=[],
        turn_state=TurnState(turn_id="turn"),
        system_prompt="system",
        reflection_hint="",
        verification_hint="",
        verification_continuation=False,
    )
    response = AgenticResponse()
    terminal = AgenticResult(
        text="done",
        rounds=1,
        termination_reason=TerminationReason.NATURAL,
    )

    async def prepare_input(*_args: Any, **_kwargs: Any) -> _phases.PreparedTurn:
        calls.append("input")
        return turn

    async def prepare_model(*_args: Any, **_kwargs: Any) -> _phases.PreparedModelCall:
        calls.append("model")
        return _phases.PreparedModelCall("system", TextSpinner("", quiet=True), None)

    async def provider(*_args: Any, **_kwargs: Any) -> AgenticResponse:
        calls.append("provider")
        return response

    async def tools(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        calls.append("tools")
        return []

    async def observe(*_args: Any, **_kwargs: Any) -> AgenticResult:
        calls.append("observe")
        return terminal

    monkeypatch.setattr(_phases, "prepare_input", prepare_input)
    monkeypatch.setattr(_phases, "prepare_model_call", prepare_model)
    monkeypatch.setattr(_phases, "call_provider", provider)
    monkeypatch.setattr(_phases, "process_tool_calls", tools)
    monkeypatch.setattr(_phases, "observe_and_compact", observe)

    class Stub:
        max_rounds = 0

    monkeypatch.setattr(_guards, "_check_round_guards", lambda *_args: None)

    result = asyncio.run(AgenticLoop._arun_once.__get__(Stub(), Stub)("task"))

    assert result is terminal
    assert calls == ["input", "model", "provider", "tools", "observe"]
