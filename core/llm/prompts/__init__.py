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
    "ANALYST_SYSTEM": _hash_prompt(ANALYST_SYSTEM),
    "ANALYST_USER": _hash_prompt(ANALYST_USER),
    "EVALUATOR_SYSTEM": _hash_prompt(EVALUATOR_SYSTEM),
    "EVALUATOR_USER": _hash_prompt(EVALUATOR_USER),
    "SYNTHESIZER_SYSTEM": _hash_prompt(SYNTHESIZER_SYSTEM),
    "SYNTHESIZER_USER": _hash_prompt(SYNTHESIZER_USER),
    "BIASBUSTER_SYSTEM": _hash_prompt(BIASBUSTER_SYSTEM),
    "BIASBUSTER_USER": _hash_prompt(BIASBUSTER_USER),
}

_log.debug("Prompt versions loaded: %s", PROMPT_VERSIONS)

# ---------------------------------------------------------------------------
# Prompt drift detection (Karpathy P4 ratchet + P6 context budget)
# ---------------------------------------------------------------------------

# Pinned hashes — update these when prompt templates are intentionally changed.
# CI test verifies computed hashes match these pins; mismatch = unintended drift.
_PINNED_HASHES: dict[str, str] = dict(PROMPT_VERSIONS)


def verify_prompt_integrity(*, raise_on_drift: bool = False) -> list[str]:
    """Re-compute prompt hashes and compare against pinned versions.

    Returns list of drift descriptions (empty = all OK).
    If ``raise_on_drift=True``, raises ``RuntimeError`` on first mismatch.
    """
    drifted: list[str] = []
    current = {
        "ANALYST_SYSTEM": _hash_prompt(ANALYST_SYSTEM),
        "ANALYST_USER": _hash_prompt(ANALYST_USER),
        "EVALUATOR_SYSTEM": _hash_prompt(EVALUATOR_SYSTEM),
        "EVALUATOR_USER": _hash_prompt(EVALUATOR_USER),
        "SYNTHESIZER_SYSTEM": _hash_prompt(SYNTHESIZER_SYSTEM),
        "SYNTHESIZER_USER": _hash_prompt(SYNTHESIZER_USER),
        "BIASBUSTER_SYSTEM": _hash_prompt(BIASBUSTER_SYSTEM),
        "BIASBUSTER_USER": _hash_prompt(BIASBUSTER_USER),
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
