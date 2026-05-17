"""Hierarchical session key construction.

Session keys encode subject, phase, and optional sub-context into a
hierarchical string for checkpoint filtering and session isolation.
"""

from __future__ import annotations

import re
from typing import Any

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
    """Normalize a key segment to lowercase with underscores."""
    return _SAFE_NAME_RE.sub("_", name.lower().strip())


def build_session_key(subject_id: str, phase: str, sub_context: str | None = None) -> str:
    """Build a hierarchical session key."""
    normalized = _normalize_name(subject_id)
    key = f"subject:{normalized}:{phase}"
    if sub_context:
        key += f":{_normalize_name(sub_context)}"
    return key


def build_subagent_session_key(subject_id: str, task_id: str, phase: str = "pipeline") -> str:
    """Build a session key for a sub-agent execution."""
    normalized_subject = _normalize_name(subject_id)
    normalized_task_id = _normalize_name(task_id)
    return f"subject:{normalized_subject}:{phase}:subagent:{normalized_task_id}"


def build_subagent_thread_config(
    subject_id: str, task_id: str, phase: str = "pipeline"
) -> dict[str, Any]:
    """Build a LangGraph thread config for a sub-agent execution."""
    thread_id = build_subagent_session_key(subject_id, task_id, phase)
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": f"geode:subagent:{subject_id}:{task_id}",
        "tags": [f"subject:{subject_id}", f"phase:{phase}", "subagent"],
        "metadata": {
            "subject_id": subject_id,
            "phase": phase,
            "task_id": task_id,
            "is_subagent": True,
        },
    }


def parse_session_key(key: str) -> dict[str, str | None | bool]:
    """Parse a session key back into components."""
    parts = key.split(":")
    if len(parts) < 3 or parts[0] != "subject":
        raise ValueError(
            f"Invalid session key format: '{key}'. Expected 'subject:{{id}}:{{phase}}'"
        )

    if len(parts) == 5 and parts[3] == "subagent":
        return {
            "prefix": parts[0],
            "subject_id": parts[1],
            "phase": parts[2],
            "sub_context": parts[3],
            "task_id": parts[4],
            "is_subagent": True,
        }

    return {
        "prefix": parts[0],
        "subject_id": parts[1],
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
    """Build a session key for a gateway inbound message."""
    key = f"gateway:{channel}:{_normalize_name(channel_id)}"
    if sender_id:
        key += f":{_normalize_name(sender_id)}"
    if thread_id:
        key += f":{_normalize_name(thread_id)}"
    return key


def build_thread_config(
    subject_id: str, phase: str, sub_context: str | None = None
) -> dict[str, Any]:
    """Build a LangGraph thread config with hierarchical session key."""
    thread_id = build_session_key(subject_id, phase, sub_context)
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": f"geode:{subject_id}:{phase}",
        "tags": [f"subject:{subject_id}", f"phase:{phase}"],
        "metadata": {"subject_id": subject_id, "phase": phase},
    }
