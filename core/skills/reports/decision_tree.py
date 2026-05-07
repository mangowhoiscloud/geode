"""Decision Tree Path formatters (P1: shows D/E/F axis cause logic).

Originally lines 804-863 of the pre-split ``core/skills/reports.py``.
"""

from __future__ import annotations

from typing import Any

from .evaluators import _extract_eval_fields

# ---------------------------------------------------------------------------
# Decision Tree Path formatters (P1: shows D/E/F axis cause logic)
# ---------------------------------------------------------------------------


def _format_decision_tree_md(synthesis: dict[str, Any], evaluations: dict[str, Any]) -> str:
    """Show the D/E/F axis values that determined the cause classification."""
    cause = synthesis.get("undervaluation_cause", "")
    if not cause or not evaluations:
        return ""
    # Extract D/E/F from hidden_value evaluator
    hv = evaluations.get("hidden_value", {})
    _, _, axes = _extract_eval_fields(hv)
    d = axes.get("d_score", axes.get("D", "?"))
    e = axes.get("e_score", axes.get("E", "?"))
    f = axes.get("f_score", axes.get("F", "?"))

    lines = [
        "## Cause Classification Logic",
        "",
        "**D-E-F Profile:**",
        f"- D (Discovery Difficulty): {d}",
        f"- E (Monetization Capability): {e}",
        f"- F (Franchise Expandability): {f}",
        "",
        f"**Classification:** `{cause}`",
        "",
        "Decision Tree:",
        "- D>=3, E>=3 -> conversion_failure",
        "- D>=3, E<3 -> undermarketed",
        "- D<=2, E>=3 -> monetization_misfit",
        "- D<=2, E<=2, F>=3 -> niche_gem",
        "- else -> discovery_failure",
    ]
    return "\n".join(lines)


def _format_decision_tree_html(synthesis: dict[str, Any], evaluations: dict[str, Any]) -> str:
    cause = synthesis.get("undervaluation_cause", "")
    if not cause or not evaluations:
        return ""
    hv = evaluations.get("hidden_value", {})
    _, _, axes = _extract_eval_fields(hv)
    d = axes.get("d_score", axes.get("D", "?"))
    e = axes.get("e_score", axes.get("E", "?"))
    f = axes.get("f_score", axes.get("F", "?"))
    return f"""<div class="section">
    <h2><span class="icon">&#x1F333;</span> Cause Classification Logic</h2>
    <div class="synthesis-grid">
      <div class="synthesis-item">
        <div class="synthesis-item-label">D (Discovery)</div>
        <div class="synthesis-item-value">{d}</div>
      </div>
      <div class="synthesis-item">
        <div class="synthesis-item-label">E (Monetization)</div>
        <div class="synthesis-item-value">{e}</div>
      </div>
      <div class="synthesis-item">
        <div class="synthesis-item-label">F (Expandability)</div>
        <div class="synthesis-item-value">{f}</div>
      </div>
    </div>
    <p style="margin-top:0.8rem"><strong>Classification:</strong> <code>{cause}</code></p>
  </div>"""
