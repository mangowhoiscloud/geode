"""Small identity preflights for verifier-centered Crucible experiments.

The contract freezes one mutation, one task pack, the measurement hashes, and
the declared whole-experiment budget before a live run. Git stores candidate
history; runtime code does not keep a ladder of historical candidate versions.

This module verifies provenance and shard identity. It deliberately does not
score raw results or claim promotion authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

EXPERIMENT_SCHEMA = "crucible.experiment.v2"
SHARD_SCHEMA = "crucible.shard.v2"
REQUIRED_VETOES = frozenset({"budget", "infra_clean", "safety", "task_coverage"})
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised when an experiment cannot provide reproducible evidence."""


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be an object")
    return value


def _require_keys(
    value: Mapping[str, Any],
    *,
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise ContractError(f"{field} is missing keys: {', '.join(missing)}")
    if extra:
        raise ContractError(f"{field} has unknown keys: {', '.join(extra)}")


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _full_git_sha(value: object, field: str) -> str:
    text = _non_empty_string(value, field)
    if not _GIT_SHA_RE.fullmatch(text):
        raise ContractError(f"{field} must be a full 40-character lowercase git SHA")
    return text


def _git_ref(value: object, field: str) -> str:
    text = _non_empty_string(value, field)
    forbidden = ("..", "@{", "\\", " ", "~", "^", ":", "?")
    if (
        not text.startswith("refs/")
        or text.endswith(("/", "."))
        or any(token in text for token in forbidden)
    ):
        raise ContractError(f"{field} must be a full, stable git ref under refs/")
    return text


def _sha256(value: object, field: str) -> str:
    text = _non_empty_string(value, field)
    if not _SHA256_RE.fullmatch(text):
        raise ContractError(f"{field} must be a 64-character lowercase SHA-256")
    return text


def _positive_float(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ContractError(f"{field} must be greater than zero")
    return float(value)


def _finite_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{field} must be a finite number")
    return float(value)


def _non_negative_float(value: object, field: str) -> float:
    number = _finite_float(value, field)
    if number < 0:
        raise ContractError(f"{field} must not be negative")
    return number


def _probability(value: object, field: str) -> float:
    number = _finite_float(value, field)
    if not 0.5 < number < 1.0:
        raise ContractError(f"{field} must be between 0.5 and 1.0")
    return number


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{field} must be a positive integer")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{field} must be a non-empty list")
    rows = tuple(_non_empty_string(item, f"{field}[]") for item in value)
    if len(set(rows)) != len(rows):
        raise ContractError(f"{field} must not contain duplicates")
    return rows


def _normalize_json(value: object, field: str) -> Any:
    """Return a JSON-safe value while rejecting ambiguous or non-finite input."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _finite_float(value, field)
    if isinstance(value, list):
        return [_normalize_json(item, f"{field}[]") for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ContractError(f"{field} keys must be non-empty strings")
            normalized[key] = _normalize_json(item, f"{field}.{key}")
        return normalized
    raise ContractError(f"{field} must contain only JSON values")


def _canonical_json(value: object, field: str) -> str:
    normalized = _normalize_json(value, field)
    if not isinstance(normalized, dict) or not normalized:
        raise ContractError(f"{field} must be a non-empty object")
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _paths_overlap(left: str, right: str) -> bool:
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def task_layout_sha256(task_ids: Sequence[str], trials_per_task: int = 1) -> str:
    """Hash ordered task IDs and trial cardinality, not task-definition bytes."""
    if trials_per_task <= 0:
        raise ContractError("trials_per_task must be a positive integer")
    encoded = json.dumps(
        {"task_ids": list(task_ids), "trials_per_task": trials_per_task},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hash_entry(digest: Any, *, mode: str, relative: str, payload: bytes) -> None:
    for chunk in (mode.encode("ascii"), relative.encode("utf-8"), payload):
        digest.update(len(chunk).to_bytes(8, "big"))
        digest.update(chunk)


def _path_payload(path: Path) -> tuple[str, bytes]:
    info = path.lstat()
    if path.is_symlink():
        return "120000", os.readlink(path).encode("utf-8")
    if not path.is_file():
        raise ContractError(f"frozen path is not a file or symlink: {path}")
    mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
    return mode, path.read_bytes()


def _repository_path(root: Path, relative: str) -> Path:
    relative_path = PurePosixPath(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ContractError(f"path escapes repository root: {relative}")
    candidate = root.joinpath(*relative_path.parts)
    cursor = root
    for part in relative_path.parts[:-1]:
        cursor /= part
        if cursor.is_symlink():
            raise ContractError(f"frozen path traverses a symlink: {relative}")
    return candidate


def content_sha256(root: Path, paths: Sequence[str]) -> str:
    """Hash repository paths, bytes, executable modes, and symlink targets."""
    root = root.resolve()
    files: set[Path] = set()
    for relative in paths:
        candidate = _repository_path(root, relative)
        if candidate.is_symlink() or candidate.is_file():
            files.add(candidate)
            continue
        if not candidate.is_dir():
            raise ContractError(f"frozen path does not exist: {relative}")
        for directory, dirnames, filenames in os.walk(candidate, followlinks=False):
            directory_path = Path(directory)
            for dirname in tuple(dirnames):
                child = directory_path / dirname
                if child.is_symlink():
                    files.add(child)
                    dirnames.remove(dirname)
            for filename in filenames:
                child = directory_path / filename
                child_relative = child.relative_to(root)
                if "__pycache__" in child_relative.parts or child.suffix == ".pyc":
                    continue
                files.add(child)
    if not files:
        raise ContractError("frozen paths do not contain any files")
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        mode, payload = _path_payload(path)
        _hash_entry(digest, mode=mode, relative=relative, payload=payload)
    return digest.hexdigest()


def _reject_symlinks(root: Path, paths: Sequence[str], field: str) -> None:
    """Require executable frozen trees to resolve entirely inside ``root``."""

    root = root.resolve()
    for relative in paths:
        candidate = _repository_path(root, relative)
        if candidate.is_symlink():
            raise ContractError(f"{field} contains a symlink: {relative}")
        if candidate.is_file():
            continue
        if not candidate.is_dir():
            raise ContractError(f"{field} path does not exist: {relative}")
        for directory, dirnames, filenames in os.walk(candidate, followlinks=False):
            directory_path = Path(directory)
            for name in (*dirnames, *filenames):
                child = directory_path / name
                if child.is_symlink():
                    child_relative = child.relative_to(root).as_posix()
                    raise ContractError(f"{field} contains a symlink: {child_relative}")


def _run_git(repo_root: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise ContractError("git executable is required to validate a checkout")
    try:
        return subprocess.run(  # noqa: S603 - fixed executable and argv; no shell
            [git, *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractError(f"cannot inspect git checkout at {repo_root}: {exc}") from exc


def tracked_tree_sha256(repo_root: Path) -> str:
    """Hash index modes, paths, bytes, and symlink targets in a clean checkout."""
    repo_root = repo_root.resolve()
    raw_entries = _run_git(repo_root, "ls-files", "-s", "-z")
    entries = [entry for entry in raw_entries.split("\0") if entry]
    if not entries:
        raise ContractError(f"git checkout has no tracked files: {repo_root}")
    digest = hashlib.sha256()
    for entry in entries:
        try:
            metadata, relative = entry.split("\t", 1)
            index_mode, _object_id, stage = metadata.split(" ", 2)
        except ValueError as exc:
            raise ContractError("cannot parse git index entry") from exc
        if stage != "0":
            raise ContractError(f"git checkout has an unmerged index entry: {relative}")
        path = _repository_path(repo_root, relative)
        actual_mode, payload = _path_payload(path)
        if actual_mode != index_mode:
            raise ContractError(f"tracked file mode differs from git index: {relative}")
        _hash_entry(digest, mode=index_mode, relative=relative, payload=payload)
    return digest.hexdigest()


@dataclass(frozen=True)
class Mutation:
    """The single candidate change under test."""

    surface: str
    hypothesis: str

    @classmethod
    def from_mapping(cls, value: object) -> Mutation:
        row = _require_mapping(value, "mutations[]")
        _require_keys(
            row,
            field="mutations[]",
            required={"hypothesis", "surface"},
        )
        surface = _non_empty_string(row["surface"], "mutations[].surface")
        path = PurePosixPath(surface)
        if path.is_absolute() or ".." in path.parts:
            raise ContractError("mutations[].surface must be a repository-relative path")
        return cls(
            surface=surface,
            hypothesis=_non_empty_string(row["hypothesis"], "mutations[].hypothesis"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"surface": self.surface, "hypothesis": self.hypothesis}


@dataclass(frozen=True)
class Budget:
    """Preregistered limits for the entire baseline/candidate experiment."""

    max_wall_seconds: float
    max_calls: int
    max_tokens: int
    max_cost_usd: float
    max_changed_lines: int

    @classmethod
    def from_mapping(cls, value: object) -> Budget:
        row = _require_mapping(value, "budget")
        _require_keys(
            row,
            field="budget",
            required={
                "max_calls",
                "max_changed_lines",
                "max_cost_usd",
                "max_tokens",
                "max_wall_seconds",
            },
        )
        return cls(
            max_wall_seconds=_positive_float(row["max_wall_seconds"], "budget.max_wall_seconds"),
            max_calls=_positive_int(row["max_calls"], "budget.max_calls"),
            max_tokens=_positive_int(row["max_tokens"], "budget.max_tokens"),
            max_cost_usd=_positive_float(row["max_cost_usd"], "budget.max_cost_usd"),
            max_changed_lines=_positive_int(row["max_changed_lines"], "budget.max_changed_lines"),
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "max_wall_seconds": self.max_wall_seconds,
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "max_changed_lines": self.max_changed_lines,
        }


@dataclass(frozen=True)
class PromotionRule:
    """Preregistered paired comparison for one higher-is-better metric.

    ``v2`` splits the two roles the retired ``v1`` threshold conflated: the
    bootstrap lower bound must merely exceed zero at ``confidence_level``
    (existence of an improvement), while ``materiality_pp`` is the economic
    floor on the point estimate — zero is an honest value for train stages.
    Pilot selection and power analysis remain external evidence; the contract
    freezes the chosen rule but does not pretend to validate a fitted model.
    """

    method: Literal["paired_bootstrap.v2"]
    primary_metric: str
    materiality_pp: float
    minimum_candidate_mean: float
    minimum_tasks: int
    confidence_level: float
    bootstrap_samples: int

    @classmethod
    def from_mapping(cls, value: object) -> PromotionRule:
        row = _require_mapping(value, "promotion")
        _require_keys(
            row,
            field="promotion",
            required={
                "bootstrap_samples",
                "confidence_level",
                "materiality_pp",
                "method",
                "minimum_candidate_mean",
                "minimum_tasks",
                "primary_metric",
            },
        )
        method = _non_empty_string(row["method"], "promotion.method")
        if method != "paired_bootstrap.v2":
            raise ContractError("promotion.method must be 'paired_bootstrap.v2'")
        bootstrap_samples = _positive_int(
            row["bootstrap_samples"],
            "promotion.bootstrap_samples",
        )
        if bootstrap_samples < 1_000:
            raise ContractError("promotion.bootstrap_samples must be at least 1000")
        return cls(
            method="paired_bootstrap.v2",
            primary_metric=_non_empty_string(
                row["primary_metric"],
                "promotion.primary_metric",
            ),
            materiality_pp=_non_negative_float(
                row["materiality_pp"],
                "promotion.materiality_pp",
            ),
            minimum_candidate_mean=_finite_float(
                row["minimum_candidate_mean"],
                "promotion.minimum_candidate_mean",
            ),
            minimum_tasks=_positive_int(row["minimum_tasks"], "promotion.minimum_tasks"),
            confidence_level=_probability(
                row["confidence_level"],
                "promotion.confidence_level",
            ),
            bootstrap_samples=bootstrap_samples,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "primary_metric": self.primary_metric,
            "materiality_pp": self.materiality_pp,
            "minimum_candidate_mean": self.minimum_candidate_mean,
            "minimum_tasks": self.minimum_tasks,
            "confidence_level": self.confidence_level,
            "bootstrap_samples": self.bootstrap_samples,
        }


@dataclass(frozen=True)
class ExperimentContract:
    """Frozen preflight identity for one train or sealed-test comparison."""

    name: str
    stage: Literal["train", "test"]
    champion_ref: str
    baseline_sha: str
    candidate_sha: str
    evaluator_sha256: str
    harness_sha256: str
    task_layout_sha256: str
    agent_route: str
    user_route: str
    task_ids: tuple[str, ...]
    trials_per_task: int
    assay_config_json: str
    mutation: Mutation
    evaluator_paths: tuple[str, ...]
    promotion: PromotionRule
    budget: Budget
    vetoes: tuple[str, ...]
    parent_contract_id: str | None = None

    @classmethod
    def from_mapping(cls, value: object) -> ExperimentContract:
        row = _require_mapping(value, "contract")
        required = {
            "agent_route",
            "assay_config",
            "baseline_sha",
            "budget",
            "candidate_sha",
            "champion_ref",
            "evaluator_paths",
            "evaluator_sha256",
            "harness_sha256",
            "mutations",
            "name",
            "promotion",
            "schema",
            "stage",
            "task_ids",
            "task_layout_sha256",
            "trials_per_task",
            "user_route",
            "vetoes",
        }
        _require_keys(
            row,
            field="contract",
            required=required,
            optional={"contract_id", "parent_contract_id"},
        )
        if row["schema"] != EXPERIMENT_SCHEMA:
            raise ContractError(f"schema must be {EXPERIMENT_SCHEMA!r}")

        stage = _non_empty_string(row["stage"], "stage")
        if stage not in {"train", "test"}:
            raise ContractError("stage must be 'train' or 'test'")

        mutations = row["mutations"]
        if not isinstance(mutations, list) or len(mutations) != 1:
            raise ContractError("mutations must contain exactly one entry")
        mutation = Mutation.from_mapping(mutations[0])
        evaluator_paths = _string_tuple(row["evaluator_paths"], "evaluator_paths")
        for evaluator_path in evaluator_paths:
            path = PurePosixPath(evaluator_path)
            if path.is_absolute() or ".." in path.parts:
                raise ContractError("evaluator_paths must be repository-relative paths")
            if _paths_overlap(mutation.surface, evaluator_path):
                raise ContractError("mutation surface must not overlap the frozen evaluator paths")

        baseline_sha = _full_git_sha(row["baseline_sha"], "baseline_sha")
        candidate_sha = _full_git_sha(row["candidate_sha"], "candidate_sha")
        if baseline_sha == candidate_sha:
            raise ContractError("candidate_sha must differ from baseline_sha")

        vetoes = _string_tuple(row["vetoes"], "vetoes")
        missing_vetoes = sorted(REQUIRED_VETOES - set(vetoes))
        if missing_vetoes:
            raise ContractError("vetoes must include: " + ", ".join(missing_vetoes))

        parent_raw = row.get("parent_contract_id")
        parent_contract_id = (
            _sha256(parent_raw, "parent_contract_id") if parent_raw is not None else None
        )
        if stage == "train" and parent_contract_id is not None:
            raise ContractError("train contracts must not have parent_contract_id")
        if stage == "test" and parent_contract_id is None:
            raise ContractError("test contracts require the frozen train parent_contract_id")

        task_ids = _string_tuple(row["task_ids"], "task_ids")
        trials_per_task = _positive_int(row["trials_per_task"], "trials_per_task")
        supplied_task_layout_sha = _sha256(
            row["task_layout_sha256"],
            "task_layout_sha256",
        )
        if supplied_task_layout_sha != task_layout_sha256(task_ids, trials_per_task):
            raise ContractError(
                "task_layout_sha256 does not match the ordered task_ids and trials_per_task"
            )

        contract = cls(
            name=_non_empty_string(row["name"], "name"),
            stage=cast(Literal["train", "test"], stage),
            champion_ref=_git_ref(row["champion_ref"], "champion_ref"),
            baseline_sha=baseline_sha,
            candidate_sha=candidate_sha,
            evaluator_sha256=_sha256(row["evaluator_sha256"], "evaluator_sha256"),
            harness_sha256=_sha256(row["harness_sha256"], "harness_sha256"),
            task_layout_sha256=supplied_task_layout_sha,
            agent_route=_non_empty_string(row["agent_route"], "agent_route"),
            user_route=_non_empty_string(row["user_route"], "user_route"),
            task_ids=task_ids,
            trials_per_task=trials_per_task,
            assay_config_json=_canonical_json(row["assay_config"], "assay_config"),
            mutation=mutation,
            evaluator_paths=evaluator_paths,
            promotion=PromotionRule.from_mapping(row["promotion"]),
            budget=Budget.from_mapping(row["budget"]),
            vetoes=vetoes,
            parent_contract_id=parent_contract_id,
        )
        supplied_id = row.get("contract_id")
        if supplied_id is not None and _sha256(supplied_id, "contract_id") != contract.contract_id:
            raise ContractError("contract_id does not match the canonical contract payload")
        return contract

    def canonical_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": EXPERIMENT_SCHEMA,
            "name": self.name,
            "stage": self.stage,
            "champion_ref": self.champion_ref,
            "baseline_sha": self.baseline_sha,
            "candidate_sha": self.candidate_sha,
            "evaluator_sha256": self.evaluator_sha256,
            "harness_sha256": self.harness_sha256,
            "task_layout_sha256": self.task_layout_sha256,
            "agent_route": self.agent_route,
            "user_route": self.user_route,
            "task_ids": list(self.task_ids),
            "trials_per_task": self.trials_per_task,
            "assay_config": self.assay_config,
            "mutations": [self.mutation.to_dict()],
            "evaluator_paths": list(self.evaluator_paths),
            "promotion": self.promotion.to_dict(),
            "budget": self.budget.to_dict(),
            "vetoes": list(self.vetoes),
        }
        if self.parent_contract_id is not None:
            payload["parent_contract_id"] = self.parent_contract_id
        return payload

    @property
    def assay_config(self) -> dict[str, Any]:
        value = json.loads(self.assay_config_json)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise AssertionError("canonical assay_config is not an object")
        return value

    @property
    def assay_config_sha256(self) -> str:
        return hashlib.sha256(self.assay_config_json.encode("utf-8")).hexdigest()

    @property
    def contract_id(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "contract_id": self.contract_id}


def load_contract(path: Path) -> ExperimentContract:
    """Load and validate a contract JSON document."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read contract {path}: {exc}") from exc
    return ExperimentContract.from_mapping(payload)


