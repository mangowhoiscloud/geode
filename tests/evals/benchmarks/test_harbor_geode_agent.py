from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
            "cache_read_tokens": 4,
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

    for cache in (None, 0, 9):
        missing = _atif_trajectory_from_geode(
            trajectory,
            model="gpt-5.6-sol",
            provider="openai",
            source="subscription",
            effort=None,
            version="test",
            metrics={"cache_read_tokens": cache},
        )
        assert missing["final_metrics"]["total_cached_tokens"] == cache
        assert missing["final_metrics"]["total_cost_usd"] is None
        assert missing["steps"][1]["reasoning_effort"] is None

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


def _observed_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cache: int | None,
    failure: BaseException | None = None,
    leave_call_open: bool = False,
) -> tuple[GeodeHarborAgent, list[Any]]:
    """Exercise real thin-loop wiring and SQLite, never a provider call."""
    from core.agent.loop import AgenticLoop
    from core.config.policy_source import EMPTY_POLICY_SOURCES
    from core.hooks.system import HookEvent
    from core.memory.atomic_write import atomic_write_json
    from core.wiring import runtime
    from evals.platforms import harbor

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEODE_HOME", str(tmp_path / "geode-home"))
    monkeypatch.setenv("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", "original")
    monkeypatch.setattr(runtime, "build_policy_sources", lambda: EMPTY_POLICY_SOURCES)
    monkeypatch.setattr(harbor, "_write_atif_trajectory", atomic_write_json)
    loops: list[Any] = []

    async def arun(loop: Any, instruction: str) -> SimpleNamespace:
        loops.append(loop)
        assert not loop._hooks._hooks and not loop._hooks._prefix_hooks
        assert list(loop._hooks._sinks) == ["harbor_observation"]
        assert loop._source == "subscription"
        assert loop._effort == "max"
        assert loop._time_budget_s == 900
        assert [t["name"] for t in loop._tools] == ["terminal_exec"]
        assert loop.max_tokens == 32768 and loop.max_rounds == 0
        loop._timeline.record_session_start(model=loop.model, provider="openai")
        loop._timeline.bind_turn("t-observed")
        loop._timeline.record_user_message(instruction)

        async def emit(session_id: str, call_id: str, cached: int | None) -> None:
            correlation = {
                "session_id": session_id,
                "turn_id": "t-observed",
                "llm_call_id": call_id,
                "llm_attempt_id": call_id + ":attempt-1",
                "model": loop.model,
                "provider": "openai",
                "adapter": "test-no-model",
            }
            await loop._hooks.trigger_async(HookEvent.LLM_CALL_STARTED, correlation)
            await loop._hooks.trigger_async(
                HookEvent.LLM_CALL_ENDED,
                {
                    **correlation,
                    "latency_ms": 1.0,
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "cached_input_tokens": cached,
                        "cache_write_tokens": None,
                    },
                },
            )

        await emit(loop._session_id, "c-1", cache)
        # A different concurrent trial may use the same canonical database.
        await emit("another-session", "other-call", 999)
        if failure is not None:
            correlation = {
                "session_id": loop._session_id,
                "llm_call_id": "c-2",
                "llm_attempt_id": "c-2:attempt-1",
                "model": loop.model,
                "provider": "openai",
                "adapter": "test-no-model",
            }
            await loop._hooks.trigger_async(HookEvent.LLM_CALL_STARTED, correlation)
            if not leave_call_open:
                await loop._hooks.trigger_async(
                    HookEvent.LLM_CALL_ENDED,
                    {**correlation, "error_type": type(failure).__name__},
                )
            raise failure
        loop._timeline.record_assistant_message("done")
        return SimpleNamespace(
            error=None,
            termination_reason="natural",
            rounds=1,
            # Legacy usage omits a zero cache; the durable record must win.
            usage=SimpleNamespace(to_dict=lambda: {"input_tokens": 10, "output_tokens": 2}),
        )

    async def complete(loop: Any) -> None:
        loop._timeline.record_session_end()

    async def error(loop: Any) -> None:
        loop._timeline.record_session_end(status="error")

    monkeypatch.setattr(AgenticLoop, "arun", arun)
    monkeypatch.setattr(AgenticLoop, "amark_session_completed", complete)
    monkeypatch.setattr(AgenticLoop, "amark_session_error", error)
    monkeypatch.setattr(GeodeHarborAgent, "version", lambda _self: "test")
    agent = object.__new__(GeodeHarborAgent)
    agent.logs_dir = tmp_path / "agent"
    agent.model_name = "gpt-5.6-sol"
    agent.provider = "openai"
    agent.source = "subscription"
    agent.effort = "max"
    agent.agent_timeout_sec = 900
    return agent, loops


