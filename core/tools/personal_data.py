"""Plan-derived tool-data persistence redaction.

Data declared ``REDACT`` is available to the active model turn but must not be
copied into durable tool logs or checkpoints. Google Workspace names remain a
compatibility fallback for unbound/transient callers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any

from core.tools.google_capabilities import (
    GOOGLE_PERSONAL_DATA_TOOLS,
    GOOGLE_READ_TOOLS,
    GOOGLE_WRITE_TOOLS,
)
from core.tools.plan import (
    BoundToolPlan,
    DataClassification,
    PersistenceRule,
    SafetyPolicy,
)

GOOGLE_WORKSPACE_READ_TOOLS: frozenset[str] = GOOGLE_READ_TOOLS
GOOGLE_WORKSPACE_MUTATION_TOOLS: frozenset[str] = GOOGLE_WRITE_TOOLS
# Compatibility fallback for unbound/transient Workspace execution.
PERSONAL_DATA_TOOLS: frozenset[str] = GOOGLE_PERSONAL_DATA_TOOLS
PERSONAL_DATA_ERROR_OMITTED = "personal account operation failed; details omitted"

# Per-task native safety snapshot. ``None`` means an unbound/legacy caller and
# deliberately falls back to the Google compatibility set below.
_safety_policies: ContextVar[Mapping[str, SafetyPolicy] | None] = ContextVar(
    "geode_tool_data_policies",
    default=None,
)


def set_bound_tool_data_policies(bound: BoundToolPlan | None) -> None:
    """Bind one plan's native data policies for durable persistence writers."""
    if bound is None:
        _safety_policies.set(None)
        return
    base = bound.base
    _safety_policies.set(
        MappingProxyType(
            {
                name: registration.safety
                for name in base.tool_names
                if (registration := base.registration_for(name)) is not None
            }
        )
    )


def requires_durable_redaction(tool_name: str) -> bool:
    """Return the plan-declared rule, or the unbound compatibility fallback."""
    policies = _safety_policies.get()
    if policies is not None and tool_name in policies:
        safety = policies[tool_name]
        return bool(
            safety.data_class is DataClassification.PERSONAL
            or safety.persistence is PersistenceRule.REDACT
        )
    return tool_name in PERSONAL_DATA_TOOLS


def personal_data_omitted(tool_name: str) -> dict[str, Any]:
    """Return the stable marker used in logs and resumable checkpoints."""
    return {
        "_personal_data_omitted": True,
        "tool_name": tool_name,
        "reason": "Tool data is not retained by its declared safety policy.",
    }


def sanitize_personal_data_payload(value: Any) -> Any:
    """Return a copy with personal tool inputs and results replaced by markers.

    Handles GEODE tool-log rows, Anthropic ``tool_use`` / ``tool_result``
    blocks, and OpenAI ``function_call`` / ``function_call_output`` sidecars.
    Call IDs are collected before rewriting so results can be recognized even
    when their tool name is not repeated on the result block.
    """
    sensitive_ids: dict[str, str] = {}

    def collect(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                collect(item)
            return
        if not isinstance(node, dict):
            return
        node_type = str(node.get("type", ""))
        tool_name = ""
        if node_type in {"tool_use", "function_call"}:
            tool_name = str(node.get("name", ""))
        elif requires_durable_redaction(str(node.get("tool", ""))):
            tool_name = str(node["tool"])
        if requires_durable_redaction(tool_name):
            for key in ("id", "call_id", "tool_use_id"):
                identifier = node.get(key)
                if isinstance(identifier, str) and identifier:
                    sensitive_ids[identifier] = tool_name
        for item in node.values():
            collect(item)

    collect(value)

    def rewrite(node: Any) -> Any:
        if isinstance(node, list):
            return [rewrite(item) for item in node]
        if not isinstance(node, dict):
            return node

        node_type = str(node.get("type", ""))
        named_tool = str(node.get("name", ""))
        logged_tool = str(node.get("tool", ""))

        if requires_durable_redaction(logged_tool):
            kept = {
                key: rewrite(item) for key, item in node.items() if key not in {"input", "result"}
            }
            kept["input"] = personal_data_omitted(logged_tool)
            kept["result"] = personal_data_omitted(logged_tool)
            return kept

        if node_type in {"tool_use", "function_call"} and requires_durable_redaction(named_tool):
            kept = dict(node)
            if "input" in kept:
                kept["input"] = personal_data_omitted(named_tool)
            if "arguments" in kept:
                kept["arguments"] = json.dumps(personal_data_omitted(named_tool))
            return {key: rewrite(item) for key, item in kept.items()}

        identifier = next(
            (
                str(node[key])
                for key in ("tool_use_id", "call_id", "id")
                if isinstance(node.get(key), str) and node.get(key)
            ),
            "",
        )
        result_tool = sensitive_ids.get(identifier, "")
        if result_tool and node_type in {"tool_result", "function_call_output"}:
            kept = dict(node)
            marker = personal_data_omitted(result_tool)
            if "content" in kept:
                kept["content"] = json.dumps(marker)
            if "output" in kept:
                kept["output"] = json.dumps(marker)
            return {key: rewrite(item) for key, item in kept.items()}

        return {key: rewrite(item) for key, item in node.items()}

    return rewrite(value)