def validate_checkout(
    contract: ExperimentContract,
    repo_root: Path,
    *,
    arm: Literal["baseline", "candidate"],
) -> None:
    """Require a clean tracked checkout at the revision named by the contract."""

    expected = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    head = _run_git(repo_root, "rev-parse", "HEAD").strip()
    dirty = _run_git(repo_root, "status", "--porcelain", "--untracked-files=all").strip()
    if head != expected:
        raise ContractError(f"checkout HEAD {head} does not match {arm} SHA {expected}")
    if dirty:
        raise ContractError("worktree must be clean before a Crucible run")


def validate_measurement_files(
    contract: ExperimentContract,
    *,
    repo_root: Path,
    harness_root: Path,
) -> None:
    """Verify that declared evaluator and harness hashes match actual bytes."""
    _reject_symlinks(repo_root, contract.evaluator_paths, "evaluator_paths")
    evaluator_sha = content_sha256(repo_root, contract.evaluator_paths)
    if evaluator_sha != contract.evaluator_sha256:
        raise ContractError("evaluator_sha256 does not match the frozen evaluator paths")
    harness_dirty = _run_git(
        harness_root,
        "status",
        "--porcelain",
        "--untracked-files=all",
    ).strip()
    if harness_dirty:
        raise ContractError("harness checkout must be clean before a Crucible run")
    if tracked_tree_sha256(harness_root) != contract.harness_sha256:
        raise ContractError("harness_sha256 does not match the frozen harness checkout")