@pytest.mark.parametrize("cache", [None, 0, 4])
def test_thin_observer_persists_missing_zero_and_positive_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cache: int | None
) -> None:
    from core.observability.event_store import HookEventStore

    agent, loops = _observed_agent(tmp_path, monkeypatch, cache=cache)
    context = SimpleNamespace()
    asyncio.run(agent.run("Inspect the task.", _Environment(), context))
    assert context.n_cache_tokens == cache
    assert context.n_input_tokens == 10 and context.n_output_tokens == 2
    assert context.metadata["usage"]["call_events"] == 1
    assert context.metadata["usage"]["attempt_pairing_complete"]
    assert context.metadata["usage"]["whole_runtime_complete"] is False
    assert loops[0]._hooks.closed
    store = HookEventStore(loops[0]._timeline.db_path)
    try:
        rows = store.read(session_id=loops[0]._session_id, event_filter="llm_call_ended")
        assert len(rows) == 1
        assert rows[0].payload["usage"]["cached_input_tokens"] == cache
    finally:
        store.close()
    trajectory = json.loads((agent.logs_dir / "geode-trajectory.json").read_text())
    assert trajectory["outcome"]["usage"] == context.metadata["usage"]
    assert trajectory["runtime_event_refs"]
    atif = json.loads((agent.logs_dir / "trajectory.json").read_text())
    assert atif["final_metrics"]["total_cached_tokens"] == cache


@pytest.mark.parametrize("failure", [TimeoutError(), asyncio.CancelledError()])
@pytest.mark.parametrize("leave_call_open", [False, True])
def test_thin_observer_exports_on_timeout_without_fabricating_complete_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    leave_call_open: bool,
) -> None:
    import os

    agent, loops = _observed_agent(
        tmp_path, monkeypatch, cache=4, failure=failure, leave_call_open=leave_call_open
    )
    context = SimpleNamespace()
    with pytest.raises(type(failure)):
        asyncio.run(agent.run("Inspect the task.", _Environment(), context))
    assert loops[0]._hooks.closed
    assert os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] == "original"
    usage = context.metadata["usage"]
    assert context.n_cache_tokens is None and context.n_input_tokens is None
    assert usage["cached_input_tokens_observed_sum"] == 4
    assert usage["started_events"] == 2
    assert usage["attempt_pairing_complete"] is not leave_call_open
    for name in ("geode-trajectory.json", "geode-trajectory.private.json"):
        trajectory = json.loads((agent.logs_dir / name).read_text())
        assert trajectory["outcome"]["error_type"] == type(failure).__name__
        assert trajectory["outcome"]["usage"] == usage
        assert trajectory["events"][-1]["kind"] == "session.ended"
    assert (agent.logs_dir / "trajectory.json").is_file()


@pytest.mark.parametrize("interrupted", [False, True])
def test_thin_observer_preserves_canonical_evidence_when_atif_export_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool
) -> None:
    from evals.platforms import harbor

    agent, loops = _observed_agent(
        tmp_path, monkeypatch, cache=0, failure=TimeoutError() if interrupted else None
    )

    def reject_atif(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError("test ATIF projection failure")

    monkeypatch.setattr(harbor, "_write_atif_trajectory", reject_atif)
    with pytest.raises(TimeoutError if interrupted else ValueError):
        asyncio.run(agent.run("Inspect the task.", _Environment(), SimpleNamespace()))
    assert loops[0]._hooks.closed
    for name in ("geode-trajectory.json", "geode-trajectory.private.json"):
        trajectory = json.loads((agent.logs_dir / name).read_text())
        assert trajectory["runtime_event_refs"]
        assert trajectory["outcome"]["usage"]["scope"] == "recorded-agentic-loop-attempts-only"
