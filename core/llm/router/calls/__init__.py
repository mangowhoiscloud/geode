"""LLM call functions — provider-aware dispatching and failover loops.

This is the transport layer: ``call_with_failover`` (async failover for
AgenticLoop), ``_route_provider`` (Plan-aware provider resolution), and the
synchronous text entry point ``call_llm``.

``call_llm`` resolves the provider, fires LLM_CALL_START, dispatches to the
Anthropic SDK or an OpenAI-compatible SDK, records usage, and fires
LLM_CALL_END (with error or latency). ``call_with_failover`` iterates a
supplied model list applying per-model retry/backoff and emits LLM_CALL_RETRIED
on each retry. Provider-internal fallback stays inside the selected provider's
retry chain.

Each entry point lives in its own leaf sub-module for SRP and testability.
Tests that need to monkeypatch a provider client (``get_anthropic_client``,
``_get_provider_client``) must target the sub-module that imports it
(e.g. ``core.llm.router.calls.text.get_anthropic_client`` for ``call_llm``).
"""

from __future__ import annotations

from ._failover import call_with_failover as call_with_failover
from ._route import _route_provider as _route_provider
from .text import call_llm as call_llm
