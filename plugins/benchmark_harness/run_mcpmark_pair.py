"""Run the pinned MCPMark Filesystem-30 GEODE/Codex pair fail closed.

This is an ordering and evidence wrapper around MCPMark's native pipeline.  It
does not reimplement fixture setup, verification, scoring, or aggregation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.observability.trajectory import verify_trajectory_integrity
from scripts.eval.contract import validate_run_spec

from plugins.benchmark_harness.manifest import REPO_ROOT, get_harness

EXPECTED_FS30_SHA256 = "50483308573ce407abaf0700885d56c6df0453557669dddce9edcece83710433"
EXPECTED_FIXTURE_SHA256 = "c8cfb2815f63ded54a7d79ffed2e0719190bb2dc1e571112a6012f97f95e9f17"
PATCH_SHA256 = "04a34e664f590c36bc85765581318c0887000f6ca79213efd97705795ca4dac4"
PATCHED_VERIFIERS = {
    "tasks/filesystem/standard/desktop/project_management/verify.py": (
        "8159f860c370a48510a126b41d692baf9e76e78314742cb59e1b17f433ddae6b"
    ),
    "tasks/filesystem/standard/file_context/duplicates_searching/verify.py": (
        "4ed5f9f1b35badd15f8a19c1efe5696c3a6a339ce9009348715d7bfdedb74e85"
    ),
    "tasks/filesystem/standard/file_context/file_splitting/verify.py": (
        "598e0856a8c0d313ae3219ae50193d363c85f609d6b0a4bc3fb31d781a8715f1"
    ),
}
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9._-]+$")
_EFFORTS = frozenset({"minimal", "low", "medium", "high", "xhigh", "max"})


class PairRunError(RuntimeError):
    """The paired attempt is infrastructure-invalid and must stop."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workload_hash(ids: tuple[str, ...]) -> str:
    encoded = json.dumps(ids, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write_exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git argv, never a shell
        ("git", "-C", str(root), *args),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise PairRunError(f"git {' '.join(args)} failed")
    return result.stdout.rstrip("\n")


def _discover_workload(root: Path) -> tuple[str, ...]:
    discovered: list[str] = []
    task_root = root / "tasks/filesystem/standard"
    for description in task_root.glob("*/*/description.md"):
        task_dir = description.parent
        if not (task_dir / "verify.py").is_file():
            continue
        meta_path = task_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        category = str(meta.get("category_id", task_dir.parent.name))
        task = str(meta.get("task_id", task_dir.name))
        discovered.append(f"{category}/{task}")
    ids = tuple(sorted(discovered, key=lambda value: tuple(value.split("/", 1))))
    if _workload_hash(ids) != EXPECTED_FS30_SHA256:
        raise PairRunError("pinned MCPMark Filesystem-30 workload identity mismatch")
    return ids


def _tree_row(path: Path, *, category: str) -> dict[str, Any]:
    if not path.is_dir():
        raise PairRunError(f"fixture category is missing: {category}")
    digest = hashlib.sha256()
    count = 0
    byte_count = 0
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        raw = item.read_bytes()
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(raw).digest())
        count += 1
        byte_count += len(raw)
    return {
        "category": category,
        "file_count": count,
        "bytes": byte_count,
        "sha256": digest.hexdigest(),
    }


def _fixture_receipt(root: Path, ids: tuple[str, ...]) -> dict[str, Any]:
    categories = tuple(sorted({task.split("/", 1)[0] for task in ids}))
    rows = [
        _tree_row(root / "test_environments" / category, category=category)
        for category in categories
    ]
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    aggregate = hashlib.sha256(encoded).hexdigest()
    if aggregate != EXPECTED_FIXTURE_SHA256:
        raise PairRunError("MCPMark Filesystem-30 source fixture digest mismatch")
    return {"categories": rows, "aggregate_sha256": aggregate}


def _validate_checkout(root: Path) -> None:
    spec = get_harness("mcpmark")
    patch = Path(__file__).with_name("patches") / (
        "mcpmark-cd45b7f-filesystem-standard-verifier-missing-output.patch"
    )
    if _sha256(patch) != PATCH_SHA256:
        raise PairRunError("checked-in MCPMark verifier patch digest mismatch")
    if _git(root, "rev-parse", "HEAD") != spec.commit:
        raise PairRunError("MCPMark revision does not match the public harness manifest")
    visible = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--")
    visible_paths = {line[3:] for line in visible.splitlines() if line}
    if visible_paths != set(PATCHED_VERIFIERS):
        raise PairRunError("MCPMark checkout contains visible changes outside the verifier patch")
    for relative, expected in PATCHED_VERIFIERS.items():
        if _sha256(root / relative) != expected:
            raise PairRunError(f"patched verifier digest mismatch: {relative}")


