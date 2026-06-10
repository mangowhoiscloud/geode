from core.self_improving import measure

"""OL-P2 — Petri quota actual enforcement invariants.

Pre-OL-P2 the `SubscriptionQuotaBanner.abort_threshold` was display-only
— ratio >= abort_threshold turned the banner red, but `aborted=True`
was only set by the credential resolver's strict-mode trip. Crossing
the threshold via natural usage did NOT abort anything.

OL-P2 adds two pieces:

1. **Auto-trip on threshold breach** — `set_state` now checks the new
   ratio against `abort_threshold` and auto-calls `trip_abort` when
   it breaches.
2. **Opt-in call gate** — `enforce_or_raise()` raises
   `QuotaAbortError` when the banner is aborted. Callers wire this
   before LLM call to fail-fast instead of consuming more quota.
3. **autoresearch audit wired** — `core/self_improving/train.py::main`'s
   audit subprocess invocation calls `enforce_or_raise` before
   `subprocess.run` so an aborted quota stops the audit at the gate.
"""

from __future__ import annotations

from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Auto-trip on threshold breach
# ---------------------------------------------------------------------------


def test_set_state_below_warn_does_not_trip() -> None:
    from core.cli.quota_banner import SubscriptionQuotaBanner

    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="anthropic", used_tokens=10, total_tokens=100)
    assert banner.state.aborted is False
    assert banner.tier() == "green"


def test_set_state_between_warn_and_abort_does_not_trip() -> None:
    """Yellow tier should NOT auto-trip — only red (>= abort_threshold) does."""
    from core.cli.quota_banner import SubscriptionQuotaBanner

    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="anthropic", used_tokens=60, total_tokens=100)
    assert banner.tier() == "yellow"
    assert banner.state.aborted is False


def test_set_state_above_abort_threshold_auto_trips() -> None:
    """Crossing abort_threshold → banner.state.aborted=True automatically."""
    from core.cli.quota_banner import SubscriptionQuotaBanner

    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="anthropic", used_tokens=95, total_tokens=100)
    assert banner.tier() == "red"
    assert banner.state.aborted is True
    assert "abort_threshold" in banner.state.abort_reason
    assert "anthropic" in banner.state.abort_reason


def test_auto_trip_does_not_overwrite_existing_abort_reason() -> None:
    """If banner is already aborted (e.g., by credential resolver),
    `set_state` keeps the original abort_reason — credential issues
    are higher priority signal than usage breach."""
    from core.cli.quota_banner import SubscriptionQuotaBanner

    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.trip_abort(reason="credential-resolver: subscription denied")
    # Now natural usage update also breaches threshold
    banner.set_state(provider="anthropic", used_tokens=95, total_tokens=100)
    # Original reason preserved (set_state preserves aborted=True path)
    assert banner.state.aborted is True
    assert "credential-resolver" in banner.state.abort_reason


def test_clear_abort_re_enables_auto_trip() -> None:
    """After clear_abort, a subsequent threshold breach should re-trip."""
    from core.cli.quota_banner import SubscriptionQuotaBanner

    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="anthropic", used_tokens=95, total_tokens=100)
    assert banner.state.aborted is True
    banner.clear_abort()
    assert banner.state.aborted is False
    # Push another threshold-breaching update — should auto-trip again
    banner.set_state(provider="anthropic", used_tokens=96, total_tokens=100)
    assert banner.state.aborted is True


def test_auto_trip_uses_configured_abort_threshold() -> None:
    """Threshold parameter is respected — 0.7 vs 0.9 produces different
    auto-trip points."""
    from core.cli.quota_banner import SubscriptionQuotaBanner

    tight = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.7)
    tight.set_state(provider="openai", used_tokens=75, total_tokens=100)
    assert tight.state.aborted is True  # 0.75 >= 0.70

    loose = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.95)
    loose.set_state(provider="openai", used_tokens=75, total_tokens=100)
    assert loose.state.aborted is False  # 0.75 < 0.95


# ---------------------------------------------------------------------------
# enforce_or_raise call gate
# ---------------------------------------------------------------------------


def test_enforce_or_raise_passes_when_not_aborted() -> None:
    from core.cli.quota_banner import SubscriptionQuotaBanner

    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="anthropic", used_tokens=10, total_tokens=100)
    banner.enforce_or_raise()  # no exception


def test_enforce_or_raise_raises_when_aborted() -> None:
    from core.cli.quota_banner import QuotaAbortError, SubscriptionQuotaBanner

    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.trip_abort(reason="quota exhausted")
    with pytest.raises(QuotaAbortError) as exc_info:
        banner.enforce_or_raise()
    # Exception carries provider + reason for downstream rendering
    assert exc_info.value.reason == "quota exhausted"


def test_enforce_or_raise_carries_provider() -> None:
    from core.cli.quota_banner import QuotaAbortError, SubscriptionQuotaBanner

    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="anthropic", used_tokens=95, total_tokens=100)
    # Auto-tripped
    with pytest.raises(QuotaAbortError) as exc_info:
        banner.enforce_or_raise()
    assert exc_info.value.provider == "anthropic"


def test_quota_abort_error_is_runtime_error_subclass() -> None:
    """`QuotaAbortError` extends RuntimeError so generic except-blocks
    catch it (callers without specific quota handling still see the
    exception in their fallback path)."""
    from core.cli.quota_banner import QuotaAbortError

    assert issubclass(QuotaAbortError, RuntimeError)
    exc = QuotaAbortError(provider="x", reason="y")
    assert "quota aborted" in str(exc)
    assert "x" in str(exc)
    assert "y" in str(exc)


# ---------------------------------------------------------------------------
# autoresearch wiring
# ---------------------------------------------------------------------------


def test_autoresearch_train_calls_enforce_or_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The audit subprocess invocation site must call `enforce_or_raise`
    before `subprocess.run`. We grep the source rather than execute the
    full audit (which would need real config + LLM credentials).
    """
    from pathlib import Path

    from core.self_improving import train

    source = Path(train.__file__).read_text(encoding="utf-8")
    # The gate call must be in the file
    assert "enforce_or_raise" in source, (
        "OL-P2 regressed: core/self_improving/train.py does not call enforce_or_raise"
    )
    # And QuotaAbortError must be imported / caught
    assert "QuotaAbortError" in source, (
        "OL-P2 regressed: core/self_improving/train.py does not handle QuotaAbortError"
    )


def test_autoresearch_run_audit_aborts_on_tripped_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `current_banner()` returns a tripped banner, `run_audit`
    should RuntimeError BEFORE `subprocess.run` is reached.

    We patch both ``current_banner`` and ``subprocess.run`` to verify the
    gate fires first.
    """
    from core.cli.quota_banner import SubscriptionQuotaBanner

    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.trip_abort(reason="test-tripped")

    monkeypatch.setattr("core.cli.quota_banner.current_banner", lambda: banner)
    subprocess_calls: list[Any] = []

    def _fake_run(*args: Any, **kwargs: Any) -> Any:
        subprocess_calls.append((args, kwargs))
        raise AssertionError("subprocess.run must not be reached when banner is tripped")

    monkeypatch.setattr(measure.subprocess, "run", _fake_run)
    # `run_audit(dry_run=False)` is the audit entry point. The gate
    # lives inside the `if not dry_run:` branch just before
    # `_build_audit_command()`.
    with pytest.raises(RuntimeError, match="quota gate tripped"):
        measure.run_audit(dry_run=False)
    assert subprocess_calls == [], (
        "OL-P2 regressed: subprocess.run was called despite tripped banner"
    )
