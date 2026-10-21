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

**Scope**:

* ``scope="project"`` (default) — current-project search via the
  active ``SessionManager``'s ``search_messages`` method (Phase 1c
  trigram-aware path).
* ``scope="all"`` (PR-Hermes-1d.2, 2026-05-26) — cross-project search
  via :class:`core.memory.search_index.SearchIndex` against
  ``~/.geode/search/global.db``. Result rows carry ``project_id`` +
  ``project_slug`` so the agent can tell where each hit came from.
  The index is rebuild-from-source — run ``geode reindex`` after a
  session-state change to refresh it.

**Visibility**: the gateway checkpoints every channel/sender/thread
conversation into the same ``sessions.db``. Both scopes return a gateway
thread's rows (and its workers') only to that thread or its workers, judged
from the executing loop's session ids (``caller_session_ids``), never from
``session_id`` or any other tool argument. Other rows are unaffected.

**Bounded**: ``limit`` is clamped to 100, and one snippet longer than
``SNIPPET_CHAR_CAP`` serialized characters becomes a marked prefix.

**Graceful**: project-scope with no active ``SessionManager`` →
returns a structured ``tool_error`` with ``error_type="dependency"``.
Cross-project scope with no ``global.db`` yet (operator never ran
``geode reindex``) → returns ``{"matched": False, "count": 0,
"hits": []}`` so the LLM can fall back to ``scope="project"``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Collection
from typing import Any

from core.tools.base import tool_error
from core.tools.memory_tools import caller_session_ids

log = logging.getLogger(__name__)

__all__ = ["SessionSearchTool"]


SCOPE_PROJECT = "project"
SCOPE_ALL = "all"
_VALID_SCOPES: frozenset[str] = frozenset({SCOPE_PROJECT, SCOPE_ALL})

# One snippet, in serialized characters as the tool processor measures them.
# FTS5 windows 16 tokens, but one unicode61 token (a base64 blob, a long
# identifier) has no length limit.
SNIPPET_CHAR_CAP = 1_000


