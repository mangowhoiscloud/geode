"""Guardrails for PR-DISPATCH-TRANSIENT-RETRY (2026-06-11).

Operator-reported incident (serve.log 2026-06-10 22:08 / 22:48 / 22:51): a
broken pooled httpx connection in the long-lived serve daemon failed the
next ``web_search`` dispatch in ~2-4ms as ``APIConnectionError`` while
sibling calls on fresh connections succeeded in 27-50s. Adapter-owned
clients run with ``max_retries=0`` (``_anthropic_common.py``), and
``web_search_via_adapters`` / ``complete_text_via_adapters`` had no retry
of their own, so one poisoned connection killed an entire parallel
tool-search batch member with no recovery.

These tests pin the repaired contract so adapter/model additions and
client-construction changes cannot silently regress it:

1. Connection-class transient → exactly ONE bounded same-adapter retry,
   then success or :class:`AdapterDispatchError`.
2. The retry NEVER crosses adapters — PR-NO-FALLBACK (2026-05-28) intact:
   a healthy sibling adapter is never touched.
3. Billing / billing-fatal errors are NEVER retried.
4. Non-connection transients (schema mismatch etc.) are NEVER retried.
5. A parallel batch with one poisoned-connection member fully recovers.
6. Real SDK/transport exception classes (``anthropic.APIConnectionError``,
   ``httpx.ReadError``, cause-chain wrapping) classify as
   connection-transient — guards SDK upgrades renaming the surface.
7. Error messages + ``AdapterAttempt`` rows carry the transport-level
   cause chain (previously swallowed by the SDK's generic wrapper).
8. Registry-wide capability parity ratchet: every builtin adapter that
   advertises a ``supports_*`` capability backs it with a coroutine
   method — a NEW adapter/model wired into ``bootstrap_builtins`` is
   automatically covered, so flag-without-method drift fails here
   instead of being silently dropped by ``_select_adapter``.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import anthropic
import httpx
import pytest
from core.llm.adapters.base import TextCompletionResult, UsageSummary, WebSearchResult
from core.llm.adapters.dispatch import (
    _CAPABILITY_METHOD,
    _CONNECTION_TRANSIENT_ERROR_NAMES,
    _CONNECTION_TRANSIENT_RETRIES,
    AdapterDispatchError,
    _is_connection_transient,
    complete_text_via_adapters,
    web_search_via_adapters,
)
from core.llm.errors import BillingError


class APIConnectionError(Exception):
    """Stand-in matched by NAME — same matching rule production uses, so a
    locally defined class with the SDK's class name exercises the policy
    without constructing real SDK request objects in every test."""


# ---------------------------------------------------------------------------
# Stub adapters
# ---------------------------------------------------------------------------


class _FlakyWebSearchAdapter:
    """Fails the first ``fail_first_n`` calls, then succeeds — models a
    poisoned pooled connection that a reconnect clears."""

    supports_web_search: bool = True

    def __init__(
        self,
        *,
        name: str = "anthropic-payg",
        provider: str = "anthropic",
        source: str = "payg",
        fail_first_n: int = 1,
        error_factory: Any = None,
    ) -> None:
        self.name = name
        self.provider = provider
        self.source = source
        self.calls = 0
        self._fail_first_n = fail_first_n
        self._error_factory = error_factory or self._default_error

    @staticmethod
    def _default_error() -> Exception:
        exc = APIConnectionError("Connection error.")
        exc.__cause__ = httpx.ReadError("peer closed connection")
        return exc

    async def aweb_search(self, query: str, *, max_results: int = 5) -> WebSearchResult:
        self.calls += 1
        if self.calls <= self._fail_first_n:
            raise self._error_factory()
        return WebSearchResult(
            query=query, text=f"results from {self.name}", adapter_name=self.name
        )


class _FlakyTextCompletionAdapter:
    supports_text_completion: bool = True

    def __init__(self, *, fail_first_n: int = 1) -> None:
        self.name = "anthropic-payg"
        self.provider = "anthropic"
        self.source = "payg"
        self.calls = 0
        self._fail_first_n = fail_first_n

    async def acomplete_text(
        self, prompt: str, *, system: str = "", model: str = "", max_tokens: int = 1024
    ) -> TextCompletionResult:
        self.calls += 1
        if self.calls <= self._fail_first_n:
            raise APIConnectionError("Connection error.")
        return TextCompletionResult(
            text=f"completed by {self.name}",
            usage=UsageSummary(input_tokens=1, output_tokens=2),
        )


class _CountingBillingAdapter:
    supports_web_search: bool = True

    def __init__(self) -> None:
        self.name = "anthropic-payg"
        self.provider = "anthropic"
        self.source = "payg"
        self.calls = 0

    async def aweb_search(self, query: str, *, max_results: int = 5) -> WebSearchResult:
        self.calls += 1
        raise BillingError("stub billing", provider=self.provider, plan_display_name=self.name)


class _HealthySiblingAdapter:
    supports_web_search: bool = True

    def __init__(self) -> None:
        self.name = "openai-payg"
        self.provider = "openai"
        self.source = "payg"
        self.calls = 0

    async def aweb_search(self, query: str, *, max_results: int = 5) -> WebSearchResult:
        self.calls += 1
        return WebSearchResult(query=query, text="sibling", adapter_name=self.name)


def _install_stubs(monkeypatch: pytest.MonkeyPatch, stubs: list[Any]) -> None:
    monkeypatch.setattr("core.llm.adapters.dispatch.list_adapters", lambda: stubs)


def _force_payg_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.llm.adapters._source_inference.infer_source", lambda provider: "payg")


def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero out the retry backoff so tests stay instant."""

    async def _instant(_delay: float) -> None:
        return None

    monkeypatch.setattr("core.llm.adapters.dispatch.asyncio.sleep", _instant)


