import hashlib
import json
from pathlib import Path

import pytest
from plugins.crucible.cli import main as crucible_main
from plugins.crucible.contract import ContractError, TaskUnit, task_pack_sha256
from plugins.crucible.prepare import prepare_campaign
from plugins.crucible.runtime_identity import (
    RUNTIME_OUTER_FINALIZATION_GRACE_SECONDS,
    canonical_runtime_hash,
    runtime_design_from_parts,
    runtime_regime_from_parts,
)
from plugins.crucible.supervisor import SupervisorConfig

from tests.plugins.crucible.test_supervisor import _config, _git


def _write_pack(tmp_path: Path, config: SupervisorConfig) -> Path:
    units = tuple(
        TaskUnit.from_mapping(row, field=f"plan tasks[{index}]")
        for index, row in enumerate(config.train_plan.payload["tasks"])
    )
    pack_path = tmp_path / "train.pack.json"
    pack_path.write_text(
        json.dumps(
            {
                "schema": "crucible.task-pack.v1",
                "task_pack_sha256": task_pack_sha256(units, 1),
                "trials_per_task": 1,
                "tasks": [unit.to_dict() for unit in units],
            }
        ),
        encoding="utf-8",
    )
    return pack_path


def _write_spec(
    tmp_path: Path,
    config: SupervisorConfig,
    *,
    include_pack: bool = True,
    **overrides: object,
) -> Path:
    template_path = tmp_path / "template.config.json"
    template_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
    spec = {
        "schema": "crucible.campaign-spec.v1",
        "campaign_id": "prepared-campaign",
        "template_config": str(template_path),
        "head_sha": config.initial_search_head_sha,
        "state_root": str(tmp_path / "campaigns"),
        **overrides,
    }
    if include_pack and "pack_file" not in spec:
        spec["pack_file"] = str(_write_pack(tmp_path, config))
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return spec_path


def _power_audit(
    tmp_path: Path,
    *,
    minimum_power: float,
    target_improvement_pp: float,
) -> dict[str, object]:
    basis = tmp_path / "pilot-evidence.json"
    basis.write_text('{"schema":"fixture-pilot.v1"}\n', encoding="utf-8")
    return {
        "schema": "crucible.family-power-spec.v1",
        "simulations": 1_000,
        "seed": 20260713,
        "minimum_power": minimum_power,
        "scenarios": [
            {
                "name": "prepared-design",
                "source": "fixture paired pilot evidence",
                "basis_file": str(basis),
                "basis_sha256": hashlib.sha256(basis.read_bytes()).hexdigest(),
                "baseline_pass_probability": 0.1,
                "target_improvement_pp": target_improvement_pp,
                "regression_probability_on_baseline_success": 0.0,
            }
        ],
    }


