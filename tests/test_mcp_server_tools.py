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
