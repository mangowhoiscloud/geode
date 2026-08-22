from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from core.agent.plan import Plan, PlanStep
from core.observability.session_metrics import SessionMetrics
from core.server.ipc_server.plan_command import run_plan_slash


def test_plan_install_rolls_back_when_checkpoint_fails(monkeypatch) -> None:
    from core.agent import plan as plan_module

    prior = Plan(steps=(PlanStep("prior", "Keep prior", "Prior remains"),))
    candidate = Plan(steps=(PlanStep("next", "Install next", "Next remains"),))
    metrics = SessionMetrics(active_plan=prior, replan_attempts_on_current_step=2)
    timeline = MagicMock()
    loop = SimpleNamespace(
        _session_metrics=metrics,
        _timeline=timeline,
        _save_checkpoint=MagicMock(return_value=False),
    )
    monkeypatch.setattr(plan_module, "plan_async", AsyncMock(return_value=candidate))

    with pytest.raises(RuntimeError, match="checkpoint failed"):
        asyncio.run(run_plan_slash(loop, "Replace the plan"))

    assert metrics.active_plan is prior
    assert metrics.replan_attempts_on_current_step == 2
    timeline.record_plan_state.assert_not_called()
