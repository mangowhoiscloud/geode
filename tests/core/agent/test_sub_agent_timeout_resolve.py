"""Pin :func:`core.agent.sub_agent._resolve_timeout_s` contract.

PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — wall-clock cap
honors ``GEODE_SUBAGENT_TIMEOUT_S`` env (clamped ``[10, 3600]``).
"""

from __future__ import annotations

import pytest
from core.agent.sub_agent import _resolve_timeout_s


def test_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_SUBAGENT_TIMEOUT_S", raising=False)
    assert _resolve_timeout_s(600.0) == pytest.approx(600.0)


def test_env_override_within_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_SUBAGENT_TIMEOUT_S", "900")
    assert _resolve_timeout_s(600.0) == pytest.approx(900.0)


def test_env_override_clamped_to_lower(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_SUBAGENT_TIMEOUT_S", "3")
    assert _resolve_timeout_s(600.0) == pytest.approx(10.0)


def test_env_override_clamped_to_upper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_SUBAGENT_TIMEOUT_S", "100000")
    assert _resolve_timeout_s(600.0) == pytest.approx(3600.0)


def test_non_numeric_env_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_SUBAGENT_TIMEOUT_S", "abc")
    assert _resolve_timeout_s(600.0) == pytest.approx(600.0)


def test_empty_env_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_SUBAGENT_TIMEOUT_S", "   ")
    assert _resolve_timeout_s(600.0) == pytest.approx(600.0)


def test_sub_agent_manager_default_is_600_seconds() -> None:
    """SubAgentManager.timeout_s default lifted from 120s (pre-S6) to
    600s. PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25)."""
    import inspect

    from core.agent.sub_agent import SubAgentManager

    sig = inspect.signature(SubAgentManager.__init__)
    assert sig.parameters["timeout_s"].default == 600.0


def test_worker_request_default_is_600_seconds() -> None:
    """WorkerRequest.timeout_s default lifted from 120s (pre-S6) to 600s."""
    import inspect

    from core.agent.worker import WorkerRequest

    sig = inspect.signature(WorkerRequest.__init__)
    assert sig.parameters["timeout_s"].default == 600.0
