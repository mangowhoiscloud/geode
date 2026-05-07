"""BiasBuster formatters (HTML + Markdown).

Originally lines 489-538 of the pre-split ``core/skills/reports.py``.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# BiasBuster formatters
# ---------------------------------------------------------------------------

_BIAS_TYPES = [
    ("confirmation_bias", "Confirmation"),
    ("recency_bias", "Recency"),
    ("anchoring_bias", "Anchoring"),
    ("position_bias", "Position"),
    ("verbosity_bias", "Verbosity"),
    ("self_enhancement_bias", "Self-Enhancement"),
]


def _format_biasbuster_html(biasbuster: dict[str, Any]) -> str:
    if not biasbuster:
        return ""
    overall = biasbuster.get("overall_pass", True)
    badge_cls = "verify-pass" if overall else "verify-fail"
    badge_text = "NO BIAS DETECTED" if overall else "BIAS DETECTED"
    explanation = biasbuster.get("explanation", "")
    flags = ""
    for field, label in _BIAS_TYPES:
        flagged = biasbuster.get(field, False)
        flag_span = "FLAGGED" if flagged else "OK"
        flag_color = "#dc2626" if flagged else "#16a34a"
        icon = f'<span style="color:{flag_color}">{flag_span}</span>'
        flags += f"      <tr><td>{label}</td><td>{icon}</td></tr>\n"
    exp_html = ""
    if explanation:
        exp_html = (
            f'<p style="margin-top:0.8rem;color:var(--muted);font-size:0.9rem">{explanation}</p>'
        )
    return f"""<div class="section">
    <h2><span class="icon">&#x1F50D;</span> BiasBuster</h2>
    <p><span class="verify-badge {badge_cls}">{badge_text}</span></p>
    <table>
      <thead><tr><th>Bias Type</th><th>Status</th></tr></thead>
      <tbody>
{flags}      </tbody>
    </table>
    {exp_html}
  </div>"""


def _format_biasbuster_md(biasbuster: dict[str, Any]) -> str:
    if not biasbuster:
        return ""
    overall = biasbuster.get("overall_pass", True)
    status = "PASS (no bias detected)" if overall else "FAIL (bias detected)"
    explanation = biasbuster.get("explanation", "")
    lines = [
        "## BiasBuster",
        "",
        f"- **Overall:** {status}",
    ]
    for field, label in _BIAS_TYPES:
        flagged = biasbuster.get(field, False)
        flag_str = "FLAGGED" if flagged else "OK"
        lines.append(f"- {label}: {flag_str}")
    if explanation:
        lines.extend(["", f"> {explanation}"])
    return "\n".join(lines)
