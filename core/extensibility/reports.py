"""Report Generation — produce formatted reports from pipeline results.

Layer 5 extensibility component for generating HTML, JSON, and Markdown
reports from GEODE pipeline output.
"""

from __future__ import annotations

import json
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
# Helpers
# ---------------------------------------------------------------------------


def _tier_class(tier: str) -> str:
    """Map tier string to CSS class."""
    tier_lower = tier.lower()
    if tier_lower in ("s", "a", "high"):
        return "tier-high"
    if tier_lower in ("b", "c", "mid", "medium"):
        return "tier-mid"
    return "tier-low"


def _format_subscores_html(subscores: dict[str, float]) -> str:
    """Format subscores as an HTML table."""
    if not subscores:
        return ""
    rows = "\n".join(
        f"    <tr><td>{key}</td><td>{value:.2f}</td></tr>"
        for key, value in sorted(subscores.items())
    )
    return f"""<div class="section">
    <h2>Sub-Scores</h2>
    <table>
      <tr><th>Dimension</th><th>Score</th></tr>
{rows}
    </table>
  </div>"""


def _format_subscores_md(subscores: dict[str, float]) -> str:
    """Format subscores as a Markdown table."""
    if not subscores:
        return ""
    lines = ["## Sub-Scores", "", "| Dimension | Score |", "| --- | --- |"]
    for key, value in sorted(subscores.items()):
        lines.append(f"| {key} | {value:.2f} |")
    return "\n".join(lines)


def _format_synthesis_html(synthesis: dict[str, Any]) -> str:
    """Format synthesis result as HTML."""
    if not synthesis:
        return ""
    cause = synthesis.get("undervaluation_cause", "N/A")
    action = synthesis.get("action_type", "N/A")
    narrative = synthesis.get("value_narrative", "")
    segment = synthesis.get("target_gamer_segment", "N/A")
    return f"""<div class="section">
    <h2>Synthesis</h2>
    <p><strong>Undervaluation Cause:</strong> {cause}</p>
    <p><strong>Action Type:</strong> {action}</p>
    <p><strong>Target Segment:</strong> {segment}</p>
    <div class="narrative">{narrative}</div>
  </div>"""


def _format_synthesis_md(synthesis: dict[str, Any]) -> str:
    """Format synthesis result as Markdown."""
    if not synthesis:
        return ""
    cause = synthesis.get("undervaluation_cause", "N/A")
    action = synthesis.get("action_type", "N/A")
    narrative = synthesis.get("value_narrative", "")
    segment = synthesis.get("target_gamer_segment", "N/A")
    lines = [
        "## Synthesis",
        "",
        f"- **Undervaluation Cause:** {cause}",
        f"- **Action Type:** {action}",
        f"- **Target Segment:** {segment}",
        "",
        f"> {narrative}",
    ]
    return "\n".join(lines)


def _format_analyses_html(analyses: list[dict[str, Any]]) -> str:
    """Format analysis results as HTML."""
    if not analyses:
        return ""
    rows = ""
    for a in analyses:
        rows += (
            f"    <tr><td>{a.get('analyst_type', 'N/A')}</td>"
            f"<td>{a.get('score', 'N/A')}</td>"
            f"<td>{a.get('key_finding', '')}</td></tr>\n"
        )
    return f"""<div class="section">
    <h2>Analyst Results</h2>
    <table>
      <tr><th>Analyst</th><th>Score</th><th>Key Finding</th></tr>
{rows}    </table>
  </div>"""


def _format_analyses_md(analyses: list[dict[str, Any]]) -> str:
    """Format analysis results as Markdown."""
    if not analyses:
        return ""
    lines = [
        "## Analyst Results",
        "",
        "| Analyst | Score | Key Finding |",
        "| --- | --- | --- |",
    ]
    for a in analyses:
        lines.append(
            f"| {a.get('analyst_type', 'N/A')} "
            f"| {a.get('score', 'N/A')} "
            f"| {a.get('key_finding', '')} |"
        )
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
    ) -> str:
        """Generate a formatted report.

        Args:
            result: Pipeline result dict with keys like ip_name, final_score,
                    tier, subscores, synthesis, analyses, etc.
            fmt: Output format (HTML, JSON, MARKDOWN).
            template: Detail level (SUMMARY, DETAILED, EXECUTIVE).

        Returns:
            Formatted report string.
        """
        if fmt == ReportFormat.JSON:
            return self._generate_json(result, template)
        if fmt == ReportFormat.HTML:
            return self._generate_html(result, template)
        return self._generate_markdown(result, template)

    def _extract_common(self, result: dict[str, Any]) -> dict[str, Any]:
        """Extract common fields from the result dict."""
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
        """Generate JSON report."""
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
        """Generate HTML report with inline CSS."""
        common = self._extract_common(result)

        subscores_section = ""
        synthesis_section = ""
        analyses_section = ""
        details_section = ""

        if template in (ReportTemplate.DETAILED, ReportTemplate.EXECUTIVE):
            subscores_section = _format_subscores_html(common["subscores"])
            synthesis_section = _format_synthesis_html(common["synthesis"])

        if template == ReportTemplate.DETAILED:
            analyses_section = _format_analyses_html(common["analyses"])
            details_section = self._format_details_html(result)

        return _HTML_TEMPLATE.substitute(
            ip_name=common["ip_name"],
            timestamp=common["timestamp"],
            template_type=template.value,
            final_score=f"{common['final_score']:.1f}",
            tier=common["tier"],
            tier_class=_tier_class(common["tier"]),
            subscores_section=subscores_section,
            synthesis_section=synthesis_section,
            analyses_section=analyses_section,
            details_section=details_section,
        )

    def _generate_markdown(self, result: dict[str, Any], template: ReportTemplate) -> str:
        """Generate Markdown report."""
        common = self._extract_common(result)

        subscores_section = ""
        synthesis_section = ""
        analyses_section = ""
        details_section = ""

        if template in (ReportTemplate.DETAILED, ReportTemplate.EXECUTIVE):
            subscores_section = _format_subscores_md(common["subscores"])
            synthesis_section = _format_synthesis_md(common["synthesis"])

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
        """Format additional details for DETAILED template."""
        guardrails = result.get("guardrails", {})
        if not guardrails:
            return ""
        passed = guardrails.get("all_passed", False)
        status = "PASSED" if passed else "FAILED"
        details_list = guardrails.get("details", [])
        items = "\n".join(f"      <li>{d}</li>" for d in details_list)
        return f"""<div class="section">
    <h2>Verification</h2>
    <p>Guardrails: <strong>{status}</strong></p>
    <ul>
{items}
    </ul>
  </div>"""

    def _format_details_md(self, result: dict[str, Any]) -> str:
        """Format additional details for DETAILED template."""
        guardrails = result.get("guardrails", {})
        if not guardrails:
            return ""
        passed = guardrails.get("all_passed", False)
        status = "PASSED" if passed else "FAILED"
        details_list = guardrails.get("details", [])
        lines = [
            "## Verification",
            "",
            f"- **Guardrails:** {status}",
        ]
        for d in details_list:
            lines.append(f"  - {d}")
        return "\n".join(lines)
