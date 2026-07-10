"""Normalize pinned tau2 results without importing the external harness."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from plugins.crucible.contract import ContractError, ExperimentContract
from plugins.crucible.evidence import EVIDENCE_SCHEMA, EvidenceEnvelope, ResourceUsage

_SNAPSHOT_SCHEMA = "crucible_tau2_trajectory_snapshot.v2"


@dataclass(frozen=True)
class Tau2AssayAdapter:
    """Pinned tau2 schema/profile; all tau2-specific cases live here."""

    schema: str = "crucible.tau2-assay.v1"
    required_evaluator_paths: tuple[str, ...] = (
        "plugins/benchmark_harness/tau2_geode_agent.py",
        "plugins/crucible",
    )
    termination_classes: tuple[tuple[str, Literal["semantic", "infra"]], ...] = (
        ("agent_error", "semantic"),
        ("agent_stop", "semantic"),
        ("context_window_exceeded", "semantic"),
        ("infrastructure_error", "infra"),
        ("max_steps", "semantic"),
        ("timeout", "semantic"),
        ("too_many_errors", "semantic"),
        ("unexpected_error", "infra"),
        ("user_error", "infra"),
        ("user_stop", "semantic"),
    )
    user_runtime_owners: tuple[tuple[str, Literal["candidate", "evaluator"]], ...] = (
        ("dummy_user", "evaluator"),
        ("geode_user", "candidate"),
        ("user_simulator", "evaluator"),
    )

    def classify_termination(self, reason: str) -> Literal["semantic", "infra"]:
        try:
            return dict(self.termination_classes)[reason]
        except KeyError as exc:
            raise ContractError(f"unsupported tau2 termination reason: {reason!r}") from exc

    def user_runtime_owner(self, implementation: str) -> Literal["candidate", "evaluator"]:
        try:
            return dict(self.user_runtime_owners)[implementation]
        except KeyError as exc:
            raise ContractError(
                f"unclassified tau2 user implementation: {implementation!r}"
            ) from exc

    def user_route(
        self,
        *,
        implementation: str,
        native_model: str,
        candidate_route: str,
    ) -> str:
        if self.user_runtime_owner(implementation) == "candidate":
            return candidate_route
        return f"tau2-{implementation}-{native_model}"

    def agent_route_from_args(self, args: Any) -> str:
        return f"{args.provider}-{args.source}-{args.model}-{args.effort}"

    def user_route_from_args(self, args: Any) -> str:
        return self.user_route(
            implementation=args.user,
            native_model=args.user_llm,
            candidate_route=(
                f"{args.user_provider}-{args.user_source}-{args.user_llm}-{args.user_effort}"
            ),
        )

    def parse_json_object(self, value: str, field: str) -> dict[str, Any]:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ContractError(f"{field} must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ContractError(f"{field} must be a JSON object")
        return parsed

    def resolved_config(
        self,
        args: Any,
        *,
        user_llm_args: Mapping[str, Any],
        retrieval_config_kwargs: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Resolve every tau2 option that can alter measurement semantics."""

        return {
            "schema": self.schema,
            "domain": args.domain,
            "task_set_name": args.task_set_name,
            "task_split_name": args.task_split_name,
            "num_trials": args.num_trials,
            "max_concurrency": args.max_concurrency,
            "max_steps": args.max_steps,
            "max_errors": args.max_errors,
            "max_retries": args.max_retries,
            "timeout": args.timeout,
            "seed": args.seed,
            "agent": {
                "implementation": "geode_agent",
                "route": self.agent_route_from_args(args),
                "model": args.model,
                "provider": args.provider,
                "source": args.source,
                "effort": args.effort,
                "time_budget_s": args.time_budget_s,
                "max_tokens": args.max_tokens,
                "max_rounds": args.agent_max_rounds,
                "cognitive_reflection": args.enable_cognitive_reflection,
                "codex_output_replay": not args.disable_codex_output_replay,
                "tool_search_defer": not args.disable_tool_search_defer,
            },
            "user": {
                "implementation": args.user,
                "runtime_owner": self.user_runtime_owner(args.user),
                "route": self.user_route_from_args(args),
                "llm": args.user_llm,
                "llm_args": dict(user_llm_args),
            },
            "retrieval": {
                "config": args.retrieval_config,
                "kwargs": dict(retrieval_config_kwargs),
            },
        }

    def validate_config(self, config: Mapping[str, Any]) -> None:
        if config.get("schema") != self.schema:
            raise ContractError(f"tau2 assay schema must be {self.schema!r}")
        user = _mapping(config.get("user"), "assay_config.user")
        implementation = str(user.get("implementation") or "")
        owner = self.user_runtime_owner(implementation)
        if user.get("runtime_owner") != owner:
            raise ContractError("tau2 user runtime_owner does not match the adapter profile")
        if owner != "evaluator":
            raise ContractError(
                "contract-backed tau2 evidence requires a user runtime isolated from candidate code"
            )

    def normalize(
        self,
        contract: ExperimentContract,
        *,
        arm: Literal["baseline", "candidate"],
        results_path: Path,
        snapshot_path: Path,
        usage: ResourceUsage,
        checks_by_pair: Mapping[tuple[str, int], Mapping[str, bool]],
    ) -> EvidenceEnvelope:
        return normalize_tau2_results(
            contract,
            arm=arm,
            results_path=results_path,
            snapshot_path=snapshot_path,
            usage=usage,
            checks_by_pair=checks_by_pair,
        )


