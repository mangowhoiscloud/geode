"""``geode-mcp`` server surface — D-3 decision ④ (2026-06-10).

Pins the promotion from a 2-tool analysis shell to the first-class entry
point: server identity, the agentic + self-improving tool registration,
the propose→apply two-step confirmation contract, and the read-only
status payload's graceful empty states.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from core.mcp_server import create_mcp_server
from geode_product.self_improving.mcp import _status_payload, register_mcp_tools

CORE_TOOLS = {
    "run_agent",
    "query_memory",
    "get_health",
}
PRODUCT_TOOLS = {
    "self_improving_status",
    "self_improving_propose",
    "self_improving_apply",
}


def test_server_identity_and_tool_surface() -> None:
    server = create_mcp_server(feature_registrar=register_mcp_tools)
    assert server.name == "geode"
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names >= CORE_TOOLS | PRODUCT_TOOLS


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
    """Kernel and product tools keep descriptions with their owners."""
    core_described = set(json.loads(Path("core/tools/mcp_tools.json").read_text(encoding="utf-8")))
    product_described = set(
        json.loads(Path("geode_product/self_improving/mcp_tools.json").read_text(encoding="utf-8"))
    )
    assert core_described >= CORE_TOOLS
    assert product_described == PRODUCT_TOOLS


def test_apply_without_propose_is_refused() -> None:
    """Two-step contract — apply must not write without a parked proposal."""
    server = create_mcp_server(feature_registrar=register_mcp_tools)
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
    # baseline.json is a SEPARATE runtime constant post PR-STATE-SOT-RUNTIME-SPLIT;
    # point it at a nonexistent tmp path so the reader doesn't fall through to the
    # operator's real ~/.geode/self-improving/baseline.json.
    monkeypatch.setattr(core_paths, "BASELINE_JSON_PATH", tmp_path / "state" / "baseline.json")
    payload = _status_payload()
    assert payload == {"baseline": None, "recent_mutations": []}


def test_status_payload_reads_baseline_and_ledger_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.paths as core_paths

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    audit_path = state_dir / "mutations.jsonl"
    monkeypatch.setattr(core_paths, "MUTATION_AUDIT_LOG_PATH", audit_path)
    # baseline.json is now a separate runtime constant (PR-STATE-SOT-RUNTIME-SPLIT);
    # co-locate it in the test's state dir and point the constant at it.
    monkeypatch.setattr(core_paths, "BASELINE_JSON_PATH", state_dir / "baseline.json")

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

    payload = _status_payload()
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
    from core.cli.bootstrap import arun_agentic_oneshot

    tree = ast.parse(textwrap.dedent(inspect.getsource(arun_agentic_oneshot)))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "bootstrap_builtins"
    ]
    assert any({kw.arg for kw in call.keywords} >= {"policy_sources"} for call in calls)


def test_run_agent_tool_awaits_injected_async_runner() -> None:
    calls: list[tuple[str, bool, float]] = []

    async def runner(prompt: str, *, quiet: bool, time_budget_s: float, **_: object) -> object:
        calls.append((prompt, quiet, time_budget_s))
        return SimpleNamespace(text="done", rounds=2, termination_reason="completed", error=None)

    server = create_mcp_server(agent_runner=runner)
    result = asyncio.run(server.call_tool("run_agent", {"prompt": "check", "time_budget_s": 3.0}))
    assert calls == [("check", True, 3.0)]
    assert "done" in json.dumps(result, default=str)


def test_sync_oneshot_wrapper_delegates_to_async_core() -> None:
    from core.cli.bootstrap import arun_agentic_oneshot, run_agentic_oneshot

    assert inspect.iscoroutinefunction(arun_agentic_oneshot)
    tree = ast.parse(textwrap.dedent(inspect.getsource(run_agentic_oneshot)))
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "arun_agentic_oneshot"
        for node in ast.walk(tree)
    )
