"""Personal-data tool classification and persistence redaction.

Google Workspace content is available to the active model turn only after an
in-context approval.  It must not be copied into GEODE's durable tool logs or
session checkpoints.  This module is dependency-light so both the agent and
memory layers can share one classification and one redaction contract.
"""

from __future__ import annotations

import json
from typing import Any

GOOGLE_WORKSPACE_READ_TOOLS: frozenset[str] = frozenset(
    {
        "gmail_search",
        "google_drive_search",
        "google_docs_read",
        "google_sheets_read",
        "google_tasks_list",
        "google_contacts_list",
        "calendar_list_events",
    }
)

GOOGLE_WORKSPACE_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        "gmail_send",
        "google_drive_create",
        "google_docs_write",
        "google_sheets_write",
        "google_tasks_write",
        "calendar_create_event",
        "calendar_sync_scheduler",
    }
)

PERSONAL_DATA_TOOLS: frozenset[str] = GOOGLE_WORKSPACE_READ_TOOLS | GOOGLE_WORKSPACE_MUTATION_TOOLS
PERSONAL_DATA_ERROR_OMITTED = "personal account operation failed; details omitted"


def personal_data_omitted(tool_name: str) -> dict[str, Any]:
    """Return the stable marker used in logs and resumable checkpoints."""
    return {
        "_personal_data_omitted": True,
        "tool_name": tool_name,
        "reason": "Google Workspace data is not retained; invoke again with consent.",
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
        elif str(node.get("tool", "")) in PERSONAL_DATA_TOOLS:
            tool_name = str(node["tool"])
        if tool_name in PERSONAL_DATA_TOOLS:
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

        if logged_tool in PERSONAL_DATA_TOOLS:
            kept = {
                key: rewrite(item) for key, item in node.items() if key not in {"input", "result"}
            }
            kept["input"] = personal_data_omitted(logged_tool)
            kept["result"] = personal_data_omitted(logged_tool)
            return kept

        if node_type in {"tool_use", "function_call"} and named_tool in PERSONAL_DATA_TOOLS:
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
