"""Analyst Reasoning formatters (P0: shows WHY each analyst scored as they did).

Originally lines 632-689 of the pre-split ``core/skills/reports.py``.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Analyst Reasoning formatters (P0: shows WHY each analyst scored as they did)
# ---------------------------------------------------------------------------


def _format_analyst_reasoning_md(analyses: list[dict[str, Any]]) -> str:
    """Extended analyst section with reasoning + evidence."""
    has_reasoning = any(a.get("reasoning") for a in analyses)
    if not analyses or not has_reasoning:
        return ""
    lines = ["## Analyst Reasoning", ""]
    for a in analyses:
        analyst = a.get("analyst_type", "N/A")
        reasoning = a.get("reasoning", "")
        evidence = a.get("evidence", [])
        provider = a.get("model_provider", "")
        if not reasoning and not evidence:
            continue
        provider_str = f" ({provider})" if provider else ""
        lines.append(f"### {analyst}{provider_str}")
        lines.append("")
        if reasoning:
            lines.append(f"{reasoning}")
            lines.append("")
        if evidence:
            lines.append("**Evidence:**")
            for ev in evidence:
                lines.append(f"- {ev}")
            lines.append("")
    return "\n".join(lines)


def _format_analyst_reasoning_html(analyses: list[dict[str, Any]]) -> str:
    has_reasoning = any(a.get("reasoning") for a in analyses)
    if not analyses or not has_reasoning:
        return ""
    items = ""
    for a in analyses:
        analyst = a.get("analyst_type", "N/A")
        reasoning = a.get("reasoning", "")
        evidence = a.get("evidence", [])
        provider = a.get("model_provider", "")
        if not reasoning and not evidence:
            continue
        provider_str = (
            f" <span style='color:var(--muted);font-size:0.85rem'>({provider})</span>"
            if provider
            else ""
        )
        ev_list = "".join(f"<li>{ev}</li>" for ev in evidence)
        ev_html = (
            f"<ul style='margin-top:0.5rem;padding-left:1.5rem'>{ev_list}</ul>" if ev_list else ""
        )
        items += f"""<div style="margin-bottom:1rem">
        <h3 style="margin:0">{analyst}{provider_str}</h3>
        <p style="margin:0.5rem 0;color:var(--muted)">{reasoning}</p>
        {ev_html}
      </div>"""
    return f"""<div class="section">
    <h2><span class="icon">&#x1F4DD;</span> Analyst Reasoning</h2>
    {items}
  </div>"""
