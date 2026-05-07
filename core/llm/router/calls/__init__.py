"""LLM call functions — provider-aware dispatching and failover loops.

This is the transport layer: ``call_with_failover`` (async failover for
AgenticLoop), ``_route_provider`` (Plan-aware provider resolution), and the
five sync entry points ``call_llm`` / ``call_llm_parsed`` / ``call_llm_json`` /
``call_llm_with_tools`` / ``call_llm_streaming``.

All five entry points share the same shape: resolve provider, fire
LLM_CALL_START, dispatch to Anthropic SDK or OpenAI-compatible SDK, record
usage, fire LLM_CALL_END (with error or latency). Cross-provider fallback
runs through ``_cross_provider_dispatch`` so a 5xx on Anthropic can flow to
OpenAI without each call site re-implementing the chain.

Each entry point lives in its own leaf sub-module for SRP and testability.
Tests that need to monkeypatch a provider client (``get_anthropic_client``,
``_get_provider_client``) must target the sub-module that imports it
(e.g. ``core.llm.router.calls.text.get_anthropic_client`` for ``call_llm``).
"""

from __future__ import annotations

from ._failover import call_with_failover as call_with_failover
from ._route import _route_provider as _route_provider
from .json import call_llm_json as call_llm_json
from .parsed import call_llm_parsed as call_llm_parsed
from .streaming import call_llm_streaming as call_llm_streaming
from .text import call_llm as call_llm
from .tools import call_llm_with_tools as call_llm_with_tools
