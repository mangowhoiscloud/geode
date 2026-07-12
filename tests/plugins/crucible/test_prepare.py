import hashlib
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
