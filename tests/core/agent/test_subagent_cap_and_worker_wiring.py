"""PR-CONFIG-SLOP-SWEEP — wiring guards for two previously-dead sub-agent knobs.

Both ``max_total_subagents`` and ``subagent_max_tokens`` were declared on
``Settings`` and mapped into the ``config.toml`` cascade, but no runtime code
read them — so an operator setting ``[subagent] max_total`` / ``max_tokens``
got silently ignored. These pin the now-wired behaviour. The worker ``model``
inherit-sentinel (was a frozen ``claude-opus-4-6`` literal) is pinned too.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from core.agent.sub_agent import SubAgentManager, SubTask
from core.agent.worker import WorkerRequest
from core.config import settings
from core.orchestration.isolated_execution import IsolatedRunner, IsolationResult


def _capped_manager(cap: int) -> SubAgentManager:
    mgr = SubAgentManager(IsolatedRunner(), max_total_subagents=cap)
    # Intercept the subprocess/thread spawn — return a canned success so the
    # test exercises only the cap arithmetic, not a real worker run.
    mgr._runner.arun = AsyncMock(  # type: ignore[method-assign]
        return_value=IsolationResult(session_id="s", success=True, output='{"ok": true}')
    )
    return mgr


def _tasks(n: int) -> list[SubTask]:
    return [SubTask(task_id=f"t{i}", description="d", task_type="analyze") for i in range(n)]


class TestSessionTotalCap:
    def test_cap_stored_and_counter_starts_zero(self) -> None:
        mgr = SubAgentManager(IsolatedRunner(), max_total_subagents=7)
        assert mgr._max_total_subagents == 7
        assert mgr._spawned_total == 0

    def test_default_cap_is_15(self) -> None:
        # Operator-approved generous ceiling (PR-CONFIG-SLOP-SWEEP).
        assert SubAgentManager(IsolatedRunner())._max_total_subagents == 15

    def test_overflow_rejected_with_error(self) -> None:
        mgr = _capped_manager(2)
        results = asyncio.run(mgr.adelegate(_tasks(3)))
        # One SubResult per submitted task: 2 spawned + 1 cap rejection.
        assert len(results) == 3
        assert sum(1 for r in results if r.success) == 2
        rejected = [r for r in results if not r.success]
        assert len(rejected) == 1
        assert "Session sub-agent limit reached" in (rejected[0].error or "")
        assert mgr._spawned_total == 2

    def test_cap_accumulates_across_calls(self) -> None:
        mgr = _capped_manager(2)
        asyncio.run(mgr.adelegate(_tasks(2)))  # consumes the whole budget
        assert mgr._spawned_total == 2
        more = asyncio.run(
            mgr.adelegate([SubTask(task_id="x", description="d", task_type="analyze")])
        )
        assert len(more) == 1
        assert not more[0].success
        assert "Session sub-agent limit reached" in (more[0].error or "")
        assert mgr._spawned_total == 2  # nothing new spawned

    def test_within_cap_spawns_all(self) -> None:
        mgr = _capped_manager(15)
        results = asyncio.run(mgr.adelegate(_tasks(3)))
        assert len(results) == 3
        assert all(r.success for r in results)
        assert mgr._spawned_total == 3


class TestWorkerRequestWiring:
    def test_model_provider_inherit_sentinels(self) -> None:
        # No frozen model literal — empty = inherit the runtime's model.
        req = WorkerRequest(task_id="t")
        assert req.model == ""
        assert req.provider == ""
        assert req.subagent_max_tokens == 32768

    def test_from_dict_defaults_to_sentinels(self) -> None:
        req = WorkerRequest.from_dict({"task_id": "t"})
        assert req.model == ""
        assert req.provider == ""
        assert req.subagent_max_tokens == 32768

    def test_subagent_max_tokens_round_trips(self) -> None:
        req = WorkerRequest(task_id="t", subagent_max_tokens=4096)
        assert WorkerRequest.from_dict(req.to_dict()).subagent_max_tokens == 4096

    def test_build_worker_request_threads_max_tokens_from_settings(self) -> None:
        mgr = SubAgentManager(IsolatedRunner())
        req = mgr._build_worker_request(
            SubTask(task_id="t", description="d", task_type="analyze"),
            default_model="claude-opus-4-8",
        )
        assert req.subagent_max_tokens == settings.subagent_max_tokens
