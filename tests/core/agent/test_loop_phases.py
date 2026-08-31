"""R3.2 characterization for the explicit AgenticLoop phase boundary."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent.loop import _guards, _phases
from core.agent.loop.agent_loop import AgenticLoop
from core.agent.loop.models import AgenticResult, TerminationReason, TurnState
from core.llm.agentic_response import AgenticResponse, ToolUseBlock
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


def test_observe_checkpoints_balanced_tool_history_before_next_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_guards, "_guard_convergence", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_guards, "_guard_repeated_success", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        _guards,
        "_tool_round_assistant_message",
        lambda *_args: {"role": "assistant", "content": [{"type": "tool_use"}]},
    )
    checkpoints: list[tuple[str, int]] = []
    context = SimpleNamespace(messages=[])
    loop = SimpleNamespace(
        context=context,
        _convergence=SimpleNamespace(total_consecutive_tool_errors=0),
        _consecutive_tool_tracker=[],
        _update_tool_error_tracking=lambda _results: None,
        _save_checkpoint=lambda user_input, round_idx=0: checkpoints.append(
            (user_input, round_idx)
        ),
    )
    turn = _phases.PreparedTurn(
        user_input="task",
        messages=[],
        turn_state=TurnState(turn_id="turn"),
        system_prompt="system",
        reflection_hint="",
        verification_hint="",
        verification_continuation=False,
    )
    response = AgenticResponse(
        content=[ToolUseBlock(id="call-1", name="read_file", input={"path": "a"})]
    )

    result = asyncio.run(
        _phases.observe_and_compact(
            loop,
            turn,
            response,
            [{"type": "tool_result", "tool_use_id": "call-1", "content": "ok"}],
            0,
        )
    )

    assert result is None
    assert turn.turn_state.round_index == 1
    assert context.messages == turn.messages
    assert [message["role"] for message in context.messages] == ["assistant", "user"]
    assert checkpoints == [("task", 1)]


def test_tool_batch_checkpoint_precedes_auxiliary_reflection() -> None:
    source = inspect.getsource(_phases.process_tool_calls)

    checkpoint = source.index("loop._save_checkpoint(")
    reflection = source.index("loop._finish_cognitive_tool_round(")
    assert checkpoint < reflection
    assert "completed tool batch could not be checkpointed" in source


def test_pending_tool_batch_checkpoint_failure_prevents_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_guards, "_guard_cost_budget", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_guards, "_guard_overthinking", _async_none)
    monkeypatch.setattr(_guards, "_guard_model_refusal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        _guards,
        "_tool_round_assistant_message",
        lambda *_args: {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "call-1", "name": "action"}],
        },
    )
    dispatched = False

    async def track_usage(_response: AgenticResponse) -> None:
        return None

    async def dispatch(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        nonlocal dispatched
        dispatched = True
        return []

    context = SimpleNamespace(messages=[])
    loop = SimpleNamespace(
        context=context,
        _checkpoint=object(),
        _session_id="s-test",
        _set_llm_retry_count=lambda _count: None,
        _track_usage_async=track_usage,
        _save_checkpoint=lambda *_args, **_kwargs: False,
        _run_cognitive_act_observe_cycle=dispatch,
    )
    turn = _phases.PreparedTurn(
        user_input="task",
        messages=[],
        turn_state=TurnState(turn_id="turn"),
        system_prompt="system",
        reflection_hint="",
        verification_hint="",
        verification_continuation=False,
    )
    response = AgenticResponse(
        content=[ToolUseBlock(id="call-1", name="action", input={})],
        stop_reason="tool_use",
    )

    with pytest.raises(RuntimeError, match="pending tool batch"):
        asyncio.run(
            _phases.process_tool_calls(
                loop,
                turn,
                response,
                0,
                is_last_round=False,
                step_snapshot=None,
            )
        )

    assert dispatched is False


async def _async_none(*_args: Any, **_kwargs: Any) -> None:
    return None
