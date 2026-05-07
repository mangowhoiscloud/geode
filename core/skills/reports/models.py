"""Report models — Enums, template loading, tier config, gauge geometry.

Originally part of ``core/skills/reports.py``; preserved verbatim during the
v0.71.0 God Object split.

Section provenance (lines from the pre-split ``reports.py``):

- Lines 23-95: ``ReportFormat`` / ``ReportTemplate`` Enums + template loading
  (``_TEMPLATES_DIR``, ``_load_template``, ``_HTML_TEMPLATE``,
  ``_MARKDOWN_SUMMARY``, ``_MARKDOWN_DETAILED``) + ``_TIER_CONFIG`` /
  ``_SUBSCORE_BARS`` constants + ``_tier_class`` / ``_get_tier_config`` helpers.
- Lines 101-108: ``_GAUGE_RADIUS`` / ``_GAUGE_CIRCUMFERENCE`` / ``_gauge_offset``.
"""

from __future__ import annotations

import math
from enum import StrEnum
from pathlib import Path
from string import Template

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
    tier_upper = tier.upper()
    if tier_upper in ("S", "A"):
        return "tier-high"
    if tier_upper in ("B",):
        return "tier-mid"
    return "tier-low"


def _get_tier_config(tier: str) -> dict[str, str]:
    return _TIER_CONFIG.get(tier.upper(), _TIER_CONFIG["C"])


# ---------------------------------------------------------------------------
# HTML formatters — gauge geometry shared across HTML formatters
# ---------------------------------------------------------------------------

_GAUGE_RADIUS = 34
_GAUGE_CIRCUMFERENCE = 2 * math.pi * _GAUGE_RADIUS


def _gauge_offset(score: float) -> float:
    """Calculate SVG stroke-dashoffset for a 0-100 score gauge."""
    pct = max(0, min(score, 100)) / 100
    return _GAUGE_CIRCUMFERENCE * (1 - pct)
