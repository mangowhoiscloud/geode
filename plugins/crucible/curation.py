"""Deterministic tau2 task-pack curation with opaque command output."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import load_json_object, write_exclusive_json
from .contract import ContractError, TaskUnit, task_pack_sha256
from .verifiers.tau2 import tau2_task_unit

SELECTION_SCHEMA = "crucible.tau2-selection.v1"
CURATION_SUMMARY_SCHEMA = "crucible.tau2-curation-summary.v1"
_TASK_ID = re.compile(r"^\[(?P<intent>[^\]]+)\](?P<faults>.+)\[PERSONA:(?P<persona>[^\]]+)\]$")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _positive_int(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{field} must be a positive integer")
    return value


def _require_absent(path: Path, field: str) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ContractError(f"cannot inspect {field} {path}: {exc}") from exc
    raise ContractError(f"refusing to overwrite immutable artifact: {path}")


def _load_json(path: Path, field: str, *, max_bytes: int) -> object:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ContractError(f"cannot read {field} {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
        raise ContractError(f"{field} must be a bounded regular file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {field} {path}: {exc}") from exc


def _load_tasks(path: Path) -> tuple[Mapping[str, Any], ...]:
    raw = _load_json(path, "tau2 tasks", max_bytes=64 * 1024 * 1024)
    if not isinstance(raw, list):
        raise ContractError("tau2 tasks must be a JSON list")
    tasks: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        if not isinstance(value, Mapping):
            raise ContractError(f"tau2 tasks[{index}] must be an object")
        task_id = str(value.get("id") if value.get("id") is not None else "").strip()
        if not task_id:
            raise ContractError(f"tau2 tasks[{index}].id is required")
        if task_id in seen:
            raise ContractError("tau2 tasks contain duplicate IDs")
        seen.add(task_id)
        tasks.append(value)
    return tuple(tasks)


def _load_split(path: Path, split_name: str) -> tuple[str, ...]:
    raw = _load_json(path, "tau2 task split", max_bytes=8 * 1024 * 1024)
    if not isinstance(raw, Mapping):
        raise ContractError("tau2 task split must be a JSON object")
    split = raw.get(split_name)
    if not isinstance(split, list) or not all(isinstance(value, str) and value for value in split):
        raise ContractError(f"tau2 task split {split_name!r} must be a list of task IDs")
    if len(set(split)) != len(split):
        raise ContractError(f"tau2 task split {split_name!r} repeats task IDs")
    return tuple(split)


def _load_excluded_pack(path: Path) -> tuple[tuple[TaskUnit, ...], dict[str, str]]:
    raw = load_json_object(path, "excluded task pack")
    if raw.get("schema") != "crucible.task-pack.v1":
        raise ContractError("excluded task pack has an unsupported schema")
    rows = raw.get("tasks")
    if not isinstance(rows, list) or not rows:
        raise ContractError("excluded task pack tasks must be a non-empty list")
    tasks = tuple(
        TaskUnit.from_mapping(value, field=f"excluded task pack tasks[{index}]")
        for index, value in enumerate(rows)
    )
    trials = raw.get("trials_per_task")
    if isinstance(trials, bool) or not isinstance(trials, int) or trials <= 0:
        raise ContractError("excluded task pack trials_per_task must be positive")
    expected = task_pack_sha256(tasks, trials)
    if raw.get("task_pack_sha256") != expected:
        raise ContractError("excluded task pack hash does not match its tasks")
    return tasks, {
        "artifact_sha256": _file_sha256(path),
        "task_pack_sha256": expected,
    }


def _task_metadata(task_id: str, field: str) -> tuple[str, str, tuple[str, ...]]:
    match = _TASK_ID.fullmatch(task_id)
    if match is None:
        raise ContractError(f"{field}.id has an unsupported selection shape")
    faults = tuple(value.strip() for value in match.group("faults").split("|"))
    if not faults or any(not value for value in faults):
        raise ContractError(f"{field}.id has empty fault tokens")
    return match.group("intent"), match.group("persona"), faults


def curate_tau2_pack(
    *,
    tasks_path: Path,
    split_path: Path,
    split_name: str,
    domain: str,
    purpose: str,
    salt: str,
    fault_tokens: int,
    take: int,
    maximum_per_intent: int,
    maximum_per_persona: int,
    trials_per_task: int,
    exclude_packs: Sequence[Path],
    selection_output: Path,
    pack_output: Path,
) -> dict[str, Any]:
    """Select a frozen pack while returning only counts and hashes to the caller."""

    for number, field in (
        (fault_tokens, "fault_tokens"),
        (take, "take"),
        (maximum_per_intent, "maximum_per_intent"),
        (maximum_per_persona, "maximum_per_persona"),
        (trials_per_task, "trials_per_task"),
    ):
        _positive_int(number, field)
    for text, field in (
        (split_name, "split_name"),
        (domain, "domain"),
        (purpose, "purpose"),
        (salt, "salt"),
    ):
        if not text.strip():
            raise ContractError(f"{field} must be non-empty")
    if purpose not in {"train", "test"}:
        raise ContractError("purpose must be 'train' or 'test'")
    if selection_output.resolve() == pack_output.resolve():
        raise ContractError("selection and pack outputs must differ")
    _require_absent(selection_output, "selection output")
    _require_absent(pack_output, "pack output")

    tasks = _load_tasks(tasks_path)
    split_ids = _load_split(split_path, split_name)
    split_set = set(split_ids)
    source_ids = {str(task["id"]).strip() for task in tasks}
    missing_split_ids = sorted(split_set - source_ids)
    if missing_split_ids:
        raise ContractError("tau2 split names tasks missing from the source file")

    excluded_tasks: set[str] = set()
    excluded_families: set[str] = set()
    excluded_content: set[str] = set()
    excluded_sources: list[dict[str, str]] = []
    for path in exclude_packs:
        excluded, source = _load_excluded_pack(path)
        excluded_sources.append(source)
        excluded_tasks.update(task.task_id for task in excluded)
        excluded_families.update(task.family_id for task in excluded)
        excluded_content.update(task.content_sha256 for task in excluded)

    eligible: list[dict[str, Any]] = []
    for source_index, raw in enumerate(tasks):
        task_id = str(raw["id"]).strip()
        if task_id not in split_set:
            continue
        intent, persona, faults = _task_metadata(task_id, f"tau2 tasks[{source_index}]")
        if len(faults) != fault_tokens:
            continue
        unit = tau2_task_unit(raw, f"tau2 tasks[{source_index}]")
        if (
            unit.task_id in excluded_tasks
            or unit.family_id in excluded_families
            or unit.content_sha256 in excluded_content
        ):
            continue
        rank = hashlib.sha256(
            salt.encode("utf-8") + b"\0" + unit.content_sha256.encode("ascii")
        ).hexdigest()
        eligible.append(
            {
                "source_index": source_index,
                "rank": rank,
                "intent": intent,
                "persona": persona,
                "unit": unit,
            }
        )

    eligible_family_count = len({row["unit"].family_id for row in eligible})
    selected: list[dict[str, Any]] = []
    selected_families: set[str] = set()
    intent_counts: Counter[str] = Counter()
    persona_counts: Counter[str] = Counter()
    for row in sorted(eligible, key=lambda item: (item["rank"], item["source_index"])):
        unit = row["unit"]
        if unit.family_id in selected_families:
            continue
        if intent_counts[row["intent"]] >= maximum_per_intent:
            continue
        if persona_counts[row["persona"]] >= maximum_per_persona:
            continue
        selected.append(row)
        selected_families.add(unit.family_id)
        intent_counts[row["intent"]] += 1
        persona_counts[row["persona"]] += 1
        if len(selected) == take:
            break
    if len(selected) != take:
        raise ContractError(
            f"selection constraints admit {len(selected)} tasks, fewer than requested take={take}"
        )

    selected.sort(key=lambda item: item["source_index"])
    selected_units = tuple(row["unit"] for row in selected)
    pack_hash = task_pack_sha256(selected_units, trials_per_task)
    pack = {
        "schema": "crucible.task-pack.v1",
        "task_pack_sha256": pack_hash,
        "trials_per_task": trials_per_task,
        "tasks": [unit.to_dict() for unit in selected_units],
    }
    selection = {
        "schema": SELECTION_SCHEMA,
        "purpose": purpose,
        "domain": domain,
        "task_split_name": split_name,
        "salt": salt,
        "rule": {
            "split_membership": True,
            "fault_tokens": fault_tokens,
            "rank": "sha256(utf8(salt) || 0x00 || utf8(content_sha256))",
            "distinct_family_id": True,
            "maximum_per_intent": maximum_per_intent,
            "maximum_per_persona": maximum_per_persona,
            "take": take,
            "execution_order": "upstream_tasks_file",
        },
        "eligible_tasks": len(eligible),
        "eligible_families": eligible_family_count,
        "selected": [
            {
                **row["unit"].to_dict(),
                "rank": row["rank"],
                "intent": row["intent"],
                "persona": row["persona"],
            }
            for row in selected
        ],
        "sources": {
            "tasks_sha256": _file_sha256(tasks_path),
            "split_sha256": _file_sha256(split_path),
            "excluded_packs": excluded_sources,
        },
    }
    write_exclusive_json(pack_output, pack)
    write_exclusive_json(selection_output, selection)
    return {
        "schema": CURATION_SUMMARY_SCHEMA,
        "purpose": purpose,
        "task_pack_sha256": pack_hash,
        "task_pack_artifact_sha256": _file_sha256(pack_output),
        "selection_artifact_sha256": _file_sha256(selection_output),
        "task_count": len(selected_units),
        "family_count": len(selected_families),
        "eligible_tasks": len(eligible),
        "eligible_families": eligible_family_count,
    }
