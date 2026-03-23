"""Report generation helpers extracted from core.cli.__init__.

Public API:
    _state_to_report_dict
    _parse_report_args
    _build_skill_narrative
    _generate_report
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.config import settings
from core.extensibility.reports import ReportFormat, ReportGenerator, ReportTemplate
from core.ui.console import console
from core.ui.status import GeodeStatus

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FORMAT_KEYWORDS = {"html", "json", "md", "markdown"}
_TEMPLATE_KEYWORDS = {"summary", "detailed", "executive"}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_REPORT_DIR = _PROJECT_ROOT / ".geode" / "reports"

# Skills relevant for report quality enhancement
_REPORT_SKILL_NAMES = ["geode-scoring", "geode-analysis", "geode-verification"]


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def _state_to_report_dict(state: dict[str, Any]) -> dict[str, Any]:
    """Convert a GeodeState dict to a plain dict suitable for ReportGenerator.

    Pydantic models are dumped via .model_dump(); scalars pass through.
    Missing fields get safe defaults.
    """
    from pydantic import BaseModel

    out: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, BaseModel):
            out[key] = value.model_dump()
        elif isinstance(value, list):
            out[key] = [v.model_dump() if isinstance(v, BaseModel) else v for v in value]
        elif isinstance(value, dict):
            out[key] = {
                k: v.model_dump() if isinstance(v, BaseModel) else v for k, v in value.items()
            }
        else:
            out[key] = value

    # Safe defaults for required report fields
    out.setdefault("ip_name", "Unknown IP")
    out.setdefault("final_score", 0.0)
    out.setdefault("tier", "N/A")
    out.setdefault("subscores", {})
    out.setdefault("synthesis", {})
    out.setdefault("analyses", [])
    out.setdefault("evaluations", {})
    out.setdefault("psm_result", {})
    out.setdefault("guardrails", {})
    out.setdefault("biasbuster", {})
    out.setdefault("signals", {})
    out.setdefault("analyst_confidence", 0.0)
    return out


def _parse_report_args(parts: list[str]) -> dict[str, str]:
    """Parse report arguments from a list of tokens.

    Returns dict with keys: ip_name, fmt, template.
    Example: ["Berserk", "html", "detailed"]
      -> {"ip_name": "Berserk", "fmt": "html", "template": "detailed"}
    """
    fmt = "md"
    template = "summary"
    ip_parts: list[str] = []

    for part in parts:
        lower = part.lower()
        if lower in _FORMAT_KEYWORDS:
            fmt = "markdown" if lower == "md" else lower
        elif lower in _TEMPLATE_KEYWORDS:
            template = lower
        else:
            ip_parts.append(part)

    return {
        "ip_name": " ".join(ip_parts) if ip_parts else "",
        "fmt": fmt,
        "template": template,
    }


def _build_skill_narrative(
    report_dict: dict[str, Any],
    skill_registry: Any,
) -> str:
    """Generate an expert narrative using skills context and LLM.

    Injects scoring/analysis/verification skills into the prompt so the LLM
    produces a domain-aware evaluation narrative.  Returns empty string on
    failure or when API key is unavailable.
    """
    from core.config import settings as _settings

    if not _settings.anthropic_api_key:
        return ""

    # Collect skill bodies
    skill_blocks: list[str] = []
    for name in _REPORT_SKILL_NAMES:
        skill = skill_registry.get(name)
        if skill and skill.body:
            skill_blocks.append(f"### {skill.name}\n{skill.body[:2000]}")

    if not skill_blocks:
        return ""

    skills_context = "\n\n".join(skill_blocks)

    ip_name = report_dict.get("ip_name", "Unknown")
    score = report_dict.get("final_score", 0)
    tier = report_dict.get("tier", "N/A")
    subscores = report_dict.get("subscores", {})
    synthesis = report_dict.get("synthesis", {})
    analyses = report_dict.get("analyses", [])

    analyst_summary = ""
    for a in analyses[:4]:
        if isinstance(a, dict):
            analyst_summary += (
                f"- {a.get('analyst_type', '?')}: score={a.get('score', '?')}, "
                f"finding={a.get('key_finding', '')[:120]}\n"
            )

    system_prompt = f"""You are a GEODE analysis expert. Write an expert analysis
