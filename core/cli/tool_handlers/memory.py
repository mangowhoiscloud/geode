"""Memory tool handlers: memory_search, memory_save, manage_rule, session_search.

Every read and mutation uses one ProjectMemory owner (the injected one, or a
single fallback resolved at build time) and reports that owner's real outcome.
"""

from __future__ import annotations

import logging
from typing import Any

from core.hooks.dispatch import fire_hook
from core.hooks.system import HookEvent
from core.tools.handlers.clarification import _clarify
from core.tools.handlers.registration import UniqueEntries

log = logging.getLogger(__name__)

_RULE_ACTIONS = ("create", "update", "delete", "list")
_RULE_EVENT = {"create": "created", "update": "updated", "delete": "deleted"}


def _memory_error(action: str, outcome: Any, detail: str, **extra: Any) -> dict[str, Any]:
    from core.memory.project import MemoryWrite

    error_type = {
        MemoryWrite.NOT_FOUND: "not_found",
        MemoryWrite.CONFLICT: "conflict",
        MemoryWrite.INVALID: "validation",
    }.get(outcome, "internal")
    return {
        "status": "error",
        "action": action,
        "outcome": str(outcome),
        "error": detail,
        "error_type": error_type,
        **extra,
    }


def _build_memory_handlers(
    memory_services: Any = None,
    hooks: Any = None,
) -> UniqueEntries[str, Any]:
    """Build memory-related tool handlers."""
    from core.memory.project import MemoryWrite, ProjectMemory
    from core.tools.memory_tools import MemorySearchTool, MemoryToolServices

    services = memory_services or MemoryToolServices()
    memory = services.project_memory or ProjectMemory()
    if services.project_memory is None:
        services = MemoryToolServices(
            session_store=services.session_store,
            project_memory=memory,
            organization_memory=services.organization_memory,
            hooks=services.hooks,
        )
    events = hooks if hooks is not None else services.hooks

    def handle_memory_search(**kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "")
        if not query:
            return _clarify("memory_search", ["query"], "무엇을 검색할까요?")
        tier = kwargs.get("tier") or "all"
        result = MemorySearchTool(services=services)._execute_sync(query=query, tier=tier)
        return {"status": "ok", "action": "memory_search", **result["result"]}

    def handle_memory_save(**kwargs: Any) -> dict[str, Any]:
        key = str(kwargs.get("key") or "").strip()
        content = str(kwargs.get("content") or "").strip()
        if not key or not content:
            missing = [k for k, v in {"key": key, "content": content}.items() if not v]
            return _clarify("memory_save", missing, "저장할 키와 내용을 알려주세요.")
        outcome = memory.record_insight(f"{key}: {content}")
        if outcome is MemoryWrite.APPLIED:
            return {"status": "ok", "action": "memory_save", "key": key, "saved": True}
        if outcome is MemoryWrite.UNCHANGED:
            return {
                "status": "ok",
                "action": "memory_save",
                "key": key,
                "saved": False,
                "unchanged": True,
                "note": "This insight is already recorded.",
            }
        detail = {
            MemoryWrite.NOT_FOUND: (
                f"Project memory file is missing: {memory.memory_file}. "
                "Run `geode init` to create it."
            ),
            MemoryWrite.INVALID: (
                "Insight rejected: it must be one line of 10-500 characters, not a "
                "stub, and memory must resolve inside the project."
            ),
        }.get(outcome, "Project memory could not be read or written; it was left unchanged.")
        return _memory_error("memory_save", outcome, detail, key=key, saved=False)

    def handle_manage_rule(**kwargs: Any) -> dict[str, Any]:
        rule_action = str(kwargs.get("action") or "list")
        name = str(kwargs.get("name") or "").strip()
        content = str(kwargs.get("content") or "")
        paths = [str(p) for p in kwargs.get("paths") or []]
        if rule_action not in _RULE_ACTIONS:
            return _memory_error(
                "manage_rule",
                MemoryWrite.INVALID,
                f"Unknown action '{rule_action}'; expected one of {list(_RULE_ACTIONS)}",
            )
        if rule_action == "list":
            rules = memory.list_rules()
            return {
                "status": "ok",
                "action": "manage_rule",
                "sub_action": "list",
                "rules": rules[:20],
                "total": len(rules),
            }
        required = {"name": name} if rule_action == "delete" else {"name": name, "content": content}
        if missing := [k for k, v in required.items() if not v.strip()]:
            return _clarify("manage_rule", missing, "규칙 이름과 내용을 알려주세요.")
        outcome = memory.change_rule(rule_action, name, paths=paths, content=content)
        if outcome is not MemoryWrite.APPLIED:
            detail = {
                MemoryWrite.CONFLICT: f"Rule '{name}' already exists; use action=update.",
                MemoryWrite.NOT_FOUND: f"Rule '{name}' not found.",
                MemoryWrite.INVALID: (
                    f"Rule name '{name}' is not usable, or the rules directory "
                    "resolves outside the project."
                ),
            }.get(outcome, f"Rule '{name}' could not be read or written; it was left unchanged.")
            return _memory_error("manage_rule", outcome, detail, sub_action=rule_action, name=name)
        payload: dict[str, Any] = {"action": _RULE_EVENT[rule_action], "name": name}
        if rule_action == "create":
            payload["paths"] = paths
        fire_hook(events, HookEvent.RULE_CHANGED, payload)
        return {
            "status": "ok",
            "action": "manage_rule",
            "sub_action": rule_action,
            "name": name,
            "outcome": str(outcome),
        }

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