# ---------------------------------------------------------------------------
# 1-2. Bounded same-adapter retry — success path + adapter isolation
# ---------------------------------------------------------------------------


def test_connection_transient_retries_same_adapter_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_payg_first(monkeypatch)
    _no_backoff(monkeypatch)
    flaky = _FlakyWebSearchAdapter(fail_first_n=1)
    sibling = _HealthySiblingAdapter()
    _install_stubs(monkeypatch, [flaky, sibling])

    result = asyncio.run(web_search_via_adapters("test query"))

    assert result.adapter_name == "anthropic-payg"
    assert flaky.calls == 2, "exactly one retry on the SAME adapter"
    assert sibling.calls == 0, "PR-NO-FALLBACK: healthy sibling must never be touched"


def test_connection_transient_retry_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A persistently broken connection exhausts the bounded retry and
    raises — no infinite loop, no adapter switch."""
    _force_payg_first(monkeypatch)
    _no_backoff(monkeypatch)
    flaky = _FlakyWebSearchAdapter(fail_first_n=99)
    sibling = _HealthySiblingAdapter()
    _install_stubs(monkeypatch, [flaky, sibling])

    with pytest.raises(AdapterDispatchError, match=r"anthropic-payg .*failed"):
        asyncio.run(web_search_via_adapters("test query"))

    assert flaky.calls == _CONNECTION_TRANSIENT_RETRIES + 1
    assert sibling.calls == 0


def test_retry_fires_transient_attempt_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Observability pin — each failed try fires a ``transient`` attempt row
    and the recovered call fires ``success``, so serve logs show the full
    retry trace instead of a silent recovery."""
    _force_payg_first(monkeypatch)
    _no_backoff(monkeypatch)
    outcomes: list[str] = []
    monkeypatch.setattr(
        "core.llm.adapters.dispatch._fire_attempt",
        lambda attempt: outcomes.append(attempt.outcome),
    )
    _install_stubs(monkeypatch, [_FlakyWebSearchAdapter(fail_first_n=1)])

    asyncio.run(web_search_via_adapters("test query"))

    assert outcomes == ["transient", "success"]