def _json_len(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _bounded_snippet(snippet: Any) -> dict[str, Any]:
    """``{"snippet": ...}``, or its longest marked prefix within ``SNIPPET_CHAR_CAP``."""
    if _json_len(snippet) <= SNIPPET_CHAR_CAP:
        return {"snippet": snippet}
    text = str(snippet)

    def marked(keep: int) -> str:
        return f"{text[:keep]}…[truncated {len(text) - keep} chars]"

    fitted = marked(0)
    low, high = 1, min(len(text), SNIPPET_CHAR_CAP)
    while low <= high:
        middle = (low + high) // 2
        candidate = marked(middle)
        if _json_len(candidate) <= SNIPPET_CHAR_CAP:
            fitted, low = candidate, middle + 1
        else:
            high = middle - 1
    return {"snippet": fitted, "truncated": True}


class SessionSearchTool:
    """FTS5-backed search over session messages — per-project or cross-project.

    Two scopes:

    * ``scope="project"`` (default) — searches the active
      ``SessionManager``'s ``messages_fts`` / ``messages_fts_trigram``
      indices (trigram-aware).
    * ``scope="all"`` — searches the cross-project
      ``~/.geode/search/global.db`` rebuilt by ``geode reindex``.
      Result rows include ``project_id`` + ``project_slug``.
    """

    @property
    def name(self) -> str:
        return "session_search"

    @property
    def description(self) -> str:
        return (
            "Search past conversation messages via FTS5 full-text index. "
            "Set scope='project' (default) to search the current project's "
            "sessions.db (trigram-aware via prefer_trigram). Set scope='all' "
            "to search the cross-project global.db index rebuilt by "
            "'geode reindex'. Returns matching messages with snippets and "
            "relevance scores. Use this to recall prior context the LLM "
            "cannot remember from earlier turns."
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
                "scope": {
                    "type": "string",
                    "enum": [SCOPE_PROJECT, SCOPE_ALL],
                    "description": (
                        "'project' = current project's sessions.db (default). "
                        "'all' = cross-project ~/.geode/search/global.db "
                        "rebuilt by 'geode reindex'."
                    ),
                    "default": SCOPE_PROJECT,
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Optional — restrict search to a single session by id. "
                        "Honoured by both scopes."
                    ),
                },
                "project_id": {
                    "type": "string",
                    "description": (
                        "Optional — restrict scope='all' results to one "
                        "project. Ignored when scope='project' (the active "
                        "session manager already pins the project)."
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
                        "scope='project' only — query the trigram index "
                        "(substring + CJK partial-word recall). Falls back "
                        "to unicode61 when trigram is unavailable. "
                        "scope='all' always uses unicode61."
                    ),
                    "default": False,
                },
                "include_artifacts": {
                    "type": "boolean",
                    "description": (
                        "Also search synthesized long-context artifacts "
                        "such as compaction summaries and dreams. Default false."
                    ),
                    "default": False,
                },
                "artifact_kinds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional artifact kind filter when include_artifacts=true, "
                        "for example ['compaction_summary', 'dream']."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            return tool_error("query is required and must be a non-empty string")
        scope_raw = kwargs.get("scope", SCOPE_PROJECT)
        scope = (
            scope_raw
            if isinstance(scope_raw, str) and scope_raw in _VALID_SCOPES
            else SCOPE_PROJECT
        )
        session_id = kwargs.get("session_id")
        limit = kwargs.get("limit", 20)
        prefer_trigram = bool(kwargs.get("prefer_trigram", False))
        project_id = kwargs.get("project_id")
        include_artifacts = bool(kwargs.get("include_artifacts", False))
        artifact_kinds_raw = kwargs.get("artifact_kinds")
        artifact_kinds = (
            [str(k) for k in artifact_kinds_raw if isinstance(k, str)]
            if isinstance(artifact_kinds_raw, list)
            else None
        )
        if not isinstance(limit, int) or limit <= 0:
            limit = 20
        try:
            limit = min(int(limit), 100)
        except (TypeError, ValueError):
            limit = 20

        # Gateway threads share the session stores; visibility follows the
        # executing loop, never the model's ``session_id`` argument.
        visible_to = caller_session_ids(kwargs.get("_tool_context"))
        if scope == SCOPE_ALL:
            return self._search_global(
                query=query,
                project_id=project_id if isinstance(project_id, str) else None,
                session_id=session_id if isinstance(session_id, str) else None,
                limit=limit,
                visible_to=visible_to,
            )
        return self._search_project(
            query=query,
            session_id=session_id if isinstance(session_id, str) else None,
            limit=limit,
            prefer_trigram=prefer_trigram,
            include_artifacts=include_artifacts,
            artifact_kinds=artifact_kinds,
            visible_to=visible_to,
        )

    def _search_project(
        self,
        *,
        query: str,
        session_id: str | None,
        limit: int,
        prefer_trigram: bool,
        include_artifacts: bool = False,
        artifact_kinds: list[str] | None = None,
        visible_to: Collection[str] = frozenset(),
    ) -> dict[str, Any]:
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
                session_id=session_id,
                limit=limit,
                prefer_trigram=prefer_trigram,
                visible_to=visible_to,
            )
            artifact_hits = (
                mgr.search_context_artifacts(
                    query,
                    session_id=session_id,
                    kinds=artifact_kinds,
                    limit=limit,
                    visible_to=visible_to,
                )
                if include_artifacts
                else []
            )
        finally:
            mgr.close()

        return {
            "matched": bool(hits or artifact_hits),
            "count": len(hits),
            "artifact_count": len(artifact_hits),
            "scope": SCOPE_PROJECT,
            "hits": [
                {
                    "session_id": h["session_id"],
                    "message_id": h["message_id"],
                    "seq": h["seq"],
                    "role": h["role"],
                    "timestamp": h["timestamp"],
                    **_bounded_snippet(h["snippet"]),
                    "score": h["score"],
                }
                for h in hits
            ],
            "artifacts": [
                {
                    "artifact_id": h["artifact_id"],
                    "session_id": h["session_id"],
                    "kind": h["kind"],
                    "source_start_seq": h["source_start_seq"],
                    "source_end_seq": h["source_end_seq"],
                    **_bounded_snippet(h["snippet"]),
                    "score": h["score"],
                    "updated_at": h["updated_at"],
                }
                for h in artifact_hits
            ],
        }

    def _search_global(
        self,
        *,
        query: str,
        project_id: str | None,
        session_id: str | None,
        limit: int,
        visible_to: Collection[str] = frozenset(),
    ) -> dict[str, Any]:
        from core.paths import GLOBAL_SEARCH_DB

        if not GLOBAL_SEARCH_DB.is_file():
            # Empty index = empty result. Graceful — let the LLM
            # decide whether to retry with scope="project".
            return {
                "matched": False,
                "count": 0,
                "scope": SCOPE_ALL,
                "hits": [],
                "reason": "global_index_not_built — run 'geode reindex' first",
            }

        try:
            from core.memory.search_index import SearchIndex
        except Exception as exc:  # pragma: no cover — defensive
            log.debug("session_search: SearchIndex import failed: %s", exc)
            return tool_error(
                "search_index_unavailable",
                error_type="dependency",
            )

        try:
            with SearchIndex() as index:
                hits = index.search(
                    query,
                    project_id=project_id,
                    session_id=session_id,
                    limit=limit,
                    visible_to=visible_to,
                )
        except Exception as exc:
            log.debug("session_search: global search failed: %s", exc)
            return tool_error(
                f"global_search_failed: {exc}",
                error_type="internal",
            )

        return {
            "matched": bool(hits),
            "count": len(hits),
            "scope": SCOPE_ALL,
            "hits": [
                {
                    "project_id": h.project_id,
                    "project_slug": h.project_slug,
                    "session_id": h.session_id,
                    "message_id": h.message_id,
                    "seq": h.seq,
                    "role": h.role,
                    "timestamp": h.timestamp,
                    **_bounded_snippet(h.snippet),
                    "score": h.score,
                }
                for h in hits
            ],
        }

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Run search off the event loop — SQLite calls are sync."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)
