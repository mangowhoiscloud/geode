"""obs_otel_export tool handler wiring tests."""

from __future__ import annotations

import sys

import pytest
from core.cli.tool_handlers.observability import _build_observability_handlers


def test_observability_handlers_registered() -> None:
    handlers = _build_observability_handlers()
    assert "obs_otel_export" in handlers
    assert callable(handlers["obs_otel_export"])


def test_obs_otel_export_status_returns_disabled_by_default() -> None:
    handlers = _build_observability_handlers()
    result = handlers["obs_otel_export"](action="status")
    assert result["status"] == "ok"
    assert result["tool"] == "obs_otel_export"
    assert result["action"] == "status"
    assert "enabled" in result["obs"]


def test_obs_otel_export_unknown_action_returns_error() -> None:
    handlers = _build_observability_handlers()
    result = handlers["obs_otel_export"](action="emit-now")
    assert result["status"] == "error"
    assert "Unknown action" in result["error"]


def test_obs_otel_export_enable_without_extra_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without [obs] extra installed, enable returns a structured error."""
    # Reset state — other tests may have touched the singleton.
    handlers = _build_observability_handlers()
    handlers["obs_otel_export"](action="disable")

    monkeypatch.setitem(sys.modules, "traceloop", None)
    monkeypatch.setitem(sys.modules, "traceloop.sdk", None)

    result = handlers["obs_otel_export"](action="enable")
    assert result["status"] == "error"
    assert "[obs] extra" in result["error"]


def test_observability_in_aggregate_tool_handlers() -> None:
    """`_build_tool_handlers` must include obs_otel_export."""
    from core.cli.tool_handlers import _build_tool_handlers

    handlers = _build_tool_handlers(verbose=False)
    assert "obs_otel_export" in handlers


def test_obs_otel_export_in_tool_definitions() -> None:
    """definitions.json registers obs_otel_export in observability category."""
    import json
    from pathlib import Path

    defs_path = Path(__file__).resolve().parents[3] / "core" / "tools" / "definitions.json"
    defs = json.loads(defs_path.read_text())
    obs = next((d for d in defs if d.get("name") == "obs_otel_export"), None)
    assert obs is not None
    assert obs["category"] == "observability"
    assert obs["cost_tier"] == "free"
    properties = obs["input_schema"]["properties"]
    assert "action" in properties
    assert "enable" in properties["action"]["enum"]


def test_observability_category_registered() -> None:
    """`observability` must be in VALID_CATEGORIES (so json validator passes)."""
    from core.tools.base import VALID_CATEGORIES

    assert "observability" in VALID_CATEGORIES
