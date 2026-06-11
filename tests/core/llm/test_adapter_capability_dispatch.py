"""Regression pin for PR-ADAPTER-PATTERN-UNIFICATION (2026-05-28) +
PR-NO-FALLBACK (2026-05-28).

The capability-based dispatch layer (``core/llm/adapters/dispatch.py``)
centralises web_search and text-completion via the adapter registry.
PR-NO-FALLBACK (2026-05-28) replaced the fallback-chain semantics with
strict single-adapter dispatch — the operator's explicit ``/login source``
is the sole switch, no silent cross-provider / cross-source fallback.

These tests pin:

1. ``WebSearchCapable`` / ``TextCompletionCapable`` mixin Protocols are
   defined and runtime-checkable on the canonical adapters.
2. ``web_search_via_adapters`` selects exactly one adapter and:
   - returns its :class:`WebSearchResult` on success
   - raises :class:`BillingError` with adapter context on billing-fatal
   - raises :class:`AdapterDispatchError` on non-connection transient
     (no retry); connection-class transients get ONE bounded SAME-adapter
     retry — PR-DISPATCH-TRANSIENT-RETRY (2026-06-11), pinned in
     ``test_dispatch_transient_retry_guardrails.py``
   - raises :class:`AdapterUnavailableError` when no adapter matches
3. ``complete_text_via_adapters`` mirrors the same semantics.
4. Adapter selection honours the operator's ``infer_source`` resolution
   so the dispatch lands on the operator-configured source.
5. ``GeneralWebSearchTool`` + ``WebSearchTool`` delegate to the dispatch
   helper (source-level pin — no direct SDK imports).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from core.llm.adapters.base import (
    TextCompletionCapable,
    TextCompletionResult,
    UsageSummary,
    WebSearchCapable,
    WebSearchResult,
)
from core.llm.adapters.dispatch import (
    AdapterDispatchError,
    AdapterUnavailableError,
    complete_text_via_adapters,
    web_search_via_adapters,
)
from core.llm.errors import BillingError

# ---------------------------------------------------------------------------
# Stub adapters — minimal capability-bearing objects for dispatch tests
# ---------------------------------------------------------------------------


class _StubWebSearchAdapter:
    name: str
    provider: str
    source: str
    supports_web_search: bool = True

    def __init__(self, *, name: str, provider: str, source: str, mode: str) -> None:
        self.name = name
        self.provider = provider
        self.source = source
        self._mode = mode  # "ok" | "billing" | "transient"

    async def aweb_search(self, query: str, *, max_results: int = 5) -> WebSearchResult:
        if self._mode == "billing":
            raise BillingError("stub billing", provider=self.provider, plan_display_name=self.name)
        if self._mode == "transient":
            raise RuntimeError(f"stub transient failure from {self.name}")
        return WebSearchResult(
            query=query, text=f"results from {self.name}", adapter_name=self.name
        )


class _StubTextCompletionAdapter:
    name: str
    provider: str
    source: str
    supports_text_completion: bool = True

    def __init__(self, *, name: str, provider: str, source: str, mode: str) -> None:
        self.name = name
        self.provider = provider
        self.source = source
        self._mode = mode

    async def acomplete_text(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = "",
        max_tokens: int = 1024,
    ) -> TextCompletionResult:
        if self._mode == "billing":
            raise BillingError("stub billing", provider=self.provider, plan_display_name=self.name)
        if self._mode == "transient":
            raise RuntimeError(f"stub transient failure from {self.name}")
        return TextCompletionResult(
            text=f"completed by {self.name}",
            usage=UsageSummary(input_tokens=1, output_tokens=2),
        )


def _install_stubs(monkeypatch: pytest.MonkeyPatch, stubs: list[Any]) -> None:
    """Replace the registry's ``list_adapters`` with a stub list, for both
    the dispatch module and the registry module (each may have imported
    ``list_adapters`` directly at module load)."""
    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: stubs)


def _force_payg_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin :func:`infer_source` to always return ``"payg"`` so the source
    preference is deterministic across machines (PAYG → subscription)."""
    monkeypatch.setattr("core.llm.adapters._source_inference.infer_source", lambda provider: "payg")


