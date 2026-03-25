"""Memory Interaction Tools — LLM-callable tools for 3-tier memory.

Layer 5 tools for memory access:
- MemorySearchTool: Search across memory tiers (session, project, organization)
- MemoryGetTool: Get specific memory entry by session ID
- MemorySaveTool: Save data to session memory (with optional persistent write)
- RuleCreateTool: Create analysis rules from learned patterns
- RuleUpdateTool: Update existing analysis rules
- RuleDeleteTool: Delete analysis rules
- RuleListTool: List active analysis rules
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from core.infrastructure.ports.memory_port import (
    OrganizationMemoryPort,
    ProjectMemoryPort,
    SessionStorePort,
)
from core.memory.session import InMemorySessionStore

log = logging.getLogger(__name__)

# Thread-safe default stores via contextvars
_default_session_store_ctx: ContextVar[SessionStorePort | None] = ContextVar(
    "default_session_store", default=None
)
_project_memory_ctx: ContextVar[ProjectMemoryPort | None] = ContextVar(
    "project_memory_tools", default=None
)
_org_memory_ctx: ContextVar[OrganizationMemoryPort | None] = ContextVar(
    "org_memory_tools", default=None
)


def set_default_session_store(store: SessionStorePort) -> None:
    """Set the context-local default session store for memory tools."""
    _default_session_store_ctx.set(store)


def set_project_memory(mem: ProjectMemoryPort | None) -> None:
    """Set the context-local project memory for memory tools."""
    _project_memory_ctx.set(mem)


def set_org_memory(mem: OrganizationMemoryPort | None) -> None:
    """Set the context-local organization memory for memory tools."""
    _org_memory_ctx.set(mem)


def _get_session_store(store: SessionStorePort | None = None) -> SessionStorePort:
    """Get the session store to use, falling back to default."""
    if store is not None:
        return store
    default = _default_session_store_ctx.get()
    if default is not None:
        return default
    return InMemorySessionStore()


class MemorySearchTool:
    """Tool for searching across memory tiers.

    Searches session, project (MEMORY.md + rules), and organization tiers.
    """

    def __init__(self, session_store: SessionStorePort | None = None) -> None:
        self._store = session_store

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search across memory tiers (session, project, organization) "
            "for entries matching a query. Returns matching data from all tiers."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to match against memory entries.",
                },
                "tier": {
                    "type": "string",
                    "enum": ["session", "project", "organization", "all"],
                    "description": "Memory tier to search. Default: all.",
                    "default": "all",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results.",
                    "default": 10,
                },
            },
            "required": ["query"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs["query"]
        tier: str = kwargs.get("tier", "all")
        limit: int = kwargs.get("limit", 10)

        store = _get_session_store(self._store)
        matches: list[dict[str, Any]] = []
        query_lower = query.lower()

        # Session tier
        if tier in ("session", "all"):
            for session_id in store.list_sessions():
                data = store.get(session_id)
                if data is None:
                    continue
                data_str = str(data).lower()
                if query_lower in data_str:
                    matches.append(
                        {
                            "session_id": session_id,
                            "tier": "session",
                            "data": data,
                        }
                    )
                    if len(matches) >= limit:
                        break

        # Project tier (MEMORY.md + rules)
        if tier in ("project", "all") and len(matches) < limit:
            proj = _project_memory_ctx.get()
            if proj is not None:
                # Search MEMORY.md content
                memory_text = proj.load_memory()
                if query_lower in memory_text.lower():
                    # Extract matching lines
                    matching_lines = [
                        line.strip()
                        for line in memory_text.split("\n")
                        if query_lower in line.lower() and line.strip()
                    ]
                    if matching_lines:
                        matches.append(
                            {
                                "tier": "project",
                                "source": "MEMORY.md",
                                "matching_lines": matching_lines[:5],
                            }
                        )

                # Search rules
                rules = proj.load_rules(query)
                for rule in rules:
                    if len(matches) >= limit:
                        break
                    matches.append(
                        {
                            "tier": "project",
                            "source": f"rules/{rule['name']}.md",
                            "rule_name": rule["name"],
                            "paths": rule.get("paths", []),
                            "preview": rule.get("content", "")[:200],
                        }
                    )

        # Organization tier (fixtures)
        if tier in ("organization", "all") and len(matches) < limit:
            org = _org_memory_ctx.get()
            if org is not None:
                ip_ctx = org.get_ip_context(query)
                if ip_ctx:
                    matches.append(
                        {
                            "tier": "organization",
                            "source": "fixtures",
                            "ip_name": query,
                            "data_keys": list(ip_ctx.keys()),
                        }
                    )

        return {
            "result": {
                "query": query,
                "tier_searched": tier,
                "matches": matches,
                "total_found": len(matches),
            }
        }


class MemoryGetTool:
    """Tool for retrieving a specific memory entry by session ID."""

    def __init__(self, session_store: SessionStorePort | None = None) -> None:
        self._store = session_store

    @property
    def name(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return "Get a specific memory entry by session ID. Returns the full session data if found."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID to retrieve.",
                },
            },
            "required": ["session_id"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        session_id: str = kwargs["session_id"]

        store = _get_session_store(self._store)
        data = store.get(session_id)

        if data is None:
            return {
                "result": {
                    "session_id": session_id,
                    "found": False,
                    "data": None,
                }
            }

        return {
            "result": {
                "session_id": session_id,
                "found": True,
                "data": data,
            }
        }


class MemorySaveTool:
    """Tool for saving data to session memory."""

    def __init__(self, session_store: SessionStorePort | None = None) -> None:
        self._store = session_store

    @property
    def name(self) -> str:
        return "memory_save"

    @property
    def description(self) -> str:
        return (
            "Save data to session memory. Creates or updates a session "
            "entry with the provided key-value data."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID to save data under.",
                },
                "data": {
                    "type": "object",
                    "description": "Key-value data to store in the session.",
                },
                "merge": {
                    "type": "boolean",
                    "description": "If true, merge with existing data. Otherwise replace.",
                    "default": True,
                },
                "persistent": {
                    "type": "boolean",
                    "description": (
                        "If true, also write to MEMORY.md via add_insight() "
                        "for cross-session persistence."
                    ),
                    "default": False,
                },
            },
            "required": ["session_id", "data"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        session_id: str = kwargs["session_id"]
        data: dict[str, Any] = kwargs["data"]
        merge: bool = kwargs.get("merge", True)
        persistent: bool = kwargs.get("persistent", False)

        store = _get_session_store(self._store)

        if merge:
            existing = store.get(session_id) or {}
            existing.update(data)
            store.set(session_id, existing)
        else:
            store.set(session_id, data)

        # Persistent write to MEMORY.md (P1.5)
        if persistent:
            proj = _project_memory_ctx.get()
            if proj is not None:
                from core.memory.project import ProjectMemory

                if isinstance(proj, ProjectMemory):
                    insight = str(data.get("content", data))
                    proj.add_insight(insight)

        return {
            "result": {
                "session_id": session_id,
                "saved": True,
                "merged": merge,
                "persistent": persistent,
                "keys_stored": list(data.keys()),
            }
        }


class RuleCreateTool:
    """Tool for creating analysis rules from learned patterns.

    Enables the agent to autonomously create .geode/rules/*.md files
    when it discovers recurring analysis patterns.
    """

    @property
    def name(self) -> str:
        return "rule_create"

    @property
    def description(self) -> str:
        return (
            "Create a new analysis rule in .geode/rules/. "
            "Use when you discover a recurring pattern that should be "
            "applied to future IP analyses matching the given paths."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Rule name (e.g. 'dark-fantasy-recovery')",
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Glob patterns for matching IPs (e.g. ['*berserk*', '*dark*'])",
                },
                "content": {
                    "type": "string",
                    "description": "Rule content in markdown format",
                },
            },
            "required": ["name", "paths", "content"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        rule_name: str = kwargs["name"]
        paths: list[str] = kwargs["paths"]
        content: str = kwargs["content"]

        proj = _project_memory_ctx.get()
        if proj is None:
            return {"result": {"created": False, "error": "Project memory not available"}}

        from core.memory.project import ProjectMemory

        if not isinstance(proj, ProjectMemory):
            return {"result": {"created": False, "error": "Project memory type mismatch"}}

        success = proj.create_rule(rule_name, paths, content)
        return {
            "result": {
                "created": success,
                "name": rule_name,
                "paths": paths,
            }
        }


class RuleUpdateTool:
    """Tool for updating existing analysis rules."""

    @property
    def name(self) -> str:
        return "rule_update"

    @property
    def description(self) -> str:
        return (
            "Update an existing analysis rule in .geode/rules/. "
            "Preserves frontmatter (paths) and replaces the rule body content."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Rule name to update (e.g. 'dark-fantasy-recovery')",
                },
                "content": {
                    "type": "string",
                    "description": "New rule content in markdown format",
                },
            },
            "required": ["name", "content"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        rule_name: str = kwargs["name"]
        content: str = kwargs["content"]

        proj = _project_memory_ctx.get()
        if proj is None:
            return {"result": {"updated": False, "error": "Project memory not available"}}

        from core.memory.project import ProjectMemory

        if not isinstance(proj, ProjectMemory):
            return {"result": {"updated": False, "error": "Project memory type mismatch"}}

        success = proj.update_rule(rule_name, content)
        return {
            "result": {
                "updated": success,
                "name": rule_name,
            }
        }


class RuleDeleteTool:
    """Tool for deleting analysis rules."""

    @property
    def name(self) -> str:
        return "rule_delete"

    @property
    def description(self) -> str:
        return "Delete an analysis rule from .geode/rules/ by name."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Rule name to delete (e.g. 'dark-fantasy-recovery')",
                },
            },
            "required": ["name"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        rule_name: str = kwargs["name"]

        proj = _project_memory_ctx.get()
        if proj is None:
            return {"result": {"deleted": False, "error": "Project memory not available"}}

        from core.memory.project import ProjectMemory

        if not isinstance(proj, ProjectMemory):
            return {"result": {"deleted": False, "error": "Project memory type mismatch"}}

        success = proj.delete_rule(rule_name)
        return {
            "result": {
                "deleted": success,
                "name": rule_name,
            }
        }


class RuleListTool:
    """Tool for listing active analysis rules."""

    @property
    def name(self) -> str:
        return "rule_list"

    @property
    def description(self) -> str:
        return (
            "List all active analysis rules in .geode/rules/ with their paths and content preview."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        proj = _project_memory_ctx.get()
        if proj is None:
            return {"result": {"rules": [], "error": "Project memory not available"}}

        from core.memory.project import ProjectMemory

        if not isinstance(proj, ProjectMemory):
            return {"result": {"rules": [], "error": "Project memory type mismatch"}}

        rules = proj.list_rules()
        return {
            "result": {
                "rules": rules,
                "total": len(rules),
            }
        }


class NoteSaveTool:
    """Save a user note to project memory (## User Notes section)."""

    @property
    def name(self) -> str:
        return "note_save"

    @property
    def description(self) -> str:
        return (
            "Save a user note or preference to persistent memory. "
            "Use when user says 'remember this', 'save this', '이거 기억해'."
        )

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        key: str = kwargs["key"]
        content: str = kwargs["content"]

        proj = _project_memory_ctx.get()
        if proj is None:
            return {"error": "Project memory not available"}

        from core.memory.project import ProjectMemory

        if not isinstance(proj, ProjectMemory):
            return {"error": "Project memory type mismatch"}

        note_text = f"**{key}**: {content}"
        proj.add_insight(note_text)
        return {
            "result": {
                "saved": True,
                "key": key,
            }
        }


class NoteReadTool:
    """Read user notes from project memory."""

    @property
    def name(self) -> str:
        return "note_read"

    @property
    def description(self) -> str:
        return (
            "Read previously saved user notes from persistent memory. "
            "Use when user asks about something they previously saved."
        )

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs.get("query", "")

        proj = _project_memory_ctx.get()
        if proj is None:
            return {"error": "Project memory not available"}

        memory_text = proj.load_memory()
        if not query:
            return {"result": {"notes": memory_text}}

        # Filter matching lines
        query_lower = query.lower()
        matching_lines = [
            line.strip()
            for line in memory_text.split("\n")
            if query_lower in line.lower() and line.strip()
        ]
        return {
            "result": {
                "query": query,
                "matching_lines": matching_lines[:20],
                "total_found": len(matching_lines),
            }
        }
