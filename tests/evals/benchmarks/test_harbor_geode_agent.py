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
    _summarize_usage,
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
    include_lost_pair: bool = False,
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

        if include_lost_pair:
            await emit(loop._session_id, "c-lost", cache)
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
        attempt = context.metadata["usage"]["recorded_attempts"][0]
        assert attempt["source_event_id"] == rows[0].id
        assert attempt["source_payload_hash"] == rows[0].payload_hash
        assert attempt["occurred_at"] == rows[0].occurred_at
        assert attempt["llm_attempt_id"] == rows[0].llm_attempt_id
        assert attempt["session_id"] == loops[0]._session_id
        assert attempt["usage"]["cached_input_tokens"] == cache
    finally:
        store.close()
    trajectory = json.loads((agent.logs_dir / "geode-trajectory.json").read_text())
    assert trajectory["outcome"]["usage"] == context.metadata["usage"]
    assert trajectory["runtime_event_refs"]
    atif = json.loads((agent.logs_dir / "trajectory.json").read_text())
    assert atif["final_metrics"]["total_cached_tokens"] == cache


@pytest.mark.parametrize(
    "purpose", ["cognitive_reflection", "turn_verification", "structured_decision"]
)
def test_recorded_attempts_keep_only_numeric_allowlist_and_source_links(purpose: str) -> None:
    start = SimpleNamespace(action="llm.call.started", session_id="s", llm_attempt_id="c:1")
    terminal = SimpleNamespace(
        action="llm.call.ended",
        session_id="s",
        llm_call_id="c",
        tool_call_id="tool-1",
        llm_attempt_id="c:1",
        id=9,
        occurred_at=0.0,
        payload_hash="a" * 64,
        payload={
            "model": "gpt-5.6-sol",
            "response_model": "gpt-5.6-sol-served",
            "provider": "openai",
            "adapter": "codex_oauth",
            "purpose": purpose,
            "source": "subscription",
            "effort": "medium",
            "error_type": None,
            "response_id": "private-response",
            "arguments": {"private": True},
            "result": "private output",
            "thinking": "private reasoning",
            "usage": {
                "input_tokens": 0,
                "output_tokens": 5,
                "cached_input_tokens": 0,
                "cache_write_tokens": None,
                "reasoning_tokens": 3,
                "raw": "private usage",
            },
        },
    )
    summary = _summarize_usage([start, terminal])
    assert summary["terminal_event_count"] == summary["call_events"] == 1
    assert summary["recorded_attempts_timestamp_unit"] == "unix-seconds-utc"
    assert summary["recorded_attempts"] == [
        {
            "session_id": "s",
            "llm_call_id": "c",
            "tool_call_id": "tool-1",
            "llm_attempt_id": "c:1",
            "source_event_id": 9,
            "occurred_at": 0.0,
            "source_payload_hash": "a" * 64,
            "model": "gpt-5.6-sol",
            "response_model": "gpt-5.6-sol-served",
            "provider": "openai",
            "adapter": "codex_oauth",
            "purpose": purpose,
            "source": "subscription",
            "effort": "medium",
            "error_type": None,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 5,
                "cached_input_tokens": 0,
                "cache_write_tokens": None,
                "reasoning_tokens": 3,
                "cache_write_1h_tokens": None,
            },
        }
    ]
    assert "private" not in json.dumps(summary)
    assert json.loads(json.dumps(summary, allow_nan=False)) == summary
    terminal.payload["response_model"] = "private\ninvalid model"
    assert _summarize_usage([start, terminal])["recorded_attempts"][0]["response_model"] is None
    terminal.payload.pop("response_model")
    assert _summarize_usage([start, terminal])["recorded_attempts"][0]["response_model"] is None
    terminal.tool_call_id = "private\ninvalid tool ID"
    assert _summarize_usage([start, terminal])["recorded_attempts"][0]["tool_call_id"] is None
    duplicate = _summarize_usage([start, terminal, terminal])
    assert len(duplicate["recorded_attempts"]) == duplicate["terminal_event_count"] == 2
    assert duplicate["attempt_pairing_complete"] is False
    assert duplicate["input_tokens"] is None
    open_call = _summarize_usage([start])
    assert open_call["recorded_attempts"] == []
    assert open_call["terminal_event_count"] == 0
    assert open_call["attempt_pairing_complete"] is False


