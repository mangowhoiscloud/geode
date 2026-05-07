"""PSM engine + scoring breakdown formatters (HTML + Markdown).

Originally lines 335-473 of the pre-split ``core/skills/reports.py``.
"""

from __future__ import annotations

from typing import Any

from plugins.game_ip.scoring_constants import (
    CONFIDENCE_BASE_FACTOR,
    CONFIDENCE_SCALE_FACTOR,
    REPORT_WEIGHTS,
)

# ---------------------------------------------------------------------------
# PSM formatters
# ---------------------------------------------------------------------------


def _format_psm_html(psm: dict[str, Any]) -> str:
    if not psm:
        return ""
    att = psm.get("att_pct", 0.0)
    z = psm.get("z_value", 0.0)
    gamma = psm.get("rosenbaum_gamma", 0.0)
    max_smd = psm.get("max_smd", 0.0)
    lift = psm.get("exposure_lift_score", 0.0)
    valid = psm.get("psm_valid", False)
    valid_cls = "verify-pass" if valid else "verify-fail"
    valid_icon = "VALID" if valid else "INVALID"
    return f"""<div class="section">
    <h2><span class="icon">&#x2696;</span> PSM Engine</h2>
    <p><span class="verify-badge {valid_cls}">{valid_icon}</span></p>
    <div class="synthesis-grid">
      <div class="synthesis-item">
        <div class="synthesis-item-label">ATT (Average Treatment Effect)</div>
        <div class="synthesis-item-value">{att:+.1f}%</div>
      </div>
      <div class="synthesis-item">
        <div class="synthesis-item-label">Z-Value</div>
        <div class="synthesis-item-value">{z:.2f}</div>
      </div>
      <div class="synthesis-item">
        <div class="synthesis-item-label">Rosenbaum Gamma</div>
        <div class="synthesis-item-value">{gamma:.2f}</div>
      </div>
      <div class="synthesis-item">
        <div class="synthesis-item-label">Max SMD</div>
        <div class="synthesis-item-value">{max_smd:.3f}</div>
      </div>
      <div class="synthesis-item">
        <div class="synthesis-item-label">Exposure Lift Score</div>
        <div class="synthesis-item-value">{lift:.1f}</div>
      </div>
    </div>
  </div>"""


def _format_psm_md(psm: dict[str, Any]) -> str:
    if not psm:
        return ""
    att = psm.get("att_pct", 0.0)
    z = psm.get("z_value", 0.0)
    gamma = psm.get("rosenbaum_gamma", 0.0)
    max_smd = psm.get("max_smd", 0.0)
    lift = psm.get("exposure_lift_score", 0.0)
    valid = psm.get("psm_valid", False)
    status = "VALID" if valid else "INVALID"
    lines = [
        "## PSM Engine",
        "",
        f"- **Status:** {status}",
        f"- **ATT (Average Treatment Effect):** {att:+.1f}%",
        f"- **Z-Value:** {z:.2f}",
        f"- **Rosenbaum Gamma:** {gamma:.2f}",
        f"- **Max SMD:** {max_smd:.3f}",
        f"- **Exposure Lift Score:** {lift:.1f}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scoring weight breakdown formatters
# ---------------------------------------------------------------------------

_SCORING_WEIGHTS = REPORT_WEIGHTS


def _format_scoring_breakdown_html(
    subscores: dict[str, float],
    confidence: float,
) -> str:
    if not subscores:
        return ""
    rows = ""
    weighted_sum = 0.0
    for key, weight in _SCORING_WEIGHTS:
        val = subscores.get(key, 0.0)
        weighted = val * weight
        weighted_sum += weighted
        label = key.upper() if key in ("psm", "dev") else key.capitalize()
        rows += (
            f"      <tr><td>{label}</td>"
            f"<td>{val:.1f}</td>"
            f"<td>{weight:.0%}</td>"
            f"<td>{weighted:.1f}</td></tr>\n"
        )
    multiplier = (
        CONFIDENCE_BASE_FACTOR + CONFIDENCE_SCALE_FACTOR * confidence / 100 if confidence else 1.0
    )
    final = weighted_sum * multiplier
    return f"""<div class="section">
    <h2><span class="icon">&#x1F9EE;</span> Scoring Breakdown</h2>
    <table>
      <thead><tr><th>Dimension</th><th>Raw Score</th><th>Weight</th><th>Weighted</th></tr></thead>
      <tbody>
{rows}      </tbody>
    </table>
    <div style="margin-top:1rem;padding:0.8rem;background:var(--bg);border-radius:8px;
                font-size:0.9rem">
      <strong>Weighted Sum:</strong> {weighted_sum:.1f} |
      <strong>Confidence:</strong> {multiplier:.3f} ({confidence:.0f}) |
      <strong>Final:</strong> {final:.1f}
    </div>
  </div>"""


def _format_scoring_breakdown_md(
    subscores: dict[str, float],
    confidence: float,
) -> str:
    if not subscores:
        return ""
    lines = [
        "## Scoring Breakdown",
        "",
        "| Dimension | Raw Score | Weight | Weighted |",
        "| --- | ---: | ---: | ---: |",
    ]
    weighted_sum = 0.0
    for key, weight in _SCORING_WEIGHTS:
        val = subscores.get(key, 0.0)
        weighted = val * weight
        weighted_sum += weighted
        label = key.upper() if key in ("psm", "dev") else key.capitalize()
        lines.append(f"| {label} | {val:.1f} | {weight:.0%} | {weighted:.1f} |")
    multiplier = (
        CONFIDENCE_BASE_FACTOR + CONFIDENCE_SCALE_FACTOR * confidence / 100 if confidence else 1.0
    )
    final = weighted_sum * multiplier
    lines.append("")
    lines.append(
        f"**Weighted Sum:** {weighted_sum:.1f} | "
        f"**Confidence Multiplier:** {multiplier:.3f} (confidence={confidence:.0f}) | "
        f"**Final:** {final:.1f}"
    )
    return "\n".join(lines)