# ---------------------------------------------------------------------------
# Capability mixin Protocols — isinstance pins
# ---------------------------------------------------------------------------


def test_anthropic_payg_adapter_advertises_web_search_and_text_completion() -> None:
    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter

    adapter = AnthropicPaygAdapter()
    assert isinstance(adapter, WebSearchCapable)
    assert isinstance(adapter, TextCompletionCapable)
    assert adapter.supports_web_search is True
    assert adapter.supports_text_completion is True


def test_anthropic_oauth_adapter_advertises_web_search_and_text_completion() -> None:
    from core.llm.adapters.anthropic_oauth import AnthropicOAuthAdapter

    adapter = AnthropicOAuthAdapter()
    assert isinstance(adapter, WebSearchCapable)
    assert isinstance(adapter, TextCompletionCapable)


def test_openai_payg_adapter_advertises_web_search_and_text_completion() -> None:
    from core.llm.adapters.openai_payg import OpenAIPaygAdapter

    adapter = OpenAIPaygAdapter()
    assert isinstance(adapter, WebSearchCapable)
    assert isinstance(adapter, TextCompletionCapable)


def test_glm_payg_adapter_advertises_web_search_and_text_completion() -> None:
    from core.llm.adapters.glm_payg import GlmPaygAdapter

    adapter = GlmPaygAdapter()
    assert isinstance(adapter, WebSearchCapable)
    assert isinstance(adapter, TextCompletionCapable)


def test_codex_oauth_adapter_advertises_web_search() -> None:
    """PR-NO-FALLBACK (2026-05-28) — SDK-contract level: openai-python
    SDK's ``ToolParam`` Union accepts ``{"type": "web_search"}`` and
    ``codex-rs/codex-api/README.md`` documents the Responses endpoint
    accepts a ``tools`` array. ``codex-oauth`` advertises the capability
    so an operator on a ChatGPT subscription gets web_search routed
    through their OAuth token (no PAYG key needed) — the prior
    conservative ``False`` was the root cause of the routing leak that
    landed web_search on ``glm-payg`` for Codex-OAuth operators.

    PR-CODEX-INSTRUCTIONS-FIX (2026-05-28) — flipped the docstring
    attestation from ``unverified — live test required`` to **verified
    live** after the Codex backend returned 200 OK with real web search
    results. Two backend-specific constraints (``instructions`` mandatory,
    ``input`` typed-item list) the live test discovered are now enforced
    in :meth:`aweb_search`. This test pins the verified attestation
    string presence so a future silent docstring rewrite cannot drop
    the evidence trail."""
    import inspect

    from core.llm.adapters.codex_oauth import CodexOAuthAdapter

    adapter = CodexOAuthAdapter()
    assert adapter.supports_web_search is True
    assert callable(getattr(adapter, "aweb_search", None)), (
        "CodexOAuthAdapter.supports_web_search=True must be backed by a "
        "callable ``aweb_search`` method — dispatch skips flag-set / "
        "method-missing adapters with a warning."
    )
    src = inspect.getsource(CodexOAuthAdapter)
    assert "verified live" in src, (
        "CodexOAuthAdapter.supports_web_search=True must carry the "
        "``verified live`` attestation per CLAUDE.md §4d (doc-before-"
        "behaviour). PR-CODEX-INSTRUCTIONS-FIX (2026-05-28) flipped the "
        "docstring from ``unverified`` after the Codex backend returned "
        "200 OK with real web search results."
    )


# ---------------------------------------------------------------------------
# web_search_via_adapters — strict single-adapter semantics (PR-NO-FALLBACK)
# ---------------------------------------------------------------------------


