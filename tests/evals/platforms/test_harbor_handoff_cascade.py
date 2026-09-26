"""Arm C stays opt-in: an explicit engine, a frozen tau, the Jev key and Choice only."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from evals.platforms import harbor_handoff
from evals.platforms.harbor_handoff import GeodeHandoffHarborAgent, _run_handoff
from tests.evals.platforms import test_harbor_handoff as _handoff_tests

# Shared fixtures from the matched profile tests; pytest registers module attributes.
host_agent = _handoff_tests.host_agent
container_trial = _handoff_tests.container_trial
_write_task = _handoff_tests._write_task

_FIXTURE = Path(__file__).parents[3] / "evals/benchmarks/fixtures/decision-handoff-inbox.json"


def _inbox_task(path: Path) -> tuple[dict[str, Any], str]:
    from evals.benchmarks.decision_handoff_runtime import inbox_request

    fixture = json.loads(_FIXTURE.read_text())
    case = fixture["admission"]
    case.update(profile="inbox", request=inbox_request(case["items"]))
    value, digest = _write_task(path, case=case, orders=fixture["orders"])
    return value, digest


def test_host_profile_records_frozen_tau_and_passes_it_to_the_container(
    host_agent: SimpleNamespace,
) -> None:
    value, digest = _inbox_task(host_agent.case)
    kwargs = host_agent.kwargs | {
        "case_sha256": digest,
        "verification_engine": "cascade",
        "cascade_tau": "0.85",
        "verify_mode": "llm_judge",
        "typesafe_key_file": str(host_agent.secret),
    }
    agent = GeodeHandoffHarborAgent(**kwargs)
    agent.exec_as_agent = AsyncMock()
    asyncio.run(agent.run(value["case"]["request"], SimpleNamespace(), SimpleNamespace()))
    contract = json.loads((agent.logs_dir / "runtime-contract.json").read_text())
    assert contract["verification_engine"] == "cascade"
    assert contract["cascade_tau"] == "0.85"
    assert "verification_primitive" not in contract
    command = agent.exec_as_agent.await_args.kwargs["command"]
    assert "--verification-engine cascade --cascade-tau 0.85" in command
    for override in (
        {"cascade_tau": None},
        {"cascade_tau": "1.0"},
        {"cascade_tau": "0.86"},
        {"typesafe_key_file": None},
        {"verification_primitive": "noul"},
        {"arm": "a"},
        {"verify_mode": "rule_based"},
    ):
        with pytest.raises(ValueError):
            GeodeHandoffHarborAgent(**(kwargs | override))


@pytest.mark.parametrize("engine", [None, "llm", "jev"])
def test_non_cascade_profiles_cannot_carry_a_tau(host_agent: SimpleNamespace, engine: str) -> None:
    _, digest = _inbox_task(host_agent.case)
    kwargs = host_agent.kwargs | {"case_sha256": digest, "cascade_tau": "0.85"}
    if engine is not None:
        kwargs |= {"verification_engine": engine, "verify_mode": "llm_judge"}
    if engine == "jev":
        kwargs["typesafe_key_file"] = str(host_agent.secret)
    with pytest.raises(ValueError):
        GeodeHandoffHarborAgent(**kwargs)
    agent = GeodeHandoffHarborAgent(**{k: v for k, v in kwargs.items() if k != "cascade_tau"})
    assert agent.cascade_tau is None


def test_container_cli_transfers_tau_and_scoped_jev_key(
    container_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial = container_trial
    _, digest = _inbox_task(Path(trial.args.task))
    trial.secret.write_text("synthetic-test-key\n")
    trial.secret.chmod(0o600)

    async def run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert not trial.secret.exists()
        assert kwargs["api_key"].get_secret_value() == "synthetic-test-key"
        return trial.result

    trial.runner.side_effect = run
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harbor_handoff",
            "--arm",
            "a0",
            "--task",
            trial.args.task,
            "--task-sha256",
            digest,
            "--revision",
            trial.args.revision,
            "--timeout",
            "180",
            "--verification-engine",
            "cascade",
            "--cascade-tau",
            "0.85",
        ],
    )
    assert harbor_handoff.main() == 0
    kwargs = trial.runner.await_args.kwargs
    assert kwargs["verification_engine"] == "cascade"
    assert kwargs["cascade_tau"] == "0.85"
    assert kwargs["verification_primitive"] == "choice"
    metadata = json.loads((trial.path / "runtime-result.json").read_text())["metadata"]
    assert metadata["cascade_tau"] == "0.85"
    assert metadata["verify_mode"] == "llm_judge"
    assert trial.settings.cost_limit_usd == 0
    for path in trial.path.glob("*.json"):
        assert "synthetic-test-key" not in path.read_text()


@pytest.mark.parametrize("gate", ["missing_tau", "tau_without_cascade", "noul"])
def test_container_arm_c_gates_precede_execution(
    container_trial: SimpleNamespace, gate: str
) -> None:
    trial = container_trial
    trial.args.verification_engine = "llm" if gate == "tau_without_cascade" else "cascade"
    trial.args.cascade_tau = None if gate == "missing_tau" else "0.85"
    if gate == "noul":
        trial.args.verification_primitive = "noul"
    with pytest.raises(ValueError):
        asyncio.run(_run_handoff(trial.args))
    trial.runner.assert_not_awaited()
    assert not (trial.path / "runtime.pid").exists()
