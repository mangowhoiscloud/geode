"""Tool-handler tests for petri_audit (NL → AgenticLoop entry point)."""

from __future__ import annotations

from core.cli.tool_handlers.audit import _build_audit_handlers


def test_petri_audit_handler_registered() -> None:
    handlers = _build_audit_handlers()
    assert "petri_audit" in handlers
    assert callable(handlers["petri_audit"])


def test_petri_audit_handler_dry_run_returns_dict() -> None:
    handlers = _build_audit_handlers()
    result = handlers["petri_audit"](
        judge="claude-haiku-4-5-20251001",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=2,
        dry_run=True,
    )
    assert result["status"] == "ok"
    assert result["tool"] == "petri_audit"
    audit = result["audit"]
    assert audit["dry_run"] is True
    assert audit["aborted"] is False
    assert "inspect eval inspect_petri/audit" in audit["command"]


def test_petri_audit_handler_defaults() -> None:
    """Handler accepts an empty kwargs dict and falls back to safe defaults."""
    handlers = _build_audit_handlers()
    result = handlers["petri_audit"]()
    assert result["status"] == "ok"
    assert result["audit"]["dry_run"] is True


def test_petri_audit_handler_unknown_model_returns_error() -> None:
    handlers = _build_audit_handlers()
    result = handlers["petri_audit"](
        judge="mystery-model",
        auditor="claude-sonnet-4-6",
        target="claude-opus-4-7",
        seeds=1,
        max_turns=2,
        dry_run=True,
    )
    # Unknown model → AuditModelMappingError → handler catches → status=error.
    assert result["status"] == "error"
    assert "mystery-model" in result["error"] or "Unknown" in result["error"]


def test_petri_audit_in_expensive_tools_registry() -> None:
    """`petri_audit` must be EXPENSIVE_TOOLS-gated so live calls trigger HITL."""
    from core.agent.safety import EXPENSIVE_TOOLS

    assert "petri_audit" in EXPENSIVE_TOOLS
    assert EXPENSIVE_TOOLS["petri_audit"] > 0


def test_petri_audit_in_tool_definitions() -> None:
    """definitions.json registers `petri_audit` as an expensive evaluation tool."""
    import json
    from pathlib import Path

    defs_path = Path(__file__).resolve().parents[3] / "core" / "tools" / "definitions.json"
    defs = json.loads(defs_path.read_text())
    audit_def = next((d for d in defs if d.get("name") == "petri_audit"), None)
    assert audit_def is not None, "petri_audit not in definitions.json"
    assert audit_def["category"] == "evaluation"
    assert audit_def["cost_tier"] == "expensive"
    properties = audit_def["input_schema"]["properties"]
    for required_field in ("judge", "auditor", "target", "dry_run"):
        assert required_field in properties


def test_petri_audit_in_aggregate_tool_handlers() -> None:
    """`_build_tool_handlers` must include petri_audit so AgenticLoop sees it."""
    from core.cli.tool_handlers import _build_tool_handlers

    handlers = _build_tool_handlers(verbose=False)
    assert "petri_audit" in handlers
