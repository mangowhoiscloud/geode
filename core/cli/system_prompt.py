"""System prompt builder for AgenticLoop.

Builds the base system prompt from the router.md template, enriched with
domain plugin IP examples and project memory context.

Extracted from ``nl_router.py`` so that the AgenticLoop can use the system
prompt without depending on the NL Router module.
"""

from __future__ import annotations

import logging
from datetime import datetime

from core.cli.ip_names import get_ip_name_map
from core.llm.prompts import ROUTER_SYSTEM

log = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = ROUTER_SYSTEM

# Well-known IPs to include as examples (recognizable across languages)
_NOTABLE_IPS = {
    "berserk",
    "cowboy bebop",
    "ghost in shell",
    "hollow knight",
    "disco elysium",
    "hades",
    "celeste",
    "cult of the lamb",
    "dead cells",
    "slay the spire",
    "vampire survivors",
    "factorio",
    "stardew valley",
    "cuphead",
    "balatro",
    "rimworld",
}


def build_system_prompt(model: str = "") -> str:
    """Build system prompt with model card, IP examples, and memory context."""
    from core.fixtures import FIXTURE_MAP, load_fixture

    name_map = get_ip_name_map()
    ip_count = len(name_map)

    # Prefer notable IPs as examples, then fill with others
    examples: list[str] = []
    for fk in _NOTABLE_IPS:
        if fk in FIXTURE_MAP:
            try:
                canonical = load_fixture(fk)["ip_info"]["ip_name"]
                examples.append(canonical)
            except Exception:
                examples.append(fk.title())

    base = _SYSTEM_PROMPT_TEMPLATE.format(
        ip_count=ip_count,
        ip_examples=", ".join(sorted(examples)),
    )

    # Model card: inject current model info so LLM can answer model questions directly
    if model:
        model_card = _build_model_card(model)
        if model_card:
            base += "\n\n" + model_card

    # Inject current date so LLM uses the correct year for searches
    base += "\n\n" + _build_date_context()

    # P1-C: Inject memory context (recent insights + active rules)
    memory_ctx = _build_memory_context()
    if memory_ctx:
        base += "\n\n" + memory_ctx

    return base


def _build_date_context() -> str:
    """Build current date string for system prompt injection.

    Prevents the LLM from defaulting to its knowledge-cutoff year when
    searching for recent information.
    """
    now = datetime.now()
    return (
        f"## Current Date\n"
        f"Today is {now.strftime('%Y-%m-%d (%A)')}. "
        f"The current year is {now.year}. "
        f"When searching for recent or latest information, use {now.year} as the base year."
    )


def _build_model_card(model: str) -> str:
    """Build a model card string for system prompt injection.

    Reads from MODEL_PRICING and MODEL_CONTEXT_WINDOW so the LLM
    can answer model-related questions directly without tool calls.
    """
    try:
        from core.config import _resolve_provider
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW, MODEL_PRICING

        provider = _resolve_provider(model)
        pricing = MODEL_PRICING.get(model)
        ctx_window = MODEL_CONTEXT_WINDOW.get(model, 0)

        parts: list[str] = [f"## Current Model\nYou are powered by **{model}** ({provider})."]

        if ctx_window:
            if ctx_window < 1_000_000:
                ctx_str = f"{ctx_window // 1000}K"
            else:
                ctx_str = f"{ctx_window / 1_000_000:.0f}M"
            parts.append(f"Context window: {ctx_str} tokens.")

        if pricing:
            parts.append(
                f"Cost: ${pricing.input:.2f} input / ${pricing.output:.2f} output per 1M tokens."
            )

        # Fallback chain
        from core.config import (
            ANTHROPIC_FALLBACK_CHAIN,
            GLM_FALLBACK_CHAIN,
            OPENAI_FALLBACK_CHAIN,
        )

        chains = {
            "anthropic": ANTHROPIC_FALLBACK_CHAIN,
            "openai": OPENAI_FALLBACK_CHAIN,
            "glm": GLM_FALLBACK_CHAIN,
        }
        chain = chains.get(provider, [])
        if chain:
            parts.append(f"Fallback chain: {' -> '.join(chain)}.")

        parts.append(
            "For model-related questions, answer directly from this context. "
            "Do NOT call check_status for model info."
        )

        return "\n".join(parts)
    except Exception:
        log.debug("Failed to build model card", exc_info=True)
        return ""


def _build_memory_context() -> str:
    """Build memory context string from ProjectMemory (recent insights + rules)."""
    try:
        from core.memory.project import ProjectMemory

        mem = ProjectMemory()
        if not mem.exists():
            return ""

        parts: list[str] = []

        # Recent insights (last 5 lines from MEMORY.md's recent insights section)
        content = mem.load_memory()
        if "## 최근 인사이트" in content:
            section = content.split("## 최근 인사이트")[1]
            lines = [ln.strip() for ln in section.split("\n") if ln.strip().startswith("- ")]
            if lines:
                parts.append("Recent insights:\n" + "\n".join(lines[:5]))

        # Active rules summary
        rules = mem.list_rules()
        if rules:
            rule_summaries = [
                f"- {r['name']} (paths: {', '.join(r.get('paths', []))})" for r in rules[:5]
            ]
            parts.append("Active analysis rules:\n" + "\n".join(rule_summaries))

        return "\n\n".join(parts)
    except Exception:
        log.debug("Failed to build memory context for system prompt", exc_info=True)
        return ""
