"""P4 (2026-05-25) — Swarm-level baseline scaffolding tests.

Plan: ``docs/plans/2026-05-25-p4-parl-swarm-scaffolding.md``.

Covers:
- SwarmConfig (sub_agent_count + swarm_aggregation)
- aggregate_swarm_fitness (mean / median / max)
- decompose_sub_agent_contribution
- ApplyRecord.swarm_id + sub_agent_index field
- backward compat (sub_agent_count=1 legacy)
"""

from __future__ import annotations

import pytest
from core.self_improving_loop.runner import ApplyRecord
from core.self_improving_loop.swarm_scaffolding import (
    aggregate_swarm_fitness,
    decompose_sub_agent_contribution,
)


class TestAggregateSwarmFitness:
    def test_mean(self) -> None:
        """D-AGG-1: method='mean' → arithmetic mean."""
        assert aggregate_swarm_fitness([0.3, 0.5, 0.7], method="mean") == pytest.approx(0.5)

    def test_median(self) -> None:
        """D-AGG-2: method='median' → middle value (odd N)."""
        assert aggregate_swarm_fitness([0.1, 0.5, 0.9], method="median") == 0.5

    def test_max(self) -> None:
        """D-AGG-3: method='max' → best-of-M."""
        assert aggregate_swarm_fitness([0.1, 0.5, 0.9], method="max") == 0.9

    def test_empty_returns_zero(self) -> None:
        """D-AGG-4: empty list → 0.0 (graceful, swarm 폐기 시그널)."""
        assert aggregate_swarm_fitness([], method="mean") == 0.0

    def test_unknown_method_raises(self) -> None:
        """D-AGG-5: invalid method → ValueError."""
        with pytest.raises(ValueError, match="unknown swarm_aggregation method"):
            aggregate_swarm_fitness([0.5], method="bogus")  # type: ignore[arg-type]


class TestDecomposeSubAgentContribution:
    def test_mean_method_deviation(self) -> None:
        """D-DEC-1: method='mean' → fitness_i - swarm_mean."""
        contributions = decompose_sub_agent_contribution(
            swarm_fitness=0.5,
            sub_agent_fitness_values=[0.3, 0.5, 0.7],
            method="mean",
        )
        assert contributions == pytest.approx([-0.2, 0.0, 0.2])

    def test_max_method_one_hot(self) -> None:
        """D-DEC-2: method='max' → argmax index = 1.0, rest = 0.0."""
        contributions = decompose_sub_agent_contribution(
            swarm_fitness=0.9,
            sub_agent_fitness_values=[0.3, 0.5, 0.9],
            method="max",
        )
        assert contributions == [0.0, 0.0, 1.0]

    def test_empty_returns_empty(self) -> None:
        """D-DEC-3: empty sub-agent list → empty contributions."""
        assert decompose_sub_agent_contribution(0.0, [], method="mean") == []


class TestSwarmConfigKnob:
    def test_sub_agent_count_default_one(self) -> None:
        """D-CFG-1: AutoresearchConfig.sub_agent_count default = 1 (legacy)."""
        from core.config.self_improving_loop import AutoresearchConfig

        cfg = AutoresearchConfig()
        assert cfg.sub_agent_count == 1

    def test_swarm_aggregation_default_mean(self) -> None:
        """D-CFG-2: swarm_aggregation default = 'mean'."""
        from core.config.self_improving_loop import AutoresearchConfig

        cfg = AutoresearchConfig()
        assert cfg.swarm_aggregation == "mean"

    def test_sub_agent_count_cap(self) -> None:
        """D-CFG-3: sub_agent_count max = 5 (Field(le=5) cost cap)."""
        from core.config.self_improving_loop import AutoresearchConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AutoresearchConfig(sub_agent_count=6)


class TestApplyRecordSwarmField:
    def test_swarm_id_optional(self) -> None:
        """D-SCH-1: ApplyRecord.swarm_id + sub_agent_index field 허용."""
        row = {
            "ts": 1716638400.0,
            "kind": "applied",
            "mutation_id": "m1",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "",
            "new_value": "x",
            "swarm_id": "swarm-abc",
            "sub_agent_index": 2,
        }
        record = ApplyRecord.model_validate(row)
        assert record.swarm_id == "swarm-abc"
        assert record.sub_agent_index == 2

    def test_swarm_id_legacy_none(self) -> None:
        """D-SCH-2: legacy row (swarm_id 없음) 도 통과."""
        row = {
            "ts": 1716638400.0,
            "kind": "applied",
            "mutation_id": "m1",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "",
            "new_value": "x",
        }
        record = ApplyRecord.model_validate(row)
        assert record.swarm_id is None
        assert record.sub_agent_index is None
