"""Cross-LLM Agreement formatters (P0: shows model consensus).

Originally lines 696-742 of the pre-split ``core/skills/reports.py``.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Cross-LLM Agreement formatters (P0: shows model consensus)
# ---------------------------------------------------------------------------


def _format_cross_llm_md(cross_llm: dict[str, Any]) -> str:
    if not cross_llm:
        return ""
    agreement = cross_llm.get("cross_llm_agreement", 0.0)
    models = cross_llm.get("models_compared", [])
    passed = cross_llm.get("passed", False)
    mode = cross_llm.get("verification_mode", "N/A")
    secondary = cross_llm.get("secondary_score")
    status = "PASS" if passed else "FAIL"
    lines = [
        "## Cross-LLM Verification",
        "",
        f"- **Agreement Score:** {agreement:.2f} ({status})",
        f"- **Verification Mode:** {mode}",
    ]
    if models:
        lines.append(f"- **Models Compared:** {', '.join(models)}")
    if secondary is not None:
        lines.append(f"- **Secondary Re-score:** {secondary}")
    return "\n".join(lines)


def _format_cross_llm_html(cross_llm: dict[str, Any]) -> str:
    if not cross_llm:
        return ""
    agreement = cross_llm.get("cross_llm_agreement", 0.0)
    models = cross_llm.get("models_compared", [])
    passed = cross_llm.get("passed", False)
    mode = cross_llm.get("verification_mode", "N/A")
    badge_cls = "verify-pass" if passed else "verify-fail"
    badge_text = f"AGREEMENT: {agreement:.2f}"
    models_str = ", ".join(models) if models else "N/A"
    return f"""<div class="section">
    <h2><span class="icon">&#x1F91D;</span> Cross-LLM Verification</h2>
    <p><span class="verify-badge {badge_cls}">{badge_text}</span></p>
    <div class="synthesis-grid">
      <div class="synthesis-item">
        <div class="synthesis-item-label">Verification Mode</div>
        <div class="synthesis-item-value">{mode}</div>
      </div>
      <div class="synthesis-item">
        <div class="synthesis-item-label">Models Compared</div>
        <div class="synthesis-item-value">{models_str}</div>
      </div>
    </div>
  </div>"""