def test_web_search_via_adapters_returns_selected_adapter_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubWebSearchAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="ok"
            ),
            _StubWebSearchAdapter(name="openai-payg", provider="openai", source="payg", mode="ok"),
        ],
    )
    result = asyncio.run(web_search_via_adapters("test query"))
    # Strict default-resolved: first provider in DEFAULT_PROVIDER_ORDER
    # whose infer_source matches a registered adapter — anthropic-payg.
    assert result.adapter_name == "anthropic-payg"


def test_web_search_via_adapters_raises_dispatch_error_on_transient_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-NO-FALLBACK — a NON-connection transient (the stub raises a bare
    ``RuntimeError``) on the selected adapter raises
    :class:`AdapterDispatchError` immediately, with no retry of any kind.
    No silent fallback to another provider either; the operator must switch
    source explicitly via ``/login``. Connection-class transients get one
    bounded same-adapter retry — see
    ``test_dispatch_transient_retry_guardrails.py``."""
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubWebSearchAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="transient"
            ),
            # openai-payg present + healthy, but dispatch must NOT use it
            # as a fallback — the strict-single-adapter contract requires
            # the operator to switch source explicitly.
            _StubWebSearchAdapter(name="openai-payg", provider="openai", source="payg", mode="ok"),
        ],
    )
    with pytest.raises(AdapterDispatchError, match=r"anthropic-payg .*failed"):
        asyncio.run(web_search_via_adapters("test query"))


def test_web_search_via_adapters_raises_billing_on_selected_adapter_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-NO-FALLBACK — billing-fatal on the selected adapter surfaces
    :class:`BillingError` immediately with adapter context, even when
    other healthy adapters are registered."""
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubWebSearchAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="billing"
            ),
            _StubWebSearchAdapter(name="openai-payg", provider="openai", source="payg", mode="ok"),
            _StubWebSearchAdapter(name="glm-payg", provider="glm", source="payg", mode="ok"),
        ],
    )
    with pytest.raises(BillingError, match=r"anthropic-payg .* credit exhausted"):
        asyncio.run(web_search_via_adapters("test"))


def test_web_search_via_adapters_raises_unavailable_with_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(monkeypatch, [])
    with pytest.raises(AdapterUnavailableError, match="no adapter registered"):
        asyncio.run(web_search_via_adapters("test"))


def test_web_search_via_adapters_raises_unavailable_when_prefer_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-NO-FALLBACK — when ``prefer_provider`` + ``prefer_source`` are
    given (from AgenticLoop's ToolContext) and no registered adapter
    matches both exactly, dispatch refuses to widen — raises
    :class:`AdapterUnavailableError` so the operator switches explicitly."""
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubWebSearchAdapter(name="openai-payg", provider="openai", source="payg", mode="ok"),
        ],
    )
    with pytest.raises(AdapterUnavailableError, match="no adapter registered matching"):
        asyncio.run(
            web_search_via_adapters(
                "test",
                prefer_provider="anthropic",
                prefer_source="subscription",
            )
        )


def test_web_search_via_adapters_prefer_exact_match_routes_to_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the AgenticLoop's adapter is anthropic-oauth, dispatch must
    route web_search to anthropic-oauth — even though anthropic-payg is
    also registered and would be the default-resolved pick."""
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubWebSearchAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="ok"
            ),
            _StubWebSearchAdapter(
                name="anthropic-oauth",
                provider="anthropic",
                source="subscription",
                mode="ok",
            ),
        ],
    )
    result = asyncio.run(
        web_search_via_adapters("test", prefer_provider="anthropic", prefer_source="subscription")
    )
    assert result.adapter_name == "anthropic-oauth"


