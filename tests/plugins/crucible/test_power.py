import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from plugins.crucible.cli import main as crucible_main
from plugins.crucible.contract import ContractError, PromotionRule, TaskUnit, task_pack_sha256
from plugins.crucible.power import audit_family_power


def _tasks(count: int = 9) -> tuple[TaskUnit, ...]:
    return tuple(
        TaskUnit(f"task-{index}", f"family-{index}", f"{index:064x}")
        for index in range(1, count + 1)
    )


def _promotion() -> PromotionRule:
    return PromotionRule.from_mapping(
        {
            "method": "paired_bootstrap.v2",
            "primary_metric": "reward",
            "materiality_pp": 0.25,
            "minimum_candidate_mean": 0.5,
            "minimum_tasks": 9,
            "minimum_families": 9,
            "confidence_level": 0.885,
            "bootstrap_samples": 1_000,
        }
    )


def _specification(tmp_path: Path, *, minimum_power: float = 0.7) -> dict[str, object]:
    basis = tmp_path / "pilot-evidence.json"
    basis.write_text('{"schema":"fixture-pilot.v1"}\n', encoding="utf-8")
    return {
        "schema": "crucible.family-power-spec.v1",
        "simulations": 1_000,
        "seed": 20260713,
        "minimum_power": minimum_power,
        "scenarios": [
            {
                "name": "large-general-improvement",
                "source": "frozen paired pilot evidence",
                "basis_file": str(basis),
                "basis_sha256": hashlib.sha256(basis.read_bytes()).hexdigest(),
                "baseline_pass_probability": 0.58,
                "target_improvement_pp": 0.4,
                "regression_probability_on_baseline_success": 0.0,
            }
        ],
    }


def test_power_audit_is_deterministic_family_aware_and_opaque(tmp_path: Path) -> None:
    tasks = _tasks()
    first = audit_family_power(
        tasks=tasks,
        trials_per_task=2,
        task_pack_sha256=task_pack_sha256(tasks, 2),
        promotion=_promotion(),
        specification=_specification(tmp_path),
        basis_root=tmp_path,
    )
    second = audit_family_power(
        tasks=tasks,
        trials_per_task=2,
        task_pack_sha256=task_pack_sha256(tasks, 2),
        promotion=_promotion(),
        specification=_specification(tmp_path),
        basis_root=tmp_path,
    )

    assert first == second
    assert first["passes"] is True
    assert first["design"] == {
        "task_count": 9,
        "family_count": 9,
        "family_task_counts": [1] * 9,
        "trials_per_task": 2,
    }
    assert first["scenarios"][0]["results"]["keep_probability"] >= 0.7
    encoded = str(first)
    assert "task-1" not in encoded
    assert "family-1" not in encoded


def test_power_audit_reports_low_power_without_changing_the_rule(tmp_path: Path) -> None:
    tasks = _tasks()
    specification = deepcopy(_specification(tmp_path, minimum_power=0.8))
    scenarios = specification["scenarios"]
    assert isinstance(scenarios, list)
    scenarios[0]["target_improvement_pp"] = 0.1

    report = audit_family_power(
        tasks=tasks,
        trials_per_task=2,
        task_pack_sha256=task_pack_sha256(tasks, 2),
        promotion=_promotion(),
        specification=specification,
        basis_root=tmp_path,
    )

    assert report["passes"] is False
    assert report["promotion"] == _promotion().to_dict()
    assert report["scenarios"][0]["passes"] is False


def test_power_audit_rejects_an_impossible_scenario(tmp_path: Path) -> None:
    tasks = _tasks()
    specification = deepcopy(_specification(tmp_path))
    scenarios = specification["scenarios"]
    assert isinstance(scenarios, list)
    scenarios[0]["regression_probability_on_baseline_success"] = 0.5

    with pytest.raises(ContractError, match="impossible gain probability"):
        audit_family_power(
            tasks=tasks,
            trials_per_task=2,
            task_pack_sha256=task_pack_sha256(tasks, 2),
            promotion=_promotion(),
            specification=specification,
            basis_root=tmp_path,
        )


def test_power_audit_rejects_a_phantom_basis_digest(tmp_path: Path) -> None:
    tasks = _tasks()
    specification = deepcopy(_specification(tmp_path))
    scenarios = specification["scenarios"]
    assert isinstance(scenarios, list)
    scenarios[0]["basis_sha256"] = "b" * 64

    with pytest.raises(ContractError, match="does not match basis_sha256"):
        audit_family_power(
            tasks=tasks,
            trials_per_task=2,
            task_pack_sha256=task_pack_sha256(tasks, 2),
            promotion=_promotion(),
            specification=specification,
            basis_root=tmp_path,
        )


def test_power_audit_cli_emits_an_opaque_hidden_pack_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tasks = _tasks(6)
    pack = tmp_path / "hidden.pack.json"
    pack.write_text(
        json.dumps(
            {
                "schema": "crucible.task-pack.v1",
                "task_pack_sha256": task_pack_sha256(tasks, 2),
                "trials_per_task": 2,
                "tasks": [task.to_dict() for task in tasks],
            }
        ),
        encoding="utf-8",
    )
    promotion_payload = _promotion().to_dict()
    promotion_payload["minimum_tasks"] = 6
    promotion_payload["minimum_families"] = 6
    promotion = tmp_path / "promotion.json"
    promotion.write_text(json.dumps(promotion_payload), encoding="utf-8")
    specification = _specification(tmp_path, minimum_power=0.7)
    spec = tmp_path / "power-spec.json"
    spec.write_text(json.dumps(specification), encoding="utf-8")
    output = tmp_path / "hidden-power.json"

    code = crucible_main(
        [
            "power-audit",
            str(pack),
            "--promotion",
            str(promotion),
            "--spec",
            str(spec),
            "--output",
            str(output),
        ]
    )

    printed = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert printed == saved
    assert saved["design"]["family_count"] == 6
    assert "task-1" not in str(saved)
