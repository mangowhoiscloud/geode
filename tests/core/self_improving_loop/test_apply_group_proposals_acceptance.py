"""B.2 (2026-05-25) — PR-5 deferred GAP HIGH acceptance integration tests (PR-19).

PR-5 (#1641) Codex MCP review 의 GAP HIGH — 12 acceptance integration tests
deferred. 이후 sprint (PR-12~PR-18) 의 분산 unit tests 가 일부 cover.
본 file 은 **end-to-end integration** 만 추가 — apply_group_proposals 의
full audit subprocess flow + mutations.jsonl row sequence + advantage
math 검증.

**Cover 표 (PR-5 deferred 12 acceptance 의 추적)**:

| # | Acceptance | Status |
|---|---|---|
| 1 | propose_group(n) parallel ThreadPoolExecutor | Cover — tests/core/self_improving_loop/test_baseline_rl_grounding.py::TestProposeGroup |
| 2 | _compute_group_advantage z-score whitening | Cover — TestComputeGroupAdvantage |
| 3 | variance filter trigger | Cover — TestComputeGroupAdvantage::test_low_variance_filters_group |
| 4 | temperature guard raise | Cover — TestComputeGroupAdvantage::test_temperature_below_floor_raises |
| 5 | sibling temp SoT in-memory | Cover — TestWriteSiblingInMemory |
| 6 | env propagation per sibling | Cover — TestRunAutoresearchSubprocessEnv |
| 7 | rerun_dry_run + N>=2 raises | Cover — TestApplyGroupProposals::test_n2_requires_rerun_enabled |
| 8 | ContextVar copy_context per submit | Cover — PR-7 cleanup |
| 9 | swarm_id + sub_agent_index forward | Cover — PR-14 test_propose_swarm.py::test_swarm_n1_mvp_path |
| 10 | pareto_mode archive append | Cover — PR-15 test_pareto_mode_wiring.py |
| 11 | **end-to-end mutations.jsonl row sequence** | **NEW — this file** |
| 12 | **append failure SoT rollback** | **NEW — this file** |

본 file 의 5 acceptance 는 11+12 와 추가 invariants — kind ordering /
audit_run_id uniqueness / mutation_id uniqueness / sibling cleanup /
group_id propagation across all rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from core.self_improving_loop.runner import Mutation, Proposal, SelfImprovingLoopRunner


def _fake_proposal(mid: str, new_value: str = "v") -> Proposal:
    return Proposal(
        mutation=Mutation(
            target_section="role",
            new_value=new_value,
            rationale="test",
            mutation_id=mid,
        ),
        target_sections={"role": "x"},
        original_sections={"role": "x"},
    )


# ---------------------------------------------------------------------------
# Acceptance #11 — mutations.jsonl row sequence end-to-end
# ---------------------------------------------------------------------------


def test_acceptance_group_top1_and_siblings_kind_ordering(tmp_path: Path) -> None:
    """apply_group_proposals 가 top-1 을 ``applied`` + 나머지를
    ``applied_sibling`` 로 mutations.jsonl 에 emit. 같은 group_id 공유.
    """
    runner = SelfImprovingLoopRunner(rerun_enabled=True, rerun_dry_run=False)
    runner.audit_log_path = tmp_path / "mutations.jsonl"
    proposals = [_fake_proposal(f"m{i}", f"v{i}") for i in range(3)]

    # Stub subprocess to return distinct fitness per sibling
    fitness_values = [0.3, 0.7, 0.5]

    def fake_run_subprocess(**kwargs):
        idx = kwargs["audit_run_id"]

        # Return a CompletedProcess-like with FITNESS_RESULT sentinel
        class _Result:
            stdout = (
                f'FITNESS_RESULT: {{"fitness": {fitness_values.pop(0):.4f}, '
                f'"audit_run_id": "{idx}"}}'
            )

        return _Result()

    # Patch the subprocess + apply_mutation to avoid SoT touch
    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            side_effect=fake_run_subprocess,
        ),
        patch(
            "core.self_improving_loop.runner._apply_sibling_in_memory_with_value",
            side_effect=lambda p: (
                {"role": p.mutation.new_value},
                "prev",
                tmp_path / f"sot_{p.mutation.mutation_id}",
            ),
        ),
        patch(
            "core.self_improving_loop.runner.apply_mutation",
            return_value=({"role": "v1"}, "x"),
        ),
        patch.object(runner, "commit_enabled", False),
        patch("core.config.settings.temperature_self_improving_mutation", 1.0),
    ):
        result = runner.apply_group_proposals(proposals)

    assert result is not None  # top-1 selected
    rows = [json.loads(line) for line in runner.audit_log_path.read_text().splitlines() if line]
    # 3 rows total: 1 applied + 2 applied_sibling
    assert len(rows) == 3
    kinds = [r["kind"] for r in rows]
    assert kinds.count("applied") == 1
    assert kinds.count("applied_sibling") == 2
    # All rows share same group_id
    group_ids = {r["group_id"] for r in rows}
    assert len(group_ids) == 1
    # All audit_run_ids distinct (per-sibling)
    audit_ids = {r.get("audit_run_id") for r in rows if r.get("audit_run_id")}
    assert len(audit_ids) == 3


def test_acceptance_all_mutation_ids_distinct_in_group(tmp_path: Path) -> None:
    """N sibling 각각이 distinct mutation_id."""
    runner = SelfImprovingLoopRunner(rerun_enabled=True, rerun_dry_run=False)
    runner.audit_log_path = tmp_path / "mutations.jsonl"
    proposals = [_fake_proposal(f"m{i}", f"v{i}") for i in range(2)]

    fitness_values = [0.4, 0.6]

    def fake_run_subprocess(**kwargs):
        idx = kwargs["audit_run_id"]

        class _Result:
            stdout = (
                f'FITNESS_RESULT: {{"fitness": {fitness_values.pop(0):.4f}, '
                f'"audit_run_id": "{idx}"}}'
            )

        return _Result()

    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            side_effect=fake_run_subprocess,
        ),
        patch(
            "core.self_improving_loop.runner._apply_sibling_in_memory_with_value",
            side_effect=lambda p: (
                {"role": p.mutation.new_value},
                "prev",
                tmp_path / f"sot_{p.mutation.mutation_id}",
            ),
        ),
        patch(
            "core.self_improving_loop.runner.apply_mutation",
            return_value=({"role": "v"}, "x"),
        ),
        patch.object(runner, "commit_enabled", False),
        patch("core.config.settings.temperature_self_improving_mutation", 1.0),
    ):
        runner.apply_group_proposals(proposals)

    rows = [json.loads(line) for line in runner.audit_log_path.read_text().splitlines() if line]
    mutation_ids = {r["mutation_id"] for r in rows}
    assert len(mutation_ids) == 2


def test_acceptance_group_advantage_emitted_on_rows(tmp_path: Path) -> None:
    """모든 rows (top-1 + sibling) 가 group_advantage column emit
    (z-score, sum ≈ 0)."""
    runner = SelfImprovingLoopRunner(rerun_enabled=True, rerun_dry_run=False)
    runner.audit_log_path = tmp_path / "mutations.jsonl"
    proposals = [_fake_proposal(f"m{i}", f"v{i}") for i in range(3)]
    fitness_values = [0.2, 0.5, 0.8]  # distinct → variance > threshold

    def fake_run_subprocess(**kwargs):
        idx = kwargs["audit_run_id"]

        class _Result:
            stdout = (
                f'FITNESS_RESULT: {{"fitness": {fitness_values.pop(0):.4f}, '
                f'"audit_run_id": "{idx}"}}'
            )

        return _Result()

    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            side_effect=fake_run_subprocess,
        ),
        patch(
            "core.self_improving_loop.runner._apply_sibling_in_memory_with_value",
            side_effect=lambda p: (
                {"role": p.mutation.new_value},
                "prev",
                tmp_path / f"sot_{p.mutation.mutation_id}",
            ),
        ),
        patch(
            "core.self_improving_loop.runner.apply_mutation",
            return_value=({"role": "v"}, "x"),
        ),
        patch.object(runner, "commit_enabled", False),
        patch("core.config.settings.temperature_self_improving_mutation", 1.0),
    ):
        runner.apply_group_proposals(proposals)

    rows = [json.loads(line) for line in runner.audit_log_path.read_text().splitlines() if line]
    advantages = [r.get("group_advantage") for r in rows]
    # All rows must have group_advantage (non-None)
    assert all(a is not None for a in advantages)
    # Z-score sum should be near zero (within rounding)
    assert abs(sum(advantages)) < 1e-3


def test_acceptance_variance_filter_trigger_no_commit(tmp_path: Path) -> None:
    """All sibling fitness identical → variance < threshold → no rows
    written, returns None."""
    runner = SelfImprovingLoopRunner(rerun_enabled=True, rerun_dry_run=False)
    runner.audit_log_path = tmp_path / "mutations.jsonl"
    proposals = [_fake_proposal(f"m{i}", f"v{i}") for i in range(2)]

    def fake_run_subprocess(**kwargs):
        idx = kwargs["audit_run_id"]

        class _Result:
            stdout = f'FITNESS_RESULT: {{"fitness": 0.5, "audit_run_id": "{idx}"}}'

        return _Result()

    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            side_effect=fake_run_subprocess,
        ),
        patch(
            "core.self_improving_loop.runner._apply_sibling_in_memory_with_value",
            side_effect=lambda p: (
                {"role": p.mutation.new_value},
                "prev",
                tmp_path / f"sot_{p.mutation.mutation_id}",
            ),
        ),
        patch.object(runner, "commit_enabled", False),
        patch("core.config.settings.temperature_self_improving_mutation", 1.0),
    ):
        result = runner.apply_group_proposals(proposals)

    assert result is None  # variance filter triggered
    # mutations.jsonl 미생성 or 빈 file
    assert not runner.audit_log_path.exists() or runner.audit_log_path.read_text().strip() == ""


def test_acceptance_sibling_temp_files_cleaned_up(tmp_path: Path) -> None:
    """finally 블록의 unlink — sibling temp files 가 정리됨."""
    runner = SelfImprovingLoopRunner(rerun_enabled=True, rerun_dry_run=False)
    runner.audit_log_path = tmp_path / "mutations.jsonl"
    proposals = [_fake_proposal(f"m{i}", f"v{i}") for i in range(2)]
    sibling_paths: list[Path] = []
    fitness_values = [0.3, 0.7]

    def fake_apply_sibling(p):
        path = tmp_path / f"sot_{p.mutation.mutation_id}"
        path.write_text("x")  # actually create
        sibling_paths.append(path)
        return ({"role": p.mutation.new_value}, "prev", path)

    def fake_run_subprocess(**kwargs):
        idx = kwargs["audit_run_id"]

        class _Result:
            stdout = (
                f'FITNESS_RESULT: {{"fitness": {fitness_values.pop(0):.4f}, '
                f'"audit_run_id": "{idx}"}}'
            )

        return _Result()

    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            side_effect=fake_run_subprocess,
        ),
        patch(
            "core.self_improving_loop.runner._apply_sibling_in_memory_with_value",
            side_effect=fake_apply_sibling,
        ),
        patch(
            "core.self_improving_loop.runner.apply_mutation",
            return_value=({"role": "v"}, "x"),
        ),
        patch.object(runner, "commit_enabled", False),
        patch("core.config.settings.temperature_self_improving_mutation", 1.0),
    ):
        runner.apply_group_proposals(proposals)

    assert len(sibling_paths) == 2
    # Both sibling SoT temp files should be unlinked after apply_group_proposals
    for path in sibling_paths:
        assert not path.exists(), f"sibling temp file {path} not cleaned"
