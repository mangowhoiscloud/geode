"""Report Generation — produce formatted reports from pipeline results.

Layer 5 extensibility component for generating HTML, JSON, and Markdown
reports from GEODE pipeline output.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from string import Template
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ReportFormat(StrEnum):
    """Supported report output formats."""

    HTML = "html"
    JSON = "json"
    MARKDOWN = "markdown"


class ReportTemplate(StrEnum):
    """Report detail levels."""

    SUMMARY = "summary"
    DETAILED = "detailed"
    EXECUTIVE = "executive"


# ---------------------------------------------------------------------------
# Templates (loaded from external files, rendered via string.Template)
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(name: str) -> Template:
    """Load a string.Template from the templates directory."""
    path = _TEMPLATES_DIR / name
    return Template(path.read_text(encoding="utf-8"))


_HTML_TEMPLATE = _load_template("report.html")
_MARKDOWN_SUMMARY = _load_template("report_summary.md")
_MARKDOWN_DETAILED = _load_template("report_detailed.md")


# ---------------------------------------------------------------------------
# Tier / Color mapping
# ---------------------------------------------------------------------------

_TIER_CONFIG: dict[str, dict[str, str]] = {
    "S": {"color": "#dc2626", "css": "s", "desc": "Exceptional — Immediate action"},
    "A": {"color": "#2563eb", "css": "a", "desc": "High potential — Priority review"},
    "B": {"color": "#16a34a", "css": "b", "desc": "Moderate — Worth monitoring"},
    "C": {"color": "#6b7280", "css": "c", "desc": "Low — Re-evaluate later"},
}

_SUBSCORE_BARS = [
    ("psm", "bar-fill-psm"),
    ("quality", "bar-fill-quality"),
    ("recovery", "bar-fill-recovery"),
    ("growth", "bar-fill-growth"),
    ("momentum", "bar-fill-momentum"),
    ("dev", "bar-fill-dev"),
]


def _tier_class(tier: str) -> str:
    """Map tier string to CSS class."""
    tier_lower = tier.upper()
    if tier_lower in ("S", "A"):
        return "tier-high"
    if tier_lower in ("B",):
        return "tier-mid"
    return "tier-low"


def _get_tier_config(tier: str) -> dict[str, str]:
    return _TIER_CONFIG.get(tier.upper(), _TIER_CONFIG["C"])


# ---------------------------------------------------------------------------
# HTML formatters
# ---------------------------------------------------------------------------

_GAUGE_RADIUS = 34
_GAUGE_CIRCUMFERENCE = 2 * math.pi * _GAUGE_RADIUS


def _gauge_offset(score: float) -> float:
    """Calculate SVG stroke-dashoffset for a 0-100 score gauge."""
    pct = max(0, min(score, 100)) / 100
    return _GAUGE_CIRCUMFERENCE * (1 - pct)


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


# ---------------------------------------------------------------------------
# Evaluator formatters
# ---------------------------------------------------------------------------


def _format_evaluators_html(evaluations: dict[str, Any]) -> str:
    if not evaluations:
        return ""
    rows = ""
    for etype, ev in evaluations.items():
        if isinstance(ev, dict):
            composite = ev.get("composite_score", 0)
            rationale = ev.get("rationale", "")
            axes = ev.get("axes", {})
        else:
            composite = getattr(ev, "composite_score", 0)
            rationale = getattr(ev, "rationale", "")
            axes = getattr(ev, "axes", {})
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
        if isinstance(ev, dict):
            composite = ev.get("composite_score", 0)
            rationale = ev.get("rationale", "")
            axes = ev.get("axes", {})
        else:
            composite = getattr(ev, "composite_score", 0)
            rationale = getattr(ev, "rationale", "")
            axes = getattr(ev, "axes", {})
        lines.append(f"| {etype} | {composite:.1f} | {rationale[:80]} |")

    # Axis breakdown per evaluator
    lines.append("")
    lines.append("### Axis Breakdown")
    lines.append("")
    for etype, ev in evaluations.items():
        axes = ev.get("axes", {}) if isinstance(ev, dict) else getattr(ev, "axes", {})
        if axes:
            lines.append(f"**{etype}**:")
            for axis_name, axis_val in axes.items():
                lines.append(f"- {axis_name}: {axis_val:.1f}")
            lines.append("")

    return "\n".join(lines)


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

_SCORING_WEIGHTS = [
    ("psm", 0.25),
    ("quality", 0.20),
    ("recovery", 0.18),
    ("growth", 0.12),
    ("momentum", 0.20),
    ("dev", 0.05),
]


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
    multiplier = 0.7 + 0.3 * confidence / 100 if confidence else 1.0
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
    multiplier = 0.7 + 0.3 * confidence / 100 if confidence else 1.0
    final = weighted_sum * multiplier
    lines.append("")
    lines.append(
        f"**Weighted Sum:** {weighted_sum:.1f} | "
        f"**Confidence Multiplier:** {multiplier:.3f} (confidence={confidence:.0f}) | "
        f"**Final:** {final:.1f}"
    )
    return "\n".join(lines)


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


# ---------------------------------------------------------------------------
# Signals formatters
# ---------------------------------------------------------------------------


def _format_signals_html(signals: dict[str, Any]) -> str:
    if not signals:
        return ""
    rows = ""
    display_map = {
        "youtube_views": ("YouTube Views", ""),
        "reddit_subscribers": ("Reddit Subscribers", ""),
        "fan_art_yoy_pct": ("Fan Art YoY Growth", "%"),
        "google_trends_index": ("Google Trends Index", ""),
        "twitter_mentions_monthly": ("Twitter Mentions (Monthly)", ""),
        "cosplay_events_annual": ("Cosplay Events (Annual)", ""),
        "mod_patch_activity": ("Mod/Patch Activity", ""),
        "game_sales_data": ("Game Sales Data", ""),
    }
    for key, (label, suffix) in display_map.items():
        val = signals.get(key)
        if val is not None:
            if isinstance(val, int | float) and not isinstance(val, bool):
                display = f"{val:,.0f}{suffix}" if isinstance(val, int) else f"{val:.1f}{suffix}"
            else:
                display = str(val)
            rows += f"      <tr><td>{label}</td><td>{display}</td></tr>\n"

    # Genre fit keywords
    keywords = signals.get("genre_fit_keywords", [])
    if keywords:
        kw_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
        rows += f"      <tr><td>Genre Fit Keywords</td><td>{kw_str}</td></tr>\n"

    if not rows:
        return ""
    return f"""<div class="section">
    <h2><span class="icon">&#x1F4E1;</span> External Signals</h2>
    <table>
      <thead><tr><th>Signal</th><th>Value</th></tr></thead>
      <tbody>
{rows}      </tbody>
    </table>
  </div>"""


def _format_signals_md(signals: dict[str, Any]) -> str:
    if not signals:
        return ""
    display_map = {
        "youtube_views": ("YouTube Views", ""),
        "reddit_subscribers": ("Reddit Subscribers", ""),
        "fan_art_yoy_pct": ("Fan Art YoY Growth", "%"),
        "google_trends_index": ("Google Trends Index", ""),
        "twitter_mentions_monthly": ("Twitter Mentions (Monthly)", ""),
        "cosplay_events_annual": ("Cosplay Events (Annual)", ""),
        "mod_patch_activity": ("Mod/Patch Activity", ""),
        "game_sales_data": ("Game Sales Data", ""),
    }
    lines = [
        "## External Signals",
        "",
        "| Signal | Value |",
        "| --- | --- |",
    ]
    has_data = False
    for key, (label, suffix) in display_map.items():
        val = signals.get(key)
        if val is not None:
            has_data = True
            if isinstance(val, int | float) and not isinstance(val, bool):
                display = f"{val:,.0f}{suffix}" if isinstance(val, int) else f"{val:.1f}{suffix}"
            else:
                display = str(val)
            lines.append(f"| {label} | {display} |")

    keywords = signals.get("genre_fit_keywords", [])
    if keywords:
        has_data = True
        kw_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
        lines.append(f"| Genre Fit Keywords | {kw_str} |")

    if not has_data:
        return ""
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report Generator
# ---------------------------------------------------------------------------


class ReportGenerator:
    """Generate reports from GEODE pipeline results.

    Takes a pipeline result dict and produces formatted output in
    HTML, JSON, or Markdown using string.Template (no Jinja2 dependency).
    """

    def generate(
        self,
        result: dict[str, Any],
        *,
        fmt: ReportFormat = ReportFormat.MARKDOWN,
        template: ReportTemplate = ReportTemplate.SUMMARY,
        enhanced_narrative: str = "",
    ) -> str:
        if enhanced_narrative:
            result = {**result, "enhanced_narrative": enhanced_narrative}
        if fmt == ReportFormat.JSON:
            return self._generate_json(result, template)
        if fmt == ReportFormat.HTML:
            return self._generate_html(result, template)
        return self._generate_markdown(result, template)

    def _extract_common(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "ip_name": result.get("ip_name", "Unknown IP"),
            "timestamp": datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "final_score": result.get("final_score", 0.0),
            "tier": result.get("tier", "N/A"),
            "subscores": result.get("subscores", {}),
            "synthesis": result.get("synthesis", {}),
            "analyses": result.get("analyses", []),
            "evaluations": result.get("evaluations", {}),
            "psm_result": result.get("psm_result", {}),
            "guardrails": result.get("guardrails", {}),
            "biasbuster": result.get("biasbuster", {}),
            "signals": result.get("signals", {}),
            "analyst_confidence": result.get("analyst_confidence", 0.0),
        }

    def _generate_json(self, result: dict[str, Any], template: ReportTemplate) -> str:
        common = self._extract_common(result)
        output: dict[str, Any] = {
            "report_type": template.value,
            "generated_at": common["timestamp"],
            "ip_name": common["ip_name"],
            "final_score": common["final_score"],
            "tier": common["tier"],
        }

        if template in (ReportTemplate.DETAILED, ReportTemplate.EXECUTIVE):
            output["subscores"] = common["subscores"]
            output["synthesis"] = common["synthesis"]

        if template == ReportTemplate.DETAILED:
            output["analyses"] = common["analyses"]
            output["evaluations"] = common["evaluations"]
            output["psm_result"] = common["psm_result"]
            output["guardrails"] = common["guardrails"]
            output["biasbuster"] = common["biasbuster"]
            output["signals"] = common["signals"]
            output["analyst_confidence"] = common["analyst_confidence"]

        return json.dumps(output, indent=2, ensure_ascii=False)

    def _generate_html(self, result: dict[str, Any], template: ReportTemplate) -> str:
        common = self._extract_common(result)
        tier = str(common["tier"]).upper()
        tier_cfg = _get_tier_config(tier)
        score = float(common["final_score"])
        synthesis = common.get("synthesis") or {}

        subscores_section = ""
        synthesis_section = ""
        analyses_section = ""
        details_section = ""
        evaluators_section = ""
        psm_section = ""
        scoring_breakdown_section = ""
        biasbuster_section = ""
        signals_section = ""

        if template in (ReportTemplate.DETAILED, ReportTemplate.EXECUTIVE):
            subscores_section = _format_subscores_html(common["subscores"])
            synthesis_section = _format_synthesis_html(synthesis)

        if template == ReportTemplate.DETAILED:
            analyses_section = _format_analyses_html(common["analyses"])
            evaluators_section = _format_evaluators_html(common["evaluations"])
            psm_section = _format_psm_html(common["psm_result"])
            scoring_breakdown_section = _format_scoring_breakdown_html(
                common["subscores"],
                common["analyst_confidence"],
            )
            details_section = self._format_details_html(result)
            biasbuster_section = _format_biasbuster_html(common["biasbuster"])
            signals_section = _format_signals_html(common["signals"])

        return _HTML_TEMPLATE.substitute(
            ip_name=common["ip_name"],
            timestamp=common["timestamp"],
            template_type=template.value,
            final_score=f"{score:.1f}",
            tier=tier,
            tier_lower=tier_cfg["css"],
            tier_color=tier_cfg["color"],
            tier_description=tier_cfg["desc"],
            tier_class=_tier_class(tier),
            gauge_circumference=f"{_GAUGE_CIRCUMFERENCE:.1f}",
            gauge_offset=f"{_gauge_offset(score):.1f}",
            cause=synthesis.get("undervaluation_cause", "---"),
            action_type=synthesis.get("action_type", "---"),
            subscores_section=subscores_section,
            synthesis_section=synthesis_section,
            analyses_section=analyses_section,
            evaluators_section=evaluators_section,
            psm_section=psm_section,
            scoring_breakdown_section=scoring_breakdown_section,
            details_section=details_section,
            biasbuster_section=biasbuster_section,
            signals_section=signals_section,
        )

    def _generate_markdown(self, result: dict[str, Any], template: ReportTemplate) -> str:
        common = self._extract_common(result)
        synthesis = common.get("synthesis") or {}

        subscores_section = ""
        synthesis_section = ""
        analyses_section = ""
        details_section = ""
        evaluators_section = ""
        psm_section = ""
        scoring_breakdown_section = ""
        biasbuster_section = ""
        signals_section = ""

        if template in (ReportTemplate.DETAILED, ReportTemplate.EXECUTIVE):
            subscores_section = _format_subscores_md(common["subscores"])
            synthesis_section = _format_synthesis_md(synthesis)

        if template == ReportTemplate.DETAILED:
            analyses_section = _format_analyses_md(common["analyses"])
            evaluators_section = _format_evaluators_md(common["evaluations"])
            psm_section = _format_psm_md(common["psm_result"])
            scoring_breakdown_section = _format_scoring_breakdown_md(
                common["subscores"],
                common["analyst_confidence"],
            )
            details_section = self._format_details_md(result)
            biasbuster_section = _format_biasbuster_md(common["biasbuster"])
            signals_section = _format_signals_md(common["signals"])

        tpl = _MARKDOWN_DETAILED if template == ReportTemplate.DETAILED else _MARKDOWN_SUMMARY
        return tpl.substitute(
            ip_name=common["ip_name"],
            timestamp=common["timestamp"],
            template_type=template.value,
            final_score=f"{common['final_score']:.1f}",
            tier=common["tier"],
            subscores_section=subscores_section,
            synthesis_section=synthesis_section,
            analyses_section=analyses_section,
            evaluators_section=evaluators_section,
            psm_section=psm_section,
            scoring_breakdown_section=scoring_breakdown_section,
            details_section=details_section,
            biasbuster_section=biasbuster_section,
            signals_section=signals_section,
        )

    def _format_details_html(self, result: dict[str, Any]) -> str:
        guardrails = result.get("guardrails", {})
        if not guardrails:
            return ""
        passed = guardrails.get("all_passed", False)
        badge_cls = "verify-pass" if passed else "verify-fail"
        badge_icon = "PASSED" if passed else "FAILED"
        details_list = guardrails.get("details", [])
        items = "\n".join(f"        <li>{d}</li>" for d in details_list)

        # Individual guardrail checks
        g_checks = ""
        g_map = [
            ("g1_schema", "G1 Schema"),
            ("g2_range", "G2 Range"),
            ("g3_grounding", "G3 Grounding"),
            ("g4_consistency", "G4 Consistency"),
        ]
        for field, label in g_map:
            val = guardrails.get(field)
            if val is not None:
                g_text = "PASS" if val else "FAIL"
                g_color = "#16a34a" if val else "#dc2626"
                icon = f'<span style="color:{g_color}">{g_text}</span>'
                g_checks += f"      <tr><td>{label}</td><td>{icon}</td></tr>\n"

        grounding = guardrails.get("grounding_ratio")
        grounding_row = ""
        if grounding is not None:
            grounding_row = (
                '<p style="margin-top:0.5rem;color:var(--muted);'
                f'font-size:0.85rem">Grounding ratio: {grounding:.0%}</p>'
            )

        g_table = ""
        if g_checks:
            g_table = f"""<table style="margin-top:0.8rem">
      <thead><tr><th>Check</th><th>Status</th></tr></thead>
      <tbody>
{g_checks}      </tbody>
    </table>"""

        return f"""<div class="section">
    <h2><span class="icon">&#x1F6E1;</span> Guardrails</h2>
    <p><span class="verify-badge {badge_cls}">{badge_icon}</span></p>
    {g_table}
    {grounding_row}
    <ul style="margin-top:0.8rem;padding-left:1.5rem;color:var(--muted);font-size:0.9rem">
{items}
    </ul>
  </div>"""

    def _format_details_md(self, result: dict[str, Any]) -> str:
        guardrails = result.get("guardrails", {})
        if not guardrails:
            return ""
        passed = guardrails.get("all_passed", False)
        status = "PASSED" if passed else "FAILED"
        lines = [
            "## Guardrails",
            "",
            f"- **Overall:** {status}",
        ]

        # Individual guardrail checks
        g_map = [
            ("g1_schema", "G1 Schema"),
            ("g2_range", "G2 Range"),
            ("g3_grounding", "G3 Grounding"),
            ("g4_consistency", "G4 Consistency"),
        ]
        for field, label in g_map:
            val = guardrails.get(field)
            if val is not None:
                flag = "PASS" if val else "FAIL"
                lines.append(f"- {label}: {flag}")

        grounding = guardrails.get("grounding_ratio")
        if grounding is not None:
            lines.append(f"- Grounding Ratio: {grounding:.0%}")

        details_list = guardrails.get("details", [])
        if details_list:
            lines.append("")
            lines.append("**Details:**")
            for d in details_list:
                lines.append(f"- {d}")
        return "\n".join(lines)
