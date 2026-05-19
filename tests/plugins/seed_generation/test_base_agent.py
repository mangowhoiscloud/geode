"""Unit tests for ``plugins.seed_generation.agents.base``."""

from __future__ import annotations

import pytest
from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult


def test_seed_agent_result_default_status_ok() -> None:
    r = SeedAgentResult(role="generator")
    assert r.status == "ok"
    assert r.success is True
    assert r.output == {}


def test_seed_agent_result_error_not_success() -> None:
    r = SeedAgentResult(role="critic", status="error", error_message="boom")
    assert r.success is False
    assert r.error_message == "boom"


def test_base_seed_agent_requires_execute_override() -> None:
    # Cannot instantiate abstract base directly.
    with pytest.raises(TypeError):
        BaseSeedAgent(role="x", model="m")  # type: ignore[abstract]


class _DummyAgent(BaseSeedAgent):
    def execute(self, state: object) -> SeedAgentResult:
        return SeedAgentResult(role=self.role, output={"candidates": [{"id": "x"}]})


def test_subclass_execute_round_trip() -> None:
    agent = _DummyAgent(role="generator", model="claude-sonnet-4-6")
    result = agent.execute(state=None)
    assert result.role == "generator"
    assert result.output["candidates"][0]["id"] == "x"


def test_repr_includes_role_model_source() -> None:
    agent = _DummyAgent(role="critic", model="gpt-5.5", source="openai-codex")
    s = repr(agent)
    assert "critic" in s
    assert "gpt-5.5" in s
    assert "openai-codex" in s
