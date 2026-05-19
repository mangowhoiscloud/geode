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


# ---------------------------------------------------------------------------
# P1a — 529 Overloaded retry classification (audit §4 row)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# P1a — llm_retry journal emit
# ---------------------------------------------------------------------------


def test_on_retry_emits_journal_event(monkeypatch: Any) -> None:
    """The ``on_retry`` callback wired into retry_with_backoff_generic must
    append an ``llm_retry`` event to the active SessionJournal so silent
    retries (esp. 529 Overloaded) become observable."""
    import json
    from pathlib import Path

    import core.paths
    from core.llm.providers.anthropic import _on_retry_journal_emit

    from core.observability import SessionJournal, session_journal_scope

    # Redirect journal writes into a tmp dir without touching real
    # ~/.geode/self-improving-loop/.
    tmp_root = Path("/tmp") / "p1a-journal-test"  # noqa: S108 - test scope only
    # NOTE: tmp_path fixture is unavailable in this function signature
    # (avoid renumbering the existing tests' imports). Use mkdtemp instead.
    import shutil
    import tempfile

    real_tmp = Path(tempfile.mkdtemp(prefix="p1a-journal-"))
    monkeypatch.setattr(core.paths, "GLOBAL_SELF_IMPROVING_LOOP_DIR", real_tmp)
    try:
        journal = SessionJournal(
            session_id="s-retry",
            gen_tag="gen-retry",
            component="autoresearch",
        )
        with session_journal_scope(journal):
            _on_retry_journal_emit(
                model="claude-opus-4-7",
                attempt=2,
                max_retries=5,
                delay_s=1.234,
                elapsed_s=3.45,
                error_type="InternalServerError",
            )
        rows = (real_tmp / "s-retry" / "journal.jsonl").read_text().splitlines()
        assert len(rows) == 1
        record = json.loads(rows[0])
        assert record["event"] == "llm_retry"
        assert record["level"] == "warn"  # InternalServerError → warn
        assert record["payload"] == {
            "provider": "anthropic",
            "model": "claude-opus-4-7",
            "attempt": 2,
            "max_retries": 5,
            "delay_s": 1.234,
            "elapsed_s": 3.45,
            "error_type": "InternalServerError",
        }
        # Smoke: tmp_root isn't used, avoid lint warning.
        assert tmp_root
    finally:
        shutil.rmtree(real_tmp, ignore_errors=True)


def test_on_retry_overloaded_emits_warn_level(monkeypatch: Any) -> None:
    """OverloadedError retries get level=warn (same treatment as 5xx +
    RateLimitError) so a flurry of 529s is conspicuous in the journal."""
    import json
    import shutil
    import tempfile
    from pathlib import Path

    import core.paths
    from core.llm.providers.anthropic import _on_retry_journal_emit

    from core.observability import SessionJournal, session_journal_scope

    real_tmp = Path(tempfile.mkdtemp(prefix="p1a-overloaded-"))
    monkeypatch.setattr(core.paths, "GLOBAL_SELF_IMPROVING_LOOP_DIR", real_tmp)
    try:
        journal = SessionJournal(
            session_id="s-529",
            gen_tag="gen-529",
            component="autoresearch",
        )
        with session_journal_scope(journal):
            _on_retry_journal_emit(
                model="claude-opus-4-7",
                attempt=1,
                max_retries=5,
                delay_s=0.5,
                elapsed_s=0.5,
                error_type="OverloadedError",
            )
        rows = (real_tmp / "s-529" / "journal.jsonl").read_text().splitlines()
        record = json.loads(rows[0])
        assert record["event"] == "llm_retry"
        assert record["level"] == "warn"
        assert record["payload"]["error_type"] == "OverloadedError"
    finally:
        shutil.rmtree(real_tmp, ignore_errors=True)


def test_on_retry_noop_when_no_journal_in_scope(monkeypatch: Any) -> None:
    """Outside an autoresearch / seed-generation run (no journal
    ContextVar), the helper must silently no-op so single REPL LLM calls
    don't crash on every retry."""
    from core.llm.providers.anthropic import _on_retry_journal_emit

    # No session_journal_scope active — must not raise.
    _on_retry_journal_emit(
        model="claude-opus-4-7",
        attempt=1,
        max_retries=5,
        delay_s=0.5,
        elapsed_s=0.5,
        error_type="APIConnectionError",
    )


def test_anthropic_retry_paths_wire_on_retry_callback(monkeypatch: Any) -> None:
    """Both sync + async retry_with_backoff entry points must pass
    on_retry=_on_retry_journal_emit so the journal hook fires regardless
    of which call path the caller used."""
    captured_sync: dict[str, Any] = {}
    captured_async: dict[str, Any] = {}

    def _fake_sync(fn: Any, **kwargs: Any) -> Any:
        captured_sync.update(kwargs)
        return "ok"

    async def _fake_async(fn: Any, **kwargs: Any) -> Any:
        captured_async.update(kwargs)
        return "ok"

    import core.llm.providers.anthropic as ap

    monkeypatch.setattr(ap, "retry_with_backoff_generic", _fake_sync)
    monkeypatch.setattr(ap, "retry_with_backoff_generic_async", _fake_async)

    ap.retry_with_backoff(lambda model: "x", model="claude-opus-4-7")
    assert captured_sync.get("on_retry") is ap._on_retry_journal_emit

    import asyncio

    asyncio.run(ap.retry_with_backoff_async(lambda model: "x", model="claude-opus-4-7"))
    assert captured_async.get("on_retry") is ap._on_retry_journal_emit
