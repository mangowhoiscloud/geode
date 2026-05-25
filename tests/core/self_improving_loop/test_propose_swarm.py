"""A.7 (2026-05-25) — propose_swarm + apply_swarm_proposals wiring invariants (PR-14).

Scope: SelfImprovingLoopRunner.propose_swarm / apply_swarm_proposals 의
- propose_swarm signature (m, n) + ValueError
- list[list[Proposal]] shape — M sub-agents × N siblings
- apply_swarm_proposals 의 swarm_id mint + sub_agent_index forwarding
- ApplyRecord 의 swarm_id / sub_agent_index emit (mutations.jsonl)
- swarm_id / sub_agent_index 는 to_audit_row 의 non-empty 시만 emit (legacy 무영향)
- run_once 분기 — sub_agent_count >= 2 → swarm mode
- empty swarm → ValueError
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from core.self_improving_loop.runner import (
    Mutation,
    Proposal,
    append_audit_log,
)

# ---------------------------------------------------------------------------
# 1. to_audit_row + append_audit_log — swarm_id / sub_agent_index emit
# ---------------------------------------------------------------------------


def _make_mutation(target_section: str = "role", new_value: str = "y") -> Mutation:
    return Mutation(
        target_section=target_section,
        new_value=new_value,
        rationale="test",
        mutation_id="m_x",
    )


def test_to_audit_row_emits_swarm_id_when_non_empty() -> None:
    mutation = _make_mutation()
    row = mutation.to_audit_row(previous_value="x", swarm_id="sw_abc")
    assert row["swarm_id"] == "sw_abc"


def test_to_audit_row_skips_swarm_id_when_empty() -> None:
    """Legacy non-swarm mode → row 에 swarm_id column 미생성."""
    mutation = _make_mutation()
    row = mutation.to_audit_row(previous_value="x")
    assert "swarm_id" not in row


def test_to_audit_row_emits_sub_agent_index_when_non_none() -> None:
    mutation = _make_mutation()
    # sub_agent_index=0 도 valid 한 첫 sub-agent → row 에 emit
    row = mutation.to_audit_row(previous_value="x", sub_agent_index=0)
    assert row["sub_agent_index"] == 0


def test_to_audit_row_emits_sub_agent_index_nonzero() -> None:
    mutation = _make_mutation()
    row = mutation.to_audit_row(previous_value="x", sub_agent_index=2)
    assert row["sub_agent_index"] == 2


def test_to_audit_row_skips_sub_agent_index_when_none() -> None:
    mutation = _make_mutation()
    row = mutation.to_audit_row(previous_value="x", sub_agent_index=None)
    assert "sub_agent_index" not in row


def test_append_audit_log_writes_swarm_fields(tmp_path: Path) -> None:
    """End-to-end — append_audit_log writes Pydantic-validated row with
    swarm_id + sub_agent_index when forwarded."""
    import json as _json

    log_path = tmp_path / "mutations.jsonl"
    mutation = _make_mutation()
    append_audit_log(
        mutation,
        previous_value="x",
        log_path=log_path,
        swarm_id="sw_42",
        sub_agent_index=1,
    )
    with log_path.open() as fh:
        row = _json.loads(fh.readline())
    assert row["swarm_id"] == "sw_42"
    assert row["sub_agent_index"] == 1


def test_append_audit_log_omits_swarm_fields_for_legacy(tmp_path: Path) -> None:
    """Backward compat — legacy callers (no swarm args) get no swarm columns."""
    import json as _json

    log_path = tmp_path / "mutations.jsonl"
    mutation = _make_mutation()
    append_audit_log(mutation, previous_value="x", log_path=log_path)
    with log_path.open() as fh:
        row = _json.loads(fh.readline())
    assert "swarm_id" not in row
    assert "sub_agent_index" not in row


# ---------------------------------------------------------------------------
# 2. propose_swarm signature + shape
# ---------------------------------------------------------------------------


def _make_runner_with_mock_propose(propose_groups: list[list[Proposal]]):
    """Build a real runner but stub propose_group to return canned data
    so we don't need an LLM. Use mock.patch on the instance method."""
    from core.self_improving_loop.runner import SelfImprovingLoopRunner

    runner = SelfImprovingLoopRunner(rerun_enabled=False)
    iterator = iter(propose_groups)

    def fake_propose_group(n: int) -> list[Proposal]:
        return next(iterator)

    runner.propose_group = fake_propose_group  # type: ignore[method-assign]
    return runner


def _fake_proposal() -> Proposal:
    return Proposal(
        mutation=_make_mutation(),
        target_sections={"role": "x"},
        original_sections={"role": "x"},
    )


def test_propose_swarm_zero_m_raises() -> None:
    from core.self_improving_loop.runner import SelfImprovingLoopRunner

    runner = SelfImprovingLoopRunner(rerun_enabled=False)
    with pytest.raises(ValueError, match=r"m must be >= 1"):
        runner.propose_swarm(0, 2)


def test_propose_swarm_zero_n_raises() -> None:
    from core.self_improving_loop.runner import SelfImprovingLoopRunner

    runner = SelfImprovingLoopRunner(rerun_enabled=False)
    with pytest.raises(ValueError, match=r"n must be >= 1"):
        runner.propose_swarm(2, 0)


def test_propose_swarm_returns_m_groups_of_n() -> None:
    groups = [[_fake_proposal(), _fake_proposal()] for _ in range(3)]
    runner = _make_runner_with_mock_propose(groups)
    result = runner.propose_swarm(3, 2)
    assert len(result) == 3  # M sub-agents
    assert all(len(g) == 2 for g in result)  # each group has N siblings


