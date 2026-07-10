"""Thin Codex subscription producer grounded by a bounded knowledge-graph slice."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

_REQUEST_SCHEMA = "crucible.proposal-request.v3"
_CANDIDATE_SCHEMA = "crucible.candidate.v2"
_GRAPH_LIMIT = 128 * 1024 * 1024
_CONTEXT_NODE_LIMIT = 16


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


def knowledge_context(path: Path, surfaces: tuple[str, ...]) -> str:
    """Select local and one-hop graph summaries without exposing task artifacts."""

    graph = _load_object(path, "knowledge graph", limit=_GRAPH_LIMIT)
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
    surface_parents = {PurePosixPath(surface).parent.as_posix() for surface in surfaces}
    selected_ids = {
        node_id
        for node_id, node in by_id.items()
        if _node_path(node) in surfaces
        or PurePosixPath(_node_path(node)).parent.as_posix() in surface_parents
    }
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
    feedback_row = feedback if isinstance(feedback, Mapping) else {}
    failure_codes = feedback_row.get("failure_codes", [])
    return f"""\
Task: propose one small, task-independent agent-policy improvement.
Runtime: Crucible candidate producer in a disposable no-remote checkout.
Model target: GPT-5.4 subscription, high reasoning.
Objective: {objective}
Allowed mutation surface: {json.dumps(surfaces)}
Prior closed failure codes: {json.dumps(failure_codes)}

Constraints:
- Edit exactly one allowed file and no other file.
- Keep the change general across tasks and domains; CANNOT add task IDs, expected
  answers, scenario literals, row-specific branches, or benchmark-specific facts.
- Preserve safety, confirmation, and tool-contract requirements.
- Prefer deleting or tightening wording over adding a large policy ladder.
- CANNOT run live/provider tests; CANNOT commit because the producer wrapper owns commit.

Bounded architecture context:
{graph_context}

Inspect the allowed file and its caller, then make the smallest defensible edit.
"""


def _write_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run() -> int:
    request_path = Path(os.environ["CRUCIBLE_PROPOSAL_REQUEST"])
    output_path = Path(os.environ["CRUCIBLE_CANDIDATE_OUTPUT"])
    graph_path = Path(os.environ["CRUCIBLE_KNOWLEDGE_GRAPH"])
    objective = _text(os.environ.get("CRUCIBLE_PRODUCER_OBJECTIVE"), "producer objective")
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
        graph_context=knowledge_context(graph_path, surfaces),
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
