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
        conf_str = f"{confidence}%" if confidence else "—"
        lines.append(f"| {analyst} | {score} | {conf_str} | {finding} |")
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

        if template in (ReportTemplate.DETAILED, ReportTemplate.EXECUTIVE):
            subscores_section = _format_subscores_html(common["subscores"])
            synthesis_section = _format_synthesis_html(synthesis)

        if template == ReportTemplate.DETAILED:
            analyses_section = _format_analyses_html(common["analyses"])
            details_section = self._format_details_html(result)

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
            cause=synthesis.get("undervaluation_cause", "—"),
            action_type=synthesis.get("action_type", "—"),
            subscores_section=subscores_section,
            synthesis_section=synthesis_section,
            analyses_section=analyses_section,
            details_section=details_section,
        )

    def _generate_markdown(self, result: dict[str, Any], template: ReportTemplate) -> str:
        common = self._extract_common(result)
        synthesis = common.get("synthesis") or {}

        subscores_section = ""
        synthesis_section = ""
        analyses_section = ""
        details_section = ""

        if template in (ReportTemplate.DETAILED, ReportTemplate.EXECUTIVE):
            subscores_section = _format_subscores_md(common["subscores"])
            synthesis_section = _format_synthesis_md(synthesis)

        if template == ReportTemplate.DETAILED:
            analyses_section = _format_analyses_md(common["analyses"])
            details_section = self._format_details_md(result)

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
            details_section=details_section,
        )

    def _format_details_html(self, result: dict[str, Any]) -> str:
        guardrails = result.get("guardrails", {})
        if not guardrails:
            return ""
        passed = guardrails.get("all_passed", False)
        badge_cls = "verify-pass" if passed else "verify-fail"
        badge_icon = "✓" if passed else "✗"
        badge_text = "PASSED" if passed else "FAILED"
        details_list = guardrails.get("details", [])
        items = "\n".join(f"        <li>{d}</li>" for d in details_list)
        return f"""<div class="section">
    <h2><span class="icon">🛡️</span> Verification</h2>
    <p><span class="verify-badge {badge_cls}">{badge_icon} {badge_text}</span></p>
    <ul style="margin-top:0.8rem;padding-left:1.5rem;color:var(--muted);font-size:0.9rem">
{items}
    </ul>
  </div>"""

    def _format_details_md(self, result: dict[str, Any]) -> str:
        guardrails = result.get("guardrails", {})
        if not guardrails:
            return ""
        passed = guardrails.get("all_passed", False)
        status = "PASSED ✓" if passed else "FAILED ✗"
        details_list = guardrails.get("details", [])
        lines = [
            "## Verification",
            "",
            f"- **Guardrails:** {status}",
        ]
        for d in details_list:
            lines.append(f"  - {d}")
        return "\n".join(lines)