def _validate_spec(
    spec_path: Path,
    *,
    ids: tuple[str, ...],
    fixture_sha256: str,
) -> dict[str, Any]:
    spec = validate_run_spec(spec_path)
    reproduction = spec["reproduction"]
    execution = reproduction["execution"]
    model = reproduction["model"]
    harness = get_harness("mcpmark")
    expected_harness = f"{harness.commit}+patch-sha256:{PATCH_SHA256}"
    expected_state = f"fixture-tree-sha256:{fixture_sha256}"
    if spec["preregistration"]["live_test_approved"] is not True:
        raise PairRunError("run spec does not approve live model calls")
    if tuple(execution["ordered_workload_ids"]) != ids:
        raise PairRunError("run spec workload order differs from pinned Filesystem-30")
    if execution["repetitions"] != 1 or execution["max_concurrency"] != 1:
        raise PairRunError("paired runner requires repetitions=1 and max_concurrency=1")
    if reproduction["harness"]["revision"] != expected_harness:
        raise PairRunError("run spec harness revision does not bind the verifier patch")
    if reproduction["environment"]["initial_state_ref"] != expected_state:
        raise PairRunError("run spec initial_state_ref does not match the fixture tree")
    if model["provider"].lower() != "openai" or model["route"] != "subscription":
        raise PairRunError("paired runner requires the OpenAI subscription route")
    if not _SAFE_MODEL.fullmatch(model["label"]):
        raise PairRunError("model label is not safe for the native argv contract")
    if model["reasoning"] not in _EFFORTS:
        raise PairRunError("reasoning effort is unsupported by the pinned MCPMark pipeline")
    timeout = float(execution["timeout_seconds"])
    if timeout <= 0 or not timeout.is_integer():
        raise PairRunError("MCPMark timeout_seconds must be a positive integer")
    if reproduction["geode"]["revision"] != _git(REPO_ROOT, "rev-parse", "HEAD"):
        raise PairRunError("run spec GEODE revision differs from the executing checkout")
    dirty = bool(_git(REPO_ROOT, "status", "--porcelain"))
    if reproduction["geode"]["dirty"] != dirty:
        raise PairRunError("run spec dirty-tree flag differs from the executing checkout")
    return spec


def _arm_order(task_index: int) -> tuple[str, str]:
    return ("geode", "codex") if task_index % 2 else ("codex", "geode")


def _has_backups(root: Path) -> bool:
    backup_root = root / ".mcpmark_backups"
    return backup_root.is_dir() and any(backup_root.iterdir())


def _one(path: Path, pattern: str) -> Path:
    found = list(path.rglob(pattern))
    if len(found) != 1:
        raise PairRunError(f"expected exactly one {pattern} in native task output")
    return found[0]


def _deadline_receipt(
    path: Path,
    *,
    arm: str,
    timeout: int,
) -> dict[str, Any]:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PairRunError("deadline receipt is unreadable") from exc
    if not isinstance(receipt, dict):
        raise PairRunError("deadline receipt must contain an object")
    identity = (
        receipt.get("schema_id"),
        receipt.get("timeout_owner"),
        receipt.get("timed_surface"),
        receipt.get("limit_seconds"),
        receipt.get("cleanup_grace_seconds"),
    )
    if identity != (
        "geode.mcpmark.execution_deadline@1",
        "adapter",
        "adapter_execute_entry_through_native_runtime_return",
        float(timeout),
        5.0,
    ):
        raise PairRunError("deadline receipt identity mismatch")
    if receipt.get("arm") != arm or receipt.get("clock") != "monotonic":
        raise PairRunError("deadline receipt arm or clock mismatch")
    status = receipt.get("action_status")
    expired = receipt.get("expired")
    if status not in {"complete", "right_censored", "aborted"} or not isinstance(expired, bool):
        raise PairRunError("deadline receipt action status is invalid")
    if expired != (status == "right_censored"):
        raise PairRunError("deadline receipt expiry contradicts action status")
    timing_fields = (
        "action_started_monotonic",
        "action_deadline_monotonic",
        "action_finished_monotonic",
        "action_elapsed_seconds",
        "cleanup_elapsed_seconds",
        "started_at_unix_seconds",
        "finished_at_unix_seconds",
    )
    timing = [receipt.get(field) for field in timing_fields]
    if any(
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        for value in timing
    ):
        raise PairRunError("deadline receipt timing fields are invalid")
    (
        action_started,
        action_deadline,
        action_finished,
        action_elapsed,
        cleanup_elapsed,
        started,
        finished,
    ) = (float(receipt[field]) for field in timing_fields)
    if (
        not math.isclose(action_deadline - action_started, float(timeout))
        or not math.isclose(action_finished - action_started, action_elapsed)
        or action_elapsed < 0
        or cleanup_elapsed < 0
        or finished < started
        or expired != (action_finished >= action_deadline)
    ):
        raise PairRunError("deadline receipt timing values are inconsistent")
    if receipt.get("cleanup_status") != "complete":
        raise PairRunError("deadline receipt marks cleanup infrastructure-invalid")
    if receipt.get("evidence_status") != "written":
        raise PairRunError("deadline receipt marks native evidence incomplete")
    return receipt


