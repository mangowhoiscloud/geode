"""System prompt builder for AgenticLoop.

Builds the base system prompt from the router.md template, enriched with
domain plugin IP examples and project memory context.

Memory hierarchy injected into the system prompt (G1-G3):
  G1: GEODE.md  — Agent identity (Core Principles + CANNOT + Defaults, ~20 lines)
  G2: .geode/MEMORY.md — Project meta-index (architecture, pipelines, key files)
  G3: .geode/LEARNING.md — Agent learning (patterns, corrections, domain knowledge)
  G4: .geode/memory/PROJECT.md — Runtime insights + rules (existing _build_memory_context)

Extracted from ``nl_router.py`` so that the AgenticLoop can use the system
prompt without depending on the NL Router module.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from core.cli.ip_names import get_ip_name_map
from core.llm.prompts import ROUTER_SYSTEM

log = logging.getLogger(__name__)

# Project root resolved from __file__ (CWD-independent)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Max lines per memory hierarchy section to control context budget
_MAX_SECTION_LINES = 20

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
    from core.domains.game_ip.fixtures import FIXTURE_MAP, load_fixture

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

    # User context: profile + career identity
    user_ctx = _build_user_context()
    if user_ctx:
        base += "\n\n" + user_ctx

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


def _build_user_context() -> str:
    """Build user context from profile + career identity.

    Sources:
      ~/.geode/user_profile/profile.md   — role, expertise, bio
      ~/.geode/user_profile/preferences.json — language, output format
      ~/.geode/user_profile/learned.md   — learned patterns
      ~/.geode/identity/career.toml      — career summary
    """
    try:
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        parts: list[str] = []

        # Profile summary (role, expertise, lang, skills)
        context_summary = profile.get_context_summary()
        if context_summary:
            parts.append(context_summary)

        # Career summary (title, experience, seeking)
        career_summary = profile.get_career_summary()
        if career_summary:
            parts.append(f"Career: {career_summary}")

        # Learned patterns (last 5)
        learned = profile.get_learned_patterns()
        if learned:
            recent = learned[:5]
            parts.append("Learned: " + " | ".join(recent))

        if not parts:
            return ""

        return "## User Context\n" + "\n".join(parts)
    except Exception:
        log.debug("Failed to build user context", exc_info=True)
        return ""


def _build_memory_context() -> str:
    """Build memory context string from the 4-tier memory hierarchy.

    Injects G1-G4 into the system prompt:
      G1: GEODE.md identity (Core Principles + CANNOT + Defaults)
      G2: .geode/MEMORY.md project meta-index
      G3: .geode/LEARNING.md agent learning records
      G4: .geode/memory/PROJECT.md runtime insights + rules (existing)

    Each section is capped at ``_MAX_SECTION_LINES`` lines.
    Missing files are silently skipped (graceful degradation).
    """
    parts: list[str] = []

    # --- G1: Agent Identity (GEODE.md) ---
    identity_ctx = _build_identity_context()
    if identity_ctx:
        parts.append(identity_ctx)

    # --- G2: Project Memory Index (.geode/MEMORY.md) ---
    geode_memory_ctx = _build_geode_memory_context()
    if geode_memory_ctx:
        parts.append(geode_memory_ctx)

    # --- G3: Agent Learning (.geode/LEARNING.md) ---
    learning_ctx = _build_learning_context()
    if learning_ctx:
        parts.append(learning_ctx)

    # --- G4: Runtime Project Memory (.geode/memory/PROJECT.md) ---
    project_ctx = _build_project_memory_context()
    if project_ctx:
        parts.append(project_ctx)

    return "\n\n".join(parts)


def _build_identity_context() -> str:
    """G1: Extract core identity from GEODE.md (Core Principles + CANNOT + Defaults).

    Reads GEODE.md via OrganizationMemory.get_soul() and extracts only the
    essential sections to stay within context budget (~20 lines).
    """
    try:
        from core.memory.organization import MonoLakeOrganizationMemory

        org = MonoLakeOrganizationMemory()
        soul = org.get_soul()
        if not soul:
            return ""

        # Extract targeted sections: Core Principles, CANNOT, Defaults
        target_sections = {"## Core Principles", "## CANNOT", "## Defaults"}
        extracted_lines: list[str] = []

        current_in_target = False
        for line in soul.split("\n"):
            stripped = line.strip()
            # Detect section headers
            if stripped.startswith("## "):
                current_in_target = stripped in target_sections
                if current_in_target:
                    extracted_lines.append(stripped)
                continue
            if current_in_target and stripped:
                extracted_lines.append(stripped)

        if not extracted_lines:
            return ""

        # Cap at budget
        capped = extracted_lines[:_MAX_SECTION_LINES]
        return "## Agent Identity\n" + "\n".join(capped)
    except Exception:
        log.debug("Failed to build identity context (G1)", exc_info=True)
        return ""


def _build_geode_memory_context() -> str:
    """G2: Load .geode/MEMORY.md project meta-index.

    Reads the file and extracts non-empty content lines (skipping blank
    placeholder sections). Capped at ``_MAX_SECTION_LINES`` lines.
    """
    try:
        memory_path = _PROJECT_ROOT / ".geode" / "MEMORY.md"
        if not memory_path.exists():
            return ""

        content = memory_path.read_text(encoding="utf-8")
        # Extract meaningful lines (headers + content, skip empty placeholders)
        meaningful: list[str] = []
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            # Skip placeholder lines like "(실행 결과가 여기에 기록됩니다)"
            if stripped.startswith("(") and stripped.endswith(")"):
                continue
            meaningful.append(stripped)

        if len(meaningful) <= 1:
            # Only title, no real content
            return ""

        capped = meaningful[:_MAX_SECTION_LINES]
        return "## Project Memory\n" + "\n".join(capped)
    except Exception:
        log.debug("Failed to build geode memory context (G2)", exc_info=True)
        return ""


def _build_learning_context() -> str:
    """G3: Load .geode/LEARNING.md agent learning records.

    Extracts only Patterns, Corrections, and Domain Knowledge sections
    that have actual content (not just placeholder text).
    Capped at ``_MAX_SECTION_LINES`` lines.
    """
    try:
        learning_path = _PROJECT_ROOT / ".geode" / "LEARNING.md"
        if not learning_path.exists():
            return ""

        content = learning_path.read_text(encoding="utf-8")

        # Extract sections with real content (not placeholders)
        target_sections = {"## Patterns", "## Corrections", "## Domain Knowledge"}
        extracted_lines: list[str] = []
        current_in_target = False

        for line in content.split("\n"):
            stripped = line.strip()

            if stripped.startswith("## "):
                current_in_target = stripped in target_sections
                if current_in_target:
                    extracted_lines.append(stripped)
                continue

            if current_in_target and stripped:
                # Skip placeholder lines
                if stripped.startswith("(") and stripped.endswith(")"):
                    continue
                extracted_lines.append(stripped)

        # Remove section headers that ended up with no content
        cleaned: list[str] = []
        i = 0
        while i < len(extracted_lines):
            line = extracted_lines[i]
            if line.startswith("## "):
                # Check if next non-header line exists
                has_body = False
                for j in range(i + 1, len(extracted_lines)):
                    if extracted_lines[j].startswith("## "):
                        break
                    has_body = True
                    break
                if has_body:
                    cleaned.append(line)
            else:
                cleaned.append(line)
            i += 1

        if not cleaned:
            return ""

        capped = cleaned[:_MAX_SECTION_LINES]
        return "## Agent Learning\n" + "\n".join(capped)
    except Exception:
        log.debug("Failed to build learning context (G3)", exc_info=True)
        return ""


def _build_project_memory_context() -> str:
    """G4: Build runtime project memory (insights + rules) from ProjectMemory.

    This is the original _build_memory_context logic, now isolated as G4.
    """
    try:
        from core.memory.project import ProjectMemory

        mem = ProjectMemory()
        if not mem.exists():
            return ""

        parts: list[str] = []

        # Recent insights (last 5 lines from PROJECT.md's recent insights section)
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
        log.debug("Failed to build project memory context (G4)", exc_info=True)
        return ""
