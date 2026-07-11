"""Thin Codex subscription producer grounded by a bounded knowledge-graph slice."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

_REQUEST_SCHEMA = "crucible.proposal-request.v3"
_CANDIDATE_SCHEMA = "crucible.candidate.v2"
_GRAPH_SCHEMA = "crucible.producer-graph.v1"
_FEEDBACK_SCHEMA = "crucible.failure-feedback.v3"
_SUPERVISOR_FEEDBACK_SCHEMA = "crucible.supervisor-feedback.v3"
_GRAPH_LIMIT = 256 * 1024
_PROGRAM_LIMIT = 64 * 1024
_CONTEXT_NODE_LIMIT = 16
_CLOSED_FAILURE_CODES = frozenset(
    {
        "quality",
        "required_user_action",
        "safety",
        "state_correctness",
        "termination",
        "tool_contract",
        "workflow_completion",
    }
)
_DEFAULT_GRAPH_PATH = Path(__file__).with_name("context_graph.json")
_DEFAULT_PROGRAM_PATH = Path(__file__).parent.parent / "program.md"
_PROGRAM_TOKEN_RE: re.Pattern[str] = re.compile(r"\{\{[a-z_]+\}\}")
_PROGRAM_SECTION_RE: re.Pattern[str] = re.compile(
    r"<candidate_program>(.*?)</candidate_program>", re.DOTALL
)
_PROGRAM_TOKENS = frozenset(
    {
        "{{failure_codes_json}}",
        "{{graph_context}}",
        "{{objective}}",
        "{{surfaces_json}}",
    }
)
_DEFAULT_OBJECTIVE = (
    "Complete every policy-required step in multi-step tool workflows, including "
    "required user actions, confirmations, state changes, and terminal verification, "
    "without redundant repetition."
)


class ProducerError(RuntimeError):
    """A candidate cannot be emitted without violating the producer contract."""


def _load_object(path: Path, field: str, *, limit: int = 1024 * 1024) -> dict[str, Any]:
    info = path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_size > limit:
        raise ProducerError(f"{field} must be a bounded regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProducerError(f"{field} must be an object")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProducerError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_policy_grammar(policy: str) -> None:
    """Keep the candidate surface on one machine-checkable clause grammar."""

    lines = policy.splitlines()
    if lines.count("Behavior:") != 1:
        raise ProducerError("candidate policy requires exactly one Behavior section")
    behavior_index = lines.index("Behavior:")
    clauses = [line for line in lines[behavior_index + 1 :] if line.strip()]
    if not clauses:
        raise ProducerError("candidate policy requires behavior clauses")
    invalid = [line for line in clauses if not line.startswith(("- CAN ", "- CANNOT "))]
    if invalid:
        raise ProducerError("candidate policy clauses must use CAN/CANNOT grammar")


def _load_program(path: Path = _DEFAULT_PROGRAM_PATH) -> str:
    """Load the model-facing section of the tracked central program."""

    info = path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_size > _PROGRAM_LIMIT:
        raise ProducerError("candidate program must be a bounded regular file")
    source = path.read_text(encoding="utf-8")
    sections = _PROGRAM_SECTION_RE.findall(source)
    if len(sections) != 1:
        raise ProducerError("candidate program requires exactly one candidate_program section")
    program = str(sections[0]).strip()
    observed = _PROGRAM_TOKEN_RE.findall(program)
    if set(observed) != _PROGRAM_TOKENS or any(
        observed.count(token) != 1 for token in _PROGRAM_TOKENS
    ):
        raise ProducerError(
            "candidate program placeholders do not match the frozen template contract"
        )
    return program


def _render_program(
    *,
    objective: str,
    surfaces: tuple[str, ...],
    failure_codes: list[str],
    graph_context: str,
) -> str:
    program = _load_program()
    replacements = {
        "{{failure_codes_json}}": json.dumps(failure_codes),
        "{{graph_context}}": graph_context,
        "{{objective}}": objective,
        "{{surfaces_json}}": json.dumps(surfaces),
    }
    for token, value in replacements.items():
        program = program.replace(token, value)
    return program


def _git(*args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ProducerError("git executable is required")
    result = subprocess.run(  # noqa: S603 - fixed git executable, wrapper-owned argv
        [executable, *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ProducerError(result.stderr.strip() or "git operation failed")
    return result.stdout.strip()


def _node_path(node: Mapping[str, Any]) -> str:
    raw = node.get("filePath")
    return raw.strip() if isinstance(raw, str) else ""


def _source_digest(repository: Path, relative: str) -> str:
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ProducerError(f"knowledge graph source is not repository-relative: {relative}")
    source = (repository / relative).resolve()
    try:
        source.relative_to(repository)
    except ValueError as exc:
        raise ProducerError(f"knowledge graph source escapes the repository: {relative}") from exc
    if source.is_symlink() or not source.is_file():
        raise ProducerError(f"knowledge graph source is not a regular file: {relative}")
    return sha256(source.read_bytes()).hexdigest()


def knowledge_context(
    path: Path,
    surfaces: tuple[str, ...],
    *,
    repository: Path | None = None,
) -> str:
    """Select a source-attested local and one-hop architecture subgraph."""

    graph = _load_object(path, "knowledge graph", limit=_GRAPH_LIMIT)
    if graph.get("schema") != _GRAPH_SCHEMA:
        raise ProducerError(f"knowledge graph must use {_GRAPH_SCHEMA}")
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ProducerError("knowledge graph requires nodes and edges arrays")
    nodes = [node for node in raw_nodes if isinstance(node, Mapping)]
    by_id = {
        str(node.get("id")): node
        for node in nodes
        if isinstance(node.get("id"), str) and node.get("id")
    }
    if len(by_id) != len(nodes):
        raise ProducerError("knowledge graph node IDs must be unique non-empty strings")
    source_root = (repository or Path.cwd()).resolve()
    for node_id, node in by_id.items():
        relative = _node_path(node)
        expected = node.get("contentSha256")
        if (
            not relative
            or not isinstance(expected, str)
            or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)
        ):
            raise ProducerError(f"knowledge graph node is not source-attested: {node_id}")
        if _source_digest(source_root, relative) != expected:
            raise ProducerError(f"knowledge graph source changed: {relative}")
    for edge in raw_edges:
        if not isinstance(edge, Mapping):
            raise ProducerError("knowledge graph edges must be objects")
        if edge.get("source") not in by_id or edge.get("target") not in by_id:
            raise ProducerError("knowledge graph edge references an unknown node")
    surface_parents = {PurePosixPath(surface).parent.as_posix() for surface in surfaces}
    selected_ids = {
        node_id
        for node_id, node in by_id.items()
        if _node_path(node) in surfaces
        or PurePosixPath(_node_path(node)).parent.as_posix() in surface_parents
    }
    if not any(_node_path(by_id[node_id]) in surfaces for node_id in selected_ids):
        raise ProducerError("knowledge graph does not attest the candidate surface")
    neighbor_ids: set[str] = set()
    for edge in raw_edges:
        if not isinstance(edge, Mapping):
            continue
        source, target = edge.get("source"), edge.get("target")
        if source in selected_ids and isinstance(target, str):
            neighbor_ids.add(target)
        if target in selected_ids and isinstance(source, str):
            neighbor_ids.add(source)
    ordered = [
        node
        for node_id, node in by_id.items()
        if node_id in selected_ids or node_id in neighbor_ids
    ][:_CONTEXT_NODE_LIMIT]
    project: Mapping[str, Any] = (
        graph["project"] if isinstance(graph.get("project"), Mapping) else {}
    )
    rows = [
        {
            "path": _node_path(node),
            "name": node.get("name"),
            "summary": node.get("summary"),
            "tags": node.get("tags"),
        }
        for node in ordered
    ]
    return json.dumps(
        {
            "project": {
                "name": project.get("name"),
                "description": project.get("description"),
            },
            "nodes": rows,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _usage_from_events(stdout: str) -> int:
    totals: list[int] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        stack: list[object] = [event]
        while stack:
            value = stack.pop()
            if isinstance(value, Mapping):
                total = value.get("total_tokens")
                if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
                    totals.append(total)
                input_tokens = value.get("input_tokens")
                output_tokens = value.get("output_tokens")
                if (
                    isinstance(input_tokens, int)
                    and not isinstance(input_tokens, bool)
                    and input_tokens >= 0
                    and isinstance(output_tokens, int)
                    and not isinstance(output_tokens, bool)
                    and output_tokens >= 0
                ):
                    totals.append(input_tokens + output_tokens)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    return max(totals, default=0)


def _prompt(
    *,
    objective: str,
    surfaces: tuple[str, ...],
    feedback: object,
    graph_context: str,
) -> str:
    failure_codes = _closed_failure_codes(feedback)
    return _render_program(
        objective=objective,
        surfaces=surfaces,
        failure_codes=failure_codes,
        graph_context=graph_context,
    )


def _closed_failure_codes(feedback: object) -> list[str]:
    """Project supervisor feedback onto the closed optimizer vocabulary."""

    if not isinstance(feedback, Mapping):
        return []
    row: object = feedback
    if feedback.get("schema") == _SUPERVISOR_FEEDBACK_SCHEMA:
        row = feedback.get("evaluator")
    if not isinstance(row, Mapping) or row.get("schema") != _FEEDBACK_SCHEMA:
        return []
    raw = row.get("failure_codes")
    if not isinstance(raw, list):
        return []
    return [code for code in raw if isinstance(code, str) and code in _CLOSED_FAILURE_CODES]


def _codex_child_environment() -> dict[str, str]:
    """Keep supervisor protocol paths outside the model-owned subprocess."""

    return {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("CRUCIBLE_") and name != "GEODE_STATE_ROOT"
    }


def _write_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run() -> int:
    request_path = Path(os.environ["CRUCIBLE_PROPOSAL_REQUEST"])
    output_path = Path(os.environ["CRUCIBLE_CANDIDATE_OUTPUT"])
    objective = _text(
        os.environ.get("CRUCIBLE_PRODUCER_OBJECTIVE", _DEFAULT_OBJECTIVE),
        "producer objective",
    )
    request = _load_object(request_path, "proposal request")
    if request.get("schema") != _REQUEST_SCHEMA:
        raise ProducerError(f"proposal request must use {_REQUEST_SCHEMA}")
    raw_surfaces = request.get("allowed_surfaces")
    if not isinstance(raw_surfaces, list) or len(raw_surfaces) != 1:
        raise ProducerError("Codex KG producer requires exactly one allowed surface")
    surfaces = tuple(_text(value, "allowed surface") for value in raw_surfaces)
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ProducerError("candidate checkout must start clean")
    executable = os.environ.get("CRUCIBLE_CODEX_EXECUTABLE") or shutil.which("codex")
    if not executable:
        raise ProducerError("codex executable is required")
    prompt = _prompt(
        objective=objective,
        surfaces=surfaces,
        feedback=request.get("feedback"),
        graph_context=knowledge_context(
            _DEFAULT_GRAPH_PATH,
            surfaces,
            repository=Path.cwd(),
        ),
    )
    model = os.environ.get("CRUCIBLE_CODEX_MODEL", "gpt-5.4")
    effort = os.environ.get("CRUCIBLE_CODEX_EFFORT", "high")
    started = time.monotonic()
    result = subprocess.run(  # noqa: S603 - operator-selected Codex executable
        [
            executable,
            "exec",
            "--model",
            model,
            "--config",
            f'model_reasoning_effort="{effort}"',
            "--sandbox",
            "workspace-write",
            "--ephemeral",
            "--ignore-user-config",
            "--color",
            "never",
            "--json",
            "-",
        ],
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
        env=_codex_child_environment(),
        timeout=float(request["remaining_budget"]["wall_seconds"]),
    )
    wall_seconds = time.monotonic() - started
    if result.returncode:
        detail = " ".join(result.stderr.split())[:2_000]
        raise ProducerError(detail or f"codex exited with status {result.returncode}")
    changed = tuple(path for path in _git("diff", "--name-only", "--").splitlines() if path.strip())
    if changed != surfaces:
        raise ProducerError(f"candidate must change exactly {surfaces!r}; observed {changed!r}")
    surface_path = Path(surfaces[0])
    if surface_path.is_symlink() or not surface_path.is_file():
        raise ProducerError("candidate surface must remain a regular file")
    if surface_path.stat().st_size > 16 * 1024:
        raise ProducerError("candidate surface exceeds 16384 bytes")
    _validate_policy_grammar(surface_path.read_text(encoding="utf-8"))
    _git("add", "--", *surfaces)
    _git("commit", "-qm", f"crucible: candidate {request['iteration']}")
    candidate_sha = _git("rev-parse", "HEAD")
    payload = {
        "schema": _CANDIDATE_SCHEMA,
        "attempt_id": request["attempt_id"],
        "request_id": request["request_id"],
        "parent_sha": request["parent_sha"],
        "candidate_sha": candidate_sha,
        "mutation": {
            "surface": surfaces[0],
            "hypothesis": objective[:500],
        },
        "usage": {
            "wall_seconds": wall_seconds,
            "calls": 1,
            "tokens": _usage_from_events(result.stdout),
            "cost_usd": 0.0,
        },
    }
    _write_exclusive(output_path, payload)
    return 0


def main() -> int:
    try:
        return run()
    except (KeyError, OSError, ValueError, json.JSONDecodeError, ProducerError) as exc:
        print(f"crucible Codex producer failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
