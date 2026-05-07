"""Rights Risk formatters (P0: shows IP licensing risk).

Originally lines 749-797 of the pre-split ``core/skills/reports.py``.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Rights Risk formatters (P0: shows IP licensing risk)
# ---------------------------------------------------------------------------


def _format_rights_risk_md(rights_risk: dict[str, Any]) -> str:
    if not rights_risk:
        return ""
    status = rights_risk.get("status", "UNKNOWN")
    risk_score = rights_risk.get("risk_score", 0)
    concerns = rights_risk.get("concerns", [])
    recommendation = rights_risk.get("recommendation", "")
    lines = [
        "## IP Rights Risk",
        "",
        f"- **Status:** {status}",
        f"- **Risk Score:** {risk_score}/100",
    ]
    if concerns:
        lines.append("- **Concerns:**")
        for c in concerns:
            lines.append(f"  - {c}")
    if recommendation:
        lines.extend(["", f"> {recommendation}"])
    return "\n".join(lines)


def _format_rights_risk_html(rights_risk: dict[str, Any]) -> str:
    if not rights_risk:
        return ""
    status = rights_risk.get("status", "UNKNOWN")
    risk_score = rights_risk.get("risk_score", 0)
    concerns = rights_risk.get("concerns", [])
    recommendation = rights_risk.get("recommendation", "")
    if status == "CLEAR":
        color = "#16a34a"
    elif status in ("NEGOTIABLE", "UNKNOWN"):
        color = "#eab308"
    else:
        color = "#dc2626"
    concerns_html = "".join(f"<li>{c}</li>" for c in concerns)
    rec_html = (
        f'<p style="margin-top:0.8rem;font-style:italic;color:var(--muted)">{recommendation}</p>'
        if recommendation
        else ""
    )
    return f"""<div class="section">
    <h2><span class="icon">&#x2696;</span> IP Rights Risk</h2>
    <p><span style="color:{color};font-weight:600">{status}</span>
    (Risk Score: {risk_score}/100)</p>
    {f'<ul style="margin-top:0.5rem">{concerns_html}</ul>' if concerns_html else ""}
    {rec_html}
  </div>"""
