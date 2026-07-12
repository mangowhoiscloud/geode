import json
from pathlib import Path

import pytest
from plugins.crucible.contract import ContractError, TaskUnit, task_pack_sha256
from plugins.crucible.prepare import prepare_campaign
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


def _write_spec(tmp_path: Path, config: SupervisorConfig, **overrides: object) -> Path:
    template_path = tmp_path / "template.config.json"
    template_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
    spec = {
        "schema": "crucible.campaign-spec.v1",
        "campaign_id": "prepared-campaign",
        "template_config": str(template_path),
        "head_sha": config.initial_search_head_sha,
        "pack_file": str(_write_pack(tmp_path, config)),
        "state_root": str(tmp_path / "campaigns"),
        **overrides,
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return spec_path


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
