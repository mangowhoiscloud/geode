"""Regression pin for PR-TOOL-EXEC-CONTEXT (2026-05-28).

LLM-touching tools must receive the AgenticLoop's resolved
``(provider, source, model, adapter_name)`` via :class:`ToolContext`
and forward the routing preference into ``dispatch.web_search_via_adapters``
+ ``dispatch.complete_text_via_adapters`` so the operator's ``/login``
choice that drives the main LLM path also drives the tool's adapter
selection.

Static + behavioural pins:

1. ``ToolContext`` carries the four LLM-identity fields with empty-string
   defaults (so callers outside an AgenticLoop are not forced to fill them).
2. The dispatch helpers accept ``prefer_provider`` / ``prefer_source``
   keyword params and stable-reorder candidates accordingly.
3. ``GeneralWebSearchTool.aexecute`` + ``WebSearchTool.aexecute`` read
   ``_tool_context`` from kwargs and forward the preference (source-level
   pin so future refactors that silently drop the wiring fail visibly).
4. ``_safe_delegate`` injects ``_tool_context`` into the tool's
   ``aexecute`` kwargs when given a non-None context.
5. ``ToolCallProcessor`` builds a fresh ``ToolContext`` per dispatch and
   passes it to ``executor.aexecute(..., context=ctx)`` (source-level
   pin — runtime test would require a full executor fixture).
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# 1. ToolContext dataclass shape
# ---------------------------------------------------------------------------


def test_tool_context_carries_llm_identity_fields() -> None:
    from core.tools.base import ToolContext

    ctx = ToolContext()
    # Empty defaults — tools called outside a loop must work without
    # operators having to fill these in.
    assert ctx.provider == ""
    assert ctx.source == ""
    assert ctx.model == ""
    assert ctx.adapter_name == ""

    fields = {f.name for f in dataclasses.fields(ToolContext)}
    assert {"provider", "source", "model", "adapter_name"}.issubset(fields), (
        "ToolContext must carry the four LLM-identity fields propagated by PR-TOOL-EXEC-CONTEXT."
    )


def test_tool_context_accepts_loop_routing() -> None:
    from core.tools.base import ToolContext

    ctx = ToolContext(
        provider="anthropic",
        source="subscription",
        model="claude-opus-4-7",
        adapter_name="anthropic-oauth",
    )
    assert ctx.provider == "anthropic"
    assert ctx.source == "subscription"
    assert ctx.model == "claude-opus-4-7"
    assert ctx.adapter_name == "anthropic-oauth"


# ---------------------------------------------------------------------------
# 2. Dispatch reordering — behavioural
# ---------------------------------------------------------------------------


def _fake_adapter(name: str, provider: str, source: str) -> Any:
    """Tiny adapter stand-in for ``_apply_prefer`` ordering tests."""
    a = MagicMock()
    a.name = name
    a.provider = provider
    a.source = source
    return a


def test_apply_prefer_floats_exact_match_first() -> None:
    from core.llm.adapters.dispatch import _apply_prefer

    cands = [
        _fake_adapter("openai-payg", "openai", "payg"),
        _fake_adapter("anthropic-payg", "anthropic", "payg"),
        _fake_adapter("anthropic-oauth", "anthropic", "subscription"),
        _fake_adapter("glm-payg", "glm", "payg"),
    ]
    out = _apply_prefer(cands, prefer_provider="anthropic", prefer_source="subscription")
    assert out[0].name == "anthropic-oauth"
    # Provider-only match comes second, then source-only, then everything else.
    assert out[1].name == "anthropic-payg"


def test_apply_prefer_provider_only_floats_provider_block_first() -> None:
    from core.llm.adapters.dispatch import _apply_prefer

    cands = [
        _fake_adapter("openai-payg", "openai", "payg"),
        _fake_adapter("anthropic-payg", "anthropic", "payg"),
        _fake_adapter("anthropic-oauth", "anthropic", "subscription"),
    ]
    out = _apply_prefer(cands, prefer_provider="anthropic", prefer_source=None)
    assert {out[0].name, out[1].name} == {"anthropic-payg", "anthropic-oauth"}
    assert out[2].name == "openai-payg"


def test_apply_prefer_empty_preference_returns_input_unchanged() -> None:
    from core.llm.adapters.dispatch import _apply_prefer

    cands = [
        _fake_adapter("anthropic-payg", "anthropic", "payg"),
        _fake_adapter("openai-payg", "openai", "payg"),
    ]
    out = _apply_prefer(cands, prefer_provider=None, prefer_source=None)
    assert [a.name for a in out] == ["anthropic-payg", "openai-payg"]


# ---------------------------------------------------------------------------
# 3. Source-level pins — web tools forward the preference
# ---------------------------------------------------------------------------


def test_general_web_search_forwards_tool_context() -> None:
    src = (Path(__file__).resolve().parents[1] / "core" / "tools" / "web_tools.py").read_text(
        encoding="utf-8"
    )
    # Tool must read _tool_context from kwargs and pass prefer_provider /
    # prefer_source to the dispatch helper. A silent drop here defeats the
    # entire PR-TOOL-EXEC-CONTEXT flow.
    assert 'kwargs.get("_tool_context")' in src
    assert "prefer_provider=prefer_provider" in src
    assert "prefer_source=prefer_source" in src


def test_web_search_tool_forwards_tool_context() -> None:
    src = (Path(__file__).resolve().parents[1] / "core" / "tools" / "web_search.py").read_text(
        encoding="utf-8"
    )
    assert 'kwargs.get("_tool_context")' in src
    assert "prefer_provider=prefer_provider" in src
    assert "prefer_source=prefer_source" in src


# ---------------------------------------------------------------------------
# 4. _safe_delegate injects _tool_context
# ---------------------------------------------------------------------------


def test_safe_delegate_injects_context_into_aexecute_kwargs() -> None:
    """When ``_safe_delegate`` receives a non-None context, the tool's
    ``aexecute`` must see ``_tool_context`` in its kwargs."""
    from core.cli.tool_handlers.clarification import _safe_delegate
    from core.tools.base import ToolContext

    captured: dict[str, Any] = {}

    class _CapturingTool:
        async def aexecute(self, **kw: Any) -> dict[str, Any]:
            captured.update(kw)
            return {"result": "ok"}

    ctx = ToolContext(provider="anthropic", source="subscription")
    result = _safe_delegate(_CapturingTool, {"query": "hello"}, context=ctx)
    assert result == {"result": "ok"}
    assert captured["query"] == "hello"
    assert captured["_tool_context"] is ctx


def test_safe_delegate_without_context_omits_kwarg() -> None:
    """Legacy callers (no context) must not have ``_tool_context`` injected
    so existing tools that strictly validate kwargs do not regress."""
    from core.cli.tool_handlers.clarification import _safe_delegate

    captured: dict[str, Any] = {}

    class _CapturingTool:
        async def aexecute(self, **kw: Any) -> dict[str, Any]:
            captured.update(kw)
            return {"result": "ok"}

    _safe_delegate(_CapturingTool, {"query": "hello"})
    assert "_tool_context" not in captured


# ---------------------------------------------------------------------------
# 5. ToolCallProcessor builds ToolContext from constructor-injected fields
# ---------------------------------------------------------------------------


def test_processor_init_accepts_provider_source_adapter() -> None:
    """ToolCallProcessor must accept provider / source / adapter_name in its
    constructor — that is the wiring point AgenticLoop uses to forward
    its resolved identity into every tool dispatch."""
    from core.agent.tool_executor.processor import ToolCallProcessor

    sig = inspect.signature(ToolCallProcessor.__init__)
    params = set(sig.parameters)
    assert {"provider", "source", "adapter_name"}.issubset(params), (
        "ToolCallProcessor must accept provider/source/adapter_name kwargs "
        "for PR-TOOL-EXEC-CONTEXT wiring."
    )


def test_processor_builds_tool_context_for_each_dispatch() -> None:
    """Source-level pin: the processor's dispatch path must construct a
    ``ToolContext`` carrying its own provider/source/model/adapter_name
    and pass it as ``context=`` to the executor. A regression here
    silently disconnects the loop from the tool layer (each tool would
    fall back to ``infer_source`` independently)."""
    src = (
        Path(__file__).resolve().parents[1] / "core" / "agent" / "tool_executor" / "processor.py"
    ).read_text(encoding="utf-8")
    assert "tool_ctx = ToolContext(" in src
    assert "provider=self._provider" in src
    assert "source=self._source" in src
    assert "model=self._model" in src
    assert "adapter_name=self._adapter_name" in src
    assert "context=tool_ctx" in src


# ---------------------------------------------------------------------------
# 6. AgenticLoop wires its identity into the processor
# ---------------------------------------------------------------------------


def test_agentic_loop_passes_identity_to_processor() -> None:
    """Source-level pin: AgenticLoop must pull provider / source from the
    RESOLVED adapter (``self._new_adapter``), not the loop's pre-
    normalisation ``self._provider`` / ``self._source``. Codex MCP audit
    catch — the loop carries ``openai-codex`` / ``zhipuai`` strings that
    the registry collapses to ``openai`` / ``glm``; ``_apply_prefer``
    compares against the adapter's own identity so passing the pre-
    normalisation values would silently miss every match."""
    src = (
        Path(__file__).resolve().parents[1] / "core" / "agent" / "loop" / "agent_loop.py"
    ).read_text(encoding="utf-8")
    assert 'getattr(self._new_adapter, "provider", self._provider)' in src
    assert 'getattr(self._new_adapter, "source", self._source)' in src
    assert 'adapter_name=getattr(self._new_adapter, "name", "")' in src


def test_handler_signature_gating_skips_closed_signature_handlers() -> None:
    """Codex MCP audit CONCERN — third-party handlers with closed
    signatures (no ``**kwargs``, no explicit ``_tool_context`` param)
    would crash with ``unexpected keyword argument`` if we injected
    blindly. The executor's signature-gating skips injection in that
    case while still forwarding ``_tool_context`` to ``**kwargs`` /
    explicit-param handlers."""
    from core.agent.tool_executor.executor import ToolExecutor

    def closed_handler(query: str, max_results: int = 5) -> dict[str, Any]:
        return {"query": query, "n": max_results}

    def kwargs_handler(**kw: Any) -> dict[str, Any]:
        return kw

    def explicit_ctx_handler(query: str, *, _tool_context: Any = None) -> dict[str, Any]:
        return {"q": query, "ctx": _tool_context}

    assert not ToolExecutor._handler_accepts_tool_context(closed_handler)
    assert ToolExecutor._handler_accepts_tool_context(kwargs_handler)
    assert ToolExecutor._handler_accepts_tool_context(explicit_ctx_handler)


# ---------------------------------------------------------------------------
# 7. End-to-end: web_search_via_adapters honours preference
# ---------------------------------------------------------------------------


def test_web_search_via_adapters_prefers_matching_adapter() -> None:
    """When the loop is on anthropic-subscription, dispatch must try the
    anthropic-subscription web_search adapter first — even if the default
    candidate order would have put a PAYG adapter ahead."""
    from core.llm.adapters.base import WebSearchResult
    from core.llm.adapters.dispatch import web_search_via_adapters

    payg = MagicMock()
    payg.name = "anthropic-payg"
    payg.provider = "anthropic"
    payg.source = "payg"
    payg.aweb_search = AsyncMock(
        return_value=WebSearchResult(query="q", text="from-payg", adapter_name="anthropic-payg")
    )
    sub = MagicMock()
    sub.name = "anthropic-oauth"
    sub.provider = "anthropic"
    sub.source = "subscription"
    sub.aweb_search = AsyncMock(
        return_value=WebSearchResult(query="q", text="from-sub", adapter_name="anthropic-oauth")
    )

    # Patch _capability_candidates so dispatch sees only these two adapters
    # in default (payg-first) order; the preference must float sub ahead.
    with patch(
        "core.llm.adapters.dispatch._capability_candidates",
        return_value=[payg, sub],
    ):
        result = asyncio.run(
            web_search_via_adapters("q", prefer_provider="anthropic", prefer_source="subscription")
        )

    assert result.adapter_name == "anthropic-oauth"
    sub.aweb_search.assert_called_once()
    payg.aweb_search.assert_not_called()
