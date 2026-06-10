"""``geode-mcp`` server surface — D-3 decision ④ (2026-06-10).

Pins the promotion from a 2-tool analysis shell to the first-class entry
point: server identity, the agentic + self-improving tool registration,
the propose→apply two-step confirmation contract, and the read-only
status payload's graceful empty states.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from core.mcp_server import _self_improving_status_payload, create_mcp_server

EXPECTED_TOOLS = {
    "run_agent",
    "self_improving_status",
    "self_improving_propose",
    "self_improving_apply",
    "query_memory",
    "get_health",
}


def test_server_identity_and_tool_surface() -> None:
    server = create_mcp_server()
    assert server.name == "geode"
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names >= EXPECTED_TOOLS


def test_handshake_advertises_geode_version_not_sdk_version() -> None:
    """The initialize handshake must carry GEODE's version. The installed
    mcp SDK's FastMCP exposes no ``version`` kwarg, so create_mcp_server
    sets it on the wrapped lowlevel server — without that, clients see the
    SDK package version (e.g. "1.26.0")."""
    from core import __version__

    server = create_mcp_server()
    assert server._mcp_server.version == __version__
    init_options = server._mcp_server.create_initialization_options()
    assert init_options.server_version == __version__


def test_get_health_reports_credential_sources() -> None:
    """``*_configured`` alone under-reports OAuth/CLI-lane setups; health
    must also expose the effective credential-source picks + version."""
    server = create_mcp_server()

    async def _call() -> dict:
        result = await server.call_tool("get_health", {})
        return result[1] if isinstance(result, tuple) else result

    payload = asyncio.run(_call())
    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]
    for key in (
        "version",
        "anthropic_credential_source",
        "openai_credential_source",
        "anthropic_configured",
        "openai_configured",
    ):
        assert key in payload, key


def test_tool_descriptions_sourced_from_json() -> None:
    """Every registered core tool keeps its description in mcp_tools.json."""
    descriptions_path = Path("core/tools/mcp_tools.json")
    described = set(json.loads(descriptions_path.read_text(encoding="utf-8")))
    assert described >= EXPECTED_TOOLS


def test_apply_without_propose_is_refused() -> None:
    """Two-step contract — apply must not write without a parked proposal."""
    server = create_mcp_server()
    result = asyncio.run(server.call_tool("self_improving_apply", {"mutation_id": "nope"}))
    payload = result[1] if isinstance(result, tuple) else result
    text = json.dumps(payload, default=str)
    assert "no pending proposal" in text


def test_status_payload_graceful_on_missing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.paths as core_paths

    monkeypatch.setattr(
        core_paths, "MUTATION_AUDIT_LOG_PATH", tmp_path / "state" / "mutations.jsonl"
    )
    payload = _self_improving_status_payload()
    assert payload == {"baseline": None, "recent_mutations": []}


def test_status_payload_reads_baseline_and_ledger_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.paths as core_paths

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    audit_path = state_dir / "mutations.jsonl"
    monkeypatch.setattr(core_paths, "MUTATION_AUDIT_LOG_PATH", audit_path)

    (state_dir / "baseline.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "fitness": 0.7915,
                "ts_utc": "2026-06-10T00:00:00Z",
                "session_id": "s-test",
            }
        ),
        encoding="utf-8",
    )
    ledger_rows = [
        {
            "ts": float(i),
            "kind": "applied",
            "mutation_id": f"m{i}",
            "target_kind": "identity",
            "target_section": "core",
        }
        for i in range(8)
    ]
    audit_path.write_text(
        "\n".join(json.dumps(row) for row in ledger_rows) + "\nnot-json\n", encoding="utf-8"
    )

    payload = _self_improving_status_payload()
    assert payload["baseline"] == {
        "fitness": 0.7915,
        "ts_utc": "2026-06-10T00:00:00Z",
        "session_id": "s-test",
        "schema_version": 2,
    }
    recent = payload["recent_mutations"]
    assert len(recent) == 5  # tail only
    assert recent[-1]["mutation_id"] == "m7"
    assert recent[0]["mutation_id"] == "m3"


def test_run_agentic_oneshot_bootstraps_adapters() -> None:
    """geode-mcp's run_agent path must self-bootstrap the adapter registry —
    it never goes through GeodeRuntime.create. First live MCP run_agent
    failed with AdapterNotFoundError "Known pairs: []" (2026-06-11)."""
    import inspect

    from core.cli.bootstrap import arun_agentic_oneshot

    source = inspect.getsource(arun_agentic_oneshot)
    assert "bootstrap_builtins()" in source


def test_run_agent_tool_is_async_and_awaits_async_core() -> None:
    """FastMCP executes tools inside the server's event loop — a sync tool
    calling run_process_coroutine raises "cannot be called from an active
    event loop" (second live HTTP run_agent failure, 2026-06-11). The tool
    must be async and await arun_agentic_oneshot."""
    import inspect

    import core.mcp_server as mod

    source = inspect.getsource(mod.create_mcp_server)
    assert "async def run_agent(" in source
    assert "await arun_agentic_oneshot(" in source


def test_sync_oneshot_wrapper_delegates_to_async_core() -> None:
    import inspect

    from core.cli.bootstrap import arun_agentic_oneshot, run_agentic_oneshot

    assert inspect.iscoroutinefunction(arun_agentic_oneshot)
    source = inspect.getsource(run_agentic_oneshot)
    assert "arun_agentic_oneshot(" in source
