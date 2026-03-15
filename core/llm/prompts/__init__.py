"""Prompt template management — .md templates + Python loader.

Prompts are stored as Markdown files with ``=== SYSTEM ===`` / ``=== USER ===``
section delimiters.  This module loads them at import time and re-exports the
same constant names that ``prompts.py`` used, so existing imports keep working.

Structured scoring data (axes, rubrics) lives in ``axes.py``.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from core.llm.prompts.axes import (
    ANALYST_SPECIFIC,
    AXES_VERSIONS,
    EVALUATOR_AXES,
    PROSPECT_EVALUATOR_AXES,
)

_log = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Template loader
# ---------------------------------------------------------------------------


def _load_template(name: str) -> dict[str, str]:
    """Load a ``.md`` template and split into named sections.

    Sections are delimited by lines matching ``=== NAME ===``.
    Returns a dict mapping lowercase section names to their content.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")

    sections: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("=== ") and stripped.endswith(" ==="):
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = stripped[4:-4].strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def load_prompt(name: str, section: str = "system") -> str:
    """Public API — load a prompt section by template name.

    >>> system = load_prompt("analyst", "system")
    >>> user = load_prompt("analyst", "user")
    """
    sections = _load_template(name)
    key = section.lower()
    if key not in sections:
        msg = f"Section '{section}' not found in {name}.md (available: {list(sections)})"
        raise KeyError(msg)
    return sections[key]


# ---------------------------------------------------------------------------
# Hashing utilities (for reproducibility auditing)
# ---------------------------------------------------------------------------


