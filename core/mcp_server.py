"""GEODE MCP Server — expose GEODE's agentic + self-improving surface.

D-3 decision ④ (2026-06-10) promoted this module from a 2-tool analysis
shell (``query_memory`` / ``get_health``) to a first-class entry point —
``geode-mcp`` console script (stdio transport). Any MCP host (Claude Code,
Codex CLI, claude.ai connectors) can:

* ``run_agent`` — execute a GEODE agentic one-shot (same minimal stack as
  context:fork skill execution, ``core.cli.bootstrap.run_agentic_oneshot``).
* ``self_improving_status`` — read the promoted baseline + recent mutation
  ledger rows (same SoTs as the ``/self-improving status`` slash).
* ``self_improving_propose`` / ``self_improving_apply`` — drive the
  mutator's propose → confirm → apply cycle. Two separate tools on
  purpose: the MCP client *is* the confirmation gate (mirrors the slash's
  interactive y/N prompt), so a propose result must be explicitly echoed
  back via its ``mutation_id`` before anything is written.

Register in an MCP host (example, Claude Code):

    claude mcp add geode -- geode-mcp
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

# Load core-generic MCP tool descriptions from centralized JSON.
# Plugin-specific descriptions live alongside their plugin module.
_MCP_TOOLS_PATH = Path(__file__).resolve().parent / "tools" / "mcp_tools.json"
with _MCP_TOOLS_PATH.open(encoding="utf-8") as _f:
    _TOOL_DESCRIPTIONS: dict[str, str] = json.load(_f)

_STATUS_RECENT_N = 5


def _self_improving_status_payload() -> dict[str, Any]:
    """Read-only loop status — promoted baseline + recent mutation rows.

    Reads the same two SoTs as ``/self-improving status``: the *promoted*
    ``baseline.json`` (updated only when a mutation passes the gate — not
    a "latest measurement" file) and the tail of ``mutations.jsonl``.
    Missing files yield ``None`` / ``[]`` rather than raising so an MCP
    client can poll on a fresh clone.
    """
    from core.paths import MUTATION_AUDIT_LOG_PATH

    audit_path = Path(MUTATION_AUDIT_LOG_PATH)
    baseline_path = audit_path.parent / "baseline.json"

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
            baseline = None

    recent: list[dict[str, Any]] = []
    if audit_path.is_file():
        try:
            lines = audit_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                recent.append(
                    {
                        "ts": row.get("ts") or row.get("timestamp"),
                        "kind": row.get("kind") or "applied",
                        "mutation_id": row.get("mutation_id") or row.get("id"),
                        "target_kind": row.get("target_kind"),
                        "target_section": row.get("target_section"),
                    }
                )
        recent = recent[-_STATUS_RECENT_N:]

    return {"baseline": baseline, "recent_mutations": recent}


def create_mcp_server() -> Any:
    """Create and configure the GEODE MCP server.

    Returns a FastMCP Server instance with the agentic, self-improving,
    and memory tools/resources registered.

    Requires the ``mcp`` package to be installed.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise ImportError(
            "MCP server requires the 'mcp' package. Install with: uv add mcp"
        ) from None

    mcp = FastMCP("geode")

    # Shared ProjectMemory instance (created once per server lifetime)
    _project_memory: Any = None
    # Pending mutator proposals — propose() parks here keyed by mutation_id;
    # apply() consumes. The two-step contract is the MCP confirmation gate.
    _pending_proposals: dict[str, tuple[Any, Any]] = {}

    @mcp.tool(description=_TOOL_DESCRIPTIONS["run_agent"])
    def run_agent(prompt: str, time_budget_s: float = 120.0) -> dict[str, Any]:
        """Run one GEODE agentic one-shot and return the result."""
        from core.cli.bootstrap import run_agentic_oneshot

        result = run_agentic_oneshot(prompt, quiet=True, time_budget_s=time_budget_s)
        return {
            "text": getattr(result, "text", ""),
            "rounds": getattr(result, "rounds", 0),
            "termination_reason": getattr(result, "termination_reason", "unknown"),
            "error": getattr(result, "error", None),
        }

    @mcp.tool(description=_TOOL_DESCRIPTIONS["self_improving_status"])
    def self_improving_status() -> dict[str, Any]:
        """Promoted baseline + recent mutation ledger rows."""
        return _self_improving_status_payload()

    @mcp.tool(description=_TOOL_DESCRIPTIONS["self_improving_propose"])
    def self_improving_propose() -> dict[str, Any]:
        """Propose one scaffold mutation — nothing is written yet."""
        from core.self_improving.loop.runner import SelfImprovingLoopRunner

        runner = SelfImprovingLoopRunner(rerun_enabled=False, commit_enabled=True)
        proposal = runner.propose()
        mutation = proposal.mutation
        _pending_proposals[mutation.mutation_id] = (runner, proposal)
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
        """Apply a previously proposed mutation (confirmation step)."""
        entry = _pending_proposals.pop(mutation_id, None)
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

    @mcp.tool(description=_TOOL_DESCRIPTIONS["query_memory"])
    def query_memory(query: str) -> dict[str, Any]:
        """Search GEODE memory."""
        nonlocal _project_memory
        if _project_memory is None:
            from core.memory.project import ProjectMemory

            _project_memory = ProjectMemory()
        context = _project_memory.get_context_for_subject(query)
        return {"query": query, "context": context}

    @mcp.tool(description=_TOOL_DESCRIPTIONS["get_health"])
    def get_health() -> dict[str, Any]:
        """Get pipeline health status."""
        from core.config import settings

        return {
            "model": settings.model,
            "ensemble_mode": settings.ensemble_mode,
            "anthropic_configured": bool(settings.anthropic_api_key),
            "openai_configured": bool(settings.openai_api_key),
        }

    @mcp.resource("geode://soul")
    def soul_resource() -> str:
        """Get SOUL.md content."""
        from core.memory.organization import DEFAULT_SOUL_PATH

        if DEFAULT_SOUL_PATH.exists():
            return DEFAULT_SOUL_PATH.read_text(encoding="utf-8")
        return ""

    return mcp


def main() -> None:
    """Entry point for running the MCP server (``geode-mcp`` console script)."""
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = create_mcp_server()
    server.run()


if __name__ == "__main__":
    main()
