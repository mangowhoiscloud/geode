"""Petri audit viz helpers — render + tool handler tests.

The matplotlib path is exercised when the ``[viz]`` extra is available;
when it isn't (default ``uv sync``), the helpers must raise
:class:`VizError` so the AgenticLoop tool surfaces a structured error
rather than crashing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from plugins.petri_audit.viz import (
    VizError,
    available_charts,
    render_agreement,
    render_cost_breakdown,
    render_from_eval_log,
    render_heatmap,
    render_tool_frequency,
    render_trend,
)

_MPL_INSTALLED = importlib.util.find_spec("matplotlib") is not None
_AUDIT_INSTALLED = importlib.util.find_spec("inspect_ai") is not None


def test_available_charts_lists_five() -> None:
    assert set(available_charts()) == {"heatmap", "cost", "tool", "agree", "trend"}


# ---------------------------------------------------------------------------
# matplotlib-required paths — skip when [viz] not installed
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MPL_INSTALLED, reason="[viz] extra not installed")
def test_render_heatmap_writes_png(tmp_path: Path) -> None:
    out = render_heatmap(
        {"sycophancy": [0.1, 0.4], "self_preservation": [0.0, 0.6]},
        tmp_path / "h.png",
    )
    assert out.exists()
    assert out.stat().st_size > 0


@pytest.mark.skipif(not _MPL_INSTALLED, reason="[viz] extra not installed")
def test_render_cost_breakdown_writes_png(tmp_path: Path) -> None:
    out = render_cost_breakdown(
        {"auditor": 0.05, "target": 0.55, "judge": 0.01},
        tmp_path / "c.png",
        gate_krw=5_000,
    )
    assert out.exists()


@pytest.mark.skipif(not _MPL_INSTALLED, reason="[viz] extra not installed")
def test_render_tool_frequency_writes_png(tmp_path: Path) -> None:
    out = render_tool_frequency(
        {"web_search": 4, "file_read": 2, "calendar_create": 1},
        tmp_path / "t.png",
    )
    assert out.exists()


@pytest.mark.skipif(not _MPL_INSTALLED, reason="[viz] extra not installed")
def test_render_agreement_writes_png(tmp_path: Path) -> None:
    out = render_agreement([(0.1, 0.2), (0.5, 0.4), (0.9, 0.85)], tmp_path / "a.png")
    assert out.exists()


@pytest.mark.skipif(not _MPL_INSTALLED, reason="[viz] extra not installed")
def test_render_trend_writes_png(tmp_path: Path) -> None:
    out = render_trend(
        {
            "sycophancy": [("2a", 0.1), ("2b", 0.15)],
            "self_preservation": [("2a", 0.0), ("2b", 0.05)],
        },
        tmp_path / "tr.png",
    )
    assert out.exists()


# ---------------------------------------------------------------------------
# Edge cases / error paths — work without matplotlib
# ---------------------------------------------------------------------------


def test_render_heatmap_empty_raises(tmp_path: Path) -> None:
    with pytest.raises(VizError, match="Empty"):
        render_heatmap({}, tmp_path / "h.png")


def test_render_cost_breakdown_empty_raises(tmp_path: Path) -> None:
    with pytest.raises(VizError, match="Empty"):
        render_cost_breakdown({}, tmp_path / "c.png")


def test_render_from_eval_log_unknown_chart_raises(tmp_path: Path) -> None:
    with pytest.raises(VizError, match="Unknown chart"):
        render_from_eval_log(tmp_path / "x.eval", "nonsense", tmp_path / "out.png")


def test_render_from_eval_log_without_audit_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "inspect_ai", None)
    monkeypatch.setitem(sys.modules, "inspect_ai.log", None)
    with pytest.raises(VizError, match=r"\[audit\] extra"):
        render_from_eval_log(tmp_path / "x.eval", "heatmap", tmp_path / "out.png")


def test_render_heatmap_without_matplotlib_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When matplotlib is absent, a structured VizError surfaces."""
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", None)
    with pytest.raises(VizError, match=r"\[viz\] extra"):
        render_heatmap({"a": [0.1]}, tmp_path / "h.png")


# ---------------------------------------------------------------------------
# Tool handler wiring (eval_inspect_viz)
# ---------------------------------------------------------------------------


def test_eval_inspect_viz_handler_registered() -> None:
    from core.cli.tool_handlers.audit import _build_audit_handlers

    handlers = _build_audit_handlers()
    assert "eval_inspect_viz" in handlers
    assert callable(handlers["eval_inspect_viz"])


def test_eval_inspect_viz_missing_log_path_returns_error() -> None:
    from core.cli.tool_handlers.audit import _build_audit_handlers

    handlers = _build_audit_handlers()
    result = handlers["eval_inspect_viz"](chart="heatmap")
    assert result["status"] == "error"
    assert "log_path is required" in result["error"]
    assert "heatmap" in result["available_charts"]


def test_eval_inspect_viz_in_definitions_json() -> None:
    import json
    from pathlib import Path

    defs_path = Path(__file__).resolve().parents[3] / "core" / "tools" / "definitions.json"
    defs = json.loads(defs_path.read_text())
    viz = next((d for d in defs if d.get("name") == "eval_inspect_viz"), None)
    assert viz is not None
    assert viz["category"] == "observability"
    assert viz["cost_tier"] == "free"
    chart_enum = viz["input_schema"]["properties"]["chart"]["enum"]
    assert set(chart_enum) == {"heatmap", "cost", "tool", "agree", "trend"}


@pytest.mark.skipif(_AUDIT_INSTALLED, reason="[audit] extra installed")
def test_eval_inspect_viz_handler_without_audit_returns_error(tmp_path: Path) -> None:
    from core.cli.tool_handlers.audit import _build_audit_handlers

    handlers = _build_audit_handlers()
    result = handlers["eval_inspect_viz"](
        log_path=str(tmp_path / "x.eval"),
        chart="heatmap",
        output_path=str(tmp_path / "out.png"),
    )
    assert result["status"] == "error"
    assert "[audit] extra" in result["error"]
