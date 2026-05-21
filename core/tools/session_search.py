"""``session_search`` tool — LLM-exposed FTS5 search over message history.

PR-Hermes-1d (2026-05-22) builds on Phase 1c (#1439) — the
``messages_fts`` / ``messages_fts_trigram`` indices over the per-project
``sessions.db``. This tool exposes that search surface to the LLM via
the standard registry, so the agent can recall prior conversation turns
without the operator running ``geode`` CLI commands.

**Why expose as a tool**: in-context wiring (M4.4 slot orchestrator)
auto-injects the 4 channels every turn, which is great for *passive*
context. ``session_search`` is the complementary *active* recall path —
when the agent wants to look up a specific past message it can run the
search itself.

**Scope** (1d-minimal):

* Current-project scope only — uses the active ``SessionManager``'s
  ``search_messages`` method introduced in 1c.
* Cross-project search (``scope="all"``) + the ``global.db`` index +
  ``geode reindex`` CLI are deferred to PR-Hermes-1d.2.

**Graceful**: missing SessionManager (no project context, or singleton
not initialised) → returns ``{"matched": False, "tools": [],
"reason": "session_manager_unavailable"}`` rather than raising.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.tools.base import tool_error

log = logging.getLogger(__name__)

__all__ = ["SessionSearchTool"]


class SessionSearchTool:
    """FTS5-backed search over the current project's session messages.

    Returns the most-relevant matching messages with snippets +
    bm25 scores. Scope is currently constrained to the current
    project's ``sessions.db``; cross-project (``global.db``) and async
    indexer land in PR-Hermes-1d.2.
    """

    @property
    def name(self) -> str:
        return "session_search"

    @property
    def description(self) -> str:
        return (
            "Search past conversation messages in the current project's session "
            "history via FTS5 full-text index. Returns matching messages with "
            "snippets and relevance scores. Use this to recall prior context "
            "the LLM cannot remember from earlier turns. Supports substring "
            "matching for partial Korean / identifier fragments via the "
            "trigram index when prefer_trigram=true."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search query. Hyphens / dots / special chars are "
                        "auto-sanitised; pass natural text or identifiers."
                    ),
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Optional — restrict search to a single session by id. "
                        "Omit to search across all sessions in the current project."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return. Default 20.",
                    "default": 20,
                },
                "prefer_trigram": {
                    "type": "boolean",
                    "description": (
                        "When true, query the trigram index (substring + CJK "
                        "partial-word recall). Falls back to the unicode61 "
                        "index when trigram is unavailable. Default false."
                    ),
                    "default": False,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            return tool_error("query is required and must be a non-empty string")
        session_id = kwargs.get("session_id")
        limit = kwargs.get("limit", 20)
        prefer_trigram = bool(kwargs.get("prefer_trigram", False))
        if not isinstance(limit, int) or limit <= 0:
            limit = 20
        try:
            limit = min(int(limit), 100)
        except (TypeError, ValueError):
            limit = 20

        try:
            from core.memory.session_manager import SessionManager
        except Exception as exc:  # pragma: no cover — defensive
            log.debug("session_search: SessionManager import failed: %s", exc)
            return tool_error(
                "session_manager_unavailable",
                error_type="dependency",
            )

        try:
            mgr = SessionManager()
        except Exception as exc:
            log.debug("session_search: SessionManager init failed: %s", exc)
            return tool_error(
                "session_manager_unavailable",
                error_type="dependency",
            )

        try:
            hits = mgr.search_messages(
                query,
                session_id=session_id if isinstance(session_id, str) else None,
                limit=limit,
                prefer_trigram=prefer_trigram,
            )
        finally:
            mgr.close()

        return {
            "matched": bool(hits),
            "count": len(hits),
            "hits": [
                {
                    "session_id": h["session_id"],
                    "message_id": h["message_id"],
                    "seq": h["seq"],
                    "role": h["role"],
                    "timestamp": h["timestamp"],
                    "snippet": h["snippet"],
                    "score": h["score"],
                }
                for h in hits
            ],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Run search off the event loop — SQLite calls are sync."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)
