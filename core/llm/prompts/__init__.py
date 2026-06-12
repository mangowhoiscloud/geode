"""Prompt template management — .md templates + Python loader.

Prompts are stored as Markdown files with XML-shaped section tags
(``<system>`` / ``<user>`` / ``<agentic_suffix>``). The 2026-05-12
prompt audit (G1+G4) converted the prior ``=== SYSTEM ===`` /
``=== USER ===`` delimiters to XML so every fragment Claude sees uses
the same tag-delimited shape — matching the Anthropic prompt-engineering
recommendation, Petri auditor's ``<thinking>``/``<seed_instructions>``,
and Claude Code's ``<system-reminder>``/``<workingDir>`` tags.

Slop-cleanup (2026-06-11): the analyst / evaluator / synthesizer /
tool_augmented templates and the empty-husk ``axes.py`` were deleted —
they served the Game-IP analysis pipeline removed in v0.99.149 and had
zero production callers since. Live templates: ``router`` (AgenticLoop
system + agentic suffix), ``commentary``, ``decomposer`` (loaded via
``load_prompt`` at call sites).
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent

# Top-level XML section tag: ``<key>...</key>``. ``re.DOTALL`` so the
# section body spans multiple lines; non-greedy so the matcher stops at
# the first closing tag. Keys are lowercase ASCII + underscore (matches
# the prior ``=== KEY ===`` convention rendered lowercase).
_SECTION_RE = re.compile(r"<([a-z][a-z0-9_]*)>(.*?)</\1>", re.DOTALL)

# ---------------------------------------------------------------------------
# Template loader
# ---------------------------------------------------------------------------


def _load_template(name: str) -> dict[str, str]:
    """Load a ``.md`` template and split into named XML sections.

    Each template is a sequence of ``<key>...</key>`` blocks at the top
    level. Returns a dict mapping the (lowercase) key to its trimmed body.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")

    sections: dict[str, str] = {m.group(1): m.group(2).strip() for m in _SECTION_RE.finditer(text)}
    if not sections:
        msg = f"No <key>...</key> sections found in {name}.md (G1 XML conversion)"
        raise ValueError(msg)
    return sections


def load_prompt(name: str, section: str = "system") -> str:
    """Public API — load a prompt section by template name.

    >>> system = load_prompt("decomposer", "system")
    >>> commentary = load_prompt("commentary", "user")
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
# Module-level constants (loaded from .md templates)
# ---------------------------------------------------------------------------

_commentary = _load_template("commentary")
COMMENTARY_SYSTEM: str = _commentary["system"]
COMMENTARY_USER: str = _commentary["user"]

_router = _load_template("router")
ROUTER_SYSTEM: str = _router["system"]
AGENTIC_SUFFIX: str = _router["agentic_suffix"]

# ---------------------------------------------------------------------------
# Prompt version hashes
# ---------------------------------------------------------------------------

PROMPT_VERSIONS: dict[str, str] = {
    "ROUTER_SYSTEM": _hash_prompt(ROUTER_SYSTEM),
    "AGENTIC_SUFFIX": _hash_prompt(AGENTIC_SUFFIX),
    "COMMENTARY_SYSTEM": _hash_prompt(COMMENTARY_SYSTEM),
    "COMMENTARY_USER": _hash_prompt(COMMENTARY_USER),
}

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
    "AGENTIC_SUFFIX": "0a32efea943d",
    "COMMENTARY_SYSTEM": "488d8916d958",
    "COMMENTARY_USER": "2024ac4eba69",
    "ROUTER_SYSTEM": "696cf5743225",
}


def verify_prompt_integrity(*, raise_on_drift: bool = False) -> list[str]:
    """Re-compute prompt hashes and compare against pinned versions.

    Returns list of drift descriptions (empty = all OK).
    If ``raise_on_drift=True``, raises ``RuntimeError`` on first mismatch.
    """
    drifted: list[str] = []
    for name, pinned_hash in _PINNED_HASHES.items():
        computed = PROMPT_VERSIONS.get(name)
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
    "COMMENTARY_SYSTEM",
    "COMMENTARY_USER",
    "PROMPT_VERSIONS",
    "ROUTER_SYSTEM",
    "_hash_prompt",
    "hash_rendered_prompt",
    "load_prompt",
    "verify_prompt_integrity",
]
