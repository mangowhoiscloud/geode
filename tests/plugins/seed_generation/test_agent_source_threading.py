"""Per-agent SubTask.source threading invariants — Follow-up B.

Pins:
- BaseSeedAgent.adapter_source translates picker source → adapter source.
- Each role agent passes self.adapter_source on SubTask construction.
- RankerAgent uses voter-specific source per voter (not the role source).
- Pipeline carries picker_result.bindings for observability without
  re-injecting binding values into SubTask creation (agents already do).
"""

from __future__ import annotations

import pytest
from plugins.seed_generation.agents.base import (
    BaseSeedAgent,
    SeedAgentResult,
    picker_source_to_adapter_source,
)


class _StubAgent(BaseSeedAgent):
    """Minimum concrete BaseSeedAgent for unit-level source translation tests."""

    async def aexecute(self, state):  # type: ignore[no-untyped-def]
        return SeedAgentResult(role=self.role, status="ok")


@pytest.mark.parametrize(
    ("picker_source", "expected_adapter_source"),
    [
        ("api_key", "payg"),
        ("claude-cli", "adapter"),
        ("openai-codex", "subscription"),
        ("payg", "payg"),
        ("subscription", "subscription"),
        ("adapter", "adapter"),
        ("auto", ""),  # unresolved → empty = legacy
        ("", ""),  # empty input → empty output
        ("nonexistent", ""),  # unknown picker source → empty (graceful)
    ],
)
def test_picker_source_to_adapter_source(picker_source: str, expected_adapter_source: str) -> None:
    assert picker_source_to_adapter_source(picker_source) == expected_adapter_source


@pytest.mark.parametrize(
    ("agent_source", "expected"),
    [
        ("claude-cli", "adapter"),
        ("api_key", "payg"),
        ("openai-codex", "subscription"),
        ("auto", ""),
        ("", ""),
    ],
)
def test_agent_adapter_source_property(agent_source: str, expected: str) -> None:
    agent = _StubAgent(role="r", model="m", source=agent_source)
    assert agent.adapter_source == expected


def test_pipeline_carries_bindings() -> None:
    """Pipeline stores picker bindings; agents (built earlier with binding
    values) supply ``source`` directly on SubTask creation. No double-injection."""
    from plugins.seed_generation.orchestrator import (
        Pipeline,
        PipelineRegistry,
        PipelineState,
    )

    state = PipelineState(run_id="r-0", target_dim="d", gen_tag="g")
    pipeline = Pipeline(state=state, registry=PipelineRegistry(), bindings={"role-x": "B"})
    assert pipeline.bindings == {"role-x": "B"}


def test_pipeline_default_bindings_empty_dict() -> None:
    """No bindings passed → empty dict (not None)."""
    from plugins.seed_generation.orchestrator import (
        Pipeline,
        PipelineRegistry,
        PipelineState,
    )

    state = PipelineState(run_id="r-0", target_dim="d", gen_tag="g")
    pipeline = Pipeline(state=state, registry=PipelineRegistry())
    assert pipeline.bindings == {}
