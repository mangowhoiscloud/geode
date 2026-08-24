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

import pytest


def test_529_overloaded_class_is_sibling_of_internal_server_error() -> None:
    """``OverloadedError`` (Anthropic status 529) inherits from
    ``APIStatusError`` directly — it is NOT a subclass of
    ``InternalServerError``. This is the exact bug P1a fixes: the
    initial RETRYABLE_ERRORS tuple assumed any 5xx → InternalServerError
    and therefore omitted OverloadedError, silently failing every 529.

    Regression guard: if a future SDK release ever makes OverloadedError
    inherit from InternalServerError, this test will fail and the tuple
    can drop the now-redundant entry.
    """
    from anthropic import APIStatusError, InternalServerError
    from anthropic._exceptions import OverloadedError

    assert issubclass(OverloadedError, APIStatusError)
    assert not issubclass(OverloadedError, InternalServerError)
    assert OverloadedError.status_code == 529


def test_anthropic_retryable_errors_contains_overloaded_error() -> None:
    """The retry tuple must include OverloadedError (status 529) so
    capacity-dip responses get the exponential backoff treatment instead
    of bubbling up as a non-retryable error.

    Regression guard against accidental removal during future refactors —
    closes the audit doc's "529 Overloaded retry 정책 미정" gap."""
    import core.llm.providers.anthropic as anthropic_provider
    from anthropic._exceptions import OverloadedError

    assert OverloadedError in anthropic_provider.RETRYABLE_ERRORS


def test_anthropic_retryable_errors_contains_internal_server_error() -> None:
    """The retry tuple must include InternalServerError (which catches
    500/502/503/504 — every 5xx EXCEPT 529 which has its own class)."""
    import anthropic
    import core.llm.providers.anthropic as anthropic_provider

    assert anthropic.InternalServerError in anthropic_provider.RETRYABLE_ERRORS


@pytest.mark.parametrize(
    "error_type",
    ["InternalServerError", "RateLimitError", "OverloadedError"],
)
def test_retry_activity_emits_run_event(
    monkeypatch: Any,
    tmp_path: Any,
    error_type: str,
) -> None:
    """The injected retry sink preserves the existing llm_retry projection."""
    import json

    import core.paths
    from core.llm.providers.anthropic import _emit_retry_activity
    from evals.run_timeline import (
        RunTimeline,
        current_run_timeline,
        run_timeline_scope,
    )

    monkeypatch.setattr(core.paths, "GLOBAL_AUTORESEARCH_HANDOFF_DIR", tmp_path)
    journal = RunTimeline(
        session_id="s-retry",
        gen_tag="gen-retry",
        component="autoresearch",
    )
    with run_timeline_scope(journal):
        _emit_retry_activity(
            current_run_timeline,
            model="claude-opus-4-7",
            attempt=2,
            max_retries=5,
            delay_s=1.234,
            elapsed_s=3.45,
            error_type=error_type,
        )

    record = json.loads((tmp_path / "s-retry" / "events.jsonl").read_text())
    assert record["event"] == "llm_retry"
    assert record["level"] == "warn"
    assert record["payload"] == {
        "provider": "anthropic",
        "model": "claude-opus-4-7",
        "attempt": 2,
        "max_retries": 5,
        "delay_s": 1.234,
        "elapsed_s": 3.45,
        "error_type": error_type,
    }


def test_retry_activity_noops_without_sink() -> None:
    from core.llm.providers.anthropic import _emit_retry_activity

    _emit_retry_activity(
        lambda: None,
        model="claude-opus-4-7",
        attempt=1,
        max_retries=5,
        delay_s=0.5,
        elapsed_s=0.5,
        error_type="APIConnectionError",
    )


def test_anthropic_retry_path_wires_activity_callback(monkeypatch: Any) -> None:
    from pathlib import Path

    from core.config.policy_source import PolicySourcePaths

    captured: dict[str, Any] = {}
    routing_sources = PolicySourcePaths(
        override_env="GEODE_TEST_ROUTING_OVERRIDE",
        packaged_default=Path("routing.json"),
    )

    async def _fake_async(fn: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return "ok"

    import asyncio

    import core.llm.providers.anthropic as anthropic_provider

    monkeypatch.setattr(
        anthropic_provider,
        "retry_with_backoff_generic_async",
        _fake_async,
    )
    asyncio.run(
        anthropic_provider.retry_with_backoff_async(
            lambda model: "x",
            model="claude-opus-4-7",
            activity_sink_provider=lambda: None,
            routing_sources=routing_sources,
        )
    )
    assert callable(captured.get("on_retry"))
    assert captured["routing_sources"] is routing_sources
