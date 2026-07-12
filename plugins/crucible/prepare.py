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
deliberately out of scope here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import load_json_object, write_exclusive_json
from .curation import curate_tau2_pack
from .preflight import campaign_token_cap, completed_campaign_tokens, decide
from .contract import (
    ContractError,
    TaskUnit,
    content_sha256,
    task_pack_sha256,
    tracked_tree_sha256,
)
from .supervisor import SupervisorConfig, SupervisorError

SPEC_SCHEMA = "crucible.campaign-spec.v1"
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
    if spec.get("schema") != SPEC_SCHEMA:
        raise ContractError(f"campaign spec must use {SPEC_SCHEMA!r}")
    for field in ("campaign_id", "template_config", "head_sha", "state_root"):
        if not spec.get(field):
            raise ContractError(f"campaign spec requires {field}")
    if not spec.get("pack_file") and not isinstance(spec.get("curation"), Mapping):
        raise ContractError("campaign spec requires pack_file or a curation block")
    if spec.get("pack_file") and isinstance(spec.get("curation"), Mapping):
        raise ContractError("campaign spec cannot carry both pack_file and curation")

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

    config["campaign_id"] = campaign_id
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
    except (ContractError, SupervisorError):
        output_path.unlink(missing_ok=True)
        raise
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
    return {
        "schema": PREPARE_REPORT_SCHEMA,
        "campaign_id": campaign_id,
        "config_path": str(output_path),
        "pack_file": str(pack_path),
        "window": window,
        "state_dir": str(state_dir),
        "initial_search_head_sha": head_sha,
        "task_count": len(units),
        "trials_per_task": plan["trials_per_task"],
        "task_pack_sha256": plan["task_pack_sha256"],
        "evaluator_sha256": plan["evaluator_sha256"],
        "harness_sha256": plan["harness_sha256"],
    }