def validate_candidate_diff(contract: ExperimentContract, repo_root: Path) -> None:
    """Require one reviewable production mutation between baseline and candidate."""
    champion_sha = _run_git(repo_root, "rev-parse", "--verify", contract.champion_ref).strip()
    if champion_sha != contract.baseline_sha:
        raise ContractError(
            f"champion ref {contract.champion_ref} does not resolve to baseline_sha"
        )
    _run_git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        contract.baseline_sha,
        contract.candidate_sha,
    )
    commit_count = _run_git(
        repo_root,
        "rev-list",
        "--count",
        f"{contract.baseline_sha}..{contract.candidate_sha}",
    ).strip()
    if commit_count != "1":
        raise ContractError(
            "candidate must be exactly one commit after baseline "
            f"(observed {commit_count or 'unknown'})"
        )
    raw = _run_git(
        repo_root,
        "diff",
        "--no-renames",
        "--numstat",
        "-z",
        contract.baseline_sha,
        contract.candidate_sha,
        "--",
    )
    rows = [row for row in raw.split("\0") if row]
    if not rows:
        raise ContractError("candidate diff is empty")

    changed_lines = 0
    changed_paths: list[str] = []
    for row in rows:
        parts = row.split("\t", 2)
        if len(parts) != 3:
            raise ContractError("cannot parse candidate diff numstat")
        additions, deletions, path = parts
        if additions == "-" or deletions == "-":
            raise ContractError(f"binary candidate changes are not reviewable: {path}")
        try:
            changed_lines += int(additions) + int(deletions)
        except ValueError as exc:
            raise ContractError(f"cannot parse changed-line count for {path}") from exc
        changed_paths.append(path)

    if changed_lines > contract.budget.max_changed_lines:
        raise ContractError(
            "candidate diff exceeds budget.max_changed_lines "
            f"({changed_lines} > {contract.budget.max_changed_lines})"
        )

    for path in changed_paths:
        if any(_paths_overlap(path, frozen) for frozen in contract.evaluator_paths):
            raise ContractError(f"candidate changes frozen evaluator path: {path}")

    mutation_paths = [
        path for path in changed_paths if _paths_overlap(path, contract.mutation.surface)
    ]
    if not mutation_paths:
        raise ContractError("candidate diff does not change the declared mutation surface")

    for path in mutation_paths:
        entry = _run_git(
            repo_root,
            "ls-tree",
            "-z",
            contract.candidate_sha,
            "--",
            f":(literal){path}",
        )
        if not entry:  # Deleting a tracked production file does not create an escape.
            continue
        metadata, separator, observed_path = entry.partition("\t")
        parts = metadata.split()
        if separator != "\t" or observed_path.rstrip("\0") != path or len(parts) != 3:
            raise ContractError(f"cannot inspect candidate tree mode for: {path}")
        mode, object_type, _object_id = parts
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise ContractError(f"candidate mutation must be a regular tracked file: {path}")

    def is_support_path(path: str) -> bool:
        # Tests can be part of the evaluator and must never be a candidate-
        # controlled escape hatch. Documentation and release notes cannot alter
        # executable measurement.
        return path == "CHANGELOG.md" or path.startswith("docs/")

    unexpected = [
        path for path in changed_paths if path not in mutation_paths and not is_support_path(path)
    ]
    if unexpected:
        raise ContractError(
            "candidate diff changes production paths outside the mutation surface: "
            + ", ".join(unexpected)
        )


