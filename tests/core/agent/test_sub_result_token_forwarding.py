"""Pin the worker-IPC → SubResult token forwarding chain.

PR-SEEDGEN-TOKENS (2026-05-30) — the sub-agent runs in a subprocess; its
``AgenticResult.usage`` reaches the parent as ``WorkerResult`` token
fields → ``IsolationResult`` → ``SubResult`` (via
``SubAgentManager._to_sub_result``). Pre-fix every link dropped the
usage and seed-gen runs reported all zeros. These tests pin the
``IsolationResult`` → ``SubResult`` link.

HARD CONSTRAINT: subscription / CLI calls expose no usage (the adapters
return an empty UsageSummary), so a 0-usage IsolationResult must produce
a 0-usage SubResult — never fabricated.
"""

from __future__ import annotations

from core.agent.sub_agent import SubAgentManager, SubTask
from core.orchestration.isolated_execution import IsolatedRunner, IsolationResult


def _manager() -> SubAgentManager:
    return SubAgentManager(IsolatedRunner())


def _task() -> SubTask:
    return SubTask(task_id="t-tok", description="d", task_type="analyze")


def test_to_sub_result_forwards_usage_on_success() -> None:
    mgr = _manager()
    isolation = IsolationResult(
        session_id="s",
        success=True,
        output='{"ok": true}',
        prompt_tokens=900,
        completion_tokens=300,
        usd_spent=0.018,
    )
    sub = mgr._to_sub_result(_task(), isolation)
    assert sub.success
    assert sub.prompt_tokens == 900
    assert sub.completion_tokens == 300
    assert sub.usd_spent == 0.018


def test_to_sub_result_forwards_usage_on_failure() -> None:
    # A sub-agent can burn tokens before failing — forward them so cost
    # accounting stays honest even for failed spawns.
    mgr = _manager()
    isolation = IsolationResult(
        session_id="s",
        success=False,
        error="boom",
        prompt_tokens=120,
        completion_tokens=40,
        usd_spent=0.003,
    )
    sub = mgr._to_sub_result(_task(), isolation)
    assert not sub.success
    assert sub.prompt_tokens == 120
    assert sub.completion_tokens == 40
    assert sub.usd_spent == 0.003


def test_to_sub_result_zero_for_subscription() -> None:
    mgr = _manager()
    isolation = IsolationResult(
        session_id="s",
        success=True,
        output='{"ok": true}',
        # Subscription / CLI path → empty UsageSummary → all 0.
    )
    sub = mgr._to_sub_result(_task(), isolation)
    assert sub.success
    assert sub.prompt_tokens == 0
    assert sub.completion_tokens == 0
    assert sub.usd_spent == 0.0


def test_isolation_result_parses_usage_from_worker_payload() -> None:
    """The worker stdout JSON token keys land on the IsolationResult.

    Mirrors ``IsolatedRunner._spawn_worker``'s parse: a worker payload
    carrying usage keys must populate the IsolationResult fields. Legacy
    payloads (no keys) default to 0.
    """
    payload = {
        "task_id": "t",
        "success": True,
        "output": "x",
        "prompt_tokens": 555,
        "completion_tokens": 222,
        "usd_spent": 0.05,
    }
    result = IsolationResult(
        session_id="s",
        success=payload.get("success", False),
        output=payload.get("output", ""),
        prompt_tokens=payload.get("prompt_tokens", 0),
        completion_tokens=payload.get("completion_tokens", 0),
        usd_spent=payload.get("usd_spent", 0.0),
    )
    assert result.prompt_tokens == 555
    assert result.completion_tokens == 222
    assert result.usd_spent == 0.05

    legacy = {"task_id": "t", "success": True}
    legacy_result = IsolationResult(
        session_id="s",
        success=legacy.get("success", False),
        prompt_tokens=legacy.get("prompt_tokens", 0),
        completion_tokens=legacy.get("completion_tokens", 0),
        usd_spent=legacy.get("usd_spent", 0.0),
    )
    assert legacy_result.prompt_tokens == 0
    assert legacy_result.usd_spent == 0.0