def _native_receipt(
    native_dir: Path,
    *,
    task: str,
    arm: str,
    model: str,
    effort: str,
    timeout: int,
) -> dict[str, Any]:
    meta_path = _one(native_dir, "meta.json")
    summary_path = _one(native_dir, "summary.json")
    trajectory_path = _one(native_dir, "execution.trajectory.json")
    deadline_path = _one(native_dir, "execution.deadline.json")
    messages_path = _one(native_dir, "messages.json")
    execution_log_path = _one(native_dir, "execution.log")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PairRunError("native MCPMark JSON evidence is unreadable") from exc
    if not all(isinstance(item, dict) for item in (meta, summary, trajectory)):
        raise PairRunError("native MCPMark JSON evidence must contain objects")
    result = meta.get("execution_result")
    if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
        raise PairRunError("native meta lacks a typed verifier outcome")
    if meta.get("model_name") != model or meta.get("reasoning_effort") != effort:
        raise PairRunError("native meta model or reasoning identity mismatch")
    if meta.get("mcp") != "filesystem" or int(meta.get("timeout", -1)) != timeout:
        raise PairRunError("native meta service or timeout identity mismatch")
    if result.get("error_message") == "State Duplication Error":
        raise PairRunError("native MCPMark fixture setup failed")
    if result.get("verification_output") is None:
        raise PairRunError("native verifier raised instead of returning a semantic outcome")
    if "Traceback (most recent call last):" in str(result.get("verification_error") or ""):
        raise PairRunError("native verifier emitted an exception traceback")
    allowed_agent_errors = {
        f"GEODE exceeded MCPMark action deadline ({timeout}s)",
        f"codex exec exceeded MCPMark action deadline ({timeout}s)",
    }
    agent_error = result.get("error_message")
    if agent_error not in (None, "") and agent_error not in allowed_agent_errors:
        raise PairRunError("native agent error lacks a score-bearing failure class")
    model_config = summary.get("model_config")
    if (
        summary.get("total_tasks") != 1
        or int(summary.get("successful_tasks", -1)) + int(summary.get("failed_tasks", -1)) != 1
        or not isinstance(model_config, dict)
        or model_config.get("model_name") != model
        or model_config.get("agent_name") != arm
    ):
        raise PairRunError("native summary is not an exact one-task arm result")
    if meta.get("task_name") != task.replace("/", "__"):
        raise PairRunError("native meta task identity mismatch")
    provenance = trajectory.get("provenance")
    source = trajectory.get("source")
    task_sha256 = source.get("task") if isinstance(source, dict) else None
    if (
        not isinstance(provenance, dict)
        or provenance.get("model") != model.removeprefix(f"{arm}-")
        or provenance.get("source") != "subscription"
        or provenance.get("effort") != effort
        or not isinstance(task_sha256, str)
        or not re.fullmatch(r"[a-f0-9]{64}", task_sha256)
    ):
        raise PairRunError("native trajectory provenance or task identity mismatch")
    deadline = _deadline_receipt(deadline_path, arm=arm, timeout=timeout)
    try:
        trajectory_integrity = verify_trajectory_integrity(trajectory)
    except (KeyError, TypeError, ValueError) as exc:
        raise PairRunError("native trajectory integrity verification failed") from exc
    if bool(deadline["expired"]) == bool(trajectory_integrity["scope_complete"]):
        expected = "scope-incomplete" if deadline["expired"] else "scope-complete"
        raise PairRunError(f"native trajectory must be {expected} for its deadline status")
    files = (
        meta_path,
        summary_path,
        trajectory_path,
        deadline_path,
        messages_path,
        execution_log_path,
    )
    return {
        "verifier_pass": result["success"],
        "agent_error_present": bool(agent_error),
        "task_sha256": task_sha256,
        "deadline": deadline,
        "files": [
            {
                "path": path.relative_to(native_dir).as_posix(),
                "sha256": _sha256(path),
            }
            for path in files
        ],
    }