def test_web_search_via_adapters_default_uses_infer_source_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no preference, dispatch picks the adapter whose source equals
    ``infer_source(provider)`` for the first provider in provider_order
    that has a capable adapter. ``infer_source`` returning ``subscription``
    for anthropic → anthropic-oauth is the selected adapter."""
    monkeypatch.setattr(
        "core.llm.adapters._source_inference.infer_source",
        lambda provider: "subscription" if provider == "anthropic" else "payg",
    )
    _install_stubs(
        monkeypatch,
        [
            _StubWebSearchAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="ok"
            ),
            _StubWebSearchAdapter(
                name="anthropic-oauth",
                provider="anthropic",
                source="subscription",
                mode="ok",
            ),
        ],
    )
    result = asyncio.run(web_search_via_adapters("test"))
    assert result.adapter_name == "anthropic-oauth"


# ---------------------------------------------------------------------------
# complete_text_via_adapters — mirror semantics
# ---------------------------------------------------------------------------


def test_complete_text_via_adapters_returns_first_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubTextCompletionAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="ok"
            ),
        ],
    )
    result = asyncio.run(complete_text_via_adapters("prompt", system="sys"))
    assert "completed by anthropic-payg" in result.text


def test_complete_text_via_adapters_provider_order_picks_first_capable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-NO-FALLBACK — caller-supplied ``provider_order`` is the *preference
    seed* for the operator-default-resolved path. Dispatch picks the first
    provider in the order with a registered capable adapter, then tries
    only that single adapter (no fallback on failure)."""
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubTextCompletionAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="ok"
            ),
            _StubTextCompletionAdapter(
                name="openai-payg", provider="openai", source="payg", mode="ok"
            ),
        ],
    )
    result = asyncio.run(
        complete_text_via_adapters("prompt", provider_order=("openai", "anthropic", "glm"))
    )
    assert result.text.endswith("openai-payg")


def test_complete_text_via_adapters_raises_billing_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-NO-FALLBACK — billing-fatal on the selected adapter raises
    :class:`BillingError` immediately even when other healthy adapters
    are registered."""
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubTextCompletionAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="billing"
            ),
            _StubTextCompletionAdapter(
                name="openai-payg", provider="openai", source="payg", mode="ok"
            ),
        ],
    )
    with pytest.raises(BillingError, match=r"anthropic-payg .* credit exhausted"):
        asyncio.run(complete_text_via_adapters("prompt"))


# ---------------------------------------------------------------------------
# Source-level pins — tools delegate to dispatch helpers (no direct SDKs)
# ---------------------------------------------------------------------------


def test_web_tools_general_web_search_delegates_to_dispatch() -> None:
    src = (Path(__file__).resolve().parents[3] / "core" / "tools" / "web_tools.py").read_text(
        encoding="utf-8"
    )
    # The legacy 3-provider direct-SDK chain must be gone.
    assert "_anthropic_search" not in src, (
        "web_tools.py still defines the legacy ``_anthropic_search`` method — "
        "tools should delegate to ``web_search_via_adapters`` instead."
    )
    assert "import anthropic" not in src and "openai.OpenAI(" not in src, (
        "web_tools.py still imports provider SDKs directly — that bypasses "
        "the adapter registry and breaks operator settings-driven switching."
    )
    assert "web_search_via_adapters" in src, (
        "web_tools.py no longer calls the central dispatch helper."
    )


def test_web_search_legacy_tool_delegates_to_dispatch() -> None:
    src = (Path(__file__).resolve().parents[3] / "core" / "tools" / "web_search.py").read_text(
        encoding="utf-8"
    )
    assert "_anthropic_search" not in src, "web_search.py still has legacy direct-SDK chain"
    assert "web_search_via_adapters" in src


def test_compaction_uses_dispatch_helper() -> None:
    src = (
        Path(__file__).resolve().parents[3] / "core" / "orchestration" / "compaction.py"
    ).read_text(encoding="utf-8")
    # Check the FUNCTION DEFINITIONS are gone — not just any substring (the
    # explanatory docstring on the migrated dispatcher mentions the old
    # names by design).
    assert "def _summarize_openai(" not in src and "def _summarize_glm(" not in src, (
        "compaction.py still defines provider-specific summarisation helpers; "
        "the registry's text-completion capability should be the single dispatch path."
    )
    assert "complete_text_via_adapters" in src
