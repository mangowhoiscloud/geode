"""Report Generation — produce formatted reports from pipeline results.

Layer 5 extensibility component for generating HTML, JSON, and Markdown
reports from GEODE pipeline output.

Originally a single 1156-line ``core/skills/reports.py`` God Object; split
into focused sub-modules in v0.71.0 while preserving every public symbol:

- ``models``           — Enums, template loading, tier/gauge constants
- ``scoring``          — Subscores / synthesis / analyses formatters
- ``evaluators``       — Evaluator field extraction + formatters
- ``psm``              — PSM engine + scoring breakdown formatters
- ``biasbuster``       — BiasBuster formatters
- ``signals``          — External signals formatters
- ``analyst_reasoning``— Analyst reasoning formatters (P0)
- ``cross_llm``        — Cross-LLM agreement formatters (P0)
- ``rights_risk``      — IP rights risk formatters (P0)
- ``decision_tree``    — Cause classification logic formatters (P1)
- ``generator``        — ``ReportGenerator`` orchestration class

Public re-exports preserve the pre-split import surface for callers in
``core.cli.report_renderer`` and ``tests.test_reports``.
"""

from __future__ import annotations

from .analyst_reasoning import _format_analyst_reasoning_html, _format_analyst_reasoning_md
from .cross_llm import _format_cross_llm_html, _format_cross_llm_md
from .decision_tree import _format_decision_tree_html, _format_decision_tree_md
from .generator import ReportGenerator
from .models import ReportFormat, ReportTemplate
from .rights_risk import _format_rights_risk_html, _format_rights_risk_md

__all__ = [
    "ReportFormat",
    "ReportGenerator",
    "ReportTemplate",
    "_format_analyst_reasoning_html",
    "_format_analyst_reasoning_md",
    "_format_cross_llm_html",
    "_format_cross_llm_md",
    "_format_decision_tree_html",
    "_format_decision_tree_md",
    "_format_rights_risk_html",
    "_format_rights_risk_md",
]
