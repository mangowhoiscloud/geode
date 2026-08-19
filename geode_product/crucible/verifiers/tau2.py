"""Normalize pinned tau2 results without importing the external harness."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from geode_product.benchmark_harness.tau2_runtime_contract import (
    GEODE_DUAL_RUNTIME_PROFILE,
    TAU2_NATIVE_USER_PROFILE,
)
from geode_product.crucible.contract import ContractError, ExperimentContract, TaskUnit
from geode_product.crucible.evidence import EVIDENCE_SCHEMA, EvidenceEnvelope, ResourceUsage

_SNAPSHOT_SCHEMA = "crucible_tau2_trajectory_snapshot.v4"
# Public alias: the row cache synthesizes snapshots the verifier must accept,
# so both sides must share one schema constant rather than drifting literals.
SNAPSHOT_SCHEMA = _SNAPSHOT_SCHEMA


@dataclass(frozen=True)
class Tau2AssayAdapter:
    """Pinned tau2 schema/profile; all tau2-specific cases live here."""

    schema: str = "crucible.tau2-assay.v1"
    required_evaluator_paths: tuple[str, ...] = (
        "geode_product/benchmark_harness/tau2_geode_agent.py",
        "geode_product/benchmark_harness/tau2_runtime_contract.py",
        "geode_product/benchmark_harness/trajectory_artifacts.py",
        "geode_product/crucible",
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
        ("crucible_user", "evaluator"),
        ("dummy_user", "evaluator"),
        ("geode_user", "candidate"),
        ("user_simulator", "evaluator"),
    )
    agent_concurrency_limits: tuple[tuple[str, int], ...] = (("geode_agent", 1),)
    metric_bounds: tuple[tuple[str, float, float], ...] = (("reward", 0.0, 1.0),)
    normal_completion_reasons: tuple[str, ...] = ("user_stop",)
    feedback_codes_by_requestor: tuple[tuple[str, str], ...] = (
        ("assistant", "state_correctness"),
        ("user", "required_user_action"),
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

    def metric_bound(self, metric: str) -> tuple[float, float]:
        try:
            lower, upper = {
                name: (minimum, maximum) for name, minimum, maximum in self.metric_bounds
            }[metric]
        except KeyError as exc:
            raise ContractError(f"unbounded tau2 metric: {metric!r}") from exc
        return lower, upper

    def feedback_code_for_requestor(self, requestor: object) -> str | None:
        return next(
            (
                failure_code
                for owner, failure_code in self.feedback_codes_by_requestor
                if requestor == owner
            ),
            None,
        )

    def user_route(
        self,
        *,
        implementation: str,
        native_model: str,
        candidate_route: str,
    ) -> str:
        if implementation == "crucible_user":
            return f"evaluator-{candidate_route}"
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
                "provider": args.user_provider,
                "source": args.user_source,
                "effort": args.user_effort,
                "time_budget_s": args.user_time_budget_s,
                "max_tokens": args.user_max_tokens,
                "max_rounds": args.user_max_rounds,
            },
            "retrieval": {
                "config": args.retrieval_config,
                "kwargs": dict(retrieval_config_kwargs),
            },
        }

    def validate_config(self, config: Mapping[str, Any]) -> None:
        if config.get("schema") != self.schema:
            raise ContractError(f"tau2 assay schema must be {self.schema!r}")
        if "timeout" not in config:
            raise ContractError(
                "contract-backed tau2 evidence requires an explicit timeout field; "
                "null disables the per-simulation wall cap"
            )
        timeout = config.get("timeout")
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ContractError("tau2 assay timeout must be null or a positive finite number")
        user = _mapping(config.get("user"), "assay_config.user")
        implementation = str(user.get("implementation") or "")
        owner = self.user_runtime_owner(implementation)
        if user.get("runtime_owner") != owner:
            raise ContractError("tau2 user runtime_owner does not match the adapter profile")
        if owner != "evaluator":
            raise ContractError(
                "contract-backed tau2 evidence requires a user runtime isolated from candidate code"
            )
        agent = _mapping(config.get("agent"), "assay_config.agent")
        for role, participant in (("agent", agent), ("user", user)):
            if participant.get("max_rounds") != 0:
                raise ContractError(
                    f"contract-backed tau2 {role} requires max_rounds=0; "
                    "the external half-duplex boundary owns the yield"
                )
        implementation = str(agent.get("implementation") or "")
        concurrency_limit = dict(self.agent_concurrency_limits).get(implementation)
        max_concurrency = config.get("max_concurrency")
        if concurrency_limit is not None and (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency < 1
            or max_concurrency > concurrency_limit
        ):
            raise ContractError(
                f"tau2 {implementation} supports max_concurrency<={concurrency_limit}"
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


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field} must be a non-negative integer")
    return value


def _canonical_task_sha256(value: Mapping[str, Any], field: str) -> str:
    content = dict(value)
    content.pop("id", None)
    # tau2's Pydantic result serialization materializes these omitted Task
    # defaults as null. Normalize the source-file and runtime shapes before
    # hashing so only executable task content contributes to identity.
    for optional_field in ("issues", "required_documents", "user_tools"):
        content.setdefault(optional_field, None)
    try:
        encoded = json.dumps(
            content,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field} must contain canonical JSON values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _tau2_family_sha256(value: Mapping[str, Any], field: str) -> str:
    """Hash the executable workflow shape without task-specific oracle values."""

    criteria = _mapping(value.get("evaluation_criteria"), f"{field}.evaluation_criteria")
    actions = criteria.get("actions")
    if not isinstance(actions, list):
        raise ContractError(f"{field}.evaluation_criteria.actions must be a list")
    action_names: list[str] = []
    for index, action in enumerate(actions):
        row = _mapping(action, f"{field}.evaluation_criteria.actions[{index}]")
        name = str(row.get("name") or "").strip()
        if not name:
            raise ContractError(f"{field}.evaluation_criteria.actions[{index}].name is required")
        action_names.append(name)

    raw_user_tools = value.get("user_tools")
    if raw_user_tools is None:
        user_tool_names: list[str] = []
    elif isinstance(raw_user_tools, list):
        user_tool_names = []
        for index, tool in enumerate(raw_user_tools):
            if isinstance(tool, str):
                name = tool.strip()
            else:
                row = _mapping(tool, f"{field}.user_tools[{index}]")
                name = str(row.get("name") or "").strip()
            if not name:
                raise ContractError(f"{field}.user_tools[{index}] name is required")
            user_tool_names.append(name)
    else:
        raise ContractError(f"{field}.user_tools must be a list or null")

    active_criteria = sorted(
        str(name) for name, criterion in criteria.items() if criterion not in (None, [], {}, "")
    )
    encoded = json.dumps(
        {
            "action_names": action_names,
            "active_criteria": active_criteria,
            "user_tool_names": user_tool_names,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def tau2_task_unit(value: Mapping[str, Any], field: str = "tau2 task") -> TaskUnit:
    """Build the content and family identity expected in a tau2 contract."""

    raw_id = value.get("id")
    task_id = str(raw_id).strip() if raw_id is not None else ""
    if not task_id:
        raise ContractError(f"{field}.id is required")
    return TaskUnit(
        task_id=task_id,
        family_id=_tau2_family_sha256(value, field),
        content_sha256=_canonical_task_sha256(value, field),
    )


def _verify_tau2_tasks(contract: ExperimentContract, raw: Mapping[str, Any]) -> None:
    raw_tasks = raw.get("tasks")
    if not isinstance(raw_tasks, list):
        raise ContractError("tau2 results tasks must be a list")
    observed: list[TaskUnit] = []
    observed_ids: set[str] = set()
    for index, value in enumerate(raw_tasks):
        field = f"tau2.tasks[{index}]"
        raw_task = _mapping(value, field)
        task = tau2_task_unit(raw_task, field)
        if task.task_id in observed_ids:
            raise ContractError(f"tau2 results tasks repeat id {task.task_id!r}")
        observed.append(task)
        observed_ids.add(task.task_id)

    if tuple(task.task_id for task in observed) != contract.task_ids:
        raise ContractError("tau2 task order/coverage does not match the frozen contract tasks")
    for expected, actual in zip(contract.tasks, observed, strict=True):
        if actual.content_sha256 != expected.content_sha256:
            raise ContractError(
                f"tau2 task {expected.task_id!r} content_sha256 does not match the frozen contract"
            )
        if actual.family_id != expected.family_id:
            raise ContractError(
                f"tau2 task {expected.task_id!r} family_id does not match the frozen contract"
            )


def _verify_snapshot(
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    raw_sha256: str,
    snapshot: Mapping[str, Any],
    snapshot_path: Path | None = None,
    raw: Mapping[str, Any] | None = None,
) -> tuple[Literal["complete", "invalid"], str | None]:
    if snapshot.get("schema") != _SNAPSHOT_SCHEMA:
        raise ContractError(f"snapshot.schema must be {_SNAPSHOT_SCHEMA!r}")
    expected_revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    expected = {
        "experiment_contract_id": contract.contract_id,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_pack_sha256": contract.task_pack_sha256,
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
    if snapshot_path is None or raw is None:
        raise ContractError("complete snapshot verification requires companion artifact context")
    expected_profile = (
        GEODE_DUAL_RUNTIME_PROFILE
        if _mapping(contract.assay_config.get("user"), "assay_config.user").get("implementation")
        in {"geode_user", "crucible_user"}
        else TAU2_NATIVE_USER_PROFILE
    )
    if snapshot.get("runtime_profile") != expected_profile:
        raise ContractError("snapshot runtime_profile does not match the user implementation")
    runtime_profile = _verify_companion(
        snapshot,
        snapshot_path=snapshot_path,
        field="runtime_profile_artifact",
        schema="geode.tau2-runtime-profile.v1",
    )
    if runtime_profile.get("runtime_revision") != expected_revision:
        raise ContractError("runtime profile revision does not match the selected arm")
    if runtime_profile.get("runtime_profile") != expected_profile:
        raise ContractError("runtime profile mode does not match the snapshot")
    native_receipt = _mapping(
        _mapping(runtime_profile.get("persistence"), "runtime_profile.persistence").get(
            "native_receipt"
        ),
        "runtime_profile.persistence.native_receipt",
    )
    if native_receipt.get("sha256") != raw_sha256:
        raise ContractError("runtime profile native receipt digest does not match results")
    attempt_manifest = _verify_companion(
        snapshot,
        snapshot_path=snapshot_path,
        field="attempt_manifest_artifact",
        schema="geode.tau2-attempt-manifest.v1",
    )
    _verify_attempt_manifest(attempt_manifest, raw)
    _verify_geode_trajectory(
        snapshot,
        snapshot_path=snapshot_path,
        raw_sha256=raw_sha256,
    )
    return "complete", None


def _verify_companion(
    snapshot: Mapping[str, Any],
    *,
    snapshot_path: Path,
    field: str,
    schema: str,
) -> Mapping[str, Any]:
    reference = _mapping(snapshot.get(field), f"snapshot.{field}")
    filename = reference.get("path")
    digest = reference.get("sha256")
    if not isinstance(filename, str) or not filename:
        raise ContractError(f"snapshot.{field}.path is required")
    relative = Path(filename)
    if relative.is_absolute() or len(relative.parts) != 1 or relative.name != filename:
        raise ContractError(f"snapshot.{field}.path must be a sibling filename")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ContractError(f"snapshot.{field}.sha256 is required")
    path = snapshot_path.parent / relative
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read snapshot companion {filename!r}: {exc}") from exc
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ContractError(f"snapshot.{field}.sha256 does not match companion bytes")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ContractError(f"cannot parse snapshot companion {filename!r}: {exc}") from exc
    row = _mapping(parsed, f"snapshot companion {filename}")
    if row.get("schema") != schema:
        raise ContractError(f"snapshot companion {filename!r} must use schema {schema!r}")
    if row.get("run_id") != snapshot.get("run_id"):
        raise ContractError(f"snapshot companion {filename!r} run_id does not match")
    return row


def _verify_geode_trajectory(
    snapshot: Mapping[str, Any],
    *,
    snapshot_path: Path,
    raw_sha256: str,
) -> None:
    """Require the portable trajectory sidecar to be hash-bound and complete."""
    from core.observability.trajectory import verify_trajectory_integrity

    run_id = str(snapshot.get("run_id") or "")
    expected_name = f"{run_id}.geode-trajectory.json"
    declared = snapshot.get("geode_trajectory")
    if not isinstance(declared, str) or Path(declared).name != expected_name:
        raise ContractError("snapshot geode_trajectory must name the run's sibling sidecar")
    digest = snapshot.get("geode_trajectory_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ContractError("snapshot geode_trajectory_sha256 is required")
    path = snapshot_path.parent / expected_name
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read GEODE trajectory companion: {exc}") from exc
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ContractError("snapshot geode_trajectory_sha256 does not match companion bytes")
    try:
        trajectory = _mapping(json.loads(payload), "GEODE trajectory companion")
        integrity = verify_trajectory_integrity(trajectory)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"invalid GEODE trajectory companion: {exc}") from exc
    if trajectory.get("schema_id") != "geode.trajectory@1":
        raise ContractError("GEODE trajectory companion must use geode.trajectory@1")
    source = _mapping(trajectory.get("source"), "GEODE trajectory source")
    if source.get("run") != run_id:
        raise ContractError("GEODE trajectory run does not match snapshot")
    if source.get("runtime_profile_sha256") != _mapping(
        snapshot.get("runtime_profile_artifact"), "snapshot.runtime_profile_artifact"
    ).get("sha256"):
        raise ContractError("GEODE trajectory runtime profile digest does not match snapshot")
    if source.get("attempt_manifest_sha256") != _mapping(
        snapshot.get("attempt_manifest_artifact"), "snapshot.attempt_manifest_artifact"
    ).get("sha256"):
        raise ContractError("GEODE trajectory attempt manifest digest does not match snapshot")
    if raw_sha256 not in {
        str(_mapping(row, "GEODE trajectory artifact digest").get("sha256") or "")
        for row in trajectory.get("artifact_digests", [])
    }:
        raise ContractError("GEODE trajectory does not bind the native receipt digest")
    if integrity.get("scope_complete") is not True:
        raise ContractError("GEODE trajectory is not scope complete")


def _verify_attempt_manifest(
    manifest: Mapping[str, Any],
    raw: Mapping[str, Any],
) -> None:
    attempts = manifest.get("attempts")
    final_results = manifest.get("final_results")
    simulations = raw.get("simulations")
    if not isinstance(attempts, list) or not isinstance(final_results, list):
        raise ContractError("tau2 attempt manifest requires attempts and final_results lists")
    if not isinstance(simulations, list):
        raise ContractError("tau2 results simulations must be a list")
    attempt_ids: set[str] = set()
    selected_ids: set[str] = set()
    selected_groups: set[tuple[str, int]] = set()
    attempts_by_id: dict[str, Mapping[str, Any]] = {}
    previous_by_run: dict[tuple[str, int], tuple[str, int, int]] = {}
    for index, value in enumerate(attempts):
        attempt = _mapping(value, f"attempt_manifest.attempts[{index}]")
        attempt_id = str(attempt.get("attempt_id") or "")
        if not attempt_id or attempt_id in attempt_ids:
            raise ContractError("tau2 attempt manifest attempt ids must be unique")
        attempt_ids.add(attempt_id)
        attempts_by_id[attempt_id] = attempt
        task_id = str(attempt.get("task_id") or "")
        trial = _integer(attempt.get("trial"), "attempt_manifest attempt trial")
        ordinal = _integer(attempt.get("attempt"), "attempt_manifest attempt ordinal")
        seed = _integer(attempt.get("seed"), "attempt_manifest attempt seed")
        if not task_id or trial < 0 or ordinal < 1:
            raise ContractError("tau2 attempt requires task_id and non-negative trial/ordinal")
        group = (task_id, trial)
        previous = previous_by_run.get(group)
        retry_of = attempt.get("retry_of")
        if previous is None:
            if ordinal != 1 or retry_of is not None:
                raise ContractError("first tau2 attempt must have ordinal 1 and no retry_of")
        else:
            previous_id, previous_ordinal, previous_seed = previous
            if ordinal != previous_ordinal + 1 or retry_of != previous_id:
                raise ContractError("tau2 retry lineage must be consecutive within task/trial")
            if seed != previous_seed:
                raise ContractError("tau2 retry seed must remain stable within task/trial")
        previous_by_run[group] = (attempt_id, ordinal, seed)
        if attempt.get("status") not in {"complete", "error"}:
            raise ContractError("final tau2 attempt status must be complete or error")
        if not isinstance(attempt.get("selected_final"), bool):
            raise ContractError("tau2 attempt selected_final must be boolean")
        if attempt.get("selected_final") is True:
            if attempt.get("status") != "complete" or not attempt.get("simulation_id"):
                raise ContractError("selected tau2 attempt must be complete with simulation_id")
            if group in selected_groups:
                raise ContractError("tau2 task/trial may have only one selected attempt")
            selected_groups.add(group)
            selected_ids.add(attempt_id)
    simulations_by_key = {
        (
            str(_mapping(value, "tau2 simulation").get("task_id") or ""),
            _integer(_mapping(value, "tau2 simulation").get("trial"), "tau2 trial"),
            str(_mapping(value, "tau2 simulation").get("id") or ""),
        ): _mapping(value, "tau2 simulation")
        for value in simulations
    }
    observed = set(simulations_by_key)
    declared: set[tuple[str, int, str]] = set()
    referenced_selected_ids: set[str] = set()
    for index, value in enumerate(final_results):
        result = _mapping(value, f"attempt_manifest.final_results[{index}]")
        key = (
            str(result.get("task_id") or ""),
            _integer(result.get("trial"), "attempt_manifest final trial"),
            str(result.get("simulation_id") or ""),
        )
        if key in declared:
            raise ContractError("tau2 attempt manifest final results must be unique")
        declared.add(key)
        selected = result.get("selected_attempt_id")
        if selected is not None and selected not in selected_ids:
            raise ContractError("final tau2 selection references a non-selected attempt")
        native_sessions = _native_session_ids(simulations_by_key.get(key, {}))
        if selected is None:
            if result.get("selection_status") != "no_successful_attempt":
                raise ContractError("unselected tau2 result requires no_successful_attempt status")
            if native_sessions:
                raise ContractError("unselected tau2 result cannot reference GEODE sessions")
            continue
        if result.get("selection_status") != "selected":
            raise ContractError("selected tau2 result requires selected status")
        referenced_selected_ids.add(str(selected))
        selected_attempt = attempts_by_id[str(selected)]
        if (
            str(selected_attempt.get("task_id") or ""),
            _integer(selected_attempt.get("trial"), "selected tau2 attempt trial"),
            str(selected_attempt.get("simulation_id") or ""),
        ) != key:
            raise ContractError("selected tau2 attempt identity does not match final result")
        session_rows = selected_attempt.get("sessions")
        if not isinstance(session_rows, list):
            raise ContractError("selected tau2 attempt requires a sessions list")
        declared_sessions = {
            str(_mapping(row, "attempt session").get("session_id") or "") for row in session_rows
        }
        declared_sessions.discard("")
        if declared_sessions != native_sessions:
            raise ContractError("selected tau2 attempt sessions do not match native messages")
    if declared != observed:
        raise ContractError("tau2 attempt manifest final results do not match native results")
    if referenced_selected_ids != selected_ids:
        raise ContractError("selected tau2 attempts must be referenced exactly once")


def _native_session_ids(simulation: Mapping[str, Any]) -> set[str]:
    messages = simulation.get("messages")
    if not isinstance(messages, list):
        return set()
    session_ids: set[str] = set()
    for value in messages:
        message = value if isinstance(value, Mapping) else {}
        raw_data = message.get("raw_data")
        if not isinstance(raw_data, Mapping):
            continue
        session_id = str(raw_data.get("geode_session_id") or "")
        if session_id:
            session_ids.add(session_id)
    return session_ids


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


def _pre_execution_retry_errors(sim: Mapping[str, Any], *, index: int) -> tuple[str, ...]:
    """Read source-attested GEODE retry telemetry from one tau2 row."""

    messages = sim.get("messages", [])
    if not isinstance(messages, list):
        raise ContractError(f"tau2.simulations[{index}].messages must be a list")
    observed: list[str] = []
    for message_index, message_value in enumerate(messages):
        message = _mapping(
            message_value,
            f"tau2.simulations[{index}].messages[{message_index}]",
        )
        raw_data = message.get("raw_data")
        if raw_data is None:
            continue
        telemetry = _mapping(
            raw_data,
            f"tau2.simulations[{index}].messages[{message_index}].raw_data",
        )
        count_raw = telemetry.get("geode_pre_execution_retry_count")
        errors_raw = telemetry.get("geode_pre_execution_retry_errors")
        if count_raw is None and errors_raw is None:
            continue
        if isinstance(count_raw, bool) or not isinstance(count_raw, int) or count_raw < 0:
            raise ContractError("tau2 GEODE pre-execution retry count must be non-negative")
        if not isinstance(errors_raw, list) or any(
            not isinstance(value, str) or not value for value in errors_raw
        ):
            raise ContractError("tau2 GEODE pre-execution retry errors must be strings")
        if len(errors_raw) != count_raw:
            raise ContractError("tau2 GEODE pre-execution retry telemetry is inconsistent")
        observed.extend(errors_raw)
    return tuple(observed)


def tau2_has_infrastructure_contamination(raw: Mapping[str, Any]) -> bool:
    """Return whether any finalized tau2 row already makes the arm invalid.

    The live evaluator polls incremental ``results.json`` output and uses this
    predicate to stop buying rows once an infrastructure-contaminated row has
    made a score-bearing verdict impossible. Incomplete rows without a
    termination reason are ignored until tau2 finalizes them.
    """

    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        raise ContractError("tau2 results simulations must be a list")
    for index, value in enumerate(simulations):
        sim = _mapping(value, f"tau2.simulations[{index}]")
        termination = str(sim.get("termination_reason") or "").strip()
        if not termination:
            continue
        if TAU2_ADAPTER.classify_termination(termination) == "infra":
            return True
        if _pre_execution_retry_errors(sim, index=index):
            return True
    return False


def tau2_resource_usage_floor(raw: Mapping[str, Any]) -> ResourceUsage:
    """Derive the minimum observable arm usage embedded in tau2 messages."""

    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        raise ContractError("tau2 results simulations must be a list")
    wall_seconds = 0.0
    calls = 0
    tokens = 0
    cost_usd = 0.0
    for sim_index, value in enumerate(simulations):
        sim = _mapping(value, f"tau2.simulations[{sim_index}]")
        duration = sim.get("duration")
        if duration is not None:
            observed_duration = _number(duration, f"tau2.simulations[{sim_index}].duration")
            if observed_duration < 0:
                raise ContractError(f"tau2.simulations[{sim_index}].duration must not be negative")
            wall_seconds = max(wall_seconds, observed_duration)
        messages = sim.get("messages", [])
        if not isinstance(messages, list):
            raise ContractError(f"tau2.simulations[{sim_index}].messages must be a list")
        for message_index, message_value in enumerate(messages):
            message = _mapping(
                message_value,
                f"tau2.simulations[{sim_index}].messages[{message_index}]",
            )
            raw_usage = message.get("usage")
            if raw_usage is None:
                continue
            message_usage = _mapping(
                raw_usage,
                f"tau2.simulations[{sim_index}].messages[{message_index}].usage",
            )
            input_tokens = _non_negative_integer(
                message_usage.get("input_tokens"),
                f"tau2.simulations[{sim_index}].messages[{message_index}].usage.input_tokens",
            )
            output_tokens = _non_negative_integer(
                message_usage.get("output_tokens"),
                f"tau2.simulations[{sim_index}].messages[{message_index}].usage.output_tokens",
            )
            observed_cost = _number(
                message_usage.get("cost_usd"),
                f"tau2.simulations[{sim_index}].messages[{message_index}].usage.cost_usd",
            )
            if observed_cost < 0:
                raise ContractError("tau2 message usage cost_usd must not be negative")
            calls += 1
            tokens += input_tokens + output_tokens
            cost_usd += observed_cost
    return ResourceUsage(
        wall_seconds=wall_seconds,
        calls=calls,
        tokens=tokens,
        cost_usd=cost_usd,
    )


def _verify_usage_floor(declared: ResourceUsage, observed: ResourceUsage) -> None:
    underreported = []
    if declared.wall_seconds + 1e-9 < observed.wall_seconds:
        underreported.append("wall_seconds")
    if declared.calls < observed.calls:
        underreported.append("calls")
    if declared.tokens < observed.tokens:
        underreported.append("tokens")
    if declared.cost_usd + 1e-9 < observed.cost_usd:
        underreported.append("cost_usd")
    if underreported:
        raise ContractError(
            "usage manifest underreports tau2 raw usage: " + ", ".join(underreported)
        )


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
    _verify_usage_floor(usage, tau2_resource_usage_floor(raw))
    snapshot = _load_object(snapshot_path, "tau2 snapshot")
    execution_status, failure_class = _verify_snapshot(
        contract,
        arm=arm,
        raw_sha256=raw_sha256,
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        raw=raw,
    )
    _verify_tau2_info(contract, raw)
    _verify_tau2_tasks(contract, raw)

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
        retry_errors = _pre_execution_retry_errors(sim, index=index)
        if termination_class == "infra" or retry_errors:
            status = "infrastructure_error"
            row_failure = "tau2_pre_execution_retry" if retry_errors else f"tau2_{termination}"
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
        reward_minimum, reward_maximum = TAU2_ADAPTER.metric_bound("reward")
        if not reward_minimum <= reward <= reward_maximum:
            raise ContractError(
                "tau2.simulations"
                f"[{index}].reward_info.reward must be within "
                f"[{reward_minimum:g}, {reward_maximum:g}]"
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
        "task_pack_sha256": contract.task_pack_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "raw_artifact_sha256": raw_sha256,
        "execution_status": execution_status,
        "usage": usage.to_dict(),
        "rows": rows,
    }
    if failure_class is not None:
        payload["failure_class"] = failure_class
    return EvidenceEnvelope.from_mapping(payload)
