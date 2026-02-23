"""Hierarchical Session Key — OpenClaw-inspired session key construction.

Session keys encode ip_name, phase, and optional sub-context into a
hierarchical string for checkpoint filtering and session isolation.

Format: ip:{name}:{phase}[:{sub_context}]

Examples:
    ip:berserk:cortex
    ip:cowboy_bebop:analysis
    ip:berserk:evaluation:quality_judge
    ip:ghost_in_the_shell:scoring
    ip:berserk:synthesis
"""

from __future__ import annotations

import re
from typing import Any

# Phase constants (pipeline stages)
CORTEX = "cortex"
SIGNALS = "signals"
ANALYSIS = "analysis"
EVALUATION = "evaluation"
SCORING = "scoring"
VERIFICATION = "verification"
SYNTHESIS = "synthesis"

ALL_PHASES = frozenset({CORTEX, SIGNALS, ANALYSIS, EVALUATION, SCORING, VERIFICATION, SYNTHESIS})

_SAFE_NAME_RE = re.compile(r"[^a-z0-9_]")


def _normalize_name(name: str) -> str:
    """Normalize IP name to lowercase with underscores."""
    return _SAFE_NAME_RE.sub("_", name.lower().strip())


def build_session_key(ip_name: str, phase: str, sub_context: str | None = None) -> str:
    """Build a hierarchical session key.

    Args:
        ip_name: IP name (e.g. "Berserk", "Cowboy Bebop").
        phase: Pipeline phase (use constants: CORTEX, ANALYSIS, etc.).
        sub_context: Optional sub-context (e.g. analyst type, evaluator type).

    Returns:
        Hierarchical key like "ip:berserk:analysis".
    """
    normalized = _normalize_name(ip_name)
    key = f"ip:{normalized}:{phase}"
    if sub_context:
        key += f":{_normalize_name(sub_context)}"
    return key


def parse_session_key(key: str) -> dict[str, str | None]:
    """Parse a session key back into components.

    Returns:
        Dict with keys: prefix, ip_name, phase, sub_context (may be None).

    Raises:
        ValueError: If key format is invalid.
    """
    parts = key.split(":")
    if len(parts) < 3 or parts[0] != "ip":
        raise ValueError(f"Invalid session key format: '{key}'. Expected 'ip:{{name}}:{{phase}}'")

    return {
        "prefix": parts[0],
        "ip_name": parts[1],
        "phase": parts[2],
        "sub_context": parts[3] if len(parts) > 3 else None,
    }


def build_thread_config(ip_name: str, phase: str, sub_context: str | None = None) -> dict[str, Any]:
    """Build a LangGraph thread config with hierarchical session key.

    Returns:
        Dict suitable for `graph.invoke(state, config=...)`.

    Example:
        config = build_thread_config("Berserk", ANALYSIS)
        result = compiled_graph.invoke(state, config=config)
    """
    thread_id = build_session_key(ip_name, phase, sub_context)
    return {"configurable": {"thread_id": thread_id}}
