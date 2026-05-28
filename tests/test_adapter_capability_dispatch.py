"""Regression pin for PR-ADAPTER-PATTERN-UNIFICATION (2026-05-28).

The capability-based dispatch layer (``core/llm/adapters/dispatch.py``)
centralises web_search and text-completion fan-out so tools never bypass
the adapter registry with hardcoded PAYG clients. These tests pin:

1. ``WebSearchCapable`` / ``TextCompletionCapable`` mixin Protocols are
   defined and runtime-checkable on the canonical adapters.
2. ``web_search_via_adapters`` raises :class:`AdapterDispatchError` when
   the registry has no capable adapter, raises :class:`BillingError` when
   every candidate hit billing-fatal, and returns the first successful
   :class:`WebSearchResult` otherwise.
3. ``complete_text_via_adapters`` mirrors the same semantics for the
   text-completion capability.
4. Source preference honours the same :func:`infer_source` flow as the
   agent loop main path — subscription-promoted operators see subscription
   adapters before PAYG.
5. ``GeneralWebSearchTool`` + ``WebSearchTool`` no longer carry direct SDK
   client imports (source-level pin) — they delegate to the dispatch
   helper instead.

Live HTTP is not required — adapters are monkey-patched with stub
``aweb_search`` / ``acomplete_text`` implementations that return canned
results or raise the desired error class.
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


def test_codex_oauth_adapter_does_not_advertise_web_search() -> None:
    """Codex backend (chatgpt.com) web_search support unconfirmed (frontier
    audit 2026-05-28). Adapter must not advertise the capability so the
    dispatch layer skips it instead of attempting + failing."""
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter

    adapter = CodexOAuthAdapter()
    assert not getattr(adapter, "supports_web_search", False), (
        "CodexOAuthAdapter accidentally advertises supports_web_search; "
        "the dispatch layer will try it and fail on Codex backend's "
        "lack of web_search tool support."
    )


# ---------------------------------------------------------------------------
# web_search_via_adapters — fallback chain semantics
# ---------------------------------------------------------------------------


def test_web_search_via_adapters_returns_first_success(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert result.adapter_name == "anthropic-payg"  # first in provider_order


def test_web_search_via_adapters_falls_through_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubWebSearchAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="transient"
            ),
            _StubWebSearchAdapter(name="openai-payg", provider="openai", source="payg", mode="ok"),
        ],
    )
    result = asyncio.run(web_search_via_adapters("test query"))
    assert result.adapter_name == "openai-payg"


def test_web_search_via_adapters_raises_billing_when_all_billing_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduces the operator's PAYG-everywhere outage: all 3 providers
    return billing-fatal → single :class:`BillingError` instead of N
    silent retries."""
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubWebSearchAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="billing"
            ),
            _StubWebSearchAdapter(
                name="openai-payg", provider="openai", source="payg", mode="billing"
            ),
            _StubWebSearchAdapter(name="glm-payg", provider="glm", source="payg", mode="billing"),
        ],
    )
    with pytest.raises(BillingError):
        asyncio.run(web_search_via_adapters("test"))


def test_web_search_via_adapters_raises_dispatch_error_with_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(monkeypatch, [])
    with pytest.raises(AdapterDispatchError, match="no registered adapter"):
        asyncio.run(web_search_via_adapters("test"))


def test_web_search_via_adapters_raises_dispatch_error_when_all_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_payg_first(monkeypatch)
    _install_stubs(
        monkeypatch,
        [
            _StubWebSearchAdapter(
                name="anthropic-payg", provider="anthropic", source="payg", mode="transient"
            ),
            _StubWebSearchAdapter(
                name="openai-payg", provider="openai", source="payg", mode="transient"
            ),
        ],
    )
    with pytest.raises(AdapterDispatchError, match=r"all .* adapters failed"):
        asyncio.run(web_search_via_adapters("test"))


def test_web_search_subscription_promoted_when_infer_source_is_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When :func:`infer_source` returns ``"subscription"`` for a provider,
    subscription-source adapters land before PAYG within that provider."""
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


def test_complete_text_via_adapters_provider_order_overrides_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller-supplied ``provider_order`` floats the requested provider
    to the front (mirrors compaction's per-call provider intent)."""
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


# ---------------------------------------------------------------------------
# Source-level pins — tools delegate to dispatch helpers (no direct SDKs)
# ---------------------------------------------------------------------------


def test_web_tools_general_web_search_delegates_to_dispatch() -> None:
    src = (Path(__file__).resolve().parents[1] / "core" / "tools" / "web_tools.py").read_text(
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
    src = (Path(__file__).resolve().parents[1] / "core" / "tools" / "web_search.py").read_text(
        encoding="utf-8"
    )
    assert "_anthropic_search" not in src, "web_search.py still has legacy direct-SDK chain"
    assert "web_search_via_adapters" in src


def test_compaction_uses_dispatch_helper() -> None:
    src = (
        Path(__file__).resolve().parents[1] / "core" / "orchestration" / "compaction.py"
    ).read_text(encoding="utf-8")
    # Check the FUNCTION DEFINITIONS are gone — not just any substring (the
    # explanatory docstring on the migrated dispatcher mentions the old
    # names by design).
    assert "def _summarize_openai(" not in src and "def _summarize_glm(" not in src, (
        "compaction.py still defines provider-specific summarisation helpers; "
        "the registry's text-completion capability should be the single dispatch path."
    )
    assert "complete_text_via_adapters" in src
