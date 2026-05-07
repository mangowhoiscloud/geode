"""Tool offload handler — recall_tool_result for retrieving offloaded tool results."""

from __future__ import annotations

from typing import Any


def _build_offload_handlers() -> dict[str, Any]:
    """Build recall_tool_result handler for retrieving offloaded tool results."""

    def handle_recall_tool_result(**kwargs: Any) -> dict[str, Any]:
        from core.orchestration.tool_offload import get_offload_store

        ref_id = kwargs.get("ref_id", "")
        if not ref_id:
            return {"error": "ref_id is required"}
        store = get_offload_store()
        if store is None:
            return {"error": "Tool offloading is not enabled in this session"}
        result: dict[str, Any] = store.recall(ref_id)
        return result

    return {
        "recall_tool_result": handle_recall_tool_result,
    }