def _invoke_arm(
    *,
    python: Path,
    mcpmark_root: Path,
    native_dir: Path,
    log_dir: Path,
    task: str,
    arm: str,
    model_label: str,
    effort: str,
    timeout: int,
    run_id: str,
) -> tuple[int, Path, Path]:
    if native_dir.exists():
        raise PairRunError("native task output directory already exists")
    log_dir.mkdir(parents=True, exist_ok=False)
    stdout_path = log_dir / "stdout.log"
    stderr_path = log_dir / "stderr.log"
    command = (
        str(python),
        "-m",
        "plugins.benchmark_harness.run_mcpmark",
        "--mcp",
        "filesystem",
        "--task-suite",
        "standard",
        "--tasks",
        task,
        "--models",
        f"{arm}-{model_label}",
        "--agent",
        arm,
        "--reasoning-effort",
        effort,
        "--k",
        "1",
        "--timeout",
        str(timeout),
        "--compaction-token",
        "999999999",
        "--exp-name",
        run_id,
        "--output-dir",
        str(native_dir),
    )
    env = os.environ.copy()
    env["MCPMARK_ROOT"] = str(mcpmark_root)
    env.setdefault("OPENAI_API_KEY", "dummy")
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(REPO_ROOT), env.get("PYTHONPATH", "")) if value
    )
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        result = subprocess.run(  # noqa: S603 - frozen argv, never a shell
            command,
            cwd=mcpmark_root,
            env=env,
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
        stdout.flush()
        stderr.flush()
        os.fsync(stdout.fileno())
        os.fsync(stderr.fileno())
    return result.returncode, stdout_path, stderr_path


def _run_tasks(
    *,
    output_dir: Path,
    mcpmark_root: Path,
    python: Path,
    ids: tuple[str, ...],
    fixture: dict[str, Any],
    run_id: str,
    model_label: str,
    effort: str,
    timeout: int,
) -> None:
    events_path = output_dir / "runner-events.jsonl"
    fixture_rows = {row["category"]: row for row in fixture["categories"]}
    if _has_backups(mcpmark_root):
        raise PairRunError("MCPMark backup directory is not empty before the paired run")
    sequence = 0
    task_hashes: dict[str, str] = {}

    def emit(event: str, **payload: Any) -> None:
        nonlocal sequence
        _append_event(
            events_path,
            {"sequence": sequence, "event": event, "recorded_at": _utc_now(), **payload},
        )
        sequence += 1

    emit("run_started", task_count=len(ids), arm_count=2)
    try:
        for index, task in enumerate(ids, start=1):
            category = task.split("/", 1)[0]
            expected_fixture = fixture_rows[category]
            for arm in _arm_order(index):
                if (
                    _tree_row(
                        mcpmark_root / "test_environments" / category,
                        category=category,
                    )
                    != expected_fixture
                ):
                    raise PairRunError("source fixture changed between paired arms")
                arm_key = f"{index:02d}-{task.replace('/', '__')}--{arm}"
                native_dir = output_dir / "native-results" / arm_key
                log_dir = output_dir / "runner-logs" / arm_key
                started = time.monotonic_ns()
                emit(
                    "arm_started",
                    task_index=index,
                    task=task,
                    arm=arm,
                    arm_first=arm == _arm_order(index)[0],
                    native_output=f"native-results/{arm_key}",
                )
                try:
                    returncode, stdout_path, stderr_path = _invoke_arm(
                        python=python,
                        mcpmark_root=mcpmark_root,
                        native_dir=native_dir,
                        log_dir=log_dir,
                        task=task,
                        arm=arm,
                        model_label=model_label,
                        effort=effort,
                        timeout=timeout,
                        run_id=run_id,
                    )
                    if returncode:
                        raise PairRunError(f"native MCPMark subprocess exited {returncode}")
                    receipt = _native_receipt(
                        native_dir,
                        task=task,
                        arm=arm,
                        model=f"{arm}-{model_label}",
                        effort=effort,
                        timeout=timeout,
                    )
                    current_task_sha256 = str(receipt.pop("task_sha256"))
                    prior_task_sha256 = task_hashes.setdefault(task, current_task_sha256)
                    if current_task_sha256 != prior_task_sha256:
                        raise PairRunError("paired arms used different task instruction hashes")
                    if _has_backups(mcpmark_root):
                        raise PairRunError("native MCPMark left a fixture backup behind")
                    emit(
                        "arm_finished",
                        task_index=index,
                        task=task,
                        arm=arm,
                        duration_ns=time.monotonic_ns() - started,
                        stdout={
                            "path": stdout_path.relative_to(output_dir).as_posix(),
                            "sha256": _sha256(stdout_path),
                        },
                        stderr={
                            "path": stderr_path.relative_to(output_dir).as_posix(),
                            "sha256": _sha256(stderr_path),
                        },
                        native=receipt,
                    )
                except BaseException as exc:
                    emit(
                        "run_stopped",
                        task_index=index,
                        task=task,
                        arm=arm,
                        failure_class="infrastructure",
                        exception_type=type(exc).__name__,
                        exception_sha256=hashlib.sha256(str(exc).encode()).hexdigest(),
                    )
                    raise
    except PairRunError:
        raise
    except BaseException as exc:
        raise PairRunError("paired MCPMark runner interrupted") from exc
    emit("run_completed", completed_tasks=len(ids), completed_arms=len(ids) * 2)


def run_pair(
    *,
    run_spec_path: Path,
    mcpmark_root: Path,
    output_dir: Path,
    python: Path,
) -> None:
    if output_dir.exists():
        raise PairRunError("output directory must not exist; retries use a fresh attempt root")
    run_spec_sha256 = _sha256(run_spec_path)
    _validate_checkout(mcpmark_root)
    ids = _discover_workload(mcpmark_root)
    fixture = _fixture_receipt(mcpmark_root, ids)
    spec = _validate_spec(
        run_spec_path,
        ids=ids,
        fixture_sha256=fixture["aggregate_sha256"],
    )
    reproduction = spec["reproduction"]
    execution = reproduction["execution"]
    model = reproduction["model"]
    run_spec_bytes = run_spec_path.read_bytes()
    if hashlib.sha256(run_spec_bytes).hexdigest() != run_spec_sha256:
        raise PairRunError("run spec changed during paired-run preflight")
    output_dir.mkdir(parents=True)
    with (output_dir / "run-spec.json").open("xb") as handle:
        handle.write(run_spec_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    _write_exclusive_json(
        output_dir / "runner-plan.json",
        {
            "schema_id": "geode.mcpmark-paired-runner-plan@1",
            "run_id": spec["run_id"],
            "created_at": _utc_now(),
            "run_spec_sha256": run_spec_sha256,
            "geode_revision": reproduction["geode"]["revision"],
            "harness_revision": reproduction["harness"]["revision"],
            "workload_ids": ids,
            "workload_ids_sha256": EXPECTED_FS30_SHA256,
            "fixture": fixture,
            "model": model["label"],
            "route": model["route"],
            "reasoning_effort": model["reasoning"],
            "timeout_seconds": int(execution["timeout_seconds"]),
            "arm_order": "odd:geode,codex;even:codex,geode",
            "max_concurrency": 1,
        },
    )
    _run_tasks(
        output_dir=output_dir,
        mcpmark_root=mcpmark_root,
        python=python,
        ids=ids,
        fixture=fixture,
        run_id=spec["run_id"],
        model_label=model["label"],
        effort=model["reasoning"],
        timeout=int(execution["timeout_seconds"]),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-spec", type=Path, required=True)
    parser.add_argument("--mcpmark-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        run_pair(
            run_spec_path=args.run_spec.resolve(),
            mcpmark_root=args.mcpmark_root.resolve(),
            output_dir=args.output_dir.resolve(),
            python=args.python.resolve(),
        )
    except PairRunError as exc:
        print(f"MCPMark paired run stopped: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
