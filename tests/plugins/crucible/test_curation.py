import hashlib
import json
from pathlib import Path

import pytest
from plugins.crucible.artifacts import write_exclusive_json
from plugins.crucible.contract import ContractError, task_pack_sha256
from plugins.crucible.curation import curate_tau2_pack
from plugins.crucible.verifiers.tau2 import tau2_task_unit


def _task(index: int, *, intent: str, persona: str, faults: int = 3) -> dict[str, object]:
    fault_names = "|".join(f"fault_{index}_{offset}" for offset in range(faults))
    return {
        "id": f"[{intent}]{fault_names}[PERSONA:{persona}]",
        "evaluation_criteria": {"actions": [{"name": f"action_{index}"}]},
        "user_tools": [],
    }


def _write_sources(tmp_path: Path, tasks: list[dict[str, object]]) -> tuple[Path, Path]:
    tasks_path = tmp_path / "tasks.json"
    split_path = tmp_path / "split.json"
    tasks_path.write_text(json.dumps(tasks), encoding="utf-8")
    split_path.write_text(json.dumps({"base": [task["id"] for task in tasks]}), encoding="utf-8")
    return tasks_path, split_path


def _curate(
    tmp_path: Path,
    tasks_path: Path,
    split_path: Path,
    *,
    exclude_packs: tuple[Path, ...] = (),
    take: int = 4,
) -> dict[str, object]:
    return curate_tau2_pack(
        tasks_path=tasks_path,
        split_path=split_path,
        split_name="base",
        domain="telecom",
        purpose="test",
        salt="sealed-salt-v1",
        fault_tokens=3,
        take=take,
        maximum_per_intent=2,
        maximum_per_persona=2,
        trials_per_task=1,
        exclude_packs=exclude_packs,
        selection_output=tmp_path / "selection.json",
        pack_output=tmp_path / "pack.json",
    )


def test_curator_returns_only_opaque_counts_and_hashes(tmp_path: Path) -> None:
    tasks = [
        _task(1, intent="mobile", persona="Easy"),
        _task(2, intent="mobile", persona="Hard"),
        _task(3, intent="service", persona="Easy"),
        _task(4, intent="service", persona="Hard"),
        _task(5, intent="mms", persona="None"),
    ]
    tasks_path, split_path = _write_sources(tmp_path, tasks)

    summary = _curate(tmp_path, tasks_path, split_path)
    selection = json.loads((tmp_path / "selection.json").read_text(encoding="utf-8"))
    pack = json.loads((tmp_path / "pack.json").read_text(encoding="utf-8"))

    assert summary["schema"] == "crucible.tau2-curation-summary.v1"
    assert summary["task_count"] == summary["family_count"] == 4
    assert "selected" not in summary
    assert not any(str(task["id"]) in json.dumps(summary) for task in tasks)
    assert len(selection["selected"]) == 4
    assert [row["task_id"] for row in pack["tasks"]] == [
        row["task_id"] for row in selection["selected"]
    ]
    assert summary["task_pack_sha256"] == pack["task_pack_sha256"]
    assert (
        summary["task_pack_artifact_sha256"]
        == hashlib.sha256((tmp_path / "pack.json").read_bytes()).hexdigest()
    )


def test_curator_excludes_task_family_and_content_from_frozen_packs(tmp_path: Path) -> None:
    tasks = [
        _task(1, intent="mobile", persona="Easy"),
        _task(2, intent="mobile", persona="Hard"),
        _task(3, intent="service", persona="Easy"),
        _task(4, intent="service", persona="Hard"),
        _task(5, intent="mms", persona="None"),
    ]
    tasks_path, split_path = _write_sources(tmp_path, tasks)
    excluded_unit = tau2_task_unit(tasks[0])
    excluded_path = tmp_path / "excluded.json"
    write_exclusive_json(
        excluded_path,
        {
            "schema": "crucible.task-pack.v1",
            "task_pack_sha256": task_pack_sha256((excluded_unit,)),
            "trials_per_task": 1,
            "tasks": [excluded_unit.to_dict()],
        },
    )

    summary = _curate(
        tmp_path,
        tasks_path,
        split_path,
        exclude_packs=(excluded_path,),
        take=3,
    )
    pack = json.loads((tmp_path / "pack.json").read_text(encoding="utf-8"))

    assert summary["eligible_tasks"] == 4
    assert excluded_unit.task_id not in {row["task_id"] for row in pack["tasks"]}
    assert excluded_unit.family_id not in {row["family_id"] for row in pack["tasks"]}
    assert excluded_unit.content_sha256 not in {row["content_sha256"] for row in pack["tasks"]}


