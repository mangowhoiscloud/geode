"""Verification consumes the original budget and receives real candidates."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig, _guards, _phases, _provider_call
from core.agent.loop.models import TerminationReason, TurnState
from core.agent.tool_executor import ToolExecutor
from core.hooks import HookCorrelation
from core.llm.agentic_response import AgenticResponse, TextBlock
from core.llm.token_tracker import LLMUsage


def _loop() -> AgenticLoop:
    return AgenticLoop(
        ConversationContext(),
        ToolExecutor(auto_approve=True),
        config=AgenticLoopConfig(max_rounds=0, time_budget_s=900),
        model="gpt-5.6-sol",
        provider="openai",
        quiet=True,
    )


def test_verification_preparation_keeps_root_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _loop()
    monkeypatch.setattr(_guards, "_open_turn", AsyncMock(return_value=None))
    monkeypatch.setattr(loop, "_prepare_task_preflight", lambda _text: "")
    monkeypatch.setattr(loop, "_build_system_prompt", lambda: "System")
    monkeypatch.setattr("core.agent.loop._phases.time.monotonic", lambda: 100.0)
    asyncio.run(
        _phases.prepare_input(
            loop,
            "request",
            verify_continuation=None,
            goal_continuation=None,
            goal_continuation_trigger="active_goal",
        )
    )
    assert loop._loop_start_time == 100.0
    monkeypatch.setattr("core.agent.loop._phases.time.monotonic", lambda: 700.0)
    asyncio.run(
        _phases.prepare_input(
            loop,
            "repair",
            verify_continuation=HookCorrelation(verify_attempt=1),
            goal_continuation=None,
            goal_continuation_trigger="active_goal",
        )
    )
    assert loop._loop_start_time == 100.0
    monkeypatch.setattr("core.agent.loop._phases.time.monotonic", lambda: 1001.0)
    assert _guards._check_round_guards(loop, 0) == "time_budget"


@pytest.mark.parametrize(
    "mode,attempt,remaining,allow_tools,expected_choice",
    [
        ("reflexion", 0, 600, True, "auto"),
        ("reflexion", 0, 299, True, "none"),
        ("reflexion", 1, 299, True, "auto"),
        ("reflexion", 1, 29, True, "none"),
        ("rule_based", 0, 299, True, "auto"),
        ("reflexion", 0, 299, False, "none"),
    ],
)
def test_first_candidate_reserves_repair_without_disabling_repair_tools(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    attempt: int,
    remaining: int,
    allow_tools: bool,
    expected_choice: str,
) -> None:
    monkeypatch.setenv("GEODE_VERIFY_MODE", mode)
    monkeypatch.setattr(_provider_call._context, "check_context_overflow", AsyncMock())
    loop = _loop()
    loop._loop_start_time = 100.0
    loop._verify_attempt = attempt
    monkeypatch.setattr("time.monotonic", lambda: 1000.0 - remaining)
    request, *_rest = asyncio.run(
        _provider_call._prepare_request(
            loop,
            "Static\n<dynamic_context></dynamic_context>",
            [],
            round_idx=0,
            model=None,
            response_schema=None,
            allow_tools=allow_tools,
        )
    )
    assert request.tool_choice == {"type": expected_choice}
    system = request.system_prompt
    assert ("Remaining wall time" in system) is (mode == "reflexion" and allow_tools)
    if "Candidate checkpoint" in system:
        assert system.index("Candidate checkpoint") < system.index("</dynamic_context>")


@pytest.mark.parametrize("is_last_round", [False, True])
def test_long_candidate_reaches_finalization(
    monkeypatch: pytest.MonkeyPatch, is_last_round: bool
) -> None:
    loop = _loop()
    loop._consecutive_text_only_rounds = 1  # a legacy checkpoint must not veto this candidate
    monkeypatch.setattr(loop, "_track_usage_async", AsyncMock())
    record_round = AsyncMock()
    monkeypatch.setattr(loop, "_record_text_only_round", record_round)
    monkeypatch.setattr(_guards, "_guard_cost_budget", lambda *_args, **_kwargs: None)
    captured: list[Any] = []

    async def finalize(_loop: Any, result: Any, **_kwargs: Any) -> Any:
        captured.append(result)
        return result

    monkeypatch.setattr(_phases, "assemble_termination", finalize)
    turn = _phases.PreparedTurn("task", [], TurnState(turn_id="t-test"), "", "", "", True)
    text = "Evidence and corrected result. " * 1000
    response = AgenticResponse(
        content=[TextBlock(text=text)],
        stop_reason="end_turn",
        usage=LLMUsage(input_tokens=100, output_tokens=12000),
    )
    result = asyncio.run(
        _phases.process_tool_calls(
            loop,
            turn,
            response,
            0,
            is_last_round=is_last_round,
            step_snapshot=None,
        )
    )
    assert captured == [result]
    record_round.assert_awaited_once_with(0, text=text.strip())
    expected = TerminationReason.FORCED_TEXT if is_last_round else TerminationReason.NATURAL
    assert result.termination_reason == expected
    assert result.text == text.strip()
