"""Regression — single SOT for retry policy across providers (GAP-E1).

Pre-fix: ``core/llm/providers/openai.py`` defined ``_MAX_RETRIES`` /
``_RETRY_BASE_DELAY`` / ``_RETRY_MAX_DELAY`` and passed them explicitly to
``retry_with_backoff_generic``, which pinned OpenAI/GLM retry behavior to
the hardcoded ``3`` regardless of ``settings.llm_max_retries`` /
``settings.llm_retry_base_delay`` / ``settings.llm_retry_max_delay``.

Post-fix: the adapter no longer pins these arguments. ``retry_with_backoff_generic``
resolves them from ``core.config.settings`` lazily, restoring the single
source of truth shared with the Anthropic path.
"""

from __future__ import annotations

from typing import Any

import core.llm.providers.openai as openai_provider
from core.llm.providers.openai import OpenAIAdapter


def test_openai_adapter_does_not_pin_retry_constants(monkeypatch: Any) -> None:
    """OpenAIAdapter._retry_with_backoff must leave retry knobs unset so
    fallback.py resolves them from ``settings.llm_*``.
    """
    captured: dict[str, Any] = {}

    def _fake_generic(fn: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return fn(model=kwargs["model"])

    monkeypatch.setattr(openai_provider, "retry_with_backoff_generic", _fake_generic)

    adapter = OpenAIAdapter()
    result = adapter._retry_with_backoff(lambda model: "ok", model="gpt-5.5")

    assert result == "ok"
    # GAP-E1 regression: None → fallback.py reads ``settings.llm_*``
    assert captured.get("max_retries") is None
    assert captured.get("retry_base_delay") is None
    assert captured.get("retry_max_delay") is None


def test_module_no_local_retry_constants() -> None:
    """The local retry constants must not return — they bypass the SOT.

    If a future refactor reintroduces module-local retry knobs, this
    regression test will fail before the issue ships.
    """
    assert not hasattr(openai_provider, "_MAX_RETRIES")
    assert not hasattr(openai_provider, "_RETRY_BASE_DELAY")
    assert not hasattr(openai_provider, "_RETRY_MAX_DELAY")
