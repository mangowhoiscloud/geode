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
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.agent.tool_executor.processor import ToolCallProcessor
from core.agent.tool_executor.result_token_guard import _guard_tool_result, _project_mcp_result
from core.observability.trajectory import verify_trajectory_integrity
from scripts.eval.contract import validate_run_spec

from plugins.benchmark_harness.manifest import REPO_ROOT, get_harness
from plugins.benchmark_harness.mcpmark_geode_agent import _tool_schema_sha256

EXPECTED_FS30_SHA256 = "50483308573ce407abaf0700885d56c6df0453557669dddce9edcece83710433"
EXPECTED_FIXTURE_SHA256 = "c8cfb2815f63ded54a7d79ffed2e0719190bb2dc1e571112a6012f97f95e9f17"
EXPECTED_FIXTURE_SEMANTIC_SHA256 = (
    "273477d554250f4f076e69651e29689ed71095ec1b3fe3e054094be82f574fbf"
)
PAIR_PROFILE = "filesystem30-geode-codex"
PAIR_SMOKE_PROFILE = "filesystem1-geode-codex-smoke"
TOOL_CAP_PROFILE = "max-tool-result-tokens"
TOOL_CAP_IDS = (
    "legal_document/dispute_review",
    "legal_document/individual_comments",
    "legal_document/solution_tracing",
    "papers/author_folders",
    "papers/organize_legacy_papers",
)
TOOL_CAP_SHA256 = "b0953abbe11808bd25a03ef97355380ae2a58f0086025cd2557f1cacf32f3a00"
TOOL_CAP_ARMS = (("guard-25000", 25_000), ("unlimited-0", 0))
TOOL_CAP_REPETITIONS = 3
TOOL_CAP_TIMEOUT_SECONDS = 1_200
PAIR_TIMEOUT_SECONDS = 1_200
PAIR_MAX_TOOL_RESULT_TOKENS = 25_000
CODEX_CLI_VERSION = "codex-cli 0.145.0"
CODEX_CLI_SOURCE_REVISION = "dad1db87bb5ad4b92af6b0f58502d12453681f81"
CODEX_CLI_EXECUTABLE_SHA256 = "1da3f4e0e96028b8a771814293c3033dafd1971f943f6c7e79b0897fe705f590"
CODEX_COMPARATOR = (
    f"{CODEX_CLI_VERSION}; openai/codex@{CODEX_CLI_SOURCE_REVISION}; "
    f"executable-sha256:{CODEX_CLI_EXECUTABLE_SHA256}"
)
PATCH_SHA256 = "3f41f13a8edf7b40f411bf0a76412c28fc9629338d9e5051d5633dc064c563e6"
PATCHED_VERIFIERS = {
    "tasks/filesystem/standard/desktop/project_management/verify.py": (
        "2442b53734cd0c62cf3f370ef1c226c163cb3a2a7d14d0279b1f7e8f74c784a8"
    ),
    "tasks/filesystem/standard/file_context/duplicates_searching/verify.py": (
        "05e7f56800f6c0ad3d50665ca044392e3b88d5f845092c5032f982625803f5bf"
    ),
    "tasks/filesystem/standard/file_context/file_splitting/verify.py": (
        "cc91a73608a1b415bcce28e96648e11e8e8305c2bddeea2545027805c6a9aa94"
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
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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


def _run_process(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(  # noqa: S603 - fixed argv, never a shell
        command,
        cwd=cwd,
        env=env,
        stdout=stdout,
        stderr=stderr,
        timeout=timeout,
        check=False,
    )


def _python_preflight(python: Path, mcpmark_root: Path) -> dict[str, Any]:
    """Reject a conflicted runtime before any benchmark model call."""
    env = os.environ.copy()
    env["MCPMARK_ROOT"] = str(mcpmark_root)
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(REPO_ROOT), env.get("PYTHONPATH", "")) if value
    )
    checks = (
        ((str(python), "-m", "pip", "check"), "dependency integrity"),
        (
            (
                str(python),
                "-c",
                "import pipeline; import src.evaluator; "
                "import plugins.benchmark_harness.mcpmark_geode_agent; "
                "from src.factory import MCPServiceFactory as F; "
                "F.create_task_manager('filesystem', task_suite='standard'); "
                "F.create_state_manager('filesystem')",
            ),
            "MCPMark source imports",
        ),
        (("npx", "--version"), "filesystem MCP executable"),
    )
    for command, label in checks:
        try:
            result = _run_process(command, cwd=mcpmark_root, env=env)
        except OSError as exc:
            raise PairRunError(f"Python preflight could not start: {label}") from exc
        if result.returncode:
            raise PairRunError(f"Python preflight failed: {label}")
    return {
        "dependency_check": "pass",
        "imports": [
            "pipeline",
            "src.evaluator",
            "plugins.benchmark_harness.mcpmark_geode_agent",
            "filesystem/standard managers",
        ],
        "filesystem_mcp_executable": "npx",
    }


def _codex_cli_preflight(mcpmark_root: Path) -> tuple[dict[str, str], Path]:
    executable = shutil.which("codex")
    if executable is None:
        raise PairRunError("Codex CLI is not available on PATH")
    resolved = Path(executable).resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise PairRunError("Codex CLI PATH target is not an executable file")
    try:
        result = _run_process((executable, "--version"), cwd=mcpmark_root, env=os.environ.copy())
    except OSError as exc:
        raise PairRunError("Codex CLI version preflight could not start") from exc
    version = (
        result.stdout.decode("utf-8", errors="strict")
        if isinstance(result.stdout, bytes)
        else str(result.stdout)
    ).strip()
    if result.returncode or version != CODEX_CLI_VERSION:
        raise PairRunError(f"Codex CLI must be exactly {CODEX_CLI_VERSION}")
    executable_sha256 = _sha256(resolved)
    if executable_sha256 != CODEX_CLI_EXECUTABLE_SHA256:
        raise PairRunError("Codex CLI executable digest does not match the frozen comparator")
    return (
        {
            "command": "codex",
            "version": version,
            "source_revision": CODEX_CLI_SOURCE_REVISION,
            "executable_sha256": executable_sha256,
        },
        resolved,
    )


def _probe_filesystem_tool_schema(python: Path, mcpmark_root: Path) -> str:
    """Start the pinned filesystem MCP server and digest its raw tool schemas."""
    script = """import asyncio,json,sys
from src.agents.mcp import MCPStdioServer
async def main():
    server=MCPStdioServer(command="npx",args=["-y","@modelcontextprotocol/server-filesystem@2025.12.18",sys.argv[1]])
    async with server:
        print(json.dumps(await server.list_tools(),ensure_ascii=False))
asyncio.run(main())
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(REPO_ROOT), env.get("PYTHONPATH", "")) if value
    )
    try:
        result = _run_process(
            (str(python), "-c", script, str(mcpmark_root / "test_environments")),
            cwd=mcpmark_root,
            env=env,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise PairRunError("filesystem MCP tool-schema probe timed out") from exc
    except OSError as exc:
        raise PairRunError("filesystem MCP tool-schema probe could not start") from exc
    if result.returncode:
        raise PairRunError("filesystem MCP tool-schema probe failed")
    try:
        schemas = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise PairRunError("filesystem MCP tool-schema probe returned invalid JSON") from exc
    if (
        not isinstance(schemas, list)
        or not schemas
        or not all(isinstance(schema, dict) for schema in schemas)
    ):
        raise PairRunError("filesystem MCP tool-schema probe returned no typed schemas")
    return _tool_schema_sha256(schemas)


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
    semantic_digest = hashlib.sha256()
    count = 0
    directory_count = 1
    byte_count = 0
    # Directory mtimes are copy-order artifacts; FS30 scores file mtimes and
    # directory structure, so the semantic receipt binds only the latter.
    semantic_digest.update(f"directory\0.\0{path.stat().st_mode & 0o7777:o}\n".encode())
    for directory in sorted(candidate for candidate in path.rglob("*") if candidate.is_dir()):
        relative = directory.relative_to(path).as_posix()
        mode = directory.stat().st_mode & 0o7777
        semantic_digest.update(f"directory\0{relative}\0{mode:o}\n".encode())
        directory_count += 1
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        raw = item.read_bytes()
        relative = item.relative_to(path).as_posix()
        item_sha256 = hashlib.sha256(raw).hexdigest()
        item_stat = item.stat()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(item_sha256))
        semantic_digest.update(
            (
                f"file\0{relative}\0{len(raw)}\0{item_stat.st_mtime_ns}\0"
                f"{item_stat.st_mode & 0o7777:o}\0{item_sha256}\n"
            ).encode()
        )
        count += 1
        byte_count += len(raw)
    return {
        "category": category,
        "directory_count": directory_count,
        "file_count": count,
        "bytes": byte_count,
        "sha256": digest.hexdigest(),
        "semantic_sha256": semantic_digest.hexdigest(),
    }


def _fixture_receipt(root: Path, ids: tuple[str, ...]) -> dict[str, Any]:
    categories = tuple(sorted({task.split("/", 1)[0] for task in ids}))
    rows = [
        _tree_row(root / "test_environments" / category, category=category)
        for category in categories
    ]
    content_rows = [
        {key: row[key] for key in ("category", "file_count", "bytes", "sha256")} for row in rows
    ]
    encoded = json.dumps(
        content_rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    aggregate = hashlib.sha256(encoded).hexdigest()
    if aggregate != EXPECTED_FIXTURE_SHA256:
        raise PairRunError("MCPMark Filesystem-30 source fixture digest mismatch")
    semantic_rows = [
        {
            key: row[key]
            for key in (
                "category",
                "directory_count",
                "file_count",
                "bytes",
                "semantic_sha256",
            )
        }
        for row in rows
    ]
    semantic_encoded = json.dumps(
        semantic_rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    semantic_aggregate = hashlib.sha256(semantic_encoded).hexdigest()
    if semantic_aggregate != EXPECTED_FIXTURE_SEMANTIC_SHA256:
        raise PairRunError("MCPMark Filesystem-30 semantic fixture digest mismatch")
    return {
        "categories": rows,
        "aggregate_sha256": aggregate,
        "semantic_aggregate_sha256": semantic_aggregate,
    }


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
        verifier = root / relative
        if _sha256(verifier) != expected:
            raise PairRunError(f"patched verifier digest mismatch: {relative}")
        try:
            compile(verifier.read_bytes(), relative, "exec")
        except SyntaxError as exc:
            raise PairRunError(f"patched verifier is not valid Python: {relative}") from exc


def _validate_spec(
    spec_path: Path,
    *,
    ids: tuple[str, ...],
    fixture_semantic_sha256: str,
    repetitions: int = 1,
) -> dict[str, Any]:
    spec = validate_run_spec(spec_path)
    reproduction = spec["reproduction"]
    execution = reproduction["execution"]
    model = reproduction["model"]
    harness = get_harness("mcpmark")
    expected_harness = f"{harness.commit}+patch-sha256:{PATCH_SHA256}"
    expected_state = f"fixture-semantic-sha256:{fixture_semantic_sha256}"
    if spec["preregistration"]["live_test_approved"] is not True:
        raise PairRunError("run spec does not approve live model calls")
    if tuple(execution["ordered_workload_ids"]) != ids:
        raise PairRunError("run spec workload order differs from the selected profile")
    if execution["workload_ids_sha256"] != _workload_hash(ids):
        raise PairRunError("run spec workload digest differs from the selected profile")
    if execution["repetitions"] != repetitions or execution["max_concurrency"] != 1:
        raise PairRunError(
            f"paired runner requires repetitions={repetitions} and max_concurrency=1"
        )
    if reproduction["harness"]["revision"] != expected_harness:
        raise PairRunError("run spec harness revision does not bind the verifier patch")
    if reproduction["environment"]["initial_state_ref"] != expected_state:
        raise PairRunError("run spec initial_state_ref does not match the semantic fixture tree")
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


def _validate_tool_cap_spec(
    spec_path: Path,
    *,
    fixture_semantic_sha256: str,
) -> dict[str, Any]:
    spec = _validate_spec(
        spec_path,
        ids=TOOL_CAP_IDS,
        fixture_semantic_sha256=fixture_semantic_sha256,
        repetitions=TOOL_CAP_REPETITIONS,
    )
    reproduction = spec["reproduction"]
    execution = reproduction["execution"]
    model = reproduction["model"]
    comparison = reproduction["comparison"]
    study = spec["study"]
    if spec["preregistration"]["mode"] != "prospective":
        raise PairRunError("tool-result cap profile requires prospective preregistration")
    if _workload_hash(TOOL_CAP_IDS) != TOOL_CAP_SHA256:
        raise PairRunError("tool-result cap workload identity mismatch")
    if (
        model["label"],
        model["reasoning"],
        int(execution["timeout_seconds"]),
    ) != ("gpt-5.4", "high", TOOL_CAP_TIMEOUT_SECONDS):
        raise PairRunError("tool-result cap profile requires GPT-5.4/high and timeout=1200")
    if execution["seed_schedule"] != [
        "upstream-run-1",
        "upstream-run-2",
        "upstream-run-3",
    ]:
        raise PairRunError("tool-result cap profile requires the frozen repetition labels")
    if execution["budget"] != {
        "kind": "wall-time",
        "limit": TOOL_CAP_TIMEOUT_SECONDS,
        "unit": "seconds",
    }:
        raise PairRunError("tool-result cap profile requires the frozen wall-time budget")
    if comparison["claim_class"] != "diagnostic" or comparison["promotion_authority"] != "none":
        raise PairRunError("tool-result cap profile is diagnostic-only")
    if study["research_question"] != (
        "Does removing the 25K tool-result guard on the same large-result MCP tasks "
        "increase verifier accuracy and change rereads, fresh input tokens, and wall time?"
    ):
        raise PairRunError("tool-result cap profile requires the frozen research question")
    if study["hypothesis"] != (
        "Across 15 task-repetitions per arm, unlimited-0 produces more verifier passes "
        "than guard-25000."
    ):
        raise PairRunError("tool-result cap profile requires the frozen hypothesis")
    if study["primary_metric"] != {
        "name": "verifier-pass-rate arm delta",
        "unit": "ratio",
        "direction": "target",
        "aggregation": "(sum(unlimited-0 passes) - sum(guard-25000 passes)) / 15",
        "denominator": 15,
    }:
        raise PairRunError("tool-result cap profile requires the frozen primary metric")
    if study["decision_rule"] != (
        "supported if unlimited-0 passes exceed guard-25000 passes; "
        "mixed if equal; not-supported if lower"
    ):
        raise PairRunError("tool-result cap profile requires the frozen decision rule")
    if study["invalidation_rule"] != (
        "Invalidate the run if any attempt changes the frozen deadline or identity contract, "
        "cannot bind the arm cap or reconstruct truncation, fails fixture cleanup or reset, "
        "lacks native result, verifier, or trajectory evidence, or exits on an unrecovered "
        "provider quota or transport error."
    ):
        raise PairRunError("tool-result cap profile requires the frozen invalidation rule")
    if study["analysis_plan"] != (
        "Select all 30 fresh attempts; compute the signed verifier-pass-rate arm delta as "
        "(unlimited-0 passes - guard-25000 passes) / 15; report secondary token, wall-time, "
        "MCP call/error, reread, and truncation metrics for explanation only; preserve "
        "infrastructure-invalid attempts and do not replace or score them."
    ):
        raise PairRunError("tool-result cap profile requires the frozen analysis plan")
    return spec


def _pair_primary_metric(*, denominator: int, smoke: bool = False) -> dict[str, Any]:
    if smoke:
        return {
            "name": "accepted paired-task coverage",
            "unit": "ratio",
            "direction": "maximize",
            "aggregation": "accepted paired tasks / 1",
            "denominator": 1,
        }
    return {
        "name": "GEODE minus Codex verifier-pass-rate delta",
        "unit": "ratio",
        "direction": "target",
        "aggregation": f"(sum(geode passes) - sum(codex passes)) / {denominator}",
        "denominator": denominator,
    }


def _pair_study_contract(*, denominator: int, smoke: bool) -> dict[str, Any]:
    invalidation_rule = (
        "Invalidate the run if any arm changes the frozen deadline, model, route, tool schema, "
        "task, semantic fixture, verifier, reset identity, or the GEODE 25K tool-result cap; "
        "fails fixture cleanup; lacks native result, verifier, deadline, or trajectory evidence; "
        "or exits on an unrecovered provider quota or transport error."
    )
    if smoke:
        return {
            "research_question": (
                "Can one frozen MCPMark Filesystem task complete through both GEODE and Codex "
                "with matching semantic fixture, reset, verifier, tool schema, trajectory, and "
                "common-deadline evidence?"
            ),
            "research_gap": (
                "The corrective Filesystem-30 run needs a no-resume paired canary under the exact "
                "public runner before spending quota on 60 arms."
            ),
            "hypothesis": (
                "Both arms produce complete identity, reset, verifier, deadline, and trajectory "
                "receipts without infrastructure contamination."
            ),
            "primary_metric": _pair_primary_metric(denominator=denominator, smoke=True),
            "decision_rule": ("clean if the accepted paired-task coverage is 1; blocked otherwise"),
            "invalidation_rule": invalidation_rule,
            "analysis_plan": (
                "Select the paired smoke only when both fresh arms are infrastructure-valid; "
                "report receipt completeness and native verifier outcomes without making a "
                "performance claim."
            ),
        }
    return {
        "research_question": (
            "On the same 30 MCPMark Filesystem tasks, semantic fixture state, verifier, GPT-5.4/"
            "high subscription route, and common timed action surface, how do GEODE and Codex "
            "differ in verifier accuracy?"
        ),
        "research_gap": (
            "The prior 30-task observation used different timeout start boundaries and its "
            "fixture receipt did not bind score-bearing file mtimes or empty directories."
        ),
        "hypothesis": (
            "Across the frozen 30-task workload, GEODE verifier accuracy is no more than 10 "
            "percentage points below Codex verifier accuracy."
        ),
        "primary_metric": _pair_primary_metric(denominator=denominator),
        "decision_rule": (
            "supported if the GEODE-minus-Codex verifier-pass-rate delta is at least -0.10; "
            "not-supported if lower"
        ),
        "invalidation_rule": invalidation_rule,
        "analysis_plan": (
            "Select all 60 fresh arms only when all 30 pairs are infrastructure-valid; compute "
            "(GEODE passes - Codex passes) / 30; report arm accuracy, paired wins, losses, ties, "
            "cache-excluded input, output, reasoning, wall time, MCP calls and errors, repeated "
            "reads, and termination classes; preserve invalid attempts and do not replace or "
            "score them."
        ),
    }


def _validate_pair_spec(
    spec_path: Path,
    *,
    ids: tuple[str, ...],
    fixture_semantic_sha256: str,
    smoke: bool,
) -> dict[str, Any]:
    spec = _validate_spec(
        spec_path,
        ids=ids,
        fixture_semantic_sha256=fixture_semantic_sha256,
    )
    reproduction = spec["reproduction"]
    execution = reproduction["execution"]
    model = reproduction["model"]
    comparison = reproduction["comparison"]
    study = spec["study"]
    if spec["preregistration"]["mode"] != "prospective":
        raise PairRunError("GEODE/Codex pair requires prospective preregistration")
    if (model["label"], model["reasoning"], int(execution["timeout_seconds"])) != (
        "gpt-5.4",
        "high",
        PAIR_TIMEOUT_SECONDS,
    ):
        raise PairRunError("GEODE/Codex pair requires GPT-5.4/high and timeout=1200")
    if execution["seed_schedule"] != ["upstream-run-1"] or execution["budget"] != {
        "kind": "wall-time",
        "limit": PAIR_TIMEOUT_SECONDS,
        "unit": "seconds",
    }:
        raise PairRunError("GEODE/Codex pair requires the frozen run label and wall-time budget")
    expected_comparison = {
        "claim_class": "smoke" if smoke else "diagnostic",
        "comparator": CODEX_COMPARATOR,
        "comparability": "direct",
        "promotion_authority": "none",
    }
    if comparison != expected_comparison:
        raise PairRunError("GEODE/Codex pair has a mismatched comparison contract")
    expected_study = _pair_study_contract(denominator=len(ids), smoke=smoke)
    for field, expected in expected_study.items():
        if study[field] != expected:
            raise PairRunError(f"GEODE/Codex pair requires the frozen {field.replace('_', ' ')}")
    return spec


def _arm_order(task_index: int) -> tuple[str, str]:
    return ("geode", "codex") if task_index % 2 else ("codex", "geode")


def _tool_cap_arm_order(task_index: int, repetition: int) -> tuple[tuple[str, int], ...]:
    return TOOL_CAP_ARMS if (task_index + repetition) % 2 == 0 else TOOL_CAP_ARMS[::-1]


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
    expected_tool_cap: int | None = None,
    expected_tool_schema_sha256: str | None = None,
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
    runtime_config = receipt.get("runtime_config")
    if expected_tool_schema_sha256 is not None and (
        not isinstance(runtime_config, dict)
        or runtime_config.get("tool_schema_sha256") != expected_tool_schema_sha256
    ):
        raise PairRunError("deadline receipt tool schema mismatch")
    if expected_tool_cap is not None and (
        not isinstance(runtime_config, dict)
        or runtime_config.get("max_tool_result_tokens") != expected_tool_cap
        or runtime_config.get("offload_store_bound") is not False
    ):
        raise PairRunError("deadline receipt runtime configuration mismatch")
    return receipt


def _truncation_count(path: Path, *, max_tokens: int) -> int:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PairRunError("native execution log is unreadable") from exc
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise PairRunError("native execution log must contain tool-call objects")
    if len(rows) >= ToolCallProcessor.MAX_TOOL_LOG_ENTRIES:
        raise PairRunError("native execution log reached the tool-log retention cap")
    count = 0
    for row in rows:
        result = row.get("result")
        if not isinstance(result, dict):
            raise PairRunError("native execution log contains an unknown tool-result shape")
        projected = _project_mcp_result(result)
        guarded = _guard_tool_result(projected, max_tokens=max_tokens)
        count += int(guarded is not projected)
    return count


def _native_receipt(
    native_dir: Path,
    *,
    task: str,
    arm: str,
    model: str,
    effort: str,
    timeout: int,
    expected_tool_cap: int | None = None,
    expected_tool_schema_sha256: str | None = None,
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
    agent_error = result.get("error_message")
    model_config = summary.get("model_config")
    successful_tasks = summary.get("successful_tasks")
    failed_tasks = summary.get("failed_tasks")
    if (
        summary.get("total_tasks") != 1
        or not isinstance(successful_tasks, int)
        or isinstance(successful_tasks, bool)
        or successful_tasks != int(result["success"])
        or not isinstance(failed_tasks, int)
        or isinstance(failed_tasks, bool)
        or failed_tasks != int(not result["success"])
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
    deadline = _deadline_receipt(
        deadline_path,
        arm=arm,
        timeout=timeout,
        expected_tool_cap=expected_tool_cap,
        expected_tool_schema_sha256=expected_tool_schema_sha256,
    )
    timeout_errors = {
        "geode": {
            "time_budget_expired",
            f"GEODE exceeded MCPMark action deadline ({timeout}s)",
        },
        "codex": {f"codex exec exceeded MCPMark action deadline ({timeout}s)"},
    }
    if (
        deadline["expired"]
        and (not isinstance(agent_error, str) or agent_error not in timeout_errors.get(arm, set()))
    ) or (not deadline["expired"] and agent_error not in (None, "")):
        raise PairRunError("native agent error lacks a score-bearing failure class")
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
    receipt = {
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
    if expected_tool_cap is not None:
        receipt["tool_result_truncation_count"] = _truncation_count(
            execution_log_path,
            max_tokens=expected_tool_cap,
        )
    return receipt


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
    max_tool_result_tokens: int | None = None,
    codex_executable: Path | None = None,
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
    if max_tool_result_tokens is not None:
        env["GEODE_MAX_TOOL_RESULT_TOKENS"] = str(max_tool_result_tokens)
    if codex_executable is not None:
        env["GEODE_MCPMARK_CODEX_BIN"] = str(codex_executable)
    env.setdefault("OPENAI_API_KEY", "dummy")
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(REPO_ROOT), env.get("PYTHONPATH", "")) if value
    )
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        result = _run_process(
            command,
            cwd=mcpmark_root,
            env=env,
            stdout=stdout,
            stderr=stderr,
        )
        stdout.flush()
        stderr.flush()
        os.fsync(stdout.fileno())
        os.fsync(stderr.fileno())
    return result.returncode, stdout_path, stderr_path


def _execution_schedule(
    profile: str,
    ids: tuple[str, ...],
) -> tuple[tuple[int, int, str, str, str, int | None, bool], ...]:
    if profile == TOOL_CAP_PROFILE:
        return tuple(
            (repetition, index, task, label, "geode", cap, position == 0)
            for repetition in range(1, TOOL_CAP_REPETITIONS + 1)
            for index, task in enumerate(ids, start=1)
            for position, (label, cap) in enumerate(_tool_cap_arm_order(index, repetition))
        )
    return tuple(
        (
            1,
            index,
            task,
            arm,
            arm,
            PAIR_MAX_TOOL_RESULT_TOKENS if arm == "geode" else None,
            position == 0,
        )
        for index, task in enumerate(ids, start=1)
        for position, arm in enumerate(_arm_order(index))
    )


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
    tool_schema_sha256: str,
    profile: str = PAIR_PROFILE,
    codex_executable: Path | None = None,
) -> None:
    events_path = output_dir / "runner-events.jsonl"
    fixture_rows = {row["category"]: row for row in fixture["categories"]}
    if _has_backups(mcpmark_root):
        raise PairRunError("MCPMark backup directory is not empty before the paired run")
    sequence = 0
    task_hashes: dict[str, str] = {}
    schedule = _execution_schedule(profile, ids)
    arm_results: dict[str, dict[str, int]] = {}

    def emit(event: str, **payload: Any) -> None:
        nonlocal sequence
        _append_event(
            events_path,
            {"sequence": sequence, "event": event, "recorded_at": _utc_now(), **payload},
        )
        sequence += 1

    emit(
        "run_started",
        profile=profile,
        task_count=len(ids),
        arm_count=2,
        repetitions=TOOL_CAP_REPETITIONS if profile == TOOL_CAP_PROFILE else 1,
    )
    try:
        for repetition, index, task, arm_label, native_agent, cap, arm_first in schedule:
            category = task.split("/", 1)[0]
            if (
                _tree_row(
                    mcpmark_root / "test_environments" / category,
                    category=category,
                )
                != fixture_rows[category]
            ):
                raise PairRunError("source fixture changed between paired arms")
            prefix = f"r{repetition}-" if profile == TOOL_CAP_PROFILE else ""
            arm_key = f"{prefix}{index:02d}-{task.replace('/', '__')}--{arm_label}"
            native_dir = output_dir / "native-results" / arm_key
            log_dir = output_dir / "runner-logs" / arm_key
            started = time.monotonic_ns()
            common = {
                "repetition": repetition,
                "task_index": index,
                "task": task,
                "arm": arm_label,
                "native_agent": native_agent,
                "max_tool_result_tokens": cap,
            }
            emit(
                "arm_started",
                **common,
                arm_first=arm_first,
                native_output=f"native-results/{arm_key}",
            )
            try:
                returncode, stdout_path, stderr_path = _invoke_arm(
                    python=python,
                    mcpmark_root=mcpmark_root,
                    native_dir=native_dir,
                    log_dir=log_dir,
                    task=task,
                    arm=native_agent,
                    model_label=model_label,
                    effort=effort,
                    timeout=timeout,
                    run_id=run_id,
                    max_tool_result_tokens=cap,
                    codex_executable=codex_executable if native_agent == "codex" else None,
                )
                if returncode:
                    raise PairRunError(f"native MCPMark subprocess exited {returncode}")
                receipt = _native_receipt(
                    native_dir,
                    task=task,
                    arm=native_agent,
                    model=f"{native_agent}-{model_label}",
                    effort=effort,
                    timeout=timeout,
                    expected_tool_cap=(
                        cap if profile == TOOL_CAP_PROFILE or native_agent == "geode" else None
                    ),
                    expected_tool_schema_sha256=(
                        tool_schema_sha256 if native_agent == "geode" else None
                    ),
                )
                current_task_sha256 = str(receipt.pop("task_sha256"))
                prior_task_sha256 = task_hashes.setdefault(task, current_task_sha256)
                if current_task_sha256 != prior_task_sha256:
                    raise PairRunError("paired arms used different task instruction hashes")
                if _has_backups(mcpmark_root):
                    raise PairRunError("native MCPMark left a fixture backup behind")
                if (
                    _tree_row(
                        mcpmark_root / "test_environments" / category,
                        category=category,
                    )
                    != fixture_rows[category]
                ):
                    raise PairRunError("source fixture changed during a paired arm")
                arm_result = arm_results.setdefault(arm_label, {"attempts": 0, "passes": 0})
                arm_result["attempts"] += 1
                arm_result["passes"] += int(receipt["verifier_pass"])
                emit(
                    "arm_finished",
                    **common,
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
                    **common,
                    failure_class="infrastructure",
                    exception_type=type(exc).__name__,
                    exception_sha256=hashlib.sha256(str(exc).encode()).hexdigest(),
                )
                raise
    except PairRunError:
        raise
    except BaseException as exc:
        raise PairRunError("paired MCPMark runner interrupted") from exc
    emit(
        "run_completed",
        completed_tasks=len(schedule) // 2,
        completed_arms=len(schedule),
    )
    result: dict[str, Any] = {
        "schema_id": "geode.mcpmark-paired-runner-result@1",
        "run_id": run_id,
        "profile": profile,
        "arms": arm_results,
        "source_events": {
            "path": events_path.name,
            "sha256": _sha256(events_path),
        },
    }
    if profile == TOOL_CAP_PROFILE:
        denominator = len(ids) * TOOL_CAP_REPETITIONS
        if set(arm_results) != {"guard-25000", "unlimited-0"} or any(
            row["attempts"] != denominator for row in arm_results.values()
        ):
            raise PairRunError("tool-result cap result has an incomplete arm denominator")
        numerator = arm_results["unlimited-0"]["passes"] - arm_results["guard-25000"]["passes"]
        result["primary_metric"] = {
            "name": "verifier-pass-rate arm delta",
            "value": numerator / denominator,
            "numerator": numerator,
            "denominator": denominator,
        }
    elif profile in {PAIR_PROFILE, PAIR_SMOKE_PROFILE}:
        denominator = len(ids)
        if set(arm_results) != {"geode", "codex"} or any(
            row["attempts"] != denominator for row in arm_results.values()
        ):
            raise PairRunError("GEODE/Codex pair result has an incomplete arm denominator")
        smoke = profile == PAIR_SMOKE_PROFILE
        numerator = (
            denominator
            if smoke
            else arm_results["geode"]["passes"] - arm_results["codex"]["passes"]
        )
        result["primary_metric"] = {
            "name": _pair_primary_metric(denominator=denominator, smoke=smoke)["name"],
            "value": numerator / denominator,
            "numerator": numerator,
            "denominator": denominator,
        }
    _write_exclusive_json(output_dir / "runner-result.json", result)


def run_pair(
    *,
    run_spec_path: Path,
    mcpmark_root: Path,
    output_dir: Path,
    python: Path,
    profile: str = PAIR_PROFILE,
    task: str | None = None,
) -> None:
    if output_dir.exists():
        raise PairRunError("output directory must not exist; retries use a fresh attempt root")
    run_spec_sha256 = _sha256(run_spec_path)
    _validate_checkout(mcpmark_root)
    full_ids = _discover_workload(mcpmark_root)
    fixture = _fixture_receipt(mcpmark_root, full_ids)
    if profile == PAIR_PROFILE:
        if task is not None:
            raise PairRunError("the Filesystem-30 profile does not accept --task")
        ids = full_ids
        spec = _validate_pair_spec(
            run_spec_path,
            ids=ids,
            fixture_semantic_sha256=fixture["semantic_aggregate_sha256"],
            smoke=False,
        )
    elif profile == PAIR_SMOKE_PROFILE:
        if task is None or task not in full_ids:
            raise PairRunError("the paired smoke profile requires one Filesystem-30 --task")
        ids = (task,)
        spec = _validate_pair_spec(
            run_spec_path,
            ids=ids,
            fixture_semantic_sha256=fixture["semantic_aggregate_sha256"],
            smoke=True,
        )
    elif profile == TOOL_CAP_PROFILE:
        if task is not None:
            raise PairRunError("the tool-result cap profile does not accept --task")
        if any(task not in full_ids for task in TOOL_CAP_IDS):
            raise PairRunError("tool-result cap profile task is absent from Filesystem-30")
        ids = TOOL_CAP_IDS
        spec = _validate_tool_cap_spec(
            run_spec_path,
            fixture_semantic_sha256=fixture["semantic_aggregate_sha256"],
        )
    else:
        raise PairRunError(f"unsupported MCPMark paired-runner profile: {profile}")
    reproduction = spec["reproduction"]
    execution = reproduction["execution"]
    model = reproduction["model"]
    python_preflight = _python_preflight(python, mcpmark_root)
    codex_preflight = (
        _codex_cli_preflight(mcpmark_root)
        if profile in {PAIR_PROFILE, PAIR_SMOKE_PROFILE}
        else None
    )
    codex_cli = codex_preflight[0] if codex_preflight is not None else None
    codex_executable = codex_preflight[1] if codex_preflight is not None else None
    tool_schema_sha256 = _probe_filesystem_tool_schema(python, mcpmark_root)
    run_spec_bytes = run_spec_path.read_bytes()
    if hashlib.sha256(run_spec_bytes).hexdigest() != run_spec_sha256:
        raise PairRunError("run spec changed during paired-run preflight")
    output_dir.mkdir(parents=True)
    with (output_dir / "run-spec.json").open("xb") as handle:
        handle.write(run_spec_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    plan: dict[str, Any] = {
        "schema_id": "geode.mcpmark-paired-runner-plan@1",
        "profile": profile,
        "run_id": spec["run_id"],
        "created_at": _utc_now(),
        "run_spec_sha256": run_spec_sha256,
        "geode_revision": reproduction["geode"]["revision"],
        "harness_revision": reproduction["harness"]["revision"],
        "workload_ids": ids,
        "workload_ids_sha256": _workload_hash(ids),
        "fixture": fixture,
        "model": model["label"],
        "route": model["route"],
        "reasoning_effort": model["reasoning"],
        "timeout_seconds": int(execution["timeout_seconds"]),
        "max_concurrency": 1,
        "python_preflight": python_preflight,
        "tool_schema_sha256": tool_schema_sha256,
    }
    if codex_cli is not None:
        plan["codex_cli"] = codex_cli
    if profile == TOOL_CAP_PROFILE:
        plan.update(
            {
                "repetitions": TOOL_CAP_REPETITIONS,
                "arms": [
                    {
                        "label": label,
                        "native_agent": "geode",
                        "environment": {"GEODE_MAX_TOOL_RESULT_TOKENS": str(cap)},
                    }
                    for label, cap in TOOL_CAP_ARMS
                ],
                "arm_order": (
                    "repetition-major; A first when (task_index + repetition) is even; "
                    "A=guard-25000, B=unlimited-0"
                ),
            }
        )
    else:
        plan.update(
            {
                "repetitions": 1,
                "arm_order": "odd:geode,codex;even:codex,geode",
                "arms": [
                    {
                        "label": "geode",
                        "environment": {
                            "GEODE_MAX_TOOL_RESULT_TOKENS": str(PAIR_MAX_TOOL_RESULT_TOKENS)
                        },
                    },
                    {"label": "codex", "environment": {}},
                ],
            }
        )
    _write_exclusive_json(output_dir / "runner-plan.json", plan)
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
        tool_schema_sha256=tool_schema_sha256,
        profile=profile,
        codex_executable=codex_executable,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=(PAIR_PROFILE, PAIR_SMOKE_PROFILE, TOOL_CAP_PROFILE),
        default=PAIR_PROFILE,
    )
    parser.add_argument("--task")
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
            python=args.python.absolute(),
            profile=args.profile,
            task=args.task,
        )
    except PairRunError as exc:
        print(f"MCPMark paired run stopped: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
