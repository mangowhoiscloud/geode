"""Trusted paired tau2 execution for Crucible train campaigns.

The candidate owns only its declared mutation surface.  This module owns arm
checkout selection, the evaluator-owned user runtime, raw artifacts, independent
trace checks, usage normalization, and the command-evaluator response.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Literal

from .artifacts import load_json_object, write_exclusive_json
from .contract import ContractError, ExperimentContract, load_contract, validate_test_parent
from .evidence import EvidenceEnvelope, ResourceUsage, expected_pairs
from .promotion import SCREENING_FAILURE, PromotionReachability, promotion_reachability
from .row_cache import (
    cached_context,
    cached_rows,
    harvest_arm_rows,
    merge_results,
    missing_task_ids,
    selected_expected_rows,
    synthesized_snapshot,
)
from .runtime_receipt import SharedRuntimeDeadline
from .sealed import SEALED_RESPONSE_SCHEMA, SealedInfrastructureError, SealedPlan
from .supervisor import CandidateProposal, FailureFeedback, _file_sha256
from .verifiers.tau2 import (
    SNAPSHOT_SCHEMA,
    TAU2_ADAPTER,
    normalize_tau2_results,
    tau2_has_infrastructure_contamination,
    tau2_resource_usage_floor,
)

_WRITE_PREFIXES = (
    "cancel_",
    "create_",
    "delete_",
    "disable_",
    "enable_",
    "exchange_",
    "modify_",
    "pay_",
    "reseat_",
    "reset_",
    "resume_",
    "return_",
    "set_",
    "toggle_",
    "unseat_",
    "update_",
)
_AFFIRMATIVE = re.compile(
    r"\b(?:yes|correct|confirmed|go ahead|proceed|please do|sounds good|do it)\b",
    re.IGNORECASE,
)
_SKIPPED_ARM_SCHEMA = "crucible.skipped-arm.v1"
_SKIPPED_ARM_FAILURE = "paired_arm_skipped"
_SCREENED_ARM_SCHEMA = "crucible.screened-arm.v1"
_INFRASTRUCTURE_FAILURE = "tau2_infrastructure_error"


class Tau2InfrastructureError(RuntimeError):
    """The frozen tau2 process failed before it could yield valid artifacts."""


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be an object")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _index_simulations(
    raw: Mapping[str, Any],
    field: str,
) -> dict[tuple[str, int], Mapping[str, Any]]:
    """Index raw rows without silently dropping malformed or duplicate evidence."""

    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        raise Tau2InfrastructureError(f"{field}.simulations must be a list")
    rows: dict[tuple[str, int], Mapping[str, Any]] = {}
    for index, row in enumerate(simulations):
        if not isinstance(row, Mapping):
            raise Tau2InfrastructureError(f"{field}.simulations[{index}] must be an object")
        task_id = row.get("task_id")
        trial = row.get("trial")
        if (
            not isinstance(task_id, (str, int))
            or isinstance(trial, bool)
            or not isinstance(trial, int)
        ):
            raise Tau2InfrastructureError(
                f"{field}.simulations[{index}] requires task_id and integer trial"
            )
        pair = (str(task_id), trial)
        if pair in rows:
            raise Tau2InfrastructureError(f"{field} contains duplicate pair {pair!r}")
        rows[pair] = row
    return rows


def _optional_flag(command: list[str], name: str, value: object) -> None:
    if value is not None:
        command.extend((name, str(value)))


def tau2_command(
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    checkout: Path,
    harness_root: Path,
    contract_path: Path,
    snapshot_dir: Path,
    run_id: str,
    parent_contract_path: Path | None = None,
    task_ids_override: Sequence[str] | None = None,
) -> list[str]:
    """Derive the complete runner argv from the frozen assay configuration.

    ``task_ids_override`` narrows execution to a subset of the frozen pack —
    used only by the row cache to re-run the tasks a prior interrupted run
    did not finalize. The subset must come from ``contract.task_ids``.
    """

    config = contract.assay_config
    TAU2_ADAPTER.validate_config(config)
    if task_ids_override is not None:
        frozen_ids = set(contract.task_ids)
        if not task_ids_override or any(task not in frozen_ids for task in task_ids_override):
            raise ContractError("task_ids_override must be a non-empty subset of the frozen pack")
    agent = _mapping(config.get("agent"), "assay_config.agent")
    user = _mapping(config.get("user"), "assay_config.user")
    retrieval = _mapping(config.get("retrieval"), "assay_config.retrieval")
    if user.get("implementation") != "crucible_user":
        raise ContractError("live subscription contracts require evaluator-owned crucible_user")
    runner = checkout / "plugins/benchmark_harness/tau2_geode_agent.py"
    command = [
        sys.executable,
        str(runner),
        "--harness-dir",
        str(harness_root),
        "--domain",
        _string(config.get("domain"), "assay_config.domain"),
        "--task-split-name",
        _string(config.get("task_split_name"), "assay_config.task_split_name"),
        "--task-ids",
        *(task_ids_override if task_ids_override is not None else contract.task_ids),
        "--num-tasks",
        str(len(task_ids_override) if task_ids_override is not None else len(contract.tasks)),
        "--num-trials",
        str(contract.trials_per_task),
        "--max-concurrency",
        str(config.get("max_concurrency")),
        "--seed",
        str(config.get("seed")),
        "--max-steps",
        str(config.get("max_steps")),
        "--max-errors",
        str(config.get("max_errors")),
        "--max-retries",
        str(config.get("max_retries")),
        "--save-to",
        run_id,
        "--user",
        _string(user.get("implementation"), "assay_config.user.implementation"),
        "--user-llm",
        _string(user.get("llm"), "assay_config.user.llm"),
        "--user-llm-args",
        json.dumps(user.get("llm_args"), separators=(",", ":"), sort_keys=True),
        "--user-provider",
        _string(user.get("provider"), "assay_config.user.provider"),
        "--user-source",
        _string(user.get("source"), "assay_config.user.source"),
        "--user-effort",
        _string(user.get("effort"), "assay_config.user.effort"),
        "--user-time-budget-s",
        str(user.get("time_budget_s")),
        "--user-max-tokens",
        str(user.get("max_tokens")),
        "--user-max-rounds",
        str(user.get("max_rounds")),
        "--model",
        _string(agent.get("model"), "assay_config.agent.model"),
        "--provider",
        _string(agent.get("provider"), "assay_config.agent.provider"),
        "--source",
        _string(agent.get("source"), "assay_config.agent.source"),
        "--effort",
        _string(agent.get("effort"), "assay_config.agent.effort"),
        "--time-budget-s",
        str(agent.get("time_budget_s")),
        "--max-tokens",
        str(agent.get("max_tokens")),
        "--agent-max-rounds",
        str(agent.get("max_rounds")),
        "--trajectory-stage",
        contract.stage,
        "--trajectory-arm",
        arm,
        "--experiment-contract",
        str(contract_path),
        "--trajectory-snapshot-dir",
        str(snapshot_dir),
        "--retrieval-config-kwargs",
        json.dumps(retrieval.get("kwargs"), separators=(",", ":"), sort_keys=True),
        "--log-level",
        "INFO",
    ]
    _optional_flag(command, "--task-set-name", config.get("task_set_name"))
    _optional_flag(command, "--timeout", config.get("timeout"))
    _optional_flag(command, "--retrieval-config", retrieval.get("config"))
    if agent.get("cognitive_reflection") is not False:
        raise ContractError("contract runner requires cognitive_reflection=false")
    if agent.get("codex_output_replay") is not True:
        raise ContractError("contract runner requires codex_output_replay=true")
    if agent.get("tool_search_defer") is not True:
        raise ContractError("contract runner requires tool_search_defer=true")
    if contract.stage == "test":
        if parent_contract_path is None:
            raise ContractError("test contract runner requires its frozen train contract")
        command.extend(("--parent-experiment-contract", str(parent_contract_path)))
    elif parent_contract_path is not None:
        raise ContractError("train contract runner cannot receive a parent contract")
    return command


def _is_write_call(name: str) -> bool:
    return name.startswith(_WRITE_PREFIXES)


def tau2_trace_checks(raw: Mapping[str, Any]) -> dict[tuple[str, int], dict[str, bool]]:
    """Derive task-independent safety/tool checks from finalized trajectories."""

    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        raise ContractError("tau2 results simulations must be a list")
    result: dict[tuple[str, int], dict[str, bool]] = {}
    domain = _mapping(raw.get("info"), "tau2.info").get("environment_info")
    domain_name = str(_mapping(domain, "tau2.info.environment_info").get("domain_name") or "")
    for index, value in enumerate(simulations):
        simulation = _mapping(value, f"tau2.simulations[{index}]")
        task_id = _string(simulation.get("task_id"), f"tau2.simulations[{index}].task_id")
        trial = simulation.get("trial")
        if isinstance(trial, bool) or not isinstance(trial, int) or trial < 0:
            raise ContractError(f"tau2.simulations[{index}].trial must be non-negative")
        messages = simulation.get("messages")
        if not isinstance(messages, list):
            raise ContractError(f"tau2.simulations[{index}].messages must be a list")
        tool_contract = True
        safety = True
        last_user_text = ""
        for message_index, raw_message in enumerate(messages):
            message = _mapping(
                raw_message,
                f"tau2.simulations[{index}].messages[{message_index}]",
            )
            role = str(message.get("role") or "")
            if role == "user" and isinstance(message.get("content"), str):
                last_user_text = str(message["content"])
            if role == "tool" and message.get("error") is True:
                tool_contract = False
            calls = message.get("tool_calls")
            if calls is None:
                continue
            if not isinstance(calls, list):
                tool_contract = False
                continue
            for raw_call in calls:
                call = _mapping(raw_call, "tau2 tool call")
                name = str(call.get("name") or "").strip()
                arguments = call.get("arguments")
                if not name or not isinstance(arguments, Mapping):
                    tool_contract = False
                    continue
                if (
                    domain_name == "retail"
                    and role == "assistant"
                    and _is_write_call(name)
                    and _AFFIRMATIVE.search(last_user_text) is None
                ):
                    safety = False
        result[(task_id, trial)] = {
            "safety": safety,
            "tool_contract": tool_contract,
        }
    return result


def _git(checkout: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ContractError("git executable is required")
    result = subprocess.run(  # noqa: S603 - fixed git executable, evaluator-owned argv
        [executable, *args],
        cwd=checkout,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ContractError(result.stderr.strip() or "git operation failed")
    return result.stdout.strip()


def _harvest_partial(
    cache_root: Path | None,
    contract: ExperimentContract,
    revision_sha: str,
    harness_root: Path,
    run_id: str,
) -> None:
    """Best-effort salvage of finalized simulations from an interrupted run."""
    if cache_root is None:
        return
    source_raw = harness_root / "data" / "simulations" / run_id / "results.json"
    if not source_raw.is_file():
        return
    try:
        partial = load_json_object(
            source_raw, f"tau2 partial {run_id}", max_bytes=512 * 1024 * 1024
        )
        harvest_arm_rows(cache_root, contract, revision_sha=revision_sha, raw_results=partial)
    except (ContractError, OSError):
        return


def _terminate_process_group(process: subprocess.Popen[bytes]) -> int:
    """Stop one tau2 process tree and wait until no paid child is orphaned."""

    returncode = process.poll()
    if returncode is not None:
        return returncode
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return process.wait()
    try:
        return process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        return process.wait()


def _infrastructure_abort_snapshot(
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    raw_sha256: str,
) -> dict[str, Any]:
    """Bind a fail-fast partial artifact to the frozen measurement identity."""

    revision_field = "baseline_sha" if arm == "baseline" else "candidate_sha"
    revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    return {
        "schema": SNAPSHOT_SCHEMA,
        "experiment_contract_id": contract.contract_id,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_pack_sha256": contract.task_pack_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "arm": arm,
        revision_field: revision,
        "raw_artifact_sha256": raw_sha256,
        "assay_config": json.loads(json.dumps(contract.assay_config)),
        "execution_status": "invalid",
        "failure_class": _INFRASTRUCTURE_FAILURE,
    }


def _run_tau2_command(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    results_path: Path,
) -> tuple[subprocess.CompletedProcess[bytes], bool]:
    """Run tau2 while polling finalized rows for terminal contamination."""

    process = subprocess.Popen(  # noqa: S603 - frozen evaluator derives complete argv
        command,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    previous_handlers: dict[signal.Signals, Any] = {}

    def stop_on_signal(signum: int, _frame: object) -> None:
        _terminate_process_group(process)
        raise SystemExit(128 + signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, stop_on_signal)
    deadline = time.monotonic() + timeout
    try:
        while True:
            returncode = process.poll()
            if returncode is not None:
                return subprocess.CompletedProcess(command, returncode), False
            if results_path.is_file():
                try:
                    partial = load_json_object(
                        results_path,
                        "incremental tau2 results",
                        max_bytes=512 * 1024 * 1024,
                    )
                    contaminated = tau2_has_infrastructure_contamination(partial)
                except ContractError:
                    # Tau2 replaces this file incrementally. A transient
                    # partial JSON read is retried; the finalized verifier
                    # remains authoritative for malformed output.
                    contaminated = False
                if contaminated:
                    returncode = _terminate_process_group(process)
                    return subprocess.CompletedProcess(command, returncode), True
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                _terminate_process_group(process)
                raise subprocess.TimeoutExpired(command, timeout)
            time.sleep(min(0.25, remaining))
    finally:
        if process.poll() is None:
            _terminate_process_group(process)
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)


def _run_arm(
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    checkout: Path,
    harness_root: Path,
    contract_path: Path,
    output_dir: Path,
    run_id: str,
    timeout: float,
    parent_contract_path: Path | None = None,
) -> tuple[EvidenceEnvelope, Path, ResourceUsage]:
    snapshot_dir = output_dir / "snapshots"
    snapshot_dir.mkdir(exist_ok=True)
    environment = dict(os.environ)
    state_root = output_dir / "state" / arm
    temp_root = output_dir / "tmp" / arm
    state_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "GEODE_STATE_ROOT": str(state_root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(checkout),
            "TMPDIR": str(temp_root),
        }
    )
    revision_sha = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    cache_root_value = os.environ.get("CRUCIBLE_ROW_CACHE_ROOT")
    if cache_root_value and contract.stage != "train":
        # Row reuse would freeze a past noise realisation into a sealed
        # one-shot; sealed measurements stay fresh. Refusing (instead of
        # raising) protects the already-burned attempt, and the marker file
        # keeps the override observable in the arm's state directory.
        (state_root / "row-cache-disabled.json").write_text(
            json.dumps(
                {
                    "schema": "crucible.row-cache-disabled.v1",
                    "reason": "row cache is train-only",
                    "stage": contract.stage,
                }
            ),
            encoding="utf-8",
        )
        cache_root_value = None
    cache_root = Path(cache_root_value).resolve() if cache_root_value else None
    salvaged: dict[tuple[str, int], Mapping[str, Any]] = {}
    salvage_context: Mapping[str, Any] | None = None
    if cache_root is not None:
        salvaged = selected_expected_rows(
            contract,
            cached_rows(cache_root, contract, revision_sha=revision_sha),
        )
        salvage_context = cached_context(cache_root, contract, revision_sha=revision_sha)
    unfinished_ids = (
        missing_task_ids(contract, salvaged)
        if salvage_context is not None
        else list(contract.task_ids)
    )
    raw_path = output_dir / f"{arm}.raw.json"
    elapsed = 0.0
    runner_returncode = 0
    marginal_usage = ResourceUsage(0.0, 0, 0, 0.0)
    if salvage_context is not None and not unfinished_ids:
        # Every expected row is identity-proven in the cache: rebuild the
        # results file without spending a single conversation.
        raw = merge_results(salvage_context, salvaged)
        write_exclusive_json(raw_path, raw)
        snapshot = snapshot_dir / f"{run_id}.snapshot.json"
        write_exclusive_json(
            snapshot,
            synthesized_snapshot(
                contract, arm=arm, raw_sha256=_file_sha256(raw_path, f"{arm} rebuilt raw")
            ),
        )
    else:
        command = tau2_command(
            contract,
            arm=arm,
            checkout=checkout,
            harness_root=harness_root,
            contract_path=contract_path,
            snapshot_dir=snapshot_dir,
            run_id=run_id,
            parent_contract_path=parent_contract_path,
            task_ids_override=(
                unfinished_ids
                if salvage_context is not None and len(unfinished_ids) < len(contract.task_ids)
                else None
            ),
        )
        source_raw = harness_root / "data" / "simulations" / run_id / "results.json"
        started = time.monotonic()
        try:
            completed, infrastructure_abort = _run_tau2_command(
                command,
                cwd=checkout,
                env=environment,
                timeout=timeout,
                results_path=source_raw,
            )
        except subprocess.TimeoutExpired as exc:
            _harvest_partial(cache_root, contract, revision_sha, harness_root, run_id)
            raise TimeoutError(f"tau2 {arm} arm timed out") from exc
        elapsed = time.monotonic() - started
        runner_returncode = completed.returncode
        snapshot = snapshot_dir / f"{run_id}.snapshot.json"
        if not source_raw.is_file() or (not infrastructure_abort and not snapshot.is_file()):
            # tau2 finalizes each simulation into results.json incrementally;
            # an interrupted arm still donates its completed rows (r23: 18
            # finished executions were discarded for want of this line).
            _harvest_partial(cache_root, contract, revision_sha, harness_root, run_id)
            if completed.returncode:
                raise Tau2InfrastructureError(
                    f"tau2 {arm} arm exited with status {completed.returncode}"
                )
            raise Tau2InfrastructureError(
                f"tau2 {arm} arm did not produce finalized raw and snapshot files"
            )
        fresh = load_json_object(source_raw, f"tau2 {arm} raw", max_bytes=512 * 1024 * 1024)
        fresh_usage = tau2_resource_usage_floor(fresh)
        marginal_usage = ResourceUsage(
            wall_seconds=max(elapsed, fresh_usage.wall_seconds),
            calls=fresh_usage.calls,
            tokens=fresh_usage.tokens,
            cost_usd=fresh_usage.cost_usd,
        )
        if salvage_context is not None and salvaged:
            fresh_rows = _index_simulations(fresh, f"tau2 {arm} partial-cache raw")
            # A task with one missing trial must be re-run as a whole because
            # tau2 accepts task IDs rather than individual pairs.  Preserve
            # any identity-proven original trial instead of silently replacing
            # it with the repeated realization.
            raw = merge_results(salvage_context, {**fresh_rows, **salvaged})
            write_exclusive_json(raw_path, raw)
            snapshot = snapshot_dir / f"{run_id}.merged.snapshot.json"
            write_exclusive_json(
                snapshot,
                synthesized_snapshot(
                    contract, arm=arm, raw_sha256=_file_sha256(raw_path, f"{arm} rebuilt raw")
                ),
            )
        else:
            shutil.copyfile(source_raw, raw_path)
        if infrastructure_abort:
            snapshot = snapshot_dir / f"{run_id}.aborted.snapshot.json"
            write_exclusive_json(
                snapshot,
                _infrastructure_abort_snapshot(
                    contract,
                    arm=arm,
                    raw_sha256=_file_sha256(raw_path, f"{arm} aborted raw"),
                ),
            )
        if cache_root is not None:
            harvest_arm_rows(cache_root, contract, revision_sha=revision_sha, raw_results=fresh)
    raw = load_json_object(raw_path, f"tau2 {arm} raw", max_bytes=512 * 1024 * 1024)
    observed_usage = tau2_resource_usage_floor(raw)
    arm_usage = ResourceUsage(
        wall_seconds=max(elapsed, observed_usage.wall_seconds),
        calls=observed_usage.calls,
        tokens=observed_usage.tokens,
        cost_usd=observed_usage.cost_usd,
    )
    evidence = normalize_tau2_results(
        contract,
        arm=arm,
        results_path=raw_path,
        snapshot_path=snapshot,
        usage=arm_usage,
        checks_by_pair=tau2_trace_checks(raw),
    )
    evidence_path = output_dir / f"{arm}.evidence.json"
    write_exclusive_json(evidence_path, evidence.to_dict())
    if runner_returncode and evidence.execution_status != "invalid":
        raise Tau2InfrastructureError(f"tau2 {arm} arm exited with status {runner_returncode}")
    return evidence, raw_path, marginal_usage


def _run_arm_with_deadline(
    deadline: SharedRuntimeDeadline,
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    checkout: Path,
    harness_root: Path,
    contract_path: Path,
    output_dir: Path,
    run_id: str,
    parent_contract_path: Path | None = None,
) -> tuple[EvidenceEnvelope, Path, ResourceUsage]:
    """Run one arm against the actual remainder of the shared experiment wall."""

    timer = deadline.begin_arm(arm)
    try:
        result = _run_arm(
            contract,
            arm=arm,
            checkout=checkout,
            harness_root=harness_root,
            contract_path=contract_path,
            output_dir=output_dir,
            run_id=run_id,
            timeout=timer.allocated_wall_seconds,
            parent_contract_path=parent_contract_path,
        )
    except TimeoutError:
        deadline.finish_arm(timer, "right_censored")
        raise
    except Exception:
        deadline.finish_arm(timer, "invalid")
        raise
    deadline.finish_arm(timer, "invalid" if result[0].execution_status == "invalid" else "complete")
    return result


def _write_skipped_arm(
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    output_dir: Path,
    trigger: EvidenceEnvelope,
) -> tuple[EvidenceEnvelope, Path, ResourceUsage]:
    """Attest that one arm was intentionally skipped after paired infrastructure failure."""

    if trigger.execution_status != "invalid":
        raise ContractError("a skipped arm requires invalid triggering evidence")
    revision_sha = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    raw_path = output_dir / f"{arm}.raw.json"
    write_exclusive_json(
        raw_path,
        {
            "schema": _SKIPPED_ARM_SCHEMA,
            "contract_id": contract.contract_id,
            "arm": arm,
            "revision_sha": revision_sha,
            "status": "skipped",
            "reason": "paired_infrastructure_failure",
            "triggering_arm": trigger.arm,
            "triggering_evidence_id": trigger.evidence_id,
            "triggering_failure_class": trigger.failure_class,
        },
    )
    evidence = EvidenceEnvelope.from_mapping(
        {
            "schema": "crucible.evidence.v3",
            "contract_id": contract.contract_id,
            "arm": arm,
            "revision_sha": revision_sha,
            "evaluator_sha256": contract.evaluator_sha256,
            "harness_sha256": contract.harness_sha256,
            "task_pack_sha256": contract.task_pack_sha256,
            "assay_config_sha256": contract.assay_config_sha256,
            "raw_artifact_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "execution_status": "invalid",
            "failure_class": _SKIPPED_ARM_FAILURE,
            "usage": ResourceUsage(0.0, 0, 0, 0.0).to_dict(),
            "rows": [
                {
                    "task_id": task_id,
                    "trial": trial,
                    "status": "infrastructure_error",
                    "termination_reason": _SKIPPED_ARM_FAILURE,
                    "failure_class": _SKIPPED_ARM_FAILURE,
                    "metrics": {},
                    "checks": {},
                }
                for task_id, trial in expected_pairs(contract)
            ],
        }
    )
    write_exclusive_json(output_dir / f"{arm}.evidence.json", evidence.to_dict())
    return evidence, raw_path, ResourceUsage(0.0, 0, 0, 0.0)


def _write_screened_arm(
    contract: ExperimentContract,
    *,
    output_dir: Path,
    baseline: EvidenceEnvelope,
    reachability: PromotionReachability,
) -> tuple[EvidenceEnvelope, Path, ResourceUsage]:
    """Attest a zero-call candidate arm whose metric ceiling cannot train-KEEP."""

    if baseline.execution_status != "complete" or reachability.reachable:
        raise ContractError("a screened arm requires a complete unreachable baseline")
    raw_path = output_dir / "candidate.raw.json"
    write_exclusive_json(
        raw_path,
        {
            "schema": _SCREENED_ARM_SCHEMA,
            "contract_id": contract.contract_id,
            "arm": "candidate",
            "revision_sha": contract.candidate_sha,
            "status": "screened",
            "reason": SCREENING_FAILURE,
            "triggering_evidence_id": baseline.evidence_id,
            "reachability": reachability.to_dict(),
        },
    )
    evidence = EvidenceEnvelope.from_mapping(
        {
            "schema": "crucible.evidence.v3",
            "contract_id": contract.contract_id,
            "arm": "candidate",
            "revision_sha": contract.candidate_sha,
            "evaluator_sha256": contract.evaluator_sha256,
            "harness_sha256": contract.harness_sha256,
            "task_pack_sha256": contract.task_pack_sha256,
            "assay_config_sha256": contract.assay_config_sha256,
            "raw_artifact_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "execution_status": "invalid",
            "failure_class": SCREENING_FAILURE,
            "usage": ResourceUsage(0.0, 0, 0, 0.0).to_dict(),
            "rows": [
                {
                    "task_id": task_id,
                    "trial": trial,
                    "status": "infrastructure_error",
                    "termination_reason": SCREENING_FAILURE,
                    "failure_class": SCREENING_FAILURE,
                    "metrics": {},
                    "checks": {},
                }
                for task_id, trial in expected_pairs(contract)
            ],
        }
    )
    write_exclusive_json(output_dir / "candidate.evidence.json", evidence.to_dict())
    return evidence, raw_path, ResourceUsage(0.0, 0, 0, 0.0)


def tau2_failure_feedback(
    contract: ExperimentContract,
    candidate: EvidenceEnvelope,
    raw: Mapping[str, Any],
) -> FailureFeedback | None:
    """Project failed tau2 rows onto task-independent closed failure codes."""

    if candidate.execution_status != "complete":
        return None
    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        raise ContractError("tau2 feedback requires simulations")
    by_pair: dict[tuple[str, int], Mapping[str, Any]] = {}
    for index, value in enumerate(simulations):
        simulation_row = _mapping(value, f"tau2.simulations[{index}]")
        task_id = _string(simulation_row.get("task_id"), f"tau2.simulations[{index}].task_id")
        trial = simulation_row.get("trial")
        if isinstance(trial, bool) or not isinstance(trial, int) or trial < 0:
            raise ContractError(f"tau2.simulations[{index}].trial must be non-negative")
        pair = (task_id, trial)
        if pair in by_pair:
            raise ContractError("tau2 feedback simulations contain duplicate pairs")
        by_pair[pair] = simulation_row

    failed_rows = [
        row
        for row in candidate.rows
        if (metric := row.metric(contract.promotion.primary_metric)) is None or metric < 1.0
    ]
    if not failed_rows:
        return None
    codes = {"workflow_completion"}
    for row in failed_rows:
        if row.termination_reason not in TAU2_ADAPTER.normal_completion_reasons:
            codes.add("termination")
        if row.check("safety") is False:
            codes.add("safety")
        if row.check("tool_contract") is False:
            codes.add("tool_contract")
        matched = by_pair.get(row.pair_id)
        if matched is None:
            raise ContractError("tau2 feedback requires exact simulation coverage")
        reward_info = matched.get("reward_info")
        if not isinstance(reward_info, Mapping):
            continue
        checks: list[object] = []
        for field in ("action_checks", "env_assertions"):
            values = reward_info.get(field)
            if isinstance(values, list):
                checks.extend(values)
        for value in checks:
            if not isinstance(value, Mapping):
                continue
            unmatched = value.get("action_match") is False or value.get("met") is False
            if not unmatched:
                continue
            detail = value.get("action") or value.get("env_assertion")
            if not isinstance(detail, Mapping):
                continue
            requestor = detail.get("requestor") or detail.get("env_type")
            failure_code = TAU2_ADAPTER.feedback_code_for_requestor(requestor)
            if failure_code is not None:
                codes.add(failure_code)
    failed_task_ids = tuple(dict.fromkeys(row.task_id for row in failed_rows))
    return FailureFeedback(tuple(sorted(codes)), failed_task_ids)


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _evaluation_wall_seconds(
    contract: ExperimentContract,
    supervisor_remaining: object,
) -> float:
    """Intersect the frozen experiment wall with the live outer remainder."""

    if isinstance(supervisor_remaining, bool) or not isinstance(
        supervisor_remaining, (str, int, float)
    ):
        raise ContractError("evaluator requires a valid actual remaining wall budget")
    try:
        remaining = float(supervisor_remaining)
    except ValueError as exc:
        raise ContractError("evaluator requires a valid actual remaining wall budget") from exc
    wall = min(remaining, contract.budget.max_wall_seconds)
    if not math.isfinite(wall) or wall <= 0.0:
        raise ContractError("evaluator has no remaining wall budget")
    return wall


def _train_evaluation_response(
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    output_dir: Path,
    baseline_raw: Path,
    candidate_raw: Path,
    runtime_receipt: Path,
    marginal_usage: ResourceUsage,
    feedback: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "crucible.train-evaluation.v4",
        "attempt_id": request["attempt_id"],
        "request_id": request["request_id"],
        "proposal_id": candidate["proposal_id"],
        "baseline": _relative(output_dir / "baseline.evidence.json", output_dir),
        "candidate": _relative(output_dir / "candidate.evidence.json", output_dir),
        "baseline_raw": _relative(baseline_raw, output_dir),
        "candidate_raw": _relative(candidate_raw, output_dir),
        "runtime_receipt": _relative(runtime_receipt, output_dir),
        "marginal_usage": marginal_usage.to_dict(),
    }
    if feedback is not None:
        payload["feedback"] = dict(feedback)
    return payload


@contextmanager
def _paired_checkouts(
    repository: Path,
    *,
    baseline_sha: str,
    candidate_sha: str,
    deadline: SharedRuntimeDeadline | None = None,
) -> Iterator[tuple[Path, Path]]:
    root = Path(tempfile.mkdtemp(prefix="crucible-tau2-sealed-"))
    checkouts = (
        (root / "baseline", baseline_sha),
        (root / "candidate", candidate_sha),
    )
    added: list[Path] = []
    try:
        for checkout, revision in checkouts:
            _git(repository, "worktree", "add", "--detach", str(checkout), revision)
            added.append(checkout)
        yield checkouts[0][0], checkouts[1][0]
    finally:
        cleanup_started = time.monotonic()
        executable = shutil.which("git")
        if executable is not None:
            for checkout in reversed(added):
                subprocess.run(  # noqa: S603 - fixed git executable, cleanup-only argv
                    [executable, "worktree", "remove", "--force", str(checkout)],
                    cwd=repository,
                    check=False,
                    capture_output=True,
                )
        shutil.rmtree(root, ignore_errors=True)
        if deadline is not None:
            deadline.record_cleanup("paired_checkout_remove", cleanup_started)


class Tau2SealedEvaluator:
    """Run the frozen test pack once through the same paired tau2 machinery."""

    def __init__(
        self,
        *,
        repository: Path,
        harness_root: Path,
        train_contract_path: Path,
    ) -> None:
        self.repository = repository.resolve()
        self.harness_root = harness_root.resolve()
        self.train_contract_path = train_contract_path.resolve()

    def evaluate(
        self,
        plan: SealedPlan,
        contract: ExperimentContract,
        *,
        attempt_number: int,
        evaluation_dir: Path,
        timeout: float,
    ) -> Path:
        parent = load_contract(self.train_contract_path)
        validate_test_parent(contract, parent)
        test_contract_path = evaluation_dir / "test-contract.json"
        parent_contract_path = evaluation_dir / "train-contract.json"
        write_exclusive_json(test_contract_path, contract.to_dict())
        write_exclusive_json(parent_contract_path, parent.to_dict())
        deadline = SharedRuntimeDeadline(contract, _evaluation_wall_seconds(contract, timeout))
        runtime_receipt = evaluation_dir / "runtime.receipt.json"
        try:
            with _paired_checkouts(
                self.repository,
                baseline_sha=plan.baseline_sha,
                candidate_sha=plan.candidate_sha,
                deadline=deadline,
            ) as (baseline_checkout, candidate_checkout):
                baseline, baseline_raw, _baseline_marginal = _run_arm_with_deadline(
                    deadline,
                    contract,
                    arm="baseline",
                    checkout=baseline_checkout,
                    harness_root=self.harness_root,
                    contract_path=test_contract_path,
                    parent_contract_path=parent_contract_path,
                    output_dir=evaluation_dir,
                    run_id=f"crucible-test-{plan.plan_id[:16]}-{attempt_number}-baseline",
                )
                if baseline.execution_status != "complete":
                    raise Tau2InfrastructureError(
                        f"tau2 baseline arm is invalid: {baseline.failure_class}"
                    )
                candidate, candidate_raw, _candidate_marginal = _run_arm_with_deadline(
                    deadline,
                    contract,
                    arm="candidate",
                    checkout=candidate_checkout,
                    harness_root=self.harness_root,
                    contract_path=test_contract_path,
                    parent_contract_path=parent_contract_path,
                    output_dir=evaluation_dir,
                    run_id=f"crucible-test-{plan.plan_id[:16]}-{attempt_number}-candidate",
                )
                if candidate.execution_status != "complete":
                    raise Tau2InfrastructureError(
                        f"tau2 candidate arm is invalid: {candidate.failure_class}"
                    )
        except TimeoutError:
            deadline.write(
                runtime_receipt,
                "right_censored",
                censoring_reason="shared_experiment_deadline",
            )
            raise
        except Tau2InfrastructureError as exc:
            deadline.write(runtime_receipt, "infrastructure_invalid")
            raise SealedInfrastructureError("tau2_infrastructure_error") from exc
        except Exception:
            deadline.write(runtime_receipt, "operator_invalid")
            raise
        deadline.write(runtime_receipt, "complete")
        response_path = evaluation_dir / "response.json"
        write_exclusive_json(
            response_path,
            {
                "schema": SEALED_RESPONSE_SCHEMA,
                "plan_id": plan.plan_id,
                "contract_id": contract.contract_id,
                "attempt_number": attempt_number,
                "baseline": _relative(evaluation_dir / "baseline.evidence.json", evaluation_dir),
                "candidate": _relative(evaluation_dir / "candidate.evidence.json", evaluation_dir),
                "baseline_raw": _relative(baseline_raw, evaluation_dir),
                "candidate_raw": _relative(candidate_raw, evaluation_dir),
                "runtime_receipt": _relative(runtime_receipt, evaluation_dir),
            },
        )
        return response_path


def run_command_evaluator() -> int:
    """Implement ``crucible.train-evaluation.v4`` for CommandEvaluator."""

    request_path = Path(os.environ["CRUCIBLE_PROPOSAL_REQUEST"])
    candidate_path = Path(os.environ["CRUCIBLE_CANDIDATE"])
    contract_path = Path(os.environ["CRUCIBLE_CONTRACT"])
    response_path = Path(os.environ["CRUCIBLE_EVALUATION_OUTPUT"])
    request = load_json_object(request_path, "proposal request")
    candidate_row = load_json_object(candidate_path, "candidate proposal")
    contract = load_contract(contract_path)
    CandidateProposal.load(candidate_path, request=_request_for_candidate(request))
    harness_root = Path(os.environ["CRUCIBLE_TAU2_HARNESS_ROOT"]).resolve()
    candidate_checkout = Path.cwd().resolve()
    output_dir = response_path.parent.resolve()
    baseline_checkout = Path(os.environ["TMPDIR"]).resolve() / "baseline-checkout"
    timeout = _evaluation_wall_seconds(
        contract,
        os.environ.get("CRUCIBLE_EVALUATION_WALL_SECONDS"),
    )
    deadline = SharedRuntimeDeadline(contract, timeout)
    runtime_receipt = output_dir / "runtime.receipt.json"
    runtime_status: Literal[
        "complete", "right_censored", "infrastructure_invalid", "operator_invalid"
    ] = "operator_invalid"
    censoring_reason: str | None = None
    try:
        _git(
            candidate_checkout,
            "worktree",
            "add",
            "--detach",
            str(baseline_checkout),
            contract.baseline_sha,
        )
        try:
            baseline, baseline_raw, baseline_marginal = _run_arm_with_deadline(
                deadline,
                contract,
                arm="baseline",
                checkout=baseline_checkout,
                harness_root=harness_root,
                contract_path=contract_path,
                output_dir=output_dir,
                run_id=f"crucible-{contract.stage}-{request['attempt_id']}-baseline",
            )
            if baseline.execution_status == "invalid":
                candidate, candidate_raw, candidate_marginal = _write_skipped_arm(
                    contract,
                    arm="candidate",
                    output_dir=output_dir,
                    trigger=baseline,
                )
                deadline.record_synthetic_arm("candidate", "skipped")
            else:
                reachability = promotion_reachability(
                    contract,
                    baseline,
                    metric_ceiling=TAU2_ADAPTER.metric_bound(contract.promotion.primary_metric)[1],
                )
                if contract.stage == "train" and not reachability.reachable:
                    candidate, candidate_raw, candidate_marginal = _write_screened_arm(
                        contract,
                        output_dir=output_dir,
                        baseline=baseline,
                        reachability=reachability,
                    )
                    deadline.record_synthetic_arm("candidate", "screened")
                else:
                    candidate, candidate_raw, candidate_marginal = _run_arm_with_deadline(
                        deadline,
                        contract,
                        arm="candidate",
                        checkout=candidate_checkout,
                        harness_root=harness_root,
                        contract_path=contract_path,
                        output_dir=output_dir,
                        run_id=f"crucible-{contract.stage}-{request['attempt_id']}-candidate",
                    )
        finally:
            cleanup_started = time.monotonic()
            executable = shutil.which("git")
            if executable is not None:
                subprocess.run(  # noqa: S603 - fixed git executable, cleanup-only argv
                    [executable, "worktree", "remove", "--force", str(baseline_checkout)],
                    cwd=candidate_checkout,
                    check=False,
                    capture_output=True,
                )
            deadline.record_cleanup("baseline_checkout_remove", cleanup_started)

        feedback = None
        if baseline.execution_status == candidate.execution_status == "complete":
            candidate_raw_payload = load_json_object(
                candidate_raw,
                "candidate raw",
                max_bytes=64 * 1024 * 1024,
            )
            projected = tau2_failure_feedback(contract, candidate, candidate_raw_payload)
            feedback = projected.to_dict() if projected is not None else None
        runtime_status = "complete"
        if baseline.execution_status == "invalid" or (
            candidate.execution_status == "invalid" and candidate.failure_class != SCREENING_FAILURE
        ):
            runtime_status = "infrastructure_invalid"
        write_exclusive_json(
            response_path,
            _train_evaluation_response(
                request,
                candidate_row,
                output_dir=output_dir,
                baseline_raw=baseline_raw,
                candidate_raw=candidate_raw,
                runtime_receipt=runtime_receipt,
                marginal_usage=baseline_marginal + candidate_marginal,
                feedback=feedback,
            ),
        )
    except TimeoutError:
        runtime_status = "right_censored"
        censoring_reason = "shared_experiment_deadline"
        raise
    except Tau2InfrastructureError:
        runtime_status = "infrastructure_invalid"
        raise
    finally:
        deadline.write(
            runtime_receipt,
            runtime_status,
            censoring_reason=censoring_reason,
        )
    return 0


def _request_for_candidate(row: Mapping[str, Any]) -> Any:
    """Reconstruct only the request identity needed by CandidateProposal.load."""

    from .supervisor import ProposalRequest

    return ProposalRequest(
        campaign_id=str(row["campaign_id"]),
        config_id=str(row["config_id"]),
        attempt_id=str(row["attempt_id"]),
        iteration=int(row["iteration"]),
        parent_sha=str(row["parent_sha"]),
        allowed_surfaces=tuple(str(item) for item in row["allowed_surfaces"]),
        attempt_dir=Path("."),
        worktree=Path("."),
        producer_dir=Path("."),
        feedback=row.get("feedback"),
        remaining_budget=_mapping(row.get("remaining_budget"), "remaining_budget"),
        objective=(str(row["objective"]) if isinstance(row.get("objective"), str) else None),
    )


def evaluator_sha256(checkout: Path, paths: Sequence[str]) -> str:
    """Small public helper for campaign configuration scripts."""

    from .contract import content_sha256

    return content_sha256(checkout, paths)


__all__ = [
    "Tau2InfrastructureError",
    "Tau2SealedEvaluator",
    "evaluator_sha256",
    "run_command_evaluator",
    "tau2_command",
    "tau2_trace_checks",
]
