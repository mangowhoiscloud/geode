"""Self-improving tools contributed to the product-composed MCP server."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.memory.atomic_write import iter_jsonl

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_STATUS_RECENT_N = 5
_TOOL_DESCRIPTIONS = json.loads(
    resources.files(__package__).joinpath("mcp_tools.json").read_text(encoding="utf-8")
)


def _status_payload() -> dict[str, Any]:
    """Read the promoted baseline and recent mutation rows."""
    import core.paths

    audit_path = Path(core.paths.MUTATION_AUDIT_LOG_PATH)
    baseline_path = Path(core.paths.BASELINE_JSON_PATH)
    baseline: dict[str, Any] | None = None
    if baseline_path.is_file():
        try:
            parsed = json.loads(baseline_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                baseline = {
                    "fitness": parsed.get("fitness"),
                    "ts_utc": parsed.get("ts_utc") or parsed.get("timestamp"),
                    "session_id": parsed.get("session_id"),
                    "schema_version": parsed.get("schema_version"),
                }
        except (OSError, json.JSONDecodeError):
            pass

    recent = [
        {
            "ts": row.get("ts") or row.get("timestamp"),
            "kind": row.get("kind") or "applied",
            "mutation_id": row.get("mutation_id") or row.get("id"),
            "target_kind": row.get("target_kind"),
            "target_section": row.get("target_section"),
        }
        for row in iter_jsonl(audit_path)
    ][-_STATUS_RECENT_N:]
    return {"baseline": baseline, "recent_mutations": recent}


def register_mcp_tools(mcp: FastMCP) -> None:
    """Register the product's status and two-step mutation tools."""
    pending: dict[str, tuple[Any, Any]] = {}

    @mcp.tool(description=_TOOL_DESCRIPTIONS["self_improving_status"])
    def self_improving_status() -> dict[str, Any]:
        return _status_payload()

    @mcp.tool(description=_TOOL_DESCRIPTIONS["self_improving_propose"])
    def self_improving_propose() -> dict[str, Any]:
        from evolve.scaffold_search.loop.mutate.runner import SelfImprovingLoopRunner

        runner = SelfImprovingLoopRunner(rerun_enabled=False, commit_enabled=True)
        proposal = runner.propose()
        mutation = proposal.mutation
        pending[mutation.mutation_id] = (runner, proposal)
        return {
            "mutation_id": mutation.mutation_id,
            "target_kind": mutation.target_kind,
            "target_section": mutation.target_section,
            "previous_value": proposal.target_sections.get(mutation.target_section, ""),
            "new_value": mutation.new_value,
            "rationale": mutation.rationale,
            "baseline_fitness": proposal.baseline_fitness,
            "next_step": "call self_improving_apply with this mutation_id to write it",
        }

    @mcp.tool(description=_TOOL_DESCRIPTIONS["self_improving_apply"])
    def self_improving_apply(mutation_id: str) -> dict[str, Any]:
        entry = pending.pop(mutation_id, None)
        if entry is None:
            return {
                "applied": False,
                "error": (
                    f"no pending proposal {mutation_id!r} in this server session — "
                    "call self_improving_propose first"
                ),
            }
        runner, proposal = entry
        runner.apply_proposal(proposal)
        return {"applied": True, "mutation_id": mutation_id}
