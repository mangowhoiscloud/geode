"""Hosted tool-search defer wiring — Anthropic adapter request shaping.

PR-TOOL-SEARCH-WIRE (2026-06-13). The official Messages API mechanism
(`defer_loading` tool field + `tool_search_tool_regex_20251119`,
platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
replaces the bespoke registry-level defer (`ToolSearchTool` +
`to_anthropic_tools_with_defer`), which never deferred on the wire — its
markers were stripped by the adapter key filter.

These tests pin the request-shaping invariants the API enforces with
400s, so a regression fails here instead of in production:
* at least one tool stays non-deferred,
* the search tool itself never carries ``defer_loading``,
* hosted/native (type-carrying) entries never defer,
* the key filter lets ``defer_loading`` through (it silently stripped it
  before this PR),
* the kill switch (``settings.tool_search_defer``) and the threshold
  short-circuit cleanly.
"""

from __future__ import annotations

from core.llm.providers.anthropic import (
    _API_ALLOWED_KEYS,
    _TOOL_SEARCH_TOOL,
    TOOL_DEFER_THRESHOLD,
    TOOL_SEARCH_ALWAYS_LOADED,
    apply_tool_search_defer,
)


def _custom_tool(name: str) -> dict:
    return {
        "name": name,
        "description": f"{name} tool",
        "input_schema": {"type": "object", "properties": {}},
    }


def _big_toolset() -> list[dict]:
    core_tools = [_custom_tool(n) for n in sorted(TOOL_SEARCH_ALWAYS_LOADED)[:4]]
    extra_tools = [_custom_tool(f"extra_{i}") for i in range(20)]
    native = [{"type": "web_search_20260209", "name": "web_search"}]
    return core_tools + extra_tools + native


def test_defer_activates_above_threshold_with_search_tool_first() -> None:
    shaped = apply_tool_search_defer(_big_toolset())
    assert shaped[0]["name"] == _TOOL_SEARCH_TOOL["name"]
    assert "defer_loading" not in shaped[0], "search tool must never defer (API 400)"
    deferred = [t for t in shaped if t.get("defer_loading")]
    assert len(deferred) == 20, "exactly the non-core custom tools defer"


def test_core_set_and_natives_stay_loaded() -> None:
    shaped = apply_tool_search_defer(_big_toolset())
    loaded_names = {t["name"] for t in shaped if not t.get("defer_loading")}
    assert "web_search" in loaded_names, "hosted/native (type-carrying) entries never defer"
    for name in sorted(TOOL_SEARCH_ALWAYS_LOADED)[:4]:
        assert name in loaded_names
    # API invariant: at least one non-deferred tool must remain.
    assert len(loaded_names) >= 1


def test_under_threshold_and_kill_switch_are_noops() -> None:
    small_toolset = [_custom_tool(f"t{i}") for i in range(TOOL_DEFER_THRESHOLD)]
    assert apply_tool_search_defer(small_toolset) is small_toolset

    big_toolset = _big_toolset()
    assert apply_tool_search_defer(big_toolset, enabled=False) is big_toolset
    assert not any(t.get("defer_loading") for t in big_toolset), "input must not be mutated"


def test_all_core_toolset_defers_nothing_and_skips_search_tool() -> None:
    """A toolset that is all core/native above threshold must NOT gain a
    search tool — a defer pass that defers zero tools is pure overhead."""
    all_core = [_custom_tool(n) for n in sorted(TOOL_SEARCH_ALWAYS_LOADED)]
    all_core += [{"type": f"hosted_{i}", "name": f"hosted_{i}"} for i in range(10)]
    shaped = apply_tool_search_defer(all_core, threshold=5)
    assert shaped is all_core


def test_api_key_filter_passes_defer_loading() -> None:
    """The adapter strips unknown keys before the wire — defer_loading must
    survive the filter or the whole mechanism silently no-ops (the exact
    pre-PR pathology)."""
    assert "defer_loading" in _API_ALLOWED_KEYS


def test_settings_kill_switch_exists_with_default_on() -> None:
    from core.config import Settings

    assert Settings.model_fields["tool_search_defer"].default is True


def test_call_site_reads_kill_switch() -> None:
    """Knob without a reader is a dead knob (v1.0 audit class) — the
    agentic_call body must consult settings.tool_search_defer."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    adapter_source = (repo_root / "core" / "llm" / "providers" / "anthropic.py").read_text(
        encoding="utf-8"
    )
    assert "tool_search_defer" in adapter_source
    assert "apply_tool_search_defer(" in adapter_source.split("async def agentic_call", 1)[1]
