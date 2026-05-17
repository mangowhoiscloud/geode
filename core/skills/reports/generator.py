"""ReportGenerator — orchestrates HTML / JSON / Markdown report rendering.

Originally lines 870-1156 of the pre-split ``core/skills/reports.py``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .analyst_reasoning import _format_analyst_reasoning_html, _format_analyst_reasoning_md
from .cross_llm import _format_cross_llm_html, _format_cross_llm_md
from .decision_tree import _format_decision_tree_html, _format_decision_tree_md
from .evaluators import _format_evaluators_html, _format_evaluators_md
from .models import (
    _GAUGE_CIRCUMFERENCE,
    _HTML_TEMPLATE,
    _MARKDOWN_DETAILED,
    _MARKDOWN_SUMMARY,
    ReportFormat,
    ReportTemplate,
    _gauge_offset,
    _get_tier_config,
    _tier_class,
)
from .psm import (
    _format_psm_html,
    _format_psm_md,
    _format_scoring_breakdown_html,
    _format_scoring_breakdown_md,
)
from .rights_risk import _format_rights_risk_html, _format_rights_risk_md
from .scoring import (
    _format_analyses_html,
    _format_analyses_md,
    _format_subscores_html,
    _format_subscores_md,
    _format_synthesis_html,
    _format_synthesis_md,
)
from .signals import _format_signals_html, _format_signals_md

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
            "signals": result.get("signals", {}),
            "analyst_confidence": result.get("analyst_confidence", 0.0),
            "cross_llm": result.get("cross_llm", {}),
            "rights_risk": result.get("rights_risk", {}),
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
            output["signals"] = common["signals"]
            output["analyst_confidence"] = common["analyst_confidence"]
            output["cross_llm"] = common["cross_llm"]
            output["rights_risk"] = common["rights_risk"]

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
        analyst_reasoning_section = ""
        details_section = ""
        evaluators_section = ""
        psm_section = ""
        scoring_breakdown_section = ""
        cross_llm_section = ""
        rights_risk_section = ""
        decision_tree_section = ""
        signals_section = ""

        if template in (ReportTemplate.DETAILED, ReportTemplate.EXECUTIVE):
            subscores_section = _format_subscores_html(common["subscores"])
            synthesis_section = _format_synthesis_html(synthesis)

        if template == ReportTemplate.DETAILED:
            analyses_section = _format_analyses_html(common["analyses"])
            analyst_reasoning_section = _format_analyst_reasoning_html(common["analyses"])
            evaluators_section = _format_evaluators_html(common["evaluations"])
            psm_section = _format_psm_html(common["psm_result"])
            scoring_breakdown_section = _format_scoring_breakdown_html(
                common["subscores"],
                common["analyst_confidence"],
            )
            decision_tree_section = _format_decision_tree_html(synthesis, common["evaluations"])
            details_section = self._format_details_html(result)
            cross_llm_section = _format_cross_llm_html(common["cross_llm"])
            rights_risk_section = _format_rights_risk_html(common["rights_risk"])
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
            analyst_reasoning_section=analyst_reasoning_section,
            evaluators_section=evaluators_section,
            psm_section=psm_section,
            scoring_breakdown_section=scoring_breakdown_section,
            decision_tree_section=decision_tree_section,
            details_section=details_section,
            cross_llm_section=cross_llm_section,
            rights_risk_section=rights_risk_section,
            signals_section=signals_section,
        )

    def _generate_markdown(self, result: dict[str, Any], template: ReportTemplate) -> str:
        common = self._extract_common(result)
        synthesis = common.get("synthesis") or {}

        subscores_section = ""
        synthesis_section = ""
        analyses_section = ""
        analyst_reasoning_section = ""
        details_section = ""
        evaluators_section = ""
        psm_section = ""
        scoring_breakdown_section = ""
        cross_llm_section = ""
        rights_risk_section = ""
        decision_tree_section = ""
        signals_section = ""

        if template in (ReportTemplate.DETAILED, ReportTemplate.EXECUTIVE):
            subscores_section = _format_subscores_md(common["subscores"])
            synthesis_section = _format_synthesis_md(synthesis)

        if template == ReportTemplate.DETAILED:
            analyses_section = _format_analyses_md(common["analyses"])
            analyst_reasoning_section = _format_analyst_reasoning_md(common["analyses"])
            evaluators_section = _format_evaluators_md(common["evaluations"])
            psm_section = _format_psm_md(common["psm_result"])
            scoring_breakdown_section = _format_scoring_breakdown_md(
                common["subscores"],
                common["analyst_confidence"],
            )
            decision_tree_section = _format_decision_tree_md(synthesis, common["evaluations"])
            details_section = self._format_details_md(result)
            cross_llm_section = _format_cross_llm_md(common["cross_llm"])
            rights_risk_section = _format_rights_risk_md(common["rights_risk"])
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
            analyst_reasoning_section=analyst_reasoning_section,
            evaluators_section=evaluators_section,
            psm_section=psm_section,
            scoring_breakdown_section=scoring_breakdown_section,
            decision_tree_section=decision_tree_section,
            details_section=details_section,
            cross_llm_section=cross_llm_section,
            rights_risk_section=rights_risk_section,
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
