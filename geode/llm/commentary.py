"""LLM commentary generation for tool call results.

After a tool call (analyze, search, list, compare) produces structured output,
this module generates a brief natural-language commentary that highlights
key insights and suggests next actions.

Graceful degradation: all exceptions are caught and return None so that
commentary failures never break the main pipeline output.
"""

from __future__ import annotations

import logging
from typing import Any

from geode.llm.client import call_llm

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

COMMENTARY_SYSTEM = """You are GEODE, an IP discovery assistant for game publishing.
Rules:
- 2-4 sentences only
- Same language as user query (Korean query → Korean response, English → English)
- Highlight the single most important insight
- Do NOT repeat raw data already shown in the panels above
- Suggest a concrete next action when appropriate
- Be conversational but professional"""

COMMENTARY_USER = """User query: {user_query}
Action performed: {action}
{context_summary}
Brief commentary (2-4 sentences):"""


# ---------------------------------------------------------------------------
# Context builders — pure data transforms, no I/O
# ---------------------------------------------------------------------------


def build_analyze_context(result: dict[str, Any]) -> dict[str, Any]:
    """Extract commentary-relevant fields from a pipeline analysis result."""
    ctx: dict[str, Any] = {}
    ctx["tier"] = result.get("tier", "?")
    ctx["final_score"] = result.get("final_score", 0)
    ctx["ip_name"] = result.get("ip_name", "")

    # Subscore highlights
    subscores = result.get("subscores", {})
    if subscores:
        ctx["subscores"] = subscores

    # Root cause from expected_results or cause field
    ctx["cause"] = result.get("cause", "")

    # Synthesis narrative (truncated for context window)
    synthesis = result.get("synthesis")
    if synthesis:
        # SynthesisResult object → extract value_narrative
        if hasattr(synthesis, "value_narrative"):
            ctx["narrative"] = str(synthesis.value_narrative)[:300]
        elif isinstance(synthesis, str):
            ctx["narrative"] = synthesis[:300]

    return ctx


def build_search_context(query: str, results: list[Any]) -> dict[str, Any]:
    """Extract commentary-relevant fields from search results."""
    ctx: dict[str, Any] = {
        "query": query,
        "result_count": len(results),
    }
    if results:
        ctx["top_matches"] = [
            {"ip_name": r.ip_name, "score": round(r.score, 2)} for r in results[:3]
        ]
    return ctx


def build_list_context(ip_names: list[str]) -> dict[str, Any]:
    """Extract commentary-relevant fields from IP list."""
    return {
        "ip_count": len(ip_names),
        "ip_names": ip_names[:10],  # cap for prompt size
    }


def build_compare_context(
    ip_a: str,
    result_a: dict[str, Any] | None,
    ip_b: str,
    result_b: dict[str, Any] | None,
) -> dict[str, Any]:
    """Extract commentary-relevant fields from a comparison of two IPs."""
    ctx: dict[str, Any] = {"ip_a": ip_a, "ip_b": ip_b}

    if result_a:
        ctx["tier_a"] = result_a.get("tier", "?")
        ctx["score_a"] = result_a.get("final_score", 0)
    else:
        ctx["tier_a"] = "N/A"
        ctx["score_a"] = 0

    if result_b:
        ctx["tier_b"] = result_b.get("tier", "?")
        ctx["score_b"] = result_b.get("final_score", 0)
    else:
        ctx["tier_b"] = "N/A"
        ctx["score_b"] = 0

    return ctx


# ---------------------------------------------------------------------------
# Commentary generation
# ---------------------------------------------------------------------------


def _format_context(context: dict[str, Any]) -> str:
    """Format context dict into a readable summary string for the prompt."""
    lines: list[str] = []
    for key, value in context.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def generate_commentary(
    user_query: str,
    action: str,
    context: dict[str, Any],
    *,
    model: str | None = None,
    max_tokens: int = 256,
    temperature: float = 0.4,
) -> str | None:
    """Generate a brief LLM commentary for tool call results.

    Returns the commentary text, or None if generation fails for any reason.
    """
    try:
        context_summary = _format_context(context)
        user_prompt = COMMENTARY_USER.format(
            user_query=user_query,
            action=action,
            context_summary=context_summary,
        )
        text = call_llm(
            COMMENTARY_SYSTEM,
            user_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        stripped = text.strip() if text else ""
        return stripped or None
    except Exception:
        log.debug("Commentary generation failed", exc_info=True)
        return None