def validate_test_parent(
    contract: ExperimentContract,
    parent: ExperimentContract,
) -> None:
    """Bind a sealed-test identity to a disjoint train contract for one candidate."""
    if contract.stage != "test":
        raise ContractError("parent validation is only valid for test contracts")
    if parent.stage != "train":
        raise ContractError("test parent must be a train contract")
    if contract.parent_contract_id != parent.contract_id:
        raise ContractError("parent contract does not match parent_contract_id")
    frozen_pairs = {
        "baseline_sha": (contract.baseline_sha, parent.baseline_sha),
        "candidate_sha": (contract.candidate_sha, parent.candidate_sha),
        "champion_ref": (contract.champion_ref, parent.champion_ref),
        "evaluator_sha256": (contract.evaluator_sha256, parent.evaluator_sha256),
        "harness_sha256": (contract.harness_sha256, parent.harness_sha256),
        "agent_route": (contract.agent_route, parent.agent_route),
        "user_route": (contract.user_route, parent.user_route),
        "trials_per_task": (contract.trials_per_task, parent.trials_per_task),
        "assay_config": (contract.assay_config_json, parent.assay_config_json),
        "mutation": (contract.mutation, parent.mutation),
        "evaluator_paths": (contract.evaluator_paths, parent.evaluator_paths),
        "promotion": (contract.promotion, parent.promotion),
        "budget": (contract.budget, parent.budget),
        "vetoes": (contract.vetoes, parent.vetoes),
    }
    for field, (test_value, train_value) in frozen_pairs.items():
        if test_value != train_value:
            raise ContractError(f"test and train contracts differ on {field}")
    overlap = sorted(set(contract.task_ids) & set(parent.task_ids))
    if overlap:
        raise ContractError("test task pack overlaps exposed train tasks: " + ", ".join(overlap))


