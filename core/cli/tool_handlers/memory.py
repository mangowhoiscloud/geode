"""Memory tool handlers: memory_search, memory_save, manage_rule."""

from __future__ import annotations

import logging
from typing import Any

from core.cli.tool_handlers.clarification import _clarify
from core.cli.tool_handlers.registration import UniqueEntries
from core.ui.console import console

log = logging.getLogger(__name__)


def _build_memory_handlers() -> UniqueEntries[str, Any]:
    """Build memory-related tool handlers."""
    from core.cli import _handle_memory_action
    from core.memory.project import ProjectMemory

    def handle_memory_search(**kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "")
        if not query:
            return _clarify("memory_search", ["query"], "무엇을 검색할까요?")
        try:
            mem = ProjectMemory()
            content = mem.search(query) if hasattr(mem, "search") else mem.load_memory()
            return {"status": "ok", "action": "memory_search", "content": content[:2000]}
        except Exception as exc:
            return {"error": str(exc)}

    def handle_memory_save(**kwargs: Any) -> dict[str, Any]:
        key = kwargs.get("key", "")
        content = kwargs.get("content", "")
        if not key or not content:
            missing = [k for k, v in {"key": key, "content": content}.items() if not v]
            return _clarify("memory_save", missing, "저장할 키와 내용을 알려주세요.")
        try:
            mem = ProjectMemory()
            mem.add_insight(f"{key}: {content}")
            console.print(f"  [success]Saved to memory: {key}[/success]")
            return {"status": "ok", "action": "memory_save", "key": key}
        except Exception as exc:
            return {"error": str(exc)}

    def handle_manage_rule(**kwargs: Any) -> dict[str, Any]:
        rule_action = kwargs.get("action", "list")
        name = kwargs.get("name", "")
        if rule_action in ("add", "delete") and not name:
            return _clarify("manage_rule", ["name"], "규칙 이름을 알려주세요.")
        memory_args = {
            "rule_action": rule_action,
            "name": name,
            "paths": kwargs.get("paths", []),
            "content": kwargs.get("content", ""),
        }
        _handle_memory_action(memory_args, "", False)
        # Return rule list for LLM context
        try:
            mem = ProjectMemory()
            rules = mem.list_rules() if hasattr(mem, "list_rules") else []
            return {
                "status": "ok",
                "action": "manage_rule",
                "sub_action": rule_action,
                "name": name,
                "rules": [str(r) for r in rules][:20],
            }
        except Exception:
            return {"status": "ok", "action": "manage_rule", "sub_action": rule_action}

    def handle_session_search(**kwargs: Any) -> dict[str, Any]:
        """PR-Hermes-1d — delegate to ``SessionSearchTool`` (FTS5 message recall)."""
        from core.tools.session_search import SessionSearchTool

        return SessionSearchTool()._execute_sync(**kwargs)

    return UniqueEntries[str, Any](
        (
            ("memory_search", handle_memory_search),
            ("memory_save", handle_memory_save),
            ("manage_rule", handle_manage_rule),
            ("session_search", handle_session_search),
        )
    )