# ---------------------------------------------------------------------------
# 3-4. Never retried: billing + non-connection transients
# ---------------------------------------------------------------------------


def test_billing_error_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_payg_first(monkeypatch)
    billing = _CountingBillingAdapter()
    _install_stubs(monkeypatch, [billing])

    with pytest.raises(BillingError):
        asyncio.run(web_search_via_adapters("test query"))

    assert billing.calls == 1, "billing-fatal must surface immediately — never retried"


def test_billing_fatal_wins_over_connection_error_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even an exception whose class name is connection-transient must NOT be
    retried when :func:`is_billing_fatal` classifies it as billing —
    billing honesty outranks the connection heuristic."""
    _force_payg_first(monkeypatch)
    monkeypatch.setattr("core.llm.adapters.dispatch.is_billing_fatal", lambda exc: True)
    flaky = _FlakyWebSearchAdapter(fail_first_n=99)
    _install_stubs(monkeypatch, [flaky])

    with pytest.raises(BillingError):
        asyncio.run(web_search_via_adapters("test query"))

    assert flaky.calls == 1


def test_non_connection_transient_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """Schema mismatches / programming errors fail fast — retry is reserved
    for connection-class transport errors only."""
    _force_payg_first(monkeypatch)
    flaky = _FlakyWebSearchAdapter(
        fail_first_n=99, error_factory=lambda: RuntimeError("schema mismatch")
    )
    _install_stubs(monkeypatch, [flaky])

    with pytest.raises(AdapterDispatchError):
        asyncio.run(web_search_via_adapters("test query"))

    assert flaky.calls == 1


# ---------------------------------------------------------------------------
# 5. Parallel batch contract — one poisoned connection, whole batch recovers
# ---------------------------------------------------------------------------


def test_parallel_batch_recovers_from_one_poisoned_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The incident shape: N concurrent web_search calls share an adapter;
    the first call lands on a broken pooled connection and insta-fails.
    Post-fix the whole batch must succeed (the poisoned member retries on a
    fresh connection)."""
    _force_payg_first(monkeypatch)
    _no_backoff(monkeypatch)
    flaky = _FlakyWebSearchAdapter(fail_first_n=1)
    _install_stubs(monkeypatch, [flaky])

    async def _batch() -> list[WebSearchResult]:
        return list(
            await asyncio.gather(*(web_search_via_adapters(f"query {i}") for i in range(4)))
        )

    results = asyncio.run(_batch())

    assert len(results) == 4
    assert all(r.adapter_name == "anthropic-payg" for r in results)
    assert flaky.calls == 5, "4 successes + 1 retried poisoned-connection failure"


# ---------------------------------------------------------------------------
# 6. Real exception-class classification — guards SDK / transport upgrades
# ---------------------------------------------------------------------------


def test_real_anthropic_and_httpx_errors_classify_as_connection_transient() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    sdk_exc = anthropic.APIConnectionError(request=request)
    assert _is_connection_transient(sdk_exc), (
        "anthropic.APIConnectionError must classify as connection-transient — "
        "if this fails after an SDK upgrade, the class was renamed and "
        "_CONNECTION_TRANSIENT_ERROR_NAMES needs the new name"
    )
    assert _is_connection_transient(httpx.ReadError("peer closed connection"))
    assert _is_connection_transient(httpx.ConnectError("connect failed"))

    wrapped = RuntimeError("adapter wrapper")
    wrapped.__cause__ = httpx.ReadError("root cause")
    assert _is_connection_transient(wrapped), "cause chain must be traversed"

    assert not _is_connection_transient(RuntimeError("schema mismatch"))
    assert not _is_connection_transient(ValueError("bad arg"))