def _runtime_audit(
    tmp_path: Path,
    config: SupervisorConfig,
    *,
    experiment_wall_seconds: float | None = None,
) -> dict[str, object]:
    plan = config.train_plan.payload
    assay = plan["assay_config"]
    tasks = tuple(
        TaskUnit.from_mapping(row, field=f"plan tasks[{index}]")
        for index, row in enumerate(plan["tasks"])
    )
    bindings = {
        "evaluator_sha256": plan["evaluator_sha256"],
        "harness_sha256": plan["harness_sha256"],
        "assay_config_sha256": hashlib.sha256(
            json.dumps(
                assay,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        "agent_route": plan["agent_route"],
        "user_route": plan["user_route"],
    }
    design = runtime_design_from_parts(
        tasks=tasks,
        trials_per_task=1,
        task_pack_sha256=task_pack_sha256(tasks, 1),
    )
    regime = runtime_regime_from_parts(
        stage="train",
        bindings=bindings,
        design=design,
        experiment_wall_seconds=(
            float(plan["budget"]["max_wall_seconds"])
            if experiment_wall_seconds is None
            else experiment_wall_seconds
        ),
    )
    pilot_payload = {
        "schema": "crucible.runtime-pilot.v2",
        "accounting_method": "sum-finalized-simulation-elapsed.v1",
        **bindings,
        "source_contract_id": "d" * 64,
        "source_runtime_receipt_id": "e" * 64,
        "runtime_regime": regime,
        "runtime_regime_id": canonical_runtime_hash(regime),
        "cycle_observation": {
            "status": "complete",
            "observed_active_wall_seconds": 80.0,
            "observed_evaluator_wall_seconds": 80.0,
            "active_wall_seconds": 80.0,
            "completed_evaluator_wall_seconds": 80.0,
            "complete_sample_count": 8,
            "right_censored_sample_count": 0,
            "infrastructure_failure_sample_count": 0,
            "fresh_measurement": True,
            "cache_reused_arm_count": 0,
        },
        "blocks": [
            {
                "samples": [
                    {"outcome": "complete", "wall_seconds": 10.0},
                    {"outcome": "complete", "wall_seconds": 10.0},
                ]
            }
            for _index in range(4)
        ],
    }
    pilot = tmp_path / "runtime-pilot.json"
    pilot.write_text(json.dumps(pilot_payload), encoding="utf-8")
    return {
        "schema": "crucible.runtime-budget-spec.v2",
        "pilot_file": str(pilot),
        "pilot_sha256": hashlib.sha256(pilot.read_bytes()).hexdigest(),
        "source": "fixture completed campaign runtime pilot",
        "simulations": 1_000,
        "seed": 20260713,
        "admission_quantile": 0.99,
        "headroom_ratio": 0.0,
        "experiment_overhead_seconds": 0.0,
        "campaign_overhead_seconds": 10.0,
        "cleanup_grace_seconds": RUNTIME_OUTER_FINALIZATION_GRACE_SECONDS,
        "minimum_usable_blocks": 4,
    }


def _runtime_ceiling() -> dict[str, object]:
    return {
        "schema": "crucible.runtime-budget-spec.v2",
        "mode": "contract_ceiling",
        "source": "fixture frozen assay timeout ceiling",
        "experiment_overhead_seconds": 0.0,
        "campaign_overhead_seconds": 10.0,
        "cleanup_grace_seconds": RUNTIME_OUTER_FINALIZATION_GRACE_SECONDS,
    }


def _operational_deadline() -> dict[str, object]:
    return {
        "schema": "crucible.runtime-budget-spec.v2",
        "mode": "operational_deadline",
        "source": "fixture preregistered experiment wall",
        "campaign_overhead_seconds": 10.0,
        "cleanup_grace_seconds": RUNTIME_OUTER_FINALIZATION_GRACE_SECONDS,
        "risk_acceptance": "nonzero_clean_timeout",
    }


def test_prepare_emits_a_config_the_loop_loader_accepts(tmp_path: Path) -> None:
    config, baseline = _config(tmp_path)
    report = prepare_campaign(_write_spec(tmp_path, config))
    prepared = SupervisorConfig.load(Path(report["config_path"]))
    assert prepared.campaign_id == "prepared-campaign"
    assert prepared.initial_search_head_sha == baseline
    # Hashes are recomputed, never inherited: they must equal the live values.
    assert report["evaluator_sha256"] == config.train_plan.payload["evaluator_sha256"]
    assert report["harness_sha256"] == config.train_plan.payload["harness_sha256"]
    assert report["task_count"] == 4


def test_prepare_binds_a_passing_family_power_report(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    report = prepare_campaign(
        _write_spec(
            tmp_path,
            config,
            power_audit=_power_audit(
                tmp_path,
                minimum_power=0.5,
                target_improvement_pp=0.8,
            ),
        )
    )

    power = report["power_audit"]
    assert power["passes"] is True
    power_path = Path(power["path"])
    saved_power = json.loads(power_path.read_text(encoding="utf-8"))
    prepared = SupervisorConfig.load(Path(report["config_path"]))
    assert power["power_audit_id"] == saved_power["power_audit_id"]
    assert prepared.prepared_by is not None
    assert prepared.prepared_by["power_audit_id"] == saved_power["power_audit_id"]


def test_prepare_rejects_low_power_before_emitting_config(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    with pytest.raises(ContractError, match="did not meet minimum_power"):
        prepare_campaign(
            _write_spec(
                tmp_path,
                config,
                power_audit=_power_audit(
                    tmp_path,
                    minimum_power=0.99,
                    target_improvement_pp=0.1,
                ),
            )
        )

    campaign_root = tmp_path / "campaigns" / "prepared-campaign"
    assert not (campaign_root / "config.json").exists()
    rejected_report = json.loads(
        (campaign_root / "prepare" / "power.json").read_text(encoding="utf-8")
    )
    assert rejected_report["passes"] is False


def test_prepare_binds_a_passing_runtime_report(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    budget = {**config.train_plan.payload["budget"], "max_wall_seconds": 86.0}
    limits = {**config.limits.to_dict(), "max_wall_seconds": 96.0}
    report = prepare_campaign(
        _write_spec(
            tmp_path,
            config,
            budget=budget,
            limits=limits,
            runtime_audit=_runtime_audit(tmp_path, config, experiment_wall_seconds=86.0),
        )
    )

    runtime = report["runtime_audit"]
    assert runtime["passes"] is True
    assert runtime["required_experiment_wall_seconds"] == 86
    assert runtime["required_campaign_wall_seconds"] == 96
    saved_runtime = json.loads(Path(runtime["path"]).read_text(encoding="utf-8"))
    prepared = SupervisorConfig.load(Path(report["config_path"]))
    assert runtime["runtime_audit_id"] == saved_runtime["runtime_audit_id"]
    assert prepared.prepared_by is not None
    assert prepared.prepared_by["runtime_audit_id"] == saved_runtime["runtime_audit_id"]


def test_prepare_binds_contract_ceiling_before_a_pilot_exists(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    budget = {**config.train_plan.payload["budget"], "max_wall_seconds": 86.0}
    limits = {**config.limits.to_dict(), "max_wall_seconds": 96.0}
    assay = {**config.train_plan.payload["assay_config"], "timeout": 10.0}
    report = prepare_campaign(
        _write_spec(
            tmp_path,
            config,
            assay_config=assay,
            budget=budget,
            limits=limits,
            runtime_audit=_runtime_ceiling(),
        )
    )

    runtime = report["runtime_audit"]
    assert runtime["passes"] is True
    assert runtime["required_experiment_wall_seconds"] == 86
    assert runtime["required_campaign_wall_seconds"] == 96
    saved = json.loads(Path(runtime["path"]).read_text(encoding="utf-8"))
    assert saved["method"] == "bounded-process-termination-envelope.v2"


def test_prepare_binds_unbounded_rows_to_an_explicit_operational_deadline(
    tmp_path: Path,
) -> None:
    config, _baseline = _config(tmp_path)
    budget = {**config.train_plan.payload["budget"], "max_wall_seconds": 80.0}
    limits = {**config.limits.to_dict(), "max_wall_seconds": 90.0}
    assay = {**config.train_plan.payload["assay_config"], "timeout": None}
    report = prepare_campaign(
        _write_spec(
            tmp_path,
            config,
            assay_config=assay,
            budget=budget,
            limits=limits,
            runtime_audit=_operational_deadline(),
        )
    )

    runtime = report["runtime_audit"]
    assert runtime["passes"] is True
    assert runtime["required_experiment_wall_seconds"] == 80.0
    assert runtime["required_campaign_wall_seconds"] == 90
    saved = json.loads(Path(runtime["path"]).read_text(encoding="utf-8"))
    assert saved["method"] == "operator-selected-deadline.v1"
    assert saved["operational_deadline"]["statistical_confidence_bound"] is None
    assert saved["operational_deadline"]["risk_acceptance"] == "nonzero_clean_timeout"
    prepared = SupervisorConfig.load(Path(report["config_path"]))
    assert prepared.train_plan.payload["assay_config"]["timeout"] is None


def test_prepare_rejects_short_runtime_budget_before_emitting_config(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    with pytest.raises(ContractError, match="runtime budget audit rejected configured wall"):
        prepare_campaign(
            _write_spec(
                tmp_path,
                config,
                runtime_audit=_runtime_audit(tmp_path, config),
            )
        )

    campaign_root = tmp_path / "campaigns" / "prepared-campaign"
    assert not (campaign_root / "config.json").exists()
    rejected_report = json.loads(
        (campaign_root / "prepare" / "runtime.json").read_text(encoding="utf-8")
    )
    assert rejected_report["passes"] is False
    assert rejected_report["admission"]["configured_experiment_wall_seconds"] == 60.0
    assert rejected_report["admission"]["required_experiment_wall_seconds"] == 86


def test_prepare_rejects_feedback_outside_the_pack(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    spec_path = _write_spec(
        tmp_path,
        config,
        initial_feedback={
            "schema": "crucible.failure-feedback.v3",
            "failure_codes": ["termination"],
            "failed_task_ids": ["task-outside-the-pack"],
        },
    )
    with pytest.raises(ContractError, match="outside the pack"):
        prepare_campaign(spec_path)


def test_prepare_refuses_a_reused_campaign_search_ref(tmp_path: Path) -> None:
    config, baseline = _config(tmp_path)
    _git(
        config.repository,
        "update-ref",
        "refs/crucible/search/prepared-campaign",
        baseline,
    )
    with pytest.raises(ContractError, match="search ref already exists"):
        prepare_campaign(_write_spec(tmp_path, config))


def test_prepare_fails_loud_on_a_dirty_harness(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    (config.harness_root / "scratch.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ContractError, match="harness checkout must be clean"):
        prepare_campaign(_write_spec(tmp_path, config))


def test_prepare_removes_output_when_round_trip_validation_fails(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    # An entrypoint outside evaluator_paths passes assembly but must die in
    # the round-trip SupervisorConfig.load — and leave no config behind.
    spec_path = _write_spec(tmp_path, config, evaluator_entrypoint="surface.txt")
    with pytest.raises((ContractError, Exception)):
        prepare_campaign(spec_path)
    assert not (tmp_path / "campaigns" / "prepared-campaign" / "config.json").exists()


def test_prepare_reports_window_verdict_from_history(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    history = tmp_path / "history" / "old-campaign" / "state"
    history.mkdir(parents=True)
    (history / "summary.json").write_text(
        json.dumps({"usage": {"tokens": 1_000_000}}), encoding="utf-8"
    )
    limits = {**config.to_dict()["limits"], "max_tokens": 5_000_000}
    report = prepare_campaign(
        _write_spec(tmp_path, config, limits=limits),
        history_root=tmp_path / "history",
        remaining_tokens=1_000_000,
    )
    window = report["window"]
    assert window["fit"] == "history_fit"
    assert window["history_worst_tokens"] == 1_000_000
    # 판정을 요청하지 않으면 window는 None으로 남는다 (별도 캠페인 id로 재실행)


def test_prepare_cli_returns_defer_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _baseline = _config(tmp_path)
    code = crucible_main(
        [
            "prepare",
            str(_write_spec(tmp_path, config)),
            "--remaining-tokens",
            "1",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 3
    assert report["window"]["fit"] == "defer"


def test_prepare_rejects_invalid_window_input_without_leaving_config(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    with pytest.raises(ContractError, match="remaining_tokens must be non-negative"):
        prepare_campaign(_write_spec(tmp_path, config), remaining_tokens=-1)

    assert not (tmp_path / "campaigns" / "prepared-campaign" / "config.json").exists()


def test_prepare_binds_search_objective_into_the_supervisor_config(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    objective = "Preserve completed work before requesting the next required action."
    report = prepare_campaign(_write_spec(tmp_path, config, search={"objective": objective}))

    prepared = SupervisorConfig.load(Path(report["config_path"]))
    assert prepared.producer_objective == objective
    assert prepared.to_dict()["search"] == {"objective": objective}


def test_prepare_curates_pack_when_spec_carries_curation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _baseline = _config(tmp_path)
    reference_pack = _write_pack(tmp_path, config)

    def fake_curate(**kwargs: object) -> dict:
        pack_output = kwargs["pack_output"]
        assert isinstance(pack_output, Path)
        pack_output.write_text(reference_pack.read_text(encoding="utf-8"), encoding="utf-8")
        return {"pack_sha256": "unused"}

    monkeypatch.setattr("plugins.crucible.prepare.curate_tau2_pack", fake_curate)
    curation = {
        "tasks_file": str(tmp_path / "tasks.json"),
        "split_file": str(tmp_path / "split.json"),
        "split_name": "base",
        "domain": "telecom",
        "purpose": "train",
        "salt": "salt-1",
        "fault_tokens": 2,
        "take": 4,
        "maximum_per_intent": 2,
        "maximum_per_persona": 2,
        "trials_per_task": 1,
    }
    report = prepare_campaign(_write_spec(tmp_path, config, include_pack=False, curation=curation))
    assert report["pack_file"].endswith("prepare/pack.json")
    assert report["task_count"] == 4


def test_prepare_rejects_pack_file_and_curation_together(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    spec_path = _write_spec(tmp_path, config, curation={"tasks_file": "x"})
    with pytest.raises(ContractError, match="cannot carry both"):
        prepare_campaign(spec_path)


def test_prepare_stamps_provenance_outside_the_identity_hash(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    spec_path = _write_spec(tmp_path, config)
    report = prepare_campaign(spec_path)

    saved = json.loads(Path(report["config_path"]).read_text(encoding="utf-8"))
    provenance = saved["prepared_by"]
    assert provenance["schema"] == "crucible.prepare-provenance.v1"
    assert provenance["entry"] == "plugins.crucible.prepare"
    assert provenance["spec_sha256"] == hashlib.sha256(spec_path.read_bytes()).hexdigest()
    assert report["spec_sha256"] == provenance["spec_sha256"]

    prepared = SupervisorConfig.load(Path(report["config_path"]))
    assert prepared.prepared_by == provenance
    assert prepared.to_dict()["prepared_by"] == provenance
    # Identity stays provenance-free: the same experiment prepared from two
    # different specs must keep one config_id.
    assert "prepared_by" not in prepared.payload()

    round_trip_path = tmp_path / "round-trip.config.json"
    round_trip_path.write_text(json.dumps(prepared.to_dict()), encoding="utf-8")
    round_tripped = SupervisorConfig.load(round_trip_path)
    assert round_tripped.prepared_by == provenance
    assert round_tripped.config_id == prepared.config_id

    mutated = {
        **prepared.to_dict(),
        "prepared_by": {
            "schema": "crucible.prepare-provenance.v1",
            "entry": "hand",
            "spec_sha256": "0" * 64,
        },
    }
    mutated_path = tmp_path / "mutated.config.json"
    mutated_path.write_text(json.dumps(mutated), encoding="utf-8")
    assert SupervisorConfig.load(mutated_path).config_id == prepared.config_id


def test_prepare_replaces_inherited_provenance(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    template_path = tmp_path / "template.config.json"
    stale = {**config.to_dict(), "prepared_by": {"schema": "stale", "entry": "hand"}}
    template_path.write_text(json.dumps(stale), encoding="utf-8")
    spec = {
        "schema": "crucible.campaign-spec.v1",
        "campaign_id": "prepared-campaign",
        "template_config": str(template_path),
        "head_sha": config.initial_search_head_sha,
        "pack_file": str(_write_pack(tmp_path, config)),
        "state_root": str(tmp_path / "campaigns"),
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    report = prepare_campaign(spec_path)
    saved = json.loads(Path(report["config_path"]).read_text(encoding="utf-8"))
    assert saved["prepared_by"]["entry"] == "plugins.crucible.prepare"
    assert saved["prepared_by"]["schema"] == "crucible.prepare-provenance.v1"
