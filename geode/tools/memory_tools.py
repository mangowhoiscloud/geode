"""Memory Interaction Tools — LLM-callable tools for 3-tier memory.

Layer 5 tools for memory access:
- MemorySearchTool: Search across memory tiers
- MemoryGetTool: Get specific memory entry by session ID
- MemorySaveTool: Save data to session memory
"""

from __future__ import annotations

from typing import Any

from geode.memory.session import InMemorySessionStore


# Module-level default session store (can be overridden at runtime)
_default_session_store: InMemorySessionStore | None = None


def set_default_session_store(store: InMemorySessionStore) -> None:
    """Set the module-level default session store for memory tools."""
    global _default_session_store  # noqa: PLW0603
    _default_session_store = store


def _get_session_store(store: InMemorySessionStore | None = None) -> InMemorySessionStore:
    """Get the session store to use, falling back to default."""
    if store is not None:
        return store
    if _default_session_store is not None:
        return _default_session_store
    return InMemorySessionStore()


class MemorySearchTool:
    """Tool for searching across memory tiers.

    Searches session memory for entries matching a query string.
    In production, would also search Project and Organization tiers.
    """

    def __init__(self, session_store: InMemorySessionStore | None = None) -> None:
        self._store = session_store

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search across memory tiers (session, project, organization) "
            "for entries matching a query. Returns matching session data."
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

        if tier in ("session", "all"):
            query_lower = query.lower()
            for session_id in store.list_sessions():
                data = store.get(session_id)
                if data is None:
                    continue
                # Simple string matching against session data values
                data_str = str(data).lower()
                if query_lower in data_str:
                    matches.append({
                        "session_id": session_id,
                        "tier": "session",
                        "data": data,
                    })
                    if len(matches) >= limit:
                        break

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

    def __init__(self, session_store: InMemorySessionStore | None = None) -> None:
        self._store = session_store

    @property
    def name(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return (
            "Get a specific memory entry by session ID. "
            "Returns the full session data if found."
        )

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

    def __init__(self, session_store: InMemorySessionStore | None = None) -> None:
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
            },
            "required": ["session_id", "data"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        session_id: str = kwargs["session_id"]
        data: dict[str, Any] = kwargs["data"]
        merge: bool = kwargs.get("merge", True)

        store = _get_session_store(self._store)

        if merge:
            existing = store.get(session_id) or {}
            existing.update(data)
            store.set(session_id, existing)
        else:
            store.set(session_id, data)

        return {
            "result": {
                "session_id": session_id,
                "saved": True,
                "merged": merge,
                "keys_stored": list(data.keys()),
            }
        }
