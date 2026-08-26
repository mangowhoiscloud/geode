from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from core.observability.trajectory import build_trajectory
from evals.platforms.harbor import (
    GeodeHarborAgent,
    HarborExecTool,
    _agent_time_budget,
    _atif_trajectory_from_geode,
)


class _Environment:
    def __init__(self) -> None:
        self.call: dict[str, object] = {}

    async def exec(self, **kwargs: object) -> SimpleNamespace:
        self.call = kwargs
        return SimpleNamespace(stdout="ok\n", stderr="", return_code=0)


def test_harbor_exec_tool_preserves_environment_result() -> None:
    environment = _Environment()
    result = asyncio.run(
        HarborExecTool(environment).aexecute(
            command="pwd",
            cwd="/root",
            timeout_seconds=7,
        )
    )
    assert environment.call == {"command": "pwd", "cwd": "/root", "timeout_sec": 7}
    assert result == {"result": "ok\n", "stderr": "", "return_code": 0}


def test_harbor_agent_projects_canonical_history_to_atif() -> None:
    trajectory = build_trajectory(
        trajectory_id="harbor-s-1",
        captured_at="2026-08-26T00:00:00Z",
        source={"harness": "harbor", "session": "s-1"},
        events=[
            {
                "occurred_at": "2026-08-26T00:00:00Z",
                "kind": "message.user",
                "actor": "user",
                "session_id": "s-1",
                "turn_id": "t-1",
                "payload": {"content": "fix it"},
            },
            {
                "occurred_at": "2026-08-26T00:00:01Z",
                "kind": "tool.called",
                "actor": "assistant",
                "session_id": "s-1",
                "turn_id": "t-1",
                "call_id": "c-1",
                "payload": {"tool": "terminal_exec", "arguments": {"command": "pwd"}},
            },
            {
                "occurred_at": "2026-08-26T00:00:02Z",
                "kind": "tool.completed",
                "actor": "tool",
                "session_id": "s-1",
                "turn_id": "t-1",
                "call_id": "c-1",
                "payload": {
                    "tool": "terminal_exec",
                    "status": "success",
                    "result": {"result": "/root\n", "return_code": 0},
                },
            },
            {
                "occurred_at": "2026-08-26T00:00:03Z",
                "kind": "message.assistant",
                "actor": "assistant",
                "session_id": "s-1",
                "turn_id": "t-1",
                "payload": {"content": "done"},
            },
        ],
        outcome={"scored": False},
        provenance={"adapter": "test"},
        privacy={"review_state": "local"},
    )

    atif = _atif_trajectory_from_geode(
        trajectory,
        model="gpt-5.6-sol",
        provider="openai",
        source="subscription",
        effort="max",
        version="1.0.26",
        metrics={
            "input_tokens": 10,
            "cache_read_input_tokens": 4,
            "output_tokens": 2,
            "cost_usd": 0.1,
        },
    )

    assert GeodeHarborAgent.SUPPORTS_ATIF is True
    assert _agent_time_budget(None) == 0.0
    assert [step["source"] for step in atif["steps"]] == ["user", "agent", "agent"]
    tool_step = atif["steps"][1]
    assert tool_step["tool_calls"][0]["tool_call_id"] == "c-1"
    assert tool_step["observation"]["results"][0]["source_call_id"] == "c-1"
    assert '"return_code": 0' in tool_step["observation"]["results"][0]["content"]
    assert atif["final_metrics"] == {
        "total_prompt_tokens": 10,
        "total_completion_tokens": 2,
        "total_cached_tokens": 4,
        "total_cost_usd": 0.1,
        "total_steps": 3,
    }

    trajectory["integrity"]["scope_complete"] = False
    with pytest.raises(ValueError, match="scope-complete"):
        _atif_trajectory_from_geode(
            trajectory,
            model="gpt-5.6-sol",
            provider="openai",
            source="subscription",
            effort="max",
            version="1.0.26",
            metrics={},
        )