def test_propose_swarm_m_equals_1_returns_single_group() -> None:
    groups = [[_fake_proposal()]]
    runner = _make_runner_with_mock_propose(groups)
    result = runner.propose_swarm(1, 1)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# 3. apply_swarm_proposals — swarm_id + sub_agent_index forwarding
# ---------------------------------------------------------------------------


def test_apply_swarm_proposals_empty_raises() -> None:
    from core.self_improving_loop.runner import SelfImprovingLoopRunner

    runner = SelfImprovingLoopRunner(rerun_enabled=False)
    with pytest.raises(ValueError, match="empty swarm"):
        runner.apply_swarm_proposals([])


def test_apply_swarm_proposals_returns_last_committed() -> None:
    """MVP last-wins — last sub-agent's mutation is returned."""
    from core.self_improving_loop.runner import SelfImprovingLoopRunner

    runner = SelfImprovingLoopRunner(rerun_enabled=False)
    mutation_a = _make_mutation(new_value="a")
    mutation_b = _make_mutation(new_value="b")

    captured: list[tuple[str, int]] = []

    def fake_apply_group(group, *, swarm_id, sub_agent_index):
        captured.append((swarm_id, sub_agent_index))
        return mutation_a if sub_agent_index == 0 else mutation_b

    runner.apply_group_proposals = fake_apply_group  # type: ignore[method-assign]
    result = runner.apply_swarm_proposals([[_fake_proposal()], [_fake_proposal()]])
    assert result is mutation_b  # last committed
    # swarm_id shared across sub-agents
    assert captured[0][0] == captured[1][0]
    assert captured[0][0] != ""
    # sub_agent_index distinct 0, 1
    assert {c[1] for c in captured} == {0, 1}


def test_apply_swarm_proposals_all_skipped_returns_none() -> None:
    """All sub-agents return None (variance filter) → swarm returns None."""
    from core.self_improving_loop.runner import SelfImprovingLoopRunner

    runner = SelfImprovingLoopRunner(rerun_enabled=False)
    runner.apply_group_proposals = lambda group, **kw: None  # type: ignore[method-assign]
    result = runner.apply_swarm_proposals(
        [[_fake_proposal()], [_fake_proposal()], [_fake_proposal()]]
    )
    assert result is None


def test_apply_swarm_proposals_partial_skip() -> None:
    """Some sub-agents skip, some commit → return last valid commit."""
    from core.self_improving_loop.runner import SelfImprovingLoopRunner

    runner = SelfImprovingLoopRunner(rerun_enabled=False)
    mutation_b = _make_mutation(new_value="b")

    def fake_apply(group, *, swarm_id, sub_agent_index):
        if sub_agent_index == 0:
            return None
        if sub_agent_index == 1:
            return mutation_b
        return None  # idx 2 skips again

    runner.apply_group_proposals = fake_apply  # type: ignore[method-assign]
    result = runner.apply_swarm_proposals(
        [[_fake_proposal()], [_fake_proposal()], [_fake_proposal()]]
    )
    assert result is mutation_b


# ---------------------------------------------------------------------------
# 4. run_once dispatch — sub_agent_count >= 2 → swarm mode
# ---------------------------------------------------------------------------


def test_run_once_dispatches_to_swarm_when_sub_agent_count_ge_2(
    tmp_path: Path,
) -> None:
    from core.self_improving_loop.runner import SelfImprovingLoopRunner

    runner = SelfImprovingLoopRunner(rerun_enabled=False)
    runner.audit_log_path = tmp_path / "mutations.jsonl"

    called = {"propose_swarm": False, "apply_swarm_proposals": False}

    def fake_propose_swarm(m: int, n: int) -> list[list[Proposal]]:
        called["propose_swarm"] = True
        assert m == 3
        assert n == 1
        return [[_fake_proposal()]]

    def fake_apply_swarm(swarm_proposals) -> Mutation:
        called["apply_swarm_proposals"] = True
        return _make_mutation()

    runner.propose_swarm = fake_propose_swarm  # type: ignore[method-assign]
    runner.apply_swarm_proposals = fake_apply_swarm  # type: ignore[method-assign]

    fake_cfg = type("Cfg", (), {})()
    fake_cfg.autoresearch = type(
        "AR",
        (),
        {"group_size": 1, "sub_agent_count": 3, "swarm_aggregation": "mean"},
    )()
    with patch(
        "core.config.self_improving_loop.load_self_improving_loop_config",
        return_value=fake_cfg,
    ):
        runner.run_once()
    assert called["propose_swarm"] is True
    assert called["apply_swarm_proposals"] is True


def test_run_once_skips_swarm_when_sub_agent_count_is_1() -> None:
    """sub_agent_count=1 (default) → legacy group_size 분기."""
    from core.self_improving_loop.runner import SelfImprovingLoopRunner

    runner = SelfImprovingLoopRunner(rerun_enabled=False)

    swarm_called = {"v": False}

    def fake_swarm(*a, **kw):
        swarm_called["v"] = True
        return _make_mutation()

    runner.propose_swarm = fake_swarm  # type: ignore[method-assign]
    runner.apply_swarm_proposals = fake_swarm  # type: ignore[method-assign]
    # group_size=1 legacy path — propose() / apply_proposal() stubbed
    runner.propose = lambda: _fake_proposal()  # type: ignore[method-assign]
    runner.apply_proposal = lambda p: _make_mutation()  # type: ignore[method-assign]

    fake_cfg = type("Cfg", (), {})()
    fake_cfg.autoresearch = type(
        "AR",
        (),
        {"group_size": 1, "sub_agent_count": 1, "swarm_aggregation": "mean"},
    )()
    with patch(
        "core.config.self_improving_loop.load_self_improving_loop_config",
        return_value=fake_cfg,
    ):
        runner.run_once()
    assert swarm_called["v"] is False  # swarm 미진입
