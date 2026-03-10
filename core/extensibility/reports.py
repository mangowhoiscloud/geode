"""Report Generation — produce formatted reports from pipeline results.

Layer 5 extensibility component for generating HTML, JSON, and Markdown
reports from GEODE pipeline output.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
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
# Templates (string.Template for zero-dependency rendering)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GEODE Report: ${ip_name}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
         sans-serif; line-height: 1.6; color: #1a1a2e; background: #f0f0f5;
         padding: 2rem; }
  .container { max-width: 900px; margin: 0 auto; background: #fff;
               border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08);
               padding: 2.5rem; }
  h1 { font-size: 1.8rem; margin-bottom: 0.5rem; color: #16213e; }
  h2 { font-size: 1.3rem; margin: 1.5rem 0 0.8rem; color: #0f3460;
       border-bottom: 2px solid #e2e8f0; padding-bottom: 0.4rem; }
  .meta { color: #64748b; font-size: 0.9rem; margin-bottom: 1.5rem; }
  .score-badge { display: inline-block; padding: 0.3rem 1rem;
                 border-radius: 20px; font-weight: 600; font-size: 1.1rem; }
  .tier-high { background: #d4edda; color: #155724; }
  .tier-mid  { background: #fff3cd; color: #856404; }
  .tier-low  { background: #f8d7da; color: #721c24; }
  table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
  th, td { text-align: left; padding: 0.6rem 1rem; border-bottom: 1px solid #e2e8f0; }
  th { background: #f8fafc; font-weight: 600; color: #334155; }
  .section { margin-bottom: 1.5rem; }
  .narrative { background: #f8fafc; padding: 1.2rem; border-radius: 8px;
               border-left: 4px solid #0f3460; margin: 1rem 0; }
  footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #e2e8f0;
           color: #94a3b8; font-size: 0.8rem; text-align: center; }
</style>
</head>
<body>
<div class="container">
  <h1>GEODE Analysis: ${ip_name}</h1>
  <div class="meta">Generated: ${timestamp} | Template: ${template_type}</div>

  <div class="section">
    <h2>Score</h2>
    <p>Final Score: <span class="score-badge ${tier_class}">${final_score}</span></p>
    <p>Tier: <strong>${tier}</strong></p>
  </div>

  ${subscores_section}

  ${synthesis_section}

  ${analyses_section}

  ${details_section}

  <footer>GEODE v0.6.0 | Undervalued IP Discovery Agent</footer>
</div>
</body>
</html>""")

_MARKDOWN_SUMMARY = Template("""\
# GEODE Report: ${ip_name}

**Generated:** ${timestamp}
**Template:** ${template_type}

## Score

- **Final Score:** ${final_score}
- **Tier:** ${tier}

${subscores_section}

${synthesis_section}
""")

_MARKDOWN_DETAILED = Template("""\
# GEODE Report: ${ip_name}

**Generated:** ${timestamp}
**Template:** ${template_type}

## Score

- **Final Score:** ${final_score}
- **Tier:** ${tier}

${subscores_section}

${synthesis_section}

${analyses_section}

${details_section}
""")


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
