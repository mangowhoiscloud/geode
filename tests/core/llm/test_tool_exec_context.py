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

import pytest

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


def _fake_adapter(
    name: str, provider: str, source: str, *, capability: str = "supports_web_search"
) -> Any:
    """Tiny adapter stand-in for ``_select_adapter`` tests."""
    a = MagicMock(spec_set=["name", "provider", "source", capability, "aweb_search"])
    a.name = name
    a.provider = provider
    a.source = source
    setattr(a, capability, True)
    a.aweb_search = MagicMock()
    return a


def test_select_adapter_exact_match_required_with_prefer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-NO-FALLBACK — when both ``prefer_provider`` and ``prefer_source``
    are given, ``_select_adapter`` returns the exact match or ``None`` —
    never widens to a partial match."""
    from core.llm.adapters.dispatch import _select_adapter

    cands = [
        _fake_adapter("openai-payg", "openai", "payg"),
        _fake_adapter("anthropic-payg", "anthropic", "payg"),
        _fake_adapter("anthropic-oauth", "anthropic", "subscription"),
    ]
    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: cands)

    # Exact match — anthropic-oauth picked.
    picked = _select_adapter(
        "supports_web_search",
        prefer_provider="anthropic",
        prefer_source="subscription",
        provider_order=("anthropic", "openai", "glm"),
    )
    assert picked is not None and picked.name == "anthropic-oauth"

    # No exact match for (openai, subscription) — even though openai-payg
    # is registered, dispatch refuses to widen.
    picked = _select_adapter(
        "supports_web_search",
        prefer_provider="openai",
        prefer_source="subscription",
        provider_order=("anthropic", "openai", "glm"),
    )
    assert picked is None


def test_select_adapter_default_resolved_uses_infer_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without preference, ``_select_adapter`` picks the first provider in
    order with an adapter whose source equals ``infer_source(provider)``."""
    from core.llm.adapters.dispatch import _select_adapter

    cands = [
        _fake_adapter("anthropic-payg", "anthropic", "payg"),
        _fake_adapter("anthropic-oauth", "anthropic", "subscription"),
        _fake_adapter("openai-payg", "openai", "payg"),
    ]
    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: cands)
    monkeypatch.setattr(
        "core.llm.adapters._source_inference.infer_source",
        lambda provider: "subscription" if provider == "anthropic" else "payg",
    )

    picked = _select_adapter(
        "supports_web_search",
        prefer_provider=None,
        prefer_source=None,
        provider_order=("anthropic", "openai", "glm"),
    )
    assert picked is not None and picked.name == "anthropic-oauth"


def test_select_adapter_returns_none_when_no_capable_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.llm.adapters.dispatch import _select_adapter

    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: [])
    picked = _select_adapter(
        "supports_web_search",
        prefer_provider=None,
        prefer_source=None,
        provider_order=("anthropic", "openai", "glm"),
    )
    assert picked is None


# ---------------------------------------------------------------------------
# 3. Source-level pins — web tools forward the preference
# ---------------------------------------------------------------------------


def test_general_web_search_forwards_tool_context() -> None:
    src = (Path(__file__).resolve().parents[3] / "core" / "tools" / "web_tools.py").read_text(
        encoding="utf-8"
    )
    # Tool must read _tool_context from kwargs and pass prefer_provider /
    # prefer_source to the dispatch helper. A silent drop here defeats the
    # entire PR-TOOL-EXEC-CONTEXT flow.
    assert 'kwargs.get("_tool_context")' in src
    assert "prefer_provider=prefer_provider" in src
    assert "prefer_source=prefer_source" in src


def test_web_search_tool_forwards_tool_context() -> None:
    src = (Path(__file__).resolve().parents[3] / "core" / "tools" / "web_search.py").read_text(
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
    # PR-LOOP-POLLUTION-FIX (2026-06-12) — _safe_delegate is a coroutine now.
    result = asyncio.run(_safe_delegate(_CapturingTool, {"query": "hello"}, context=ctx))
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

    asyncio.run(_safe_delegate(_CapturingTool, {"query": "hello"}))
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
        Path(__file__).resolve().parents[3] / "core" / "agent" / "tool_executor" / "processor.py"
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
    normalisation ``self._provider`` / ``self._source``. The registry
    collapses ``openai-codex → openai`` / ``zhipuai → glm``; the
    strict-dispatch helper (``_select_adapter`` PR-NO-FALLBACK) compares
    against the adapter's own identity so the pre-normalisation values
    would silently miss every match."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "agent" / "loop" / "agent_loop.py"
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
# 7. End-to-end: web_search_via_adapters honours exact-match preference
# ---------------------------------------------------------------------------


def test_web_search_via_adapters_routes_to_exact_match() -> None:
    """PR-NO-FALLBACK — when the loop is on anthropic-subscription,
    dispatch routes to anthropic-oauth (the exact match). The PAYG sibling
    is registered but never tried — strict single-adapter mode."""
    from core.llm.adapters.base import WebSearchResult
    from core.llm.adapters.dispatch import web_search_via_adapters

    payg = MagicMock(spec_set=["name", "provider", "source", "supports_web_search", "aweb_search"])
    payg.name = "anthropic-payg"
    payg.provider = "anthropic"
    payg.source = "payg"
    payg.supports_web_search = True
    payg.aweb_search = AsyncMock(
        return_value=WebSearchResult(query="q", text="from-payg", adapter_name="anthropic-payg")
    )
    sub = MagicMock(spec_set=["name", "provider", "source", "supports_web_search", "aweb_search"])
    sub.name = "anthropic-oauth"
    sub.provider = "anthropic"
    sub.source = "subscription"
    sub.supports_web_search = True
    sub.aweb_search = AsyncMock(
        return_value=WebSearchResult(query="q", text="from-sub", adapter_name="anthropic-oauth")
    )

    with patch("core.llm.adapters.dispatch.list_adapters", return_value=[payg, sub]):
        result = asyncio.run(
            web_search_via_adapters("q", prefer_provider="anthropic", prefer_source="subscription")
        )

    assert result.adapter_name == "anthropic-oauth"
    sub.aweb_search.assert_called_once()
    payg.aweb_search.assert_not_called()


def test_web_search_via_adapters_no_fallback_on_billing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-NO-FALLBACK — billing-fatal on the selected adapter raises
    immediately. No fallback to other capable adapters even when they are
    registered + healthy."""
    from core.llm.adapters.dispatch import web_search_via_adapters
    from core.llm.errors import BillingError

    selected = MagicMock(
        spec_set=["name", "provider", "source", "supports_web_search", "aweb_search"]
    )
    selected.name = "anthropic-payg"
    selected.provider = "anthropic"
    selected.source = "payg"
    selected.supports_web_search = True
    selected.aweb_search = AsyncMock(
        side_effect=BillingError("quota exceeded", provider="anthropic")
    )
    fallback = MagicMock(
        spec_set=["name", "provider", "source", "supports_web_search", "aweb_search"]
    )
    fallback.name = "openai-payg"
    fallback.provider = "openai"
    fallback.source = "payg"
    fallback.supports_web_search = True
    fallback.aweb_search = AsyncMock()  # Should NEVER be called.

    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: [selected, fallback])
    monkeypatch.setattr("core.llm.adapters._source_inference.infer_source", lambda provider: "payg")

    with pytest.raises(BillingError, match=r"anthropic-payg .* credit exhausted"):
        asyncio.run(web_search_via_adapters("q"))

    selected.aweb_search.assert_called_once()
    fallback.aweb_search.assert_not_called()
