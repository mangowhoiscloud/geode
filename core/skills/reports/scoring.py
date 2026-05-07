"""Subscores / synthesis / analyses formatters (HTML + Markdown).

Originally lines 111-248 of the pre-split ``core/skills/reports.py``.
"""

from __future__ import annotations

from typing import Any

from .models import _SUBSCORE_BARS


def _format_subscores_html(subscores: dict[str, float]) -> str:
    if not subscores:
        return ""
    rows: list[str] = []
    for key, css_class in _SUBSCORE_BARS:
        val = subscores.get(key, 0.0)
        pct = max(0, min(val, 100))
        label = key.upper() if key in ("psm", "dev") else key.capitalize()
        rows.append(f"""      <div class="subscore-row">
        <span class="subscore-label">{label}</span>
        <div class="bar-track"><div class="{css_class} bar-fill" style="width:{pct}%"></div></div>
        <span class="subscore-value">{val:.1f}</span>
      </div>""")
    return f"""<div class="section">
    <h2><span class="icon">📊</span> Sub-Scores</h2>
    <div class="subscore-grid">
{chr(10).join(rows)}
    </div>
  </div>"""


def _format_subscores_md(subscores: dict[str, float]) -> str:
    if not subscores:
        return ""
    lines = ["## Sub-Scores", "", "| Dimension | Score | Bar |", "| --- | ---: | --- |"]
    for key, _ in _SUBSCORE_BARS:
        val = subscores.get(key, 0.0)
        label = key.upper() if key in ("psm", "dev") else key.capitalize()
        bar = "█" * int(val / 5) + "░" * (20 - int(val / 5))
        lines.append(f"| {label} | {val:.1f} | `{bar}` |")
    return "\n".join(lines)


def _format_synthesis_html(synthesis: dict[str, Any]) -> str:
    if not synthesis:
        return ""
    cause = synthesis.get("undervaluation_cause", "N/A")
    action = synthesis.get("action_type", "N/A")
    narrative = synthesis.get("value_narrative", "")
    segment = synthesis.get("target_segment", "N/A")
    return f"""<div class="section">
    <h2><span class="icon">🔍</span> Synthesis</h2>
    <div class="synthesis-grid">
      <div class="synthesis-item">
        <div class="synthesis-item-label">Undervaluation Cause</div>
        <div class="synthesis-item-value">{cause}</div>
      </div>
      <div class="synthesis-item">
        <div class="synthesis-item-label">Recommended Action</div>
        <div class="synthesis-item-value">{action}</div>
      </div>
      <div class="synthesis-item">
        <div class="synthesis-item-label">Target Segment</div>
        <div class="synthesis-item-value">{segment}</div>
      </div>
    </div>
    {f'<div class="narrative">{narrative}</div>' if narrative else ""}
  </div>"""


def _format_synthesis_md(synthesis: dict[str, Any]) -> str:
    if not synthesis:
        return ""
    cause = synthesis.get("undervaluation_cause", "N/A")
    action = synthesis.get("action_type", "N/A")
    narrative = synthesis.get("value_narrative", "")
    segment = synthesis.get("target_segment", "N/A")
    lines = [
        "## Synthesis",
        "",
        f"- **Undervaluation Cause:** {cause}",
        f"- **Recommended Action:** {action}",
        f"- **Target Segment:** {segment}",
    ]
    if narrative:
        lines.extend(["", f"> {narrative}"])
    return "\n".join(lines)


def _format_analyses_html(analyses: list[dict[str, Any]]) -> str:
    if not analyses:
        return ""
    rows = ""
    for a in analyses:
        score = a.get("score", 0)
        analyst = a.get("analyst_type", "N/A")
        finding = a.get("key_finding", "")
        confidence = a.get("confidence", "")
        conf_str = f"{confidence}%" if confidence else "—"
        rows += (
            f"      <tr><td style='font-weight:600'>{analyst}</td>"
            f"<td>{score}</td>"
            f"<td>{conf_str}</td>"
            f"<td>{finding}</td></tr>\n"
        )
    return f"""<div class="section">
    <h2><span class="icon">🔬</span> Analyst Results</h2>
    <table>
      <thead><tr><th>Analyst</th><th>Score</th><th>Confidence</th><th>Key Finding</th></tr></thead>
      <tbody>
{rows}      </tbody>
    </table>
  </div>"""


def _format_analyses_md(analyses: list[dict[str, Any]]) -> str:
    if not analyses:
        return ""
    lines = [
        "## Analyst Results",
        "",
        "| Analyst | Score | Confidence | Key Finding |",
        "| --- | ---: | ---: | --- |",
    ]
    for a in analyses:
        score = a.get("score", "N/A")
        analyst = a.get("analyst_type", "N/A")
        finding = a.get("key_finding", "")
        confidence = a.get("confidence", "")
        conf_str = f"{confidence}%" if confidence else "---"
        lines.append(f"| {analyst} | {score} | {conf_str} | {finding} |")

    # Evidence chain --- list cited evidence per analyst
    has_evidence = any(a.get("evidence") for a in analyses)
    if has_evidence:
        lines.append("")
        lines.append("### Evidence Chain")
        lines.append("")
        for a in analyses:
            evidence = a.get("evidence", [])
            if evidence:
                analyst = a.get("analyst_type", "N/A")
                lines.append(f"**{analyst}**:")
                for ev in evidence:
                    lines.append(f"- {ev}")
                lines.append("")

    return "\n".join(lines)
