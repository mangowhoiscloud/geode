"""Tests for P1-revised baseline RL grounding (2026-05-25 sprint).

Covers ``docs/plans/2026-05-25-baseline-fitness-rl-grounding.md`` §11
acceptance criteria invariants:

* **Group sampling** — ``propose_group(N)`` parallel mutator call, distinct
  responses under temperature > 0
* **Variance filter** (DAPO Dynamic Sampling = EXAONE 4.5 zero-variance) —
  std < threshold → group skip
* **Advantage normalization** (GRPO whitening) — Â_i = (r_i - μ) / (σ + ε)
* **Temperature guard** — mutator_temperature < 0.1 raises RuntimeError
* **Sibling SoT in-memory** — temp file (NOT canonical SoT path)
* **Top-1 commit** — best advantage mutation → canonical SoT + apply row
* **mutations.jsonl kind extension** — applied_sibling row
* **group_id propagation** — apply row + attribution row both carry id
* **FITNESS_RESULT sentinel** — train.py stdout → apply_group_proposals fitness
* **Legacy N=1 backward compat** — propose_group(1) == [propose()]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from core.self_improving_loop.attribution import (
    AttributionRecord,
    compute_attribution,
)
from core.self_improving_loop.policies import (
    TARGET_KINDS,
    write_sibling_in_memory,
)
from core.self_improving_loop.runner import (
    _SIBLING_SOT_ENV_MAP,
    ApplyRecord,
    Mutation,
    _compute_group_advantage,
    _parse_fitness_from_subprocess_stdout,
    _run_autoresearch_subprocess,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# _compute_group_advantage — DAPO Dynamic Sampling + GRPO whitening + guard
# ---------------------------------------------------------------------------


class TestComputeGroupAdvantage:
    def test_normal_case_returns_z_score_whitening(self) -> None:
        """W-VAR-1: std > threshold → advantages = whitening, status=ok."""
        fitness = [0.30, 0.50, 0.70]
        advantages, status = _compute_group_advantage(
            fitness, threshold=0.01, mutator_temperature=1.0
        )
        assert status == "ok"
        assert advantages is not None
        # Mean=0.50, std=sqrt(((0.30-0.50)^2 + 0 + (0.70-0.50)^2)/3) ≈ 0.1633
        # Advantages roughly [-1.22, 0, 1.22]
        assert advantages[0] < 0
        assert abs(advantages[1]) < 0.1
        assert advantages[2] > 0
        assert advantages[2] > advantages[0]  # top-1 = idx 2

    def test_low_variance_filters_group(self) -> None:
        """W-VAR-2: std < threshold → status=filtered_low_variance."""
        fitness = [0.500001, 0.500000, 0.500002]  # std ≈ 1e-6
        advantages, status = _compute_group_advantage(
            fitness, threshold=0.01, mutator_temperature=1.0
        )
        assert status == "filtered_low_variance"
        assert advantages is None

    def test_group_too_small(self) -> None:
        """W-VAR-3: n < 2 → status=group_too_small (legacy guard)."""
        advantages, status = _compute_group_advantage(
            [0.5], threshold=0.01, mutator_temperature=1.0
        )
        assert status == "group_too_small"
        assert advantages is None

    def test_temperature_below_floor_raises(self) -> None:
        """W-VAR-4: mutator_temperature < 0.1 → RuntimeError (avoid silent
        infinite cycle skip). plan §6 risk 표."""
        with pytest.raises(RuntimeError, match=r"temperature >= 0\.1"):
            _compute_group_advantage([0.3, 0.5, 0.7], threshold=0.01, mutator_temperature=0.0)

    def test_temperature_exactly_floor_passes(self) -> None:
        """W-VAR-4b: temperature == 0.1 boundary OK."""
        advantages, status = _compute_group_advantage(
            [0.3, 0.7], threshold=0.01, mutator_temperature=0.1
        )
        assert status == "ok"
        assert advantages is not None


# ---------------------------------------------------------------------------
# _parse_fitness_from_subprocess_stdout — FITNESS_RESULT sentinel
# ---------------------------------------------------------------------------


class TestParseFitnessFromSubprocessStdout:
    def test_parses_sentinel_line(self) -> None:
        """W-FIT-1: FITNESS_RESULT sentinel → fitness float."""
        stdout = (
            "baseline_promoted:        false (--no-promote)\n"
            'FITNESS_RESULT: {"fitness": 0.4321, "audit_run_id": "abc123"}\n'
        )
        fitness = _parse_fitness_from_subprocess_stdout(
            stdout, audit_run_id="abc123", sibling_idx=0
        )
        assert fitness == pytest.approx(0.4321)

    def test_raises_when_sentinel_missing(self) -> None:
        """W-FIT-2: no sentinel → RuntimeError (fail-fast, no silent zero)."""
        stdout = "baseline_promoted:        false\nsome other log line\n"
        with pytest.raises(RuntimeError, match="did not emit FITNESS_RESULT"):
            _parse_fitness_from_subprocess_stdout(stdout, audit_run_id="abc123", sibling_idx=2)

    def test_audit_run_id_mismatch_warns_but_returns(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """W-FIT-3: audit_run_id mismatch logs WARNING but still returns
        fitness (env propagation drift signal)."""
        import logging

        stdout = 'FITNESS_RESULT: {"fitness": 0.5, "audit_run_id": "wrong-id"}\n'
        with caplog.at_level(logging.WARNING, logger="core.self_improving_loop.runner"):
            fitness = _parse_fitness_from_subprocess_stdout(
                stdout, audit_run_id="expected-id", sibling_idx=1
            )
        assert fitness == 0.5
        assert any("mismatch" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# write_sibling_in_memory — temp file, NOT canonical SoT
# ---------------------------------------------------------------------------


class TestWriteSiblingInMemory:
    def test_writes_to_temp_file_with_kind_suffix(self) -> None:
        """W-SIB-1: temp file path contains kind in filename, not canonical SoT."""
        sections = {"role": "You are GEODE.", "thinking_visibility": "Surface."}
        temp_path = write_sibling_in_memory("prompt", sections)
        try:
            assert temp_path.exists()
            assert "prompt-sibling.json" in temp_path.name
            assert "geode-sibling-" in temp_path.name
            # NOT canonical SoT
            assert "autoresearch/state/policies" not in str(temp_path)
            payload = json.loads(temp_path.read_text(encoding="utf-8"))
            assert payload["role"] == "You are GEODE."
        finally:
            temp_path.unlink(missing_ok=True)

    def test_rejects_unknown_kind(self) -> None:
        """W-SIB-2: invalid target_kind → ValueError."""
        with pytest.raises(ValueError, match="unknown target_kind"):
            write_sibling_in_memory("invalid_kind", {"x": "y"})

    def test_all_target_kinds_writable(self) -> None:
        """W-SIB-3: TARGET_KINDS 의 모든 kind 가 write 가능."""
        for kind in TARGET_KINDS:
            sections = {"test_section": "test value"}
            if kind in {"skill_catalog", "agent_contract"}:
                # _NESTED_KINDS — flat dotted keys
                sections = {"test_skill.description": "test value"}
            temp_path = write_sibling_in_memory(kind, sections)
            try:
                assert temp_path.exists()
            finally:
                temp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _run_autoresearch_subprocess — env propagation (W3 + P1-revised)
# ---------------------------------------------------------------------------


class TestRunAutoresearchSubprocessEnv:
    def test_sibling_sot_env_propagates(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """W-ENV-1: sibling_sot_kind + sibling_sot_path → GEODE_<KIND>_OVERRIDE
        + STRICT env."""
        captured: dict[str, str] = {}

        def fake_run(argv: list[str], *args: object, **kwargs: object) -> object:
            env = kwargs.get("env") or {}
            captured.update(
                {
                    k: v
                    for k, v in env.items()
                    if k.startswith("GEODE_") or k in {"--dry-run", "--no-promote"}
                }
            )

            class _Fake:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Fake()

        monkeypatch.setattr("core.self_improving_loop.runner.subprocess.run", fake_run)
        fake_sot = tmp_path / "sibling.json"
        fake_sot.write_text('{"x": "y"}', encoding="utf-8")
        _run_autoresearch_subprocess(
            repo_root=tmp_path,
            dry_run=True,
            audit_run_id="audit-1",
            mutation_id="mut-1",
            expected_dim={"safety": 0.1},
            sibling_sot_kind="tool_policy",
            sibling_sot_path=fake_sot,
            group_id="group-abc",
            no_promote=True,
        )
        # W3 base env
        assert captured["GEODE_SIL_AUDIT_RUN_ID"] == "audit-1"
        assert captured["GEODE_SIL_MUTATION_ID"] == "mut-1"
        # P1-revised group env
        assert captured["GEODE_SIL_GROUP_ID"] == "group-abc"
        # Sibling SoT override + STRICT
        assert captured["GEODE_TOOL_POLICY_OVERRIDE"] == str(fake_sot)
        assert captured["GEODE_TOOL_POLICY_STRICT"] == "1"

    def test_legacy_no_sibling_kind_skips_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """W-ENV-2: sibling_sot_kind 미지정 → override env 없음 (legacy preserved)."""
        captured: dict[str, str] = {}

        def fake_run(argv: list[str], *args: object, **kwargs: object) -> object:
            env = kwargs.get("env") or {}
            captured.update({k: v for k, v in env.items() if "OVERRIDE" in k or "GROUP" in k})

            class _Fake:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Fake()

        monkeypatch.setattr("core.self_improving_loop.runner.subprocess.run", fake_run)
        _run_autoresearch_subprocess(repo_root=tmp_path, dry_run=True)
        # Legacy mode — no group_id, no sibling override
        assert "GEODE_SIL_GROUP_ID" not in captured
        assert "GEODE_TOOL_POLICY_OVERRIDE" not in captured

    def test_sibling_sot_kind_unknown_raises(self, tmp_path: Path) -> None:
        """W-ENV-3: sibling_sot_kind 가 _SIBLING_SOT_ENV_MAP 에 없으면 ValueError."""
        with pytest.raises(ValueError, match="no env mapping"):
            _run_autoresearch_subprocess(
                repo_root=tmp_path,
                dry_run=True,
                sibling_sot_kind="bogus_kind",
                sibling_sot_path=tmp_path / "x.json",
            )

    def test_env_map_covers_all_target_kinds(self) -> None:
        """W-ENV-4: _SIBLING_SOT_ENV_MAP 가 TARGET_KINDS 의 모든 kind 를 cover."""
        for kind in TARGET_KINDS:
            assert kind in _SIBLING_SOT_ENV_MAP, (
                f"target_kind {kind!r} missing env mapping — sibling sampling 안 됨"
            )


# ---------------------------------------------------------------------------
# Pydantic schema — applied_sibling kind + group_id field
# ---------------------------------------------------------------------------


class TestApplyRecordSchemaExtension:
    def test_applied_sibling_kind_passes(self) -> None:
        """W-SCH-1: ApplyRecord 의 kind regex 가 applied_sibling 허용."""
        row = {
            "ts": 1716638400.0,
            "kind": "applied_sibling",
            "mutation_id": "mut-1",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "",
            "new_value": "x",
            "group_id": "group-abc",
            "group_advantage": -0.5,
        }
        record = ApplyRecord.model_validate(row)
        assert record.kind == "applied_sibling"
        assert record.group_id == "group-abc"
        assert record.group_advantage == -0.5

    def test_invalid_kind_rejected(self) -> None:
        """W-SCH-2: applied / applied_sibling 외 kind 는 거부."""
        row = {
            "ts": 1716638400.0,
            "kind": "applied_random",  # invalid
            "mutation_id": "mut-1",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "",
            "new_value": "x",
        }
        with pytest.raises(ValidationError):
            ApplyRecord.model_validate(row)

    def test_legacy_applied_row_unchanged(self) -> None:
        """W-SCH-3: legacy apply row (no group_id) 그대로 통과."""
        row = {
            "ts": 1716638400.0,
            "kind": "applied",
            "mutation_id": "mut-1",
            "target_kind": "prompt",
            "target_section": "role",
            "previous_value": "old",
            "new_value": "new",
        }
        record = ApplyRecord.model_validate(row)
        assert record.kind == "applied"
        assert record.group_id is None
        assert record.group_advantage is None


class TestAttributionRecordGroupId:
    def test_group_id_propagates_in_compute_attribution(self) -> None:
        """W-SCH-4: compute_attribution 의 group_id parameter 가 payload 로."""
        payload = compute_attribution(
            mutation_id="mut-1",
            expected_dim={"safety": 0.1},
            baseline_before=None,
            baseline_after=None,
            group_id="group-xyz",
        )
        assert payload["group_id"] == "group-xyz"
        record = AttributionRecord.model_validate(payload)
        assert record.group_id == "group-xyz"

    def test_group_id_empty_omits_column(self) -> None:
        """W-SCH-5: group_id="" → payload 에 column 미생성 (legacy graceful)."""
        payload = compute_attribution(
            mutation_id="mut-1",
            expected_dim={"safety": 0.1},
            baseline_before=None,
            baseline_after=None,
            group_id="",
        )
        assert "group_id" not in payload


# ---------------------------------------------------------------------------
# Mutation.to_audit_row — kind + group_id + group_advantage
# ---------------------------------------------------------------------------


class TestMutationToAuditRowGroup:
    def test_to_audit_row_with_group_fields(self) -> None:
        """W-ROW-1: kind=applied_sibling + group_id + group_advantage 가 row 에 포함."""
        mutation = Mutation(
            target_section="role",
            new_value="You are GEODE.",
            rationale="test",
            expected_dim={"safety": 0.1},
        )
        row = mutation.to_audit_row(
            previous_value="",
            timestamp=1716638400.0,
            audit_run_id="audit-1",
            kind="applied_sibling",
            group_id="group-abc",
            group_advantage=-0.5,
        )
        assert row["kind"] == "applied_sibling"
        assert row["group_id"] == "group-abc"
        assert row["group_advantage"] == -0.5
        assert row["audit_run_id"] == "audit-1"

    def test_to_audit_row_legacy_no_group(self) -> None:
        """W-ROW-2: group_id="" + group_advantage=None → row 에서 column 생략."""
        mutation = Mutation(
            target_section="role",
            new_value="You are GEODE.",
            rationale="test",
        )
        row = mutation.to_audit_row(
            previous_value="",
            timestamp=1716638400.0,
        )
        assert row["kind"] == "applied"
        assert "group_id" not in row
        assert "group_advantage" not in row


# ---------------------------------------------------------------------------
# Group sampling integration — propose_group + apply_group_proposals
# ---------------------------------------------------------------------------


class TestProposeGroup:
    def test_n1_returns_legacy_single_proposal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """W-PROP-1: propose_group(1) → list[propose() result]. legacy fallback."""
        from core.self_improving_loop.runner import (
            Proposal,
            SelfImprovingLoopRunner,
        )

        called = {"propose_count": 0}

        def fake_propose(self: Any) -> Proposal:
            called["propose_count"] += 1
            return Proposal(
                mutation=Mutation(
                    target_section="role",
                    new_value="test",
                    rationale="test",
                ),
                target_sections={},
                original_sections={},
                baseline_fitness=None,
            )

        monkeypatch.setattr(SelfImprovingLoopRunner, "propose", fake_propose)
        runner = SelfImprovingLoopRunner()
        result = runner.propose_group(1)
        assert len(result) == 1
        assert called["propose_count"] == 1

    def test_n2_invokes_propose_twice(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """W-PROP-2: propose_group(2) → 2 ThreadPool calls."""
        from core.self_improving_loop.runner import (
            Proposal,
            SelfImprovingLoopRunner,
        )

        called = {"count": 0}

        def fake_propose(self: Any) -> Proposal:
            called["count"] += 1
            return Proposal(
                mutation=Mutation(
                    target_section=f"role_{called['count']}",
                    new_value=f"value_{called['count']}",
                    rationale="test",
                ),
                target_sections={},
                original_sections={},
                baseline_fitness=None,
            )

        monkeypatch.setattr(SelfImprovingLoopRunner, "propose", fake_propose)
        runner = SelfImprovingLoopRunner()
        result = runner.propose_group(2)
        assert len(result) == 2
        assert called["count"] == 2


class TestApplyGroupProposals:
    def test_n1_falls_back_to_apply_proposal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """W-APP-1: len(proposals)==1 → apply_proposal() legacy path."""
        from core.self_improving_loop.runner import (
            Proposal,
            SelfImprovingLoopRunner,
        )

        called = {"apply_proposal_count": 0}

        def fake_apply_proposal(
            self: Any,
            proposal: Proposal,
            *,
            swarm_id: str = "",
            sub_agent_index: int | None = None,
        ) -> Mutation:
            called["apply_proposal_count"] += 1
            return proposal.mutation

        monkeypatch.setattr(SelfImprovingLoopRunner, "apply_proposal", fake_apply_proposal)
        runner = SelfImprovingLoopRunner()
        single = Proposal(
            mutation=Mutation(target_section="r", new_value="v", rationale="t"),
            target_sections={},
            original_sections={},
            baseline_fitness=None,
        )
        result = runner.apply_group_proposals([single])
        assert called["apply_proposal_count"] == 1
        assert result is not None

    def test_n2_requires_rerun_enabled(self) -> None:
        """W-APP-2: rerun_enabled=False + N>=2 → RuntimeError (audit 없으면
        real fitness 없어 group advantage 무의미)."""
        from core.self_improving_loop.runner import (
            Proposal,
            SelfImprovingLoopRunner,
        )

        runner = SelfImprovingLoopRunner(rerun_enabled=False)
        proposals = [
            Proposal(
                mutation=Mutation(target_section=f"r{i}", new_value=f"v{i}", rationale="t"),
                target_sections={},
                original_sections={},
                baseline_fitness=None,
            )
            for i in range(2)
        ]
        with pytest.raises(RuntimeError, match="rerun_enabled=True"):
            runner.apply_group_proposals(proposals)