def test_usage_pairing_cannot_borrow_another_sessions_terminal() -> None:
    start = SimpleNamespace(action="llm.call.started", session_id="a", llm_attempt_id="c:1")
    end = SimpleNamespace(
        action="llm.call.ended",
        session_id="b",
        llm_attempt_id="c:1",
        payload={"usage": {"input_tokens": 0}},
    )
    mismatched = _summarize_usage([start, end])
    assert mismatched["attempt_pairing_complete"] is False
    assert mismatched["input_tokens"] is None
    end.session_id = "a"
    assert _summarize_usage([start, end])["input_tokens"] == 0
    start.session_id = end.session_id = None
    assert _summarize_usage([start, end])["attempt_pairing_complete"] is False


def test_recorded_attempts_reject_malformed_metadata_without_invented_zero() -> None:
    event = SimpleNamespace(
        action="llm.call.ended",
        llm_attempt_id="c:1",
        id=True,
        occurred_at=float("nan"),
        payload_hash="private",
        payload={
            "model": "x" * 257,
            "provider": "private provider text",
            "purpose": ["private"],
            "effort": "private effort text",
            "source": "/private/source",
            "error_type": "private failure text",
            "usage": {
                "input_tokens": False,
                "output_tokens": -1,
                "cached_input_tokens": 0,
                "reasoning_tokens": None,
            },
        },
    )
    summary = _summarize_usage([event])
    attempt = summary["recorded_attempts"][0]
    assert (
        attempt["source_event_id"]
        is attempt["occurred_at"]
        is attempt["source_payload_hash"]
        is None
    )
    assert attempt["model"] is attempt["provider"] is attempt["error_type"] is None
    assert attempt["purpose"] is attempt["effort"] is attempt["source"] is None
    assert attempt["usage"] == {
        "input_tokens": None,
        "output_tokens": None,
        "cached_input_tokens": 0,
        "cache_write_tokens": None,
        "cache_write_1h_tokens": None,
    }
    assert "private" not in json.dumps(summary, allow_nan=False)


@pytest.mark.parametrize(
    "path",
    ["C:/Users/user/private/config", "C:\\Users\\user\\private\\config", "/srv/private/config"],
)
def test_recorded_attempts_do_not_treat_absolute_paths_as_identifiers(path: str) -> None:
    event = SimpleNamespace(
        action="llm.call.ended",
        session_id=path,
        llm_call_id=path,
        llm_attempt_id=path,
        payload={"model": path, "provider": path, "adapter": path, "error_type": path},
    )
    attempt = _summarize_usage([event])["recorded_attempts"][0]
    for field in (
        "session_id",
        "llm_call_id",
        "llm_attempt_id",
        "model",
        "provider",
        "adapter",
        "error_type",
    ):
        assert attempt[field] is None
    assert "private" not in json.dumps(attempt)


def test_thin_observer_lost_start_and_end_cannot_fake_complete_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.observability.event_store import HookEventStore

    agent, loops = _observed_agent(tmp_path, monkeypatch, cache=4, include_lost_pair=True)
    append = HookEventStore.append

    def fail_lost_pair(store, event):
        if event.llm_call_id == "c-lost":
            raise OSError("private write failure")
        return append(store, event)

    monkeypatch.setattr(HookEventStore, "append", fail_lost_pair)
    context = SimpleNamespace()
    asyncio.run(agent.run("Inspect the task.", _Environment(), context))
    usage = context.metadata["usage"]
    assert usage["attempt_pairing_complete"] is True
    assert usage["call_events"] == usage["started_events"] == 1
    assert usage["known_sink_failure"] is True
    assert loops[0]._hooks.has_sink_failures is True
    assert usage["observation_status"] == "degraded"
    assert usage["mapping_anomaly_events"] == 0
    assert usage["input_tokens"] is context.n_input_tokens is None
    assert usage["cached_input_tokens"] is context.n_cache_tokens is None
    assert usage["input_tokens_observed_sum"] == 10
    assert usage["cached_input_tokens_observed_sum"] == 4
    assert usage["whole_runtime_complete"] is False
    trajectory = json.loads((agent.logs_dir / "geode-trajectory.json").read_text())
    assert trajectory["outcome"]["usage"] == usage


