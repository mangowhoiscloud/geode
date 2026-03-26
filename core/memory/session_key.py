"""Hierarchical Session Key — OpenClaw-inspired session key construction.

Session keys encode ip_name, phase, and optional sub-context into a
hierarchical string for checkpoint filtering and session isolation.

Format: ip:{name}:{phase}[:{sub_context}]

Examples:
    ip:berserk:router
    ip:cowboy_bebop:analysis
    ip:berserk:evaluation:quality_judge
    ip:ghost_in_the_shell:scoring
    ip:berserk:synthesis
"""

from __future__ import annotations

import re
from typing import Any

# Phase constants (pipeline stages)
ROUTER = "router"
SIGNALS = "signals"
ANALYSIS = "analysis"
EVALUATION = "evaluation"
SCORING = "scoring"
VERIFICATION = "verification"
SYNTHESIS = "synthesis"

ALL_PHASES = frozenset({ROUTER, SIGNALS, ANALYSIS, EVALUATION, SCORING, VERIFICATION, SYNTHESIS})

_SAFE_NAME_RE = re.compile(r"[^a-z0-9_]")


def _normalize_name(name: str) -> str:
    """Normalize IP name to lowercase with underscores."""
    return _SAFE_NAME_RE.sub("_", name.lower().strip())


def build_session_key(ip_name: str, phase: str, sub_context: str | None = None) -> str:
    """Build a hierarchical session key.

    Args:
        ip_name: IP name (e.g. "Berserk", "Cowboy Bebop").
        phase: Pipeline phase (use constants: ROUTER, ANALYSIS, etc.).
        sub_context: Optional sub-context (e.g. analyst type, evaluator type).

    Returns:
        Hierarchical key like "ip:berserk:analysis".
    """
    normalized = _normalize_name(ip_name)
    key = f"ip:{normalized}:{phase}"
    if sub_context:
        key += f":{_normalize_name(sub_context)}"
    return key


def build_subagent_session_key(ip_name: str, task_id: str, phase: str = "pipeline") -> str:
    """Build a session key for a sub-agent execution.

    Returns a key with format: ip:{normalized_name}:{phase}:subagent:{normalized_task_id}

    Args:
        ip_name: IP name (e.g. "Berserk").
        task_id: Unique task identifier for the sub-agent.
        phase: Pipeline phase (default "pipeline").
    """
    normalized_name = _normalize_name(ip_name)
    normalized_task_id = _normalize_name(task_id)
    return f"ip:{normalized_name}:{phase}:subagent:{normalized_task_id}"


def build_subagent_thread_config(
    ip_name: str, task_id: str, phase: str = "pipeline"
) -> dict[str, Any]:
    """Build a LangGraph thread config for a sub-agent execution.

    Includes LangSmith trace enrichment with subagent-specific metadata.

    Returns:
        Dict suitable for ``graph.invoke(state, config=...)``.
    """
    thread_id = build_subagent_session_key(ip_name, task_id, phase)
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": f"geode:subagent:{ip_name}:{task_id}",
        "tags": [f"ip:{ip_name}", f"phase:{phase}", "subagent"],
        "metadata": {
            "ip_name": ip_name,
            "phase": phase,
            "task_id": task_id,
            "is_subagent": True,
        },
    }


def parse_session_key(key: str) -> dict[str, str | None | bool]:
    """Parse a session key back into components.

    Returns:
        Dict with keys: prefix, ip_name, phase, sub_context (may be None),
        task_id (None for non-subagent keys), is_subagent (bool).

    Raises:
        ValueError: If key format is invalid.
    """
    parts = key.split(":")
    if len(parts) < 3 or parts[0] != "ip":
        raise ValueError(f"Invalid session key format: '{key}'. Expected 'ip:{{name}}:{{phase}}'")

    # 5-part subagent key: ip:X:Y:subagent:Z
    if len(parts) == 5 and parts[3] == "subagent":
        return {
            "prefix": parts[0],
            "ip_name": parts[1],
            "phase": parts[2],
            "sub_context": parts[3],
            "task_id": parts[4],
            "is_subagent": True,
        }

    return {
        "prefix": parts[0],
        "ip_name": parts[1],
        "phase": parts[2],
        "sub_context": parts[3] if len(parts) > 3 else None,
        "task_id": None,
        "is_subagent": False,
    }


def build_gateway_session_key(
    channel: str,
    channel_id: str,
    sender_id: str = "",
    thread_id: str = "",
) -> str:
    """Build a session key for a gateway inbound message.

    Format: gateway:{channel}:{channel_id}[:{sender_id}][:{thread_id}]

    When ``thread_id`` is provided the key scopes to a specific
    conversation thread, enabling multi-turn context within that thread.

    Examples:
        gateway:slack:C12345
        gateway:slack:C12345:U789:1234567890.123456
        gateway:telegram:987654321:U123
        gateway:discord:456789
    """
    key = f"gateway:{channel}:{_normalize_name(channel_id)}"
    if sender_id:
        key += f":{_normalize_name(sender_id)}"
    if thread_id:
        key += f":{_normalize_name(thread_id)}"
    return key


def build_thread_config(ip_name: str, phase: str, sub_context: str | None = None) -> dict[str, Any]:
    """Build a LangGraph thread config with hierarchical session key.

    Includes LangSmith trace enrichment: run_name, tags, metadata.

    Returns:
        Dict suitable for `graph.invoke(state, config=...)`.

    Example:
        config = build_thread_config("Berserk", ANALYSIS)
        result = compiled_graph.invoke(state, config=config)
    """
    thread_id = build_session_key(ip_name, phase, sub_context)
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": f"geode:{ip_name}:{phase}",
        "tags": [f"ip:{ip_name}", f"phase:{phase}"],
        "metadata": {"ip_name": ip_name, "phase": phase},
    }