def test_retry_policy_invariants() -> None:
    assert _CONNECTION_TRANSIENT_RETRIES >= 1, (
        "adapter-owned clients run with max_retries=0 (_anthropic_common.py) "
        "— the dispatch layer MUST own at least one connection-transient "
        "retry or the 2026-06-10 poisoned-pooled-connection incident returns"
    )
    assert "BillingError" not in _CONNECTION_TRANSIENT_ERROR_NAMES
    assert "APIStatusError" not in _CONNECTION_TRANSIENT_ERROR_NAMES, (
        "HTTP status errors carry server verdicts (4xx/5xx) — they are not "
        "connection-class and must not be blanket-retried here"
    )


# ---------------------------------------------------------------------------
# 7. Cause-chain observability
# ---------------------------------------------------------------------------


def test_dispatch_error_message_carries_transport_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-fix the operator saw only ``APIConnectionError: Connection error.``
    — the httpx root cause was swallowed. The error message must now name
    the transport-level cause."""
    _force_payg_first(monkeypatch)
    _no_backoff(monkeypatch)
    _install_stubs(monkeypatch, [_FlakyWebSearchAdapter(fail_first_n=99)])

    with pytest.raises(AdapterDispatchError) as excinfo:
        asyncio.run(web_search_via_adapters("test query"))

    message = str(excinfo.value)
    assert "APIConnectionError" in message
    assert "ReadError" in message, "transport root cause must appear in the message"
    attempt = excinfo.value.attempt
    assert attempt is not None
    assert "ReadError" in attempt.error_msg


# ---------------------------------------------------------------------------
# complete_text mirrors the same contract (compaction / reflection path)
# ---------------------------------------------------------------------------


def test_complete_text_retries_connection_transient_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """serve.log 2026-06-10 22:51 — reflection calls (complete_text path)
    insta-failed on the same poisoned connection. The mirror retry must
    recover them too."""
    _force_payg_first(monkeypatch)
    _no_backoff(monkeypatch)
    flaky = _FlakyTextCompletionAdapter(fail_first_n=1)
    _install_stubs(monkeypatch, [flaky])

    result = asyncio.run(complete_text_via_adapters("prompt"))

    assert result.text == "completed by anthropic-payg"
    assert flaky.calls == 2


def test_both_dispatch_paths_share_the_retry_policy() -> None:
    """Drift invariant — the two dispatch coroutines must keep using the
    shared retry constant; a refactor that drops one silently reopens the
    incident for that path."""
    for fn in (web_search_via_adapters, complete_text_via_adapters):
        src = inspect.getsource(fn)
        assert "_CONNECTION_TRANSIENT_RETRIES" in src, fn.__name__
        assert "_is_connection_transient" in src, fn.__name__


# ---------------------------------------------------------------------------
# 8. Registry-wide capability parity ratchet — adapter/model additions
# ---------------------------------------------------------------------------


def test_every_builtin_adapter_backs_advertised_capabilities_with_coroutines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parity ratchet over the REAL builtin set. ``_select_adapter`` silently
    drops a flag-set / method-missing adapter (warning only), so a new
    adapter wired into ``bootstrap_builtins`` with a capability flag but no
    method would disappear from dispatch without an error anywhere — this
    test turns that drift into a hard failure. Covers future adapters
    automatically because it iterates ``bootstrap_builtins`` output."""
    from core.llm.adapters import registry as registry_mod

    monkeypatch.setattr(registry_mod, "_REGISTRY", {})
    registry_mod.bootstrap_builtins()
    adapters = registry_mod.list_adapters()
    assert len(adapters) >= 8, "builtin set shrank — update bootstrap_builtins or this ratchet"

    for adapter in adapters:
        assert adapter.name and adapter.provider and adapter.source
        for capability_flag, method_name in _CAPABILITY_METHOD.items():
            if not getattr(adapter, capability_flag, False):
                continue
            method = getattr(adapter, method_name, None)
            assert callable(method), (
                f"{adapter.name}: {capability_flag}=True but no callable "
                f"{method_name} — dispatch would silently drop this adapter"
            )
            assert inspect.iscoroutinefunction(method), (
                f"{adapter.name}.{method_name} must be a coroutine function"
            )