TAU2_ADAPTER = Tau2AssayAdapter()


def _load_object(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {field} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{field} must be a JSON object")
    return value


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be an object")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{field} must be an integer")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{field} must be a finite number")
    return float(value)


def _verify_snapshot(
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    raw_sha256: str,
    snapshot: Mapping[str, Any],
) -> tuple[Literal["complete", "invalid"], str | None]:
    if snapshot.get("schema") != _SNAPSHOT_SCHEMA:
        raise ContractError(f"snapshot.schema must be {_SNAPSHOT_SCHEMA!r}")
    expected_revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    expected = {
        "experiment_contract_id": contract.contract_id,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_layout_sha256": contract.task_layout_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "arm": arm,
    }
    for field, value in expected.items():
        if snapshot.get(field) != value:
            raise ContractError(f"snapshot.{field} does not match the frozen contract")
    revision_field = "baseline_sha" if arm == "baseline" else "candidate_sha"
    if snapshot.get(revision_field) != expected_revision:
        raise ContractError(f"snapshot.{revision_field} does not match the selected arm")
    if snapshot.get("raw_artifact_sha256") != raw_sha256:
        raise ContractError("snapshot raw_artifact_sha256 does not match the raw results bytes")
    if snapshot.get("assay_config") != contract.assay_config:
        raise ContractError("snapshot assay_config does not match the frozen contract")
    status = snapshot.get("execution_status")
    if status not in {"complete", "invalid"}:
        raise ContractError("snapshot.execution_status must be 'complete' or 'invalid'")
    failure = snapshot.get("failure_class")
    if status == "invalid":
        if not isinstance(failure, str) or not failure:
            raise ContractError("invalid snapshot requires failure_class")
        return "invalid", failure
    if failure is not None:
        raise ContractError("complete snapshot cannot carry failure_class")
    return "complete", None


