"""Deferred tool loading policy — provider-neutral SoT.

PR-CODEX-TOOL-SEARCH (2026-06-13): the always-loaded core set and the
activation threshold moved here from ``core/llm/providers/anthropic.py``
so the OpenAI Responses builder (``_openai_common.build_responses_kwargs``)
shares ONE policy with the Anthropic adapter instead of growing a second
copy (dual-SoT rule). Both providers expose the same official mechanism:
a ``defer_loading`` field on tool definitions plus a hosted search tool
(Anthropic ``tool_search_tool_regex_20251119`` / OpenAI
``{"type": "tool_search"}``).
"""

from __future__ import annotations

TOOL_DEFER_THRESHOLD = 16
"""Tool count above which deferred loading activates (both vendors cite
10+ tools as the good-use-case bar; GEODE ships ~60). Below it, defer
adds a search round-trip for no context saving."""

TOOL_SEARCH_ALWAYS_LOADED: frozenset[str] = frozenset(
    {
        "memory_search",
        "memory_save",
        "note_read",
        "note_save",
        "read_document",
        "glob_files",
        "grep_files",
        "general_web_search",
        "web_fetch",
        "llms_txt_index",
        "check_status",
        "use_skill",
    }
)
"""Immediately-loaded core set — high-frequency tools the loop should
never pay a search round-trip for. Everything else defers behind the
provider's hosted tool-search tool."""

# OpenAI Responses 500 bug (community.openai.com/t/.../1375850):
# tool_search + hosted web_search + a DEFERRED function named "web"
# returns a 500. GEODE ships no tool named "web", but the exclusion is
# pinned so a future tool cannot trip the upstream bug.
OPENAI_DEFER_NAME_BLOCKLIST: frozenset[str] = frozenset({"web"})
