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

log = logging.getLogger(__name__)

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
    import core.paths

    audit_path = Path(core.paths.MUTATION_AUDIT_LOG_PATH)
    # baseline.json is RUNTIME (out-of-repo); mutations.jsonl is the tracked
    # in-repo SoT — they no longer share a parent (PR-STATE-SOT-RUNTIME-SPLIT),
    # so read each from its own constant rather than deriving one from the other.
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


class _StaticTokenVerifier:
    """Constant-time bearer-token check for the HTTP transport.

    The MCP SDK's auth stack is OAuth-shaped; for a single-operator remote
    setup a static shared secret is the honest fit. ``verify_token`` is the
    SDK's :class:`~mcp.server.auth.provider.TokenVerifier` protocol
    (verified against the installed mcp 1.26 source — Protocol with one
    async method returning ``AccessToken | None``).
    """

    def __init__(self, expected_token: str) -> None:
        self._expected = expected_token

    async def verify_token(self, token: str) -> Any | None:
        import hmac

        from mcp.server.auth.provider import AccessToken

        if not hmac.compare_digest(token, self._expected):
            return None
        return AccessToken(token=token, client_id="geode-mcp-static", scopes=[], expires_at=None)


def create_mcp_server(
    *,
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
) -> Any:
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

    server_kwargs: dict[str, Any] = {}
    if host is not None:
        server_kwargs["host"] = host
    if port is not None:
        server_kwargs["port"] = port
    if auth_token:
        # SDK contract (verified in the installed mcp 1.26 source): passing
        # ``token_verifier`` WITHOUT ``auth=AuthSettings(...)`` silently
        # skips the auth middleware — ``streamable_http_app`` gates the
        # BearerAuthBackend on ``self.settings.auth``. Both must be set or
        # the server is open despite the token.
        from mcp.server.auth.settings import AuthSettings

        base_url = f"http://{host or '127.0.0.1'}:{port or 8765}"
        server_kwargs["token_verifier"] = _StaticTokenVerifier(auth_token)
        server_kwargs["auth"] = AuthSettings(
            issuer_url=base_url,
            resource_server_url=f"{base_url}/mcp",
            required_scopes=[],
        )

    mcp = FastMCP("geode", **server_kwargs)
    # Report GEODE's own version in the initialize handshake. The installed
    # mcp SDK's FastMCP.__init__ (1.26.x) exposes no ``version`` kwarg even
    # though the wrapped lowlevel ``Server(name, version, ...)`` accepts one,
    # so without this the handshake advertises the SDK's package version
    # ("1.26.0") instead of GEODE's. Verified against the installed SDK:
    # mcp.server.fastmcp.FastMCP -> self._mcp_server.version (None by default).
    from core import __version__ as _geode_version

    mcp._mcp_server.version = _geode_version

    # Shared ProjectMemory instance (created once per server lifetime)
    _project_memory: Any = None
    # Pending mutator proposals — propose() parks here keyed by mutation_id;
    # apply() consumes. The two-step contract is the MCP confirmation gate.
    _pending_proposals: dict[str, tuple[Any, Any]] = {}

    @mcp.tool(description=_TOOL_DESCRIPTIONS["run_agent"])
    async def run_agent(prompt: str, time_budget_s: float = 120.0) -> dict[str, Any]:
        """Run one GEODE agentic one-shot and return the result."""
        from core.cli.bootstrap import arun_agentic_oneshot

        result = await arun_agentic_oneshot(prompt, quiet=True, time_budget_s=time_budget_s)
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
        from core.self_improving.loop.mutate.runner import SelfImprovingLoopRunner

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
        from core import __version__
        from core.config import settings

        # ``*_configured`` historically meant "API key present", which
        # under-reports health for OAuth/CLI-lane setups (the common case:
        # both read false while the agent runs fine on subscription auth).
        # Keep the legacy keys but scope them honestly as api_key bits, and
        # add the effective credential-source picks so a client can tell
        # "no API key" apart from "not authenticated at all".
        return {
            "version": __version__,
            "model": settings.model,
            "ensemble_mode": settings.ensemble_mode,
            "anthropic_configured": bool(settings.anthropic_api_key),
            "openai_configured": bool(settings.openai_api_key),
            "anthropic_credential_source": settings.anthropic_credential_source,
            "openai_credential_source": settings.openai_credential_source,
        }

    @mcp.resource("geode://soul")
    def soul_resource() -> str:
        """Get SOUL.md content."""
        from core.memory.organization import DEFAULT_SOUL_PATH

        if DEFAULT_SOUL_PATH.exists():
            return DEFAULT_SOUL_PATH.read_text(encoding="utf-8")
        return ""

    return mcp


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost")


def main() -> None:
    """Entry point for running the MCP server (``geode-mcp`` console script).

    Default transport is stdio (the MCP client spawns this process — local
    only). ``--http`` switches to the SDK's streamable-http transport for
    remote access; the bearer token comes from ``GEODE_MCP_TOKEN`` (a
    secret, so it lives in ``~/.geode/.env`` per the C-2 contract — the
    shared :func:`core.config.env_io.load_env_files` promotion runs first
    so a token written there is found).

    Fail-loud guard: binding to a NON-loopback host without a token is
    refused — ``run_agent`` reaches GEODE's full tool surface (bash, file
    ops) and ``self_improving_apply`` mutates the scaffold, so an open
    network bind is a remote-execution surface, not a convenience.
    Loopback HTTP without a token is allowed (same trust boundary as
    stdio) but logged as a warning.
    """
    import argparse
    import os
    import sys

    from core.observability.logging_config import configure_logging

    parser = argparse.ArgumentParser(prog="geode-mcp")
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve over streamable HTTP instead of stdio (remote access)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8765, help="HTTP bind port")
    args = parser.parse_args()

    configure_logging("mcp")

    if not args.http:
        server = create_mcp_server()
        server.run()
        return

    from core.config.env_io import load_env_files

    load_env_files()
    auth_token = (os.environ.get("GEODE_MCP_TOKEN") or "").strip()

    if not auth_token and not _is_loopback(args.host):
        print(
            f"geode-mcp: refusing to bind {args.host}:{args.port} without "
            "GEODE_MCP_TOKEN — a tokenless non-loopback bind exposes "
            "run_agent (full tool surface) to the network. Set "
            "GEODE_MCP_TOKEN in ~/.geode/.env or the environment.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not auth_token:
        log.warning(
            "geode-mcp: HTTP on loopback without GEODE_MCP_TOKEN — local "
            "processes can call all tools (same trust as stdio)."
        )

    server = create_mcp_server(host=args.host, port=args.port, auth_token=auth_token or None)
    log.info(
        "geode-mcp: streamable HTTP on %s:%d (auth=%s)",
        args.host,
        args.port,
        "bearer-token" if auth_token else "none/loopback",
    )
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