def _verify_tau2_info(contract: ExperimentContract, raw: Mapping[str, Any]) -> None:
    config = contract.assay_config
    TAU2_ADAPTER.validate_config(config)
    info = _mapping(raw.get("info"), "tau2.info")
    exact = {
        "num_trials": contract.trials_per_task,
        "max_steps": config.get("max_steps"),
        "max_errors": config.get("max_errors"),
        "seed": config.get("seed"),
    }
    for field, expected in exact.items():
        if info.get(field) != expected:
            raise ContractError(f"tau2.info.{field} does not match assay_config")
    environment = _mapping(info.get("environment_info"), "tau2.info.environment_info")
    if environment.get("domain_name") != config.get("domain"):
        raise ContractError("tau2 environment domain does not match assay_config")
    agent = _mapping(info.get("agent_info"), "tau2.info.agent_info")
    agent_config = _mapping(config.get("agent"), "assay_config.agent")
    if agent.get("implementation") != agent_config.get("implementation"):
        raise ContractError("tau2 agent implementation does not match assay_config")
    if agent.get("llm") != agent_config.get("model"):
        raise ContractError("tau2 agent model does not match assay_config")
    user = _mapping(info.get("user_info"), "tau2.info.user_info")
    user_config = _mapping(config.get("user"), "assay_config.user")
    if user.get("implementation") != user_config.get("implementation"):
        raise ContractError("tau2 user implementation does not match assay_config")
    if user.get("llm") != user_config.get("llm"):
        raise ContractError("tau2 user model does not match assay_config")
    if user.get("llm_args") != user_config.get("llm_args"):
        raise ContractError("tau2 user llm_args do not match assay_config")
    retrieval = _mapping(config.get("retrieval"), "assay_config.retrieval")
    if info.get("retrieval_config") != retrieval.get("config"):
        raise ContractError("tau2 retrieval config does not match assay_config")
    if info.get("retrieval_config_kwargs") != retrieval.get("kwargs"):
        raise ContractError("tau2 retrieval kwargs do not match assay_config")


def normalize_tau2_results(
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    results_path: Path,
    snapshot_path: Path,
    usage: ResourceUsage,
    checks_by_pair: Mapping[tuple[str, int], Mapping[str, bool]],
) -> EvidenceEnvelope:
    """Convert one finalized tau2 artifact into an assay-neutral envelope.

    ``checks_by_pair`` comes from independent deterministic verifiers. In
    particular, the required ``safety`` check is never inferred from reward.
    """

    raw_bytes = results_path.read_bytes()
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ContractError(f"cannot parse tau2 results {results_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContractError("tau2 results must be a JSON object")
    snapshot = _load_object(snapshot_path, "tau2 snapshot")
    execution_status, failure_class = _verify_snapshot(
        contract,
        arm=arm,
        raw_sha256=raw_sha256,
        snapshot=snapshot,
    )
    _verify_tau2_info(contract, raw)

    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        raise ContractError("tau2 results simulations must be a list")
    rows: list[dict[str, Any]] = []
    saw_infrastructure_error = False
    for index, value in enumerate(simulations):
        sim = _mapping(value, f"tau2.simulations[{index}]")
        task_id = str(sim.get("task_id") or "").strip()
        if not task_id:
            raise ContractError(f"tau2.simulations[{index}].task_id is required")
        trial = _integer(sim.get("trial"), f"tau2.simulations[{index}].trial")
        termination = str(sim.get("termination_reason") or "").strip()
        termination_class = TAU2_ADAPTER.classify_termination(termination)
        if termination_class == "infra":
            status = "infrastructure_error"
            row_failure = f"tau2_{termination}"
            saw_infrastructure_error = True
        else:
            status = "completed"
            row_failure = None
        reward_info = sim.get("reward_info")
        if reward_info is None:
            reward = 0.0
        else:
            reward_row = _mapping(reward_info, f"tau2.simulations[{index}].reward_info")
            reward = _number(
                reward_row.get("reward"),
                f"tau2.simulations[{index}].reward_info.reward",
            )
        checks = checks_by_pair.get((task_id, trial))
        if checks is None:
            raise ContractError(f"independent checks missing for tau2 pair {task_id!r}/{trial}")
        row: dict[str, Any] = {
            "task_id": task_id,
            "trial": trial,
            "status": status,
            "termination_reason": termination,
            "metrics": {"reward": reward},
            "checks": dict(checks),
        }
        if row_failure is not None:
            row["failure_class"] = row_failure
        rows.append(row)

    if saw_infrastructure_error and execution_status == "complete":
        execution_status = "invalid"
        failure_class = "tau2_infrastructure_error"
    revision_sha = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    payload: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "contract_id": contract.contract_id,
        "arm": arm,
        "revision_sha": revision_sha,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_layout_sha256": contract.task_layout_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "raw_artifact_sha256": raw_sha256,
        "execution_status": execution_status,
        "usage": usage.to_dict(),
        "rows": rows,
    }
    if failure_class is not None:
        payload["failure_class"] = failure_class
    return EvidenceEnvelope.from_mapping(payload)