@pytest.mark.parametrize("fallback", ["registry", "sink"])
def test_thin_observer_both_mapping_fallbacks_degrade_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fallback: str
) -> None:
    from core.hooks import HookEvent
    from core.observability import activity_registry

    agent, _loops = _observed_agent(tmp_path, monkeypatch, cache=4, include_lost_pair=True)
    if fallback == "sink":
        mapper = activity_registry.map_hook_to_activity

        def fail_mapping(event, data, *, run_id):
            if data.get("llm_call_id") == "c-lost":
                raise ValueError("private mapping failure")
            return mapper(event, data, run_id=run_id)

        monkeypatch.setattr(activity_registry, "map_hook_to_activity", fail_mapping)
    else:
        for event in (HookEvent.LLM_CALL_STARTED, HookEvent.LLM_CALL_ENDED):
            builder = activity_registry.HOOK_EVENT_TO_ROW_BUILDER[event]

            def fail_builder(data, run_id, delegate=builder):
                if data.get("llm_call_id") == "c-lost":
                    raise ValueError("private mapping failure")
                return delegate(data, run_id)

            monkeypatch.setitem(activity_registry.HOOK_EVENT_TO_ROW_BUILDER, event, fail_builder)

    context = SimpleNamespace()
    asyncio.run(agent.run("Inspect the task.", _Environment(), context))
    usage = context.metadata["usage"]
    assert usage["attempt_pairing_complete"] is True
    assert usage["known_sink_failure"] is False
    assert usage["mapping_anomaly_events"] == 2
    assert usage["observation_status"] == "degraded"
    assert usage["input_tokens"] is context.n_input_tokens is None
    assert usage["input_tokens_observed_sum"] == 10
    assert usage["whole_runtime_complete"] is False
    assert "private mapping failure" not in str(context.metadata)


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
        assert trajectory["outcome"]["usage"]["scope"] == "recorded-runtime-llm-attempts-only"


@pytest.mark.parametrize("phase", ["session_error", "hooks", "export"])
@pytest.mark.parametrize("primary", [TimeoutError("primary"), asyncio.CancelledError("primary")])
@pytest.mark.parametrize(
    "secondary", [RuntimeError("secondary"), asyncio.CancelledError("secondary")]
)
def test_thin_observer_preserves_primary_failure_through_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    primary: BaseException,
    secondary: BaseException,
) -> None:
    import os

    from core.agent.loop import AgenticLoop
    from core.hooks.system import HookSystem
    from evals.platforms import harbor

    agent, loops = _observed_agent(tmp_path, monkeypatch, cache=4, failure=primary)

    async def reject_finalization(_loop: Any) -> None:
        raise secondary

    close = HookSystem.close

    def reject_cleanup(hooks: HookSystem) -> None:
        close(hooks)
        raise secondary

    def reject_export(*_args: Any, **_kwargs: Any) -> None:
        raise secondary

    if phase == "session_error":
        monkeypatch.setattr(AgenticLoop, "amark_session_error", reject_finalization)
    elif phase == "hooks":
        monkeypatch.setattr(HookSystem, "close", reject_cleanup)
    else:
        monkeypatch.setattr(harbor, "_write_atif_trajectory", reject_export)

    context = SimpleNamespace()
    with pytest.raises(type(primary)) as raised:
        asyncio.run(agent.run("Inspect the task.", _Environment(), context))
    assert raised.value is primary
    assert loops[0]._hooks.closed
    assert os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] == "original"
    assert context.metadata["error_type"] == type(primary).__name__
    assert context.metadata["usage"]["cached_input_tokens_observed_sum"] == 4
    assert (agent.logs_dir / "geode-trajectory.json").is_file()


@pytest.mark.parametrize("phase", ["hooks", "export"])
@pytest.mark.parametrize("failure", [RuntimeError("cleanup"), asyncio.CancelledError("cleanup")])
def test_thin_observer_does_not_swallow_first_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    failure: BaseException,
) -> None:
    import os

    from core.hooks.system import HookSystem
    from evals.platforms import harbor

    agent, loops = _observed_agent(tmp_path, monkeypatch, cache=0)
    close = HookSystem.close

    def reject_cleanup(hooks: HookSystem) -> None:
        close(hooks)
        raise failure

    def reject_export(*_args: Any, **_kwargs: Any) -> None:
        raise failure

    if phase == "hooks":
        monkeypatch.setattr(HookSystem, "close", reject_cleanup)
    else:
        monkeypatch.setattr(harbor, "_write_atif_trajectory", reject_export)
    with pytest.raises(type(failure)) as raised:
        asyncio.run(agent.run("Inspect the task.", _Environment(), SimpleNamespace()))
    assert raised.value is failure
    assert loops[0]._hooks.closed
    assert os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] == "original"