def validate_shards(
    contract: ExperimentContract,
    shards: Sequence[Mapping[str, Any]],
    *,
    arm: Literal["baseline", "candidate"],
) -> tuple[str, ...]:
    """Reject row stitching across revisions and require exact task coverage."""

    if not shards:
        raise ContractError("at least one shard is required")
    revision_sha = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    observed: list[str] = []
    for index, shard in enumerate(shards):
        field = f"shards[{index}]"
        expected = {
            "contract_id": contract.contract_id,
            "revision_sha": revision_sha,
            "evaluator_sha256": contract.evaluator_sha256,
            "harness_sha256": contract.harness_sha256,
            "task_layout_sha256": contract.task_layout_sha256,
            "assay_config_sha256": contract.assay_config_sha256,
            "trials_per_task": contract.trials_per_task,
        }
        if shard.get("schema") != SHARD_SCHEMA:
            raise ContractError(f"{field}.schema must be {SHARD_SCHEMA!r}")
        for key, value in expected.items():
            if shard.get(key) != value:
                raise ContractError(f"{field}.{key} does not match the frozen contract")
        task_ids = _string_tuple(shard.get("task_ids"), f"{field}.task_ids")
        overlap = sorted(set(observed) & set(task_ids))
        if overlap:
            raise ContractError(f"shards repeat task ids: {', '.join(overlap)}")
        observed.extend(task_ids)
    if tuple(observed) != contract.task_ids:
        raise ContractError(
            "shard task order/coverage must exactly match the frozen contract task_ids"
        )
    return tuple(observed)
