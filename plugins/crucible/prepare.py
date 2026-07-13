"""One-command campaign preparation — Crucible's centralized ``prepare.py``.

autoresearch prepares its measurement apparatus in one place (``prepare.py``
builds the corpus and the frozen ``evaluate_bpb`` shard once). Crucible's
apparatus had fragmented into hand steps — curate a pack, compute three
hashes against the right revisions, assemble a train plan, hand-write a
supervisor config — and the 2026-07-12 live validation paid for that with
three launch-time fail-louds that were all *preparation* mistakes (feedback
outside the pack, a reused campaign ref, a mis-sized budget).

``prepare_campaign`` reassembles the apparatus deterministically from one
declarative spec and then round-trip validates its output through the SAME
``SupervisorConfig.load`` the loop uses, so every launch-time contract check
moves to prepare time. It only *generates* configs — the loop CLI, the config
schema, and every validator stay untouched, and hand-written configs remain
first-class.

Hashes are never inherited from the template: the evaluator hash is
recomputed over a pristine temporary checkout of the campaign head, the
harness hash over the actual harness tree, and the pack hash from the pack
file's verified task units.

The spec may carry a ``curation`` block instead of a ``pack_file`` — the pack
is then curated as part of preparation — and callers may pass the remaining
window budget to fold the launch-capacity verdict (``crucible.preflight``)
into the report. Sealed plans keep their own promotion-time lifecycle and are
deliberately out of scope here. An optional runtime audit admits a
digest-matched pilot bootstrap, a frozen bounded-row contract ceiling, or an
uncensored fixed experiment wall before the config is emitted.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from . import TRIAD_PREPARE
from .artifacts import load_json_object, write_exclusive_json
from .contract import (
    Budget,
    ContractError,
    PromotionRule,
    TaskUnit,
    content_sha256,
    task_pack_sha256,
    tracked_tree_sha256,
)
from .curation import curate_tau2_pack
from .power import audit_family_power
from .preflight import campaign_token_cap, completed_campaign_tokens, decide
from .runtime_budget import audit_runtime_budget
from .supervisor import LoopLimits, SupervisorConfig, SupervisorError

SPEC_SCHEMA = "crucible.campaign-spec.v1"
PREPARE_PROVENANCE_SCHEMA = "crucible.prepare-provenance.v1"
PREPARE_REPORT_SCHEMA = "crucible.prepare-report.v1"

# Spec keys copied verbatim onto the supervisor config when present.
_CONFIG_OVERRIDES = (
    "allowed_surfaces",
    "producer_command",
    "producer_environment",
    "evaluator_entrypoint",
    "evaluator_environment",
    "repository",
    "harness_root",
    "limits",
    "initial_feedback",
    "search",
)
# Spec keys applied inside train_plan when present.
_PLAN_OVERRIDES = ("assay_config", "promotion", "budget", "evaluator_paths", "trials_per_task")


def _git(cwd: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ContractError("git is required to prepare a campaign")
    result = subprocess.run(  # noqa: S603 - fixed git executable and argv
        [executable, *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ContractError(f"git {' '.join(args)} failed: {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def load_pack(path: Path) -> tuple[tuple[TaskUnit, ...], int]:
    """Load a ``crucible.task-pack.v1`` file and verify its self-declared hash."""
    raw = load_json_object(path, "task pack")
    if raw.get("schema") != "crucible.task-pack.v1":
        raise ContractError(f"task pack {path} has an unsupported schema")
    rows = raw.get("tasks")
    if not isinstance(rows, list) or not rows:
        raise ContractError(f"task pack {path} tasks must be a non-empty list")
    units = tuple(
        TaskUnit.from_mapping(value, field=f"task pack tasks[{index}]")
        for index, value in enumerate(rows)
    )
    trials = raw.get("trials_per_task")
    if isinstance(trials, bool) or not isinstance(trials, int) or trials <= 0:
        raise ContractError(f"task pack {path} trials_per_task must be positive")
    if raw.get("task_pack_sha256") != task_pack_sha256(units, trials):
        raise ContractError(f"task pack {path} hash does not match its tasks")
    return units, trials


def evaluator_hash_at(repository: Path, head_sha: str, evaluator_paths: Sequence[str]) -> str:
    """Hash the evaluator paths at ``head_sha`` in a pristine throwaway checkout.

    A working tree can carry pycache/untracked residue that would poison the
    hash; the measurement checkout at run time is pristine, so the prepared
    hash must be too.
    """
    scratch = Path(tempfile.mkdtemp(prefix="crucible-prepare-"))
    checkout = scratch / "head"
    try:
        _git(repository, "worktree", "add", "--detach", str(checkout), head_sha)
        try:
            return content_sha256(checkout, list(evaluator_paths))
        finally:
            _git(repository, "worktree", "remove", "--force", str(checkout))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _merged(template: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = json.loads(json.dumps(dict(template)))
    config.pop("config_id", None)
    config.pop("prepared_by", None)
    for key in _CONFIG_OVERRIDES:
        if key in spec:
            if spec[key] is None:
                config.pop(key, None)
            else:
                config[key] = json.loads(json.dumps(spec[key]))
    plan = dict(config.get("train_plan") or {})
    for key in _PLAN_OVERRIDES:
        if key in spec:
            plan[key] = json.loads(json.dumps(spec[key]))
    config["train_plan"] = plan
    return config


_CURATION_FIELDS = (
    "tasks_file",
    "split_file",
    "split_name",
    "domain",
    "purpose",
    "salt",
    "fault_tokens",
    "take",
    "maximum_per_intent",
    "maximum_per_persona",
    "trials_per_task",
)


def _curate_pack(curation: Mapping[str, Any], *, prepare_dir: Path) -> Path:
    """Curate the frozen pack as part of preparation (no invented defaults)."""
    for field in _CURATION_FIELDS:
        if curation.get(field) in (None, ""):
            raise ContractError(f"curation block requires {field}")
    prepare_dir.mkdir(parents=True, exist_ok=True)
    pack_output = prepare_dir / "pack.json"
    if pack_output.exists():
        raise ContractError(f"curated pack already exists: {pack_output}")
    curate_tau2_pack(
        tasks_path=Path(str(curation["tasks_file"])).expanduser(),
        split_path=Path(str(curation["split_file"])).expanduser(),
        split_name=str(curation["split_name"]),
        domain=str(curation["domain"]),
        purpose=str(curation["purpose"]),
        salt=str(curation["salt"]),
        fault_tokens=int(curation["fault_tokens"]),
        take=int(curation["take"]),
        maximum_per_intent=int(curation["maximum_per_intent"]),
        maximum_per_persona=int(curation["maximum_per_persona"]),
        trials_per_task=int(curation["trials_per_task"]),
        exclude_packs=[
            Path(str(entry)).expanduser() for entry in curation.get("exclude_packs", ())
        ],
        selection_output=prepare_dir / "selection.json",
        pack_output=pack_output,
    )
    return pack_output


def prepare_campaign(
    spec_path: Path,
    *,
    output: Path | None = None,
    history_root: Path | None = None,
    remaining_tokens: int | None = None,
) -> dict[str, Any]:
    spec = load_json_object(spec_path, "campaign spec")
    spec_sha256 = sha256(spec_path.read_bytes()).hexdigest()
    if spec.get("schema") != SPEC_SCHEMA:
        raise ContractError(f"campaign spec must use {SPEC_SCHEMA!r}")
    for field in ("campaign_id", "template_config", "head_sha", "state_root"):
        if not spec.get(field):
            raise ContractError(f"campaign spec requires {field}")
    if not spec.get("pack_file") and not isinstance(spec.get("curation"), Mapping):
        raise ContractError("campaign spec requires pack_file or a curation block")
    if spec.get("pack_file") and isinstance(spec.get("curation"), Mapping):
        raise ContractError("campaign spec cannot carry both pack_file and curation")
    if remaining_tokens is not None and remaining_tokens < 0:
        raise ContractError("remaining_tokens must be non-negative")

    campaign_id = str(spec["campaign_id"])
    template = load_json_object(Path(str(spec["template_config"])).expanduser(), "template config")
    config = _merged(template, spec)

    repository = Path(str(config["repository"])).expanduser().resolve()
    harness_root = Path(str(config["harness_root"])).expanduser().resolve()
    head_sha = _git(repository, "rev-parse", "--verify", f"{spec['head_sha']}^{{commit}}")

    plan = config["train_plan"]
    state_dir_root = Path(str(spec["state_root"])).expanduser().resolve() / campaign_id
    if isinstance(spec.get("curation"), Mapping):
        pack_path = _curate_pack(spec["curation"], prepare_dir=state_dir_root / "prepare")
    else:
        pack_path = Path(str(spec["pack_file"])).expanduser()
    units, pack_trials = load_pack(pack_path)
    plan["tasks"] = [unit.to_dict() for unit in units]
    plan["trials_per_task"] = int(spec.get("trials_per_task", pack_trials))
    plan["task_pack_sha256"] = task_pack_sha256(units, plan["trials_per_task"])
    plan["name"] = str(spec.get("plan_name", campaign_id))
    plan["evaluator_sha256"] = evaluator_hash_at(
        repository, head_sha, plan.get("evaluator_paths") or ()
    )
    if _git(harness_root, "status", "--porcelain", "--untracked-files=all"):
        raise ContractError("harness checkout must be clean at prepare time")
    plan["harness_sha256"] = tracked_tree_sha256(harness_root)

    power_report: dict[str, Any] | None = None
    power_report_path: Path | None = None
    power_specification = spec.get("power_audit")
    if power_specification is not None:
        if not isinstance(power_specification, Mapping):
            raise ContractError("campaign spec power_audit must be an object")
        promotion = PromotionRule.from_mapping(plan.get("promotion"))
        power_report = audit_family_power(
            tasks=units,
            trials_per_task=plan["trials_per_task"],
            task_pack_sha256=plan["task_pack_sha256"],
            promotion=promotion,
            specification=power_specification,
            basis_root=spec_path.resolve().parent,
        )
        power_report_path = state_dir_root / "prepare" / "power.json"
        power_report_path.parent.mkdir(parents=True, exist_ok=True)
        write_exclusive_json(power_report_path, power_report)
        if not power_report["passes"]:
            failed = next(
                scenario for scenario in power_report["scenarios"] if not scenario["passes"]
            )
            raise ContractError(
                "family power audit did not meet minimum_power: "
                f"{failed['name']} lower95="
                f"{failed['results']['keep_probability_95pct_lower_bound']:.6f}; "
                f"report={power_report_path}"
            )

    runtime_report: dict[str, Any] | None = None
    runtime_report_path: Path | None = None
    runtime_specification = spec.get("runtime_audit")
    if runtime_specification is not None:
        if not isinstance(runtime_specification, Mapping):
            raise ContractError("campaign spec runtime_audit must be an object")
        budget = plan.get("budget")
        limits = config.get("limits")
        if not isinstance(budget, Mapping):
            raise ContractError("train_plan budget must be an object")
        if not isinstance(limits, Mapping):
            raise ContractError("campaign limits must be an object")
        experiment_budget = Budget.from_mapping(budget)
        campaign_limits = LoopLimits.from_mapping(limits)
        runtime_report = audit_runtime_budget(
            tasks=units,
            trials_per_task=plan["trials_per_task"],
            evaluator_sha256=plan["evaluator_sha256"],
            harness_sha256=plan["harness_sha256"],
            agent_route=str(plan.get("agent_route", "")),
            user_route=str(plan.get("user_route", "")),
            assay_config=plan.get("assay_config") or {},
            configured_experiment_wall_seconds=experiment_budget.max_wall_seconds,
            configured_campaign_wall_seconds=campaign_limits.max_wall_seconds,
            specification=runtime_specification,
            basis_root=spec_path.resolve().parent,
        )
        runtime_report_path = state_dir_root / "prepare" / "runtime.json"
        runtime_report_path.parent.mkdir(parents=True, exist_ok=True)
        write_exclusive_json(runtime_report_path, runtime_report)
        if not runtime_report["passes"]:
            admission = runtime_report["admission"]
            raise ContractError(
                "runtime budget audit rejected configured wall: "
                f"experiment={admission['configured_experiment_wall_seconds']}/"
                f"{admission['required_experiment_wall_seconds']}, "
                f"campaign={admission['configured_campaign_wall_seconds']}/"
                f"{admission['required_campaign_wall_seconds']}; "
                f"report={runtime_report_path}"
            )

    config["campaign_id"] = campaign_id
    provenance: dict[str, Any] = {
        "schema": PREPARE_PROVENANCE_SCHEMA,
        "entry": TRIAD_PREPARE,
        "spec_sha256": spec_sha256,
    }
    if power_report is not None:
        provenance["power_audit_id"] = power_report["power_audit_id"]
    if runtime_report is not None:
        provenance["runtime_audit_id"] = runtime_report["runtime_audit_id"]
    config["prepared_by"] = provenance
    config["initial_search_head_sha"] = head_sha
    state_dir = state_dir_root / "state"
    config["state_dir"] = str(state_dir)

    # Launch-time fail-louds, moved to prepare time (all three were paid for
    # live on 2026-07-12).
    pack_ids = {unit.task_id for unit in units}
    feedback = config.get("initial_feedback")
    if isinstance(feedback, Mapping):
        outside = [
            task_id for task_id in feedback.get("failed_task_ids", ()) if task_id not in pack_ids
        ]
        if outside:
            raise ContractError(
                f"initial_feedback.failed_task_ids are outside the pack: {outside[0]}"
            )
    search_ref = f"refs/crucible/search/{campaign_id}"
    probe = subprocess.run(  # noqa: S603 - fixed git executable and argv
        [shutil.which("git") or "git", "rev-parse", "--verify", "--quiet", search_ref],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    if probe.returncode == 0:
        raise ContractError(f"campaign search ref already exists: {search_ref}")
    if state_dir.exists():
        raise ContractError(f"campaign state_dir already exists: {state_dir}")

    output_path = output or (state_dir.parent / "config.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_exclusive_json(output_path, config)
    try:
        # The workflow-preservation guarantee: the exact loader the loop uses
        # must accept the prepared config, or preparation failed.
        SupervisorConfig.load(output_path)
        window: dict[str, Any] | None = None
        if remaining_tokens is not None:
            history = completed_campaign_tokens(history_root) if history_root else []
            window = dict(
                decide(
                    hard_cap_tokens=campaign_token_cap(output_path),
                    remaining_tokens=remaining_tokens,
                    history_tokens=history,
                )
            )
    except (ContractError, SupervisorError):
        output_path.unlink(missing_ok=True)
        raise
    power_summary: dict[str, Any] | None = None
    if power_report is not None and power_report_path is not None:
        power_summary = {
            "path": str(power_report_path),
            "power_audit_id": power_report["power_audit_id"],
            "passes": power_report["passes"],
            "minimum_power": power_report["minimum_power"],
            "scenarios": [
                {
                    "name": scenario["name"],
                    "keep_probability": scenario["results"]["keep_probability"],
                    "keep_probability_95pct_lower_bound": scenario["results"][
                        "keep_probability_95pct_lower_bound"
                    ],
                    "passes": scenario["passes"],
                }
                for scenario in power_report["scenarios"]
            ],
        }
    runtime_summary: dict[str, Any] | None = None
    if runtime_report is not None and runtime_report_path is not None:
        runtime_summary = {
            "path": str(runtime_report_path),
            "runtime_audit_id": runtime_report["runtime_audit_id"],
            "passes": runtime_report["passes"],
            **runtime_report["admission"],
        }
    return {
        "schema": PREPARE_REPORT_SCHEMA,
        "campaign_id": campaign_id,
        "config_path": str(output_path),
        "pack_file": str(pack_path),
        "spec_sha256": spec_sha256,
        "window": window,
        "state_dir": str(state_dir),
        "initial_search_head_sha": head_sha,
        "task_count": len(units),
        "trials_per_task": plan["trials_per_task"],
        "task_pack_sha256": plan["task_pack_sha256"],
        "evaluator_sha256": plan["evaluator_sha256"],
        "harness_sha256": plan["harness_sha256"],
        "power_audit": power_summary,
        "runtime_audit": runtime_summary,
    }