section for a report on the subject below. Use the domain knowledge provided.

## Domain Knowledge (GEODE Skills)
{skills_context}

## Rules
- Write 3-5 paragraphs of expert analysis in Korean.
- Reference specific scoring dimensions and formulas from the skills context.
- Explain WHY this subject received its tier/score using scoring dimensions from skills context.
- Provide actionable insights and recommendations.
- Do NOT repeat raw data — interpret and synthesize it."""

    user_prompt = f"""## IP: {ip_name}
- Final Score: {score:.1f} / 100
- Tier: {tier}
- Subscores: {subscores}
- Synthesis: {synthesis}
- Analyst Findings:
{analyst_summary}

Write the Expert Analysis section."""

    try:
        from core.llm.client import call_llm

        return str(call_llm(system_prompt, user_prompt, max_tokens=2048, temperature=0.4))
    except Exception as exc:
        log.warning("Skill-enhanced narrative generation failed: %s", exc)
        return ""


def _generate_report(
    ip_name: str,
    *,
    fmt: str = "markdown",
    template: str = "summary",
    output: str | None = None,
    dry_run: bool = True,
    verbose: bool = False,
    skill_registry: Any = None,
) -> tuple[str, str] | None:
    """Generate a report for the given IP.

    Reuses cached pipeline result if available for the same IP,
    otherwise runs analysis first.  Always saves to ``.geode/reports/``
    and returns ``(file_path, content)``.
    """
    # Deferred imports to avoid circular dependency with core.cli.__init__
    # Import from core.cli (not pipeline_executor) so monkeypatching in tests works.
    from core.cli import _result_cache, _run_analysis

    # Resolve format/template enums
    try:
        report_fmt = ReportFormat(fmt)
    except ValueError:
        console.print(f"  [warning]Unknown format: {fmt}. Using markdown.[/warning]")
        report_fmt = ReportFormat.MARKDOWN

    try:
        report_tpl = ReportTemplate(template)
    except ValueError:
        console.print(f"  [warning]Unknown template: {template}. Using summary.[/warning]")
        report_tpl = ReportTemplate.SUMMARY

    # Try cached result first (multi-IP LRU)
    cached = _result_cache.get(ip_name)
    if cached is not None:
        result: dict[str, Any] = cached
    else:
        fresh = _run_analysis(ip_name, dry_run=dry_run, verbose=verbose)
        if fresh is None:
            return None
        result = fresh

    report_dict = _state_to_report_dict(result)

    # Skill-enhanced narrative (skip in dry-run to avoid LLM call)
    enhanced_narrative = ""
    if skill_registry is not None and not dry_run:
        with GeodeStatus("Generating expert analysis...", model=settings.model) as st:
            enhanced_narrative = _build_skill_narrative(report_dict, skill_registry)
            st.stop("expert analysis" if enhanced_narrative else "expert analysis (skipped)")

    generator = ReportGenerator()
    with console.status("  [cyan]Building report...[/cyan]", spinner="dots", spinner_style="cyan"):
        content = generator.generate(
            report_dict, fmt=report_fmt, template=report_tpl, enhanced_narrative=enhanced_narrative
        )

    # Determine save path
    ext_map = {ReportFormat.HTML: "html", ReportFormat.JSON: "json", ReportFormat.MARKDOWN: "md"}
    ext = ext_map.get(report_fmt, "md")
    safe_name = ip_name.lower().replace(" ", "-")

    if output:
        save_path = Path(output)
    else:
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        save_path = _REPORT_DIR / f"{safe_name}-{template}.{ext}"

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(content, encoding="utf-8")
    console.print(f"\n  [success]Report saved → {save_path}[/success]")

    # Also print to console
    console.print()
    console.print(content)
    console.print()

    return str(save_path), content