def test_curator_fails_closed_when_caps_cannot_fill_the_pack(tmp_path: Path) -> None:
    tasks = [
        _task(1, intent="mobile", persona="Easy"),
        _task(2, intent="mobile", persona="Easy"),
        _task(3, intent="mobile", persona="Easy"),
    ]
    tasks_path, split_path = _write_sources(tmp_path, tasks)

    with pytest.raises(ContractError, match="fewer than requested"):
        _curate(tmp_path, tasks_path, split_path, take=3)


def test_curator_refuses_to_replace_immutable_outputs(tmp_path: Path) -> None:
    tasks = [
        _task(1, intent="mobile", persona="Easy"),
        _task(2, intent="mobile", persona="Hard"),
        _task(3, intent="service", persona="Easy"),
        _task(4, intent="service", persona="Hard"),
    ]
    tasks_path, split_path = _write_sources(tmp_path, tasks)
    _curate(tmp_path, tasks_path, split_path)

    with pytest.raises(ContractError, match="refusing to overwrite"):
        _curate(tmp_path, tasks_path, split_path)


def test_curator_errors_do_not_disclose_selected_task_ids(tmp_path: Path) -> None:
    secret_id = "sealed-row-that-must-stay-opaque"
    tasks = [
        {
            "id": secret_id,
            "evaluation_criteria": {"actions": [{"name": "action"}]},
            "user_tools": [],
        }
    ]
    tasks_path, split_path = _write_sources(tmp_path, tasks)

    with pytest.raises(ContractError, match="unsupported selection shape") as captured:
        _curate(tmp_path, tasks_path, split_path, take=1)

    assert secret_id not in str(captured.value)


def test_priority_task_ids_front_load_the_frozen_execution_order(tmp_path: Path) -> None:
    tasks = [
        _task(0, intent="ADD_LINE", persona="EASY"),
        _task(1, intent="MOVE_PLAN", persona="HARD"),
        _task(2, intent="CANCEL", persona="EASY"),
        _task(3, intent="UPGRADE", persona="HARD"),
        _task(4, intent="SUSPEND", persona="MEDIUM"),
        _task(5, intent="RESUME", persona="MEDIUM"),
    ]
    tasks_path, split_path = _write_sources(tmp_path, tasks)
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    curate_tau2_pack(
        tasks_path=tasks_path,
        split_path=split_path,
        split_name="base",
        domain="telecom",
        purpose="train",
        salt="sealed-salt-v1",
        fault_tokens=3,
        take=4,
        maximum_per_intent=2,
        maximum_per_persona=2,
        trials_per_task=1,
        exclude_packs=(),
        selection_output=plain_dir / "selection.json",
        pack_output=plain_dir / "pack.json",
    )
    plain_pack = json.loads((plain_dir / "pack.json").read_text(encoding="utf-8"))
    plain_order = [task["task_id"] for task in plain_pack["tasks"]]
    # The prior champion's failure sits at the tail of the upstream order —
    # exactly the r23 shape where quota death truncated the improvement zone.
    failure_id = plain_order[-1]

    priority_dir = tmp_path / "priority"
    priority_dir.mkdir()
    curate_tau2_pack(
        tasks_path=tasks_path,
        split_path=split_path,
        split_name="base",
        domain="telecom",
        purpose="train",
        salt="sealed-salt-v1",
        fault_tokens=3,
        take=4,
        maximum_per_intent=2,
        maximum_per_persona=2,
        trials_per_task=1,
        exclude_packs=(),
        selection_output=priority_dir / "selection.json",
        pack_output=priority_dir / "pack.json",
        priority_task_ids=(failure_id, "task-never-selected"),
    )
    priority_pack = json.loads((priority_dir / "pack.json").read_text(encoding="utf-8"))
    priority_order = [task["task_id"] for task in priority_pack["tasks"]]
    assert priority_order[0] == failure_id
    assert sorted(priority_order) == sorted(plain_order)  # selection unchanged, order moved
    selection = json.loads((priority_dir / "selection.json").read_text(encoding="utf-8"))
    assert selection["rule"]["execution_order"] == "priority_task_ids_first+upstream_tasks_file"
    assert selection["rule"]["front_loaded_task_ids"] == [failure_id]
    # The reorder changes the frozen pack hash: ordering is preregistered identity.
    assert priority_pack["task_pack_sha256"] != plain_pack["task_pack_sha256"]
