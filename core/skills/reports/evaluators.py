"""Evaluator field extraction + HTML/Markdown formatters.

Originally lines 256-329 of the pre-split ``core/skills/reports.py``.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Evaluator data extraction helper
# ---------------------------------------------------------------------------


def _extract_eval_fields(ev: Any) -> tuple[float, str, dict[str, Any]]:
    """Extract (composite_score, rationale, axes) from a dict or Pydantic object.

    Evaluator results may arrive as plain dicts (from JSON deserialization) or
    as Pydantic model instances.  This helper normalises access so callers
    don't need to repeat the isinstance/getattr dispatch.
    """
    if isinstance(ev, dict):
        composite: float = ev.get("composite_score", 0)
        rationale: str = ev.get("rationale", "")
        axes: dict[str, Any] = ev.get("axes", {})
    else:
        composite = getattr(ev, "composite_score", 0)
        rationale = getattr(ev, "rationale", "")
        axes = getattr(ev, "axes", {})
    return composite, rationale, axes


# ---------------------------------------------------------------------------
# Evaluator formatters
# ---------------------------------------------------------------------------


def _format_evaluators_html(evaluations: dict[str, Any]) -> str:
    if not evaluations:
        return ""
    rows = ""
    for etype, ev in evaluations.items():
        composite, rationale, axes = _extract_eval_fields(ev)
        axes_str = ", ".join(f"{k}: {v:.1f}" for k, v in axes.items()) if axes else "---"
        rows += (
            f"      <tr><td style='font-weight:600'>{etype}</td>"
            f"<td>{composite:.1f}</td>"
            f"<td style='font-size:0.82rem'>{axes_str}</td>"
            f"<td>{rationale[:120]}{'...' if len(rationale) > 120 else ''}</td></tr>\n"
        )
    return f"""<div class="section">
    <h2><span class="icon">&#x1F4D0;</span> Evaluator Results</h2>
    <table>
      <thead><tr><th>Evaluator</th><th>Composite</th><th>Axes</th><th>Rationale</th></tr></thead>
      <tbody>
{rows}      </tbody>
    </table>
  </div>"""


def _format_evaluators_md(evaluations: dict[str, Any]) -> str:
    if not evaluations:
        return ""
    lines = [
        "## Evaluator Results",
        "",
        "| Evaluator | Composite | Rationale |",
        "| --- | ---: | --- |",
    ]
    for etype, ev in evaluations.items():
        composite, rationale, axes = _extract_eval_fields(ev)
        lines.append(f"| {etype} | {composite:.1f} | {rationale[:80]} |")

    # Axis breakdown per evaluator
    lines.append("")
    lines.append("### Axis Breakdown")
    lines.append("")
    for etype, ev in evaluations.items():
        _, _, axes = _extract_eval_fields(ev)
        if axes:
            lines.append(f"**{etype}**:")
            for axis_name, axis_val in axes.items():
                lines.append(f"- {axis_name}: {axis_val:.1f}")
            lines.append("")

    return "\n".join(lines)