def _hash_prompt(text: str) -> str:
    """Return first 12 chars of SHA-256 hash for template versioning."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def hash_rendered_prompt(template: str, **kwargs: Any) -> str:
    """Hash a rendered prompt (not template) for reproducibility auditing."""
    rendered = template.format(**kwargs) if kwargs else template
    return hashlib.sha256(rendered.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Backward-compatible constants (loaded from .md templates)
# ---------------------------------------------------------------------------

_analyst = _load_template("analyst")
ANALYST_SYSTEM: str = _analyst["system"]
ANALYST_USER: str = _analyst["user"]

_evaluator = _load_template("evaluator")
EVALUATOR_SYSTEM: str = _evaluator["system"]
EVALUATOR_USER: str = _evaluator["user"]

_synthesizer = _load_template("synthesizer")
SYNTHESIZER_SYSTEM: str = _synthesizer["system"]
SYNTHESIZER_USER: str = _synthesizer["user"]

_biasbuster = _load_template("biasbuster")
BIASBUSTER_SYSTEM: str = _biasbuster["system"]
BIASBUSTER_USER: str = _biasbuster["user"]

_commentary = _load_template("commentary")
COMMENTARY_SYSTEM: str = _commentary["system"]
COMMENTARY_USER: str = _commentary["user"]

_router = _load_template("router")
ROUTER_SYSTEM: str = _router["system"]
AGENTIC_SUFFIX: str = _router["agentic_suffix"]

_cross_llm = _load_template("cross_llm")
CROSS_LLM_SYSTEM: str = _cross_llm["system"]
CROSS_LLM_RESCORE: str = _cross_llm["rescore"]
CROSS_LLM_DUAL_VERIFY: str = _cross_llm["dual_verify"]

_tool_augmented = _load_template("tool_augmented")
ANALYST_TOOLS_SUFFIX: str = _tool_augmented["analyst_tools"]
SYNTHESIZER_TOOLS_SUFFIX: str = _tool_augmented["synthesizer_tools"]

# ---------------------------------------------------------------------------
# Prompt version hashes
# ---------------------------------------------------------------------------

PROMPT_VERSIONS: dict[str, str] = {
    # Base templates (8)
    "ANALYST_SYSTEM": _hash_prompt(ANALYST_SYSTEM),
    "ANALYST_USER": _hash_prompt(ANALYST_USER),
    "EVALUATOR_SYSTEM": _hash_prompt(EVALUATOR_SYSTEM),
    "EVALUATOR_USER": _hash_prompt(EVALUATOR_USER),
    "SYNTHESIZER_SYSTEM": _hash_prompt(SYNTHESIZER_SYSTEM),
    "SYNTHESIZER_USER": _hash_prompt(SYNTHESIZER_USER),
    "BIASBUSTER_SYSTEM": _hash_prompt(BIASBUSTER_SYSTEM),
    "BIASBUSTER_USER": _hash_prompt(BIASBUSTER_USER),
    # Extended templates (9)
    "ROUTER_SYSTEM": _hash_prompt(ROUTER_SYSTEM),
    "AGENTIC_SUFFIX": _hash_prompt(AGENTIC_SUFFIX),
    "COMMENTARY_SYSTEM": _hash_prompt(COMMENTARY_SYSTEM),
    "COMMENTARY_USER": _hash_prompt(COMMENTARY_USER),
    "CROSS_LLM_SYSTEM": _hash_prompt(CROSS_LLM_SYSTEM),
    "CROSS_LLM_RESCORE": _hash_prompt(CROSS_LLM_RESCORE),
    "CROSS_LLM_DUAL_VERIFY": _hash_prompt(CROSS_LLM_DUAL_VERIFY),
    "ANALYST_TOOLS_SUFFIX": _hash_prompt(ANALYST_TOOLS_SUFFIX),
    "SYNTHESIZER_TOOLS_SUFFIX": _hash_prompt(SYNTHESIZER_TOOLS_SUFFIX),
}
# Merge axes version hashes (3)
PROMPT_VERSIONS.update(AXES_VERSIONS)

_log.debug("Prompt versions loaded (%d): %s", len(PROMPT_VERSIONS), PROMPT_VERSIONS)

# ---------------------------------------------------------------------------
# Prompt drift detection (Karpathy P4 ratchet + P6 context budget)
# ---------------------------------------------------------------------------

# Pinned hashes — HARDCODED. Update when prompt templates are *intentionally* changed.
# CI test verifies computed hashes match these pins; mismatch = unintended drift.
# To regenerate after intentional edits:
#   python -c "from core.llm.prompts import PROMPT_VERSIONS as V; \
#     print(dict(sorted(V.items())))"
_PINNED_HASHES: dict[str, str] = {
    "AGENTIC_SUFFIX": "de69b49ab33a",
    "ANALYST_SPECIFIC": "5a696a2d5ebb",
    "ANALYST_SYSTEM": "924433f5bf11",
    "ANALYST_TOOLS_SUFFIX": "2961fb31d96f",
    "ANALYST_USER": "e59d00faadd5",
    "BIASBUSTER_SYSTEM": "07987c709fd9",
    "BIASBUSTER_USER": "378be01a6310",
    "COMMENTARY_SYSTEM": "b7d886e0905a",
    "COMMENTARY_USER": "2024ac4eba69",
    "CROSS_LLM_DUAL_VERIFY": "602669128ae2",
    "CROSS_LLM_RESCORE": "163b08e97d66",
    "CROSS_LLM_SYSTEM": "bf303f600fce",
    "EVALUATOR_AXES": "0d82eb1aa5b4",
    "EVALUATOR_SYSTEM": "e891c0ce27d4",
    "EVALUATOR_USER": "f6d7f955338d",
    "PROSPECT_EVALUATOR_AXES": "a9954477497b",
    "ROUTER_SYSTEM": "67d070bce2fc",
    "SYNTHESIZER_SYSTEM": "666d8e1fe137",
    "SYNTHESIZER_TOOLS_SUFFIX": "c6c65e47e191",
    "SYNTHESIZER_USER": "30d99edc79a5",
}


def verify_prompt_integrity(*, raise_on_drift: bool = False) -> list[str]:
    """Re-compute prompt hashes and compare against pinned versions.

    Returns list of drift descriptions (empty = all OK).
    If ``raise_on_drift=True``, raises ``RuntimeError`` on first mismatch.
    """
    from core.llm.prompts.axes import AXES_VERSIONS as LIVE_AXES

    drifted: list[str] = []
    current: dict[str, str] = {
        # Base templates (8)
        "ANALYST_SYSTEM": _hash_prompt(ANALYST_SYSTEM),
        "ANALYST_USER": _hash_prompt(ANALYST_USER),
        "EVALUATOR_SYSTEM": _hash_prompt(EVALUATOR_SYSTEM),
        "EVALUATOR_USER": _hash_prompt(EVALUATOR_USER),
        "SYNTHESIZER_SYSTEM": _hash_prompt(SYNTHESIZER_SYSTEM),
        "SYNTHESIZER_USER": _hash_prompt(SYNTHESIZER_USER),
        "BIASBUSTER_SYSTEM": _hash_prompt(BIASBUSTER_SYSTEM),
        "BIASBUSTER_USER": _hash_prompt(BIASBUSTER_USER),
        # Extended templates (9)
        "ROUTER_SYSTEM": _hash_prompt(ROUTER_SYSTEM),
        "AGENTIC_SUFFIX": _hash_prompt(AGENTIC_SUFFIX),
        "COMMENTARY_SYSTEM": _hash_prompt(COMMENTARY_SYSTEM),
        "COMMENTARY_USER": _hash_prompt(COMMENTARY_USER),
        "CROSS_LLM_SYSTEM": _hash_prompt(CROSS_LLM_SYSTEM),
        "CROSS_LLM_RESCORE": _hash_prompt(CROSS_LLM_RESCORE),
        "CROSS_LLM_DUAL_VERIFY": _hash_prompt(CROSS_LLM_DUAL_VERIFY),
        "ANALYST_TOOLS_SUFFIX": _hash_prompt(ANALYST_TOOLS_SUFFIX),
        "SYNTHESIZER_TOOLS_SUFFIX": _hash_prompt(SYNTHESIZER_TOOLS_SUFFIX),
        # Axes hashes (3)
        **LIVE_AXES,
    }
    for name, pinned_hash in _PINNED_HASHES.items():
        computed = current.get(name)
        if computed != pinned_hash:
            msg = f"Prompt drift: {name} pin={pinned_hash} now={computed}"
            drifted.append(msg)
            _log.warning(msg)
    if drifted and raise_on_drift:
        raise RuntimeError(f"Prompt drift detected: {', '.join(drifted)}")
    return drifted


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "AGENTIC_SUFFIX",
    "ANALYST_SPECIFIC",
    "ANALYST_SYSTEM",
    "ANALYST_TOOLS_SUFFIX",
    "ANALYST_USER",
    "AXES_VERSIONS",
    "BIASBUSTER_SYSTEM",
    "BIASBUSTER_USER",
    "COMMENTARY_SYSTEM",
    "COMMENTARY_USER",
    "CROSS_LLM_DUAL_VERIFY",
    "CROSS_LLM_RESCORE",
    "CROSS_LLM_SYSTEM",
    "EVALUATOR_AXES",
    "EVALUATOR_SYSTEM",
    "EVALUATOR_USER",
    "PROMPT_VERSIONS",
    "PROSPECT_EVALUATOR_AXES",
    "ROUTER_SYSTEM",
    "SYNTHESIZER_SYSTEM",
    "SYNTHESIZER_TOOLS_SUFFIX",
    "SYNTHESIZER_USER",
    "_hash_prompt",
    "hash_rendered_prompt",
    "load_prompt",
    "verify_prompt_integrity",
]
