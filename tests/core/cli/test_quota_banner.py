"""Tests for PR-γ1 — 3-tier quota banner + abort dialog."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from core.cli.quota_banner import (
    AbortDialog,
    QuotaBannerRefresher,
    QuotaState,
    SubscriptionQuotaBanner,
    current_banner,
    install_banner,
    render_abort_message,
    uninstall_banner,
)


@pytest.fixture(autouse=True)
def _detach_banner() -> Any:
    """Ensure the module-level banner singleton is reset between tests."""
    uninstall_banner()
    yield
    uninstall_banner()


# ── QuotaState ────────────────────────────────────────────────────────────


def test_usage_ratio_zero_when_total_zero() -> None:
    """Cold start (no audit yet) → ratio = 0, banner stays out of red."""
    s = QuotaState(total_tokens=0, used_tokens=100)
    assert s.usage_ratio == 0.0


def test_usage_ratio_clamps_above_one() -> None:
    """Pathological case (overage) — clamp to 1.0 so render math stays safe."""
    s = QuotaState(total_tokens=100, used_tokens=200)
    assert s.usage_ratio == 1.0


def test_usage_ratio_clamps_below_zero() -> None:
    """Negative used_tokens (provider bug) clamps to 0.0."""
    s = QuotaState(total_tokens=100, used_tokens=-10)
    assert s.usage_ratio == 0.0


# ── tier transitions ──────────────────────────────────────────────────────


def test_tier_blue_below_warn() -> None:
    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="anthropic", used_tokens=30, total_tokens=100)
    assert banner.tier() == "blue"


def test_tier_yellow_between_warn_and_abort() -> None:
    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="anthropic", used_tokens=60, total_tokens=100)
    assert banner.tier() == "yellow"


def test_tier_red_at_or_above_abort() -> None:
    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="anthropic", used_tokens=90, total_tokens=100)
    assert banner.tier() == "red"


def test_tier_red_when_aborted_regardless_of_usage() -> None:
    """Strict-mode trip_abort locks the banner to red."""
    banner = SubscriptionQuotaBanner()
    banner.set_state(provider="anthropic", used_tokens=5, total_tokens=100)
    banner.trip_abort(reason="oauth quota exhausted")
    assert banner.tier() == "red"


def test_clear_abort_returns_to_usage_tier() -> None:
    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="anthropic", used_tokens=10, total_tokens=100)
    banner.trip_abort(reason="quota")
    assert banner.tier() == "red"
    banner.clear_abort()
    assert banner.tier() == "blue"


# ── render ──────────────────────────────────────────────────────────────


def test_render_empty_on_cold_start() -> None:
    """No provider set + no quota counters → empty string (no flash)."""
    banner = SubscriptionQuotaBanner()
    assert banner.render() == ""


def test_render_blue_format() -> None:
    banner = SubscriptionQuotaBanner()
    banner.set_state(provider="anthropic", used_tokens=10, total_tokens=100)
    out = banner.render()
    assert "#5f9ea0" in out
    assert "anthropic" in out
    assert "10%" in out


def test_render_yellow_format() -> None:
    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="openai", used_tokens=70, total_tokens=100)
    out = banner.render()
    assert "yellow" in out
    assert "openai" in out
    assert "70%" in out
    assert "approaching" in out


def test_render_red_when_at_abort_threshold() -> None:
    """OL-P2 (2026-05-22) — crossing abort_threshold now auto-trips the
    ``aborted`` flag (set_state has actual enforcement, not just display).
    The render path therefore takes the aborted branch, not the raw-
    percentage branch. Pre-OL-P2 this test asserted "95%" in the output;
    now it asserts the abort message.
    """
    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    banner.set_state(provider="openai", used_tokens=95, total_tokens=100)
    assert banner.state.aborted is True  # OL-P2 auto-trip
    out = banner.render()
    assert "red" in out
    assert "aborted" in out


def test_render_red_when_aborted_carries_resolution_hint() -> None:
    banner = SubscriptionQuotaBanner()
    banner.trip_abort(reason="oauth quota")
    out = banner.render()
    assert "red" in out
    assert "aborted" in out
    assert "/status" in out


# ── threading ────────────────────────────────────────────────────────────


def test_set_state_is_thread_safe() -> None:
    """Concurrent set_state calls from many threads don't corrupt state."""
    banner = SubscriptionQuotaBanner()

    def _write(i: int) -> None:
        for _ in range(100):
            banner.set_state(provider=f"f-{i}", used_tokens=i, total_tokens=1000)

    threads = [threading.Thread(target=_write, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Final state is whatever the last write was; the invariant is no crash
    # and a coherent QuotaState dataclass.
    final = banner.state
    assert final.total_tokens == 1000
    assert final.provider.startswith("f-")


# ── singleton accessor ───────────────────────────────────────────────────


def test_current_banner_returns_none_before_install() -> None:
    assert current_banner() is None


def test_install_then_current_returns_same_instance() -> None:
    banner = SubscriptionQuotaBanner()
    install_banner(banner)
    assert current_banner() is banner


def test_uninstall_resets_to_none() -> None:
    install_banner(SubscriptionQuotaBanner())
    uninstall_banner()
    assert current_banner() is None


def test_install_replaces_prior_banner() -> None:
    install_banner(SubscriptionQuotaBanner())
    new = SubscriptionQuotaBanner()
    install_banner(new)
    assert current_banner() is new


# ── refresher background thread ──────────────────────────────────────────


def test_refresher_invokes_invalidate_at_cadence() -> None:
    """Background thread calls the injected invalidate callable."""
    calls: list[None] = []
    finished = threading.Event()

    def _invalidate() -> None:
        calls.append(None)
        if len(calls) >= 3:
            finished.set()

    def _sleep(_: float) -> None:
        # Replace real time.sleep with no-op so test runs fast.
        return None

    refresher = QuotaBannerRefresher(
        invalidate=_invalidate,
        interval_seconds=0.0,
        sleep=_sleep,
    )
    refresher.start()
    assert finished.wait(timeout=2.0)
    refresher.stop()
    assert len(calls) >= 3


def test_refresher_swallows_invalidate_exception() -> None:
    """An exception inside invalidate must not kill the thread."""
    attempts: list[int] = []

    def _invalidate() -> None:
        attempts.append(1)
        raise RuntimeError("simulated")

    refresher = QuotaBannerRefresher(
        invalidate=_invalidate,
        interval_seconds=0.0,
        sleep=lambda _: None,
    )
    refresher.start()
    # Give it a moment to loop a few times, then stop.
    import time

    time.sleep(0.05)
    refresher.stop()
    assert len(attempts) >= 1


def test_refresher_start_is_idempotent() -> None:
    """Calling start() twice doesn't spawn two threads."""
    refresher = QuotaBannerRefresher(
        invalidate=lambda: None,
        interval_seconds=10.0,
        sleep=lambda _: None,
    )
    refresher.start()
    thread1 = refresher._thread
    refresher.start()
    thread2 = refresher._thread
    refresher.stop()
    assert thread1 is thread2


# ── abort dialog ─────────────────────────────────────────────────────────


def test_render_abort_message_includes_family_in_title() -> None:
    dlg = render_abort_message("anthropic", "subscription quota exhausted")
    assert isinstance(dlg, AbortDialog)
    assert "anthropic" in dlg.title
    assert dlg.body == "subscription quota exhausted"


def test_render_abort_message_passes_resolver_text_verbatim() -> None:
    """Body MUST be the resolver's actionable message verbatim so the
    operator sees the same remedies in dialog + log + stderr."""
    msg = (
        "no subscription credential source available\n"
        "To continue NOW:\n"
        "  1. Wait until reset.\n"
        "  2. Enable fallback_to_payg = true.\n"
        "  3. Pin a different source."
    )
    dlg = render_abort_message("openai", msg)
    assert dlg.body == msg


# ── P0c — banner writer wiring (anthropic.py response hook) ─────────────


def test_extract_anthropic_quota_parses_rate_limit_headers() -> None:
    """Headers carrying anthropic-ratelimit-tokens-{limit,remaining} parse
    to (used, total) tuple."""
    from core.llm.providers.anthropic import _extract_anthropic_quota

    headers = {
        "anthropic-ratelimit-tokens-limit": "1000",
        "anthropic-ratelimit-tokens-remaining": "250",
    }
    assert _extract_anthropic_quota(headers) == (750, 1000)


def test_extract_anthropic_quota_returns_none_when_headers_missing() -> None:
    """PAYG path — no rate-limit headers → no-op signal back to caller."""
    from core.llm.providers.anthropic import _extract_anthropic_quota

    assert _extract_anthropic_quota({}) is None
    assert _extract_anthropic_quota({"x-other": "v"}) is None


def test_extract_anthropic_quota_returns_none_on_unparseable_values() -> None:
    """Defensive — never raise from the response hook."""
    from core.llm.providers.anthropic import _extract_anthropic_quota

    assert (
        _extract_anthropic_quota(
            {
                "anthropic-ratelimit-tokens-limit": "not-a-number",
                "anthropic-ratelimit-tokens-remaining": "250",
            }
        )
        is None
    )


def test_feed_banner_from_anthropic_response_invokes_registered_setter() -> None:
    """Hook reads headers off the response and pushes through the
    registered ``register_quota_setter`` callback. The agent path does
    NOT import ``core.cli.quota_banner`` directly (import-linter forbids
    it); the CLI front-end registers its setter on REPL startup."""
    from core.llm.providers.anthropic import (
        _feed_banner_from_anthropic_response,
        register_quota_setter,
    )

    received: dict[str, object] = {}

    def _setter(**kwargs: object) -> None:
        received.update(kwargs)

    register_quota_setter(_setter)
    try:

        class _FakeResponse:
            headers = {
                "anthropic-ratelimit-tokens-limit": "1000",
                "anthropic-ratelimit-tokens-remaining": "700",
            }

        _feed_banner_from_anthropic_response(_FakeResponse())
        assert received == {
            "provider": "anthropic",
            "used_tokens": 300,
            "total_tokens": 1000,
        }
    finally:
        register_quota_setter(None)


def test_feed_banner_noops_when_no_setter_registered() -> None:
    """Without a registered setter, the hook must silently return —
    non-REPL invocations (geode audit subprocess) get no banner update
    and no crash."""
    from core.llm.providers.anthropic import (
        _feed_banner_from_anthropic_response,
        register_quota_setter,
    )

    register_quota_setter(None)

    class _FakeResponse:
        headers = {
            "anthropic-ratelimit-tokens-limit": "1000",
            "anthropic-ratelimit-tokens-remaining": "700",
        }

    # Just ensures no exception is raised.
    _feed_banner_from_anthropic_response(_FakeResponse())


def test_feed_banner_noops_on_missing_headers() -> None:
    """PAYG path keeps banner state untouched."""
    from core.llm.providers.anthropic import (
        _feed_banner_from_anthropic_response,
        register_quota_setter,
    )

    received: list[dict[str, object]] = []

    def _setter(**kwargs: object) -> None:
        received.append(kwargs)

    register_quota_setter(_setter)
    try:

        class _FakeResponse:
            headers: dict[str, str] = {}

        _feed_banner_from_anthropic_response(_FakeResponse())
        assert received == []
    finally:
        register_quota_setter(None)


def test_install_banner_then_register_setter_wires_end_to_end() -> None:
    """Integration: prompt_session installs the banner then registers
    banner.set_state as the setter. A subsequent response feed updates
    the banner via the callback (matching real REPL behavior)."""
    from core.llm.providers.anthropic import (
        _feed_banner_from_anthropic_response,
        register_quota_setter,
    )

    banner = SubscriptionQuotaBanner(warn_threshold=0.5, abort_threshold=0.9)
    install_banner(banner)
    register_quota_setter(banner.set_state)
    try:

        class _FakeResponse:
            headers = {
                "anthropic-ratelimit-tokens-limit": "1000",
                "anthropic-ratelimit-tokens-remaining": "200",
            }

        _feed_banner_from_anthropic_response(_FakeResponse())
        assert banner.state.provider == "anthropic"
        assert banner.state.used_tokens == 800
        assert banner.state.total_tokens == 1000
    finally:
        register_quota_setter(None)


def test_uninstall_banner_clears_registered_setter() -> None:
    """``uninstall_banner`` MUST also clear the anthropic quota setter so
    a teardown doesn't leave a dangling reference to the detached
    banner. Otherwise the next response feed would still call the old
    banner's ``set_state`` and silently update a banner that the CLI no
    longer renders."""
    from core.llm.providers.anthropic import (
        _feed_banner_from_anthropic_response,
        register_quota_setter,
    )

    banner = SubscriptionQuotaBanner()
    install_banner(banner)
    register_quota_setter(banner.set_state)
    uninstall_banner()

    # After uninstall, the setter should be cleared — feeding more
    # responses must NOT update banner state.
    banner.set_state(provider="anthropic", used_tokens=42, total_tokens=100)

    class _FakeResponse:
        headers = {
            "anthropic-ratelimit-tokens-limit": "999",
            "anthropic-ratelimit-tokens-remaining": "500",
        }

    _feed_banner_from_anthropic_response(_FakeResponse())
    # Banner state stays at the value we wrote manually, not 499/999.
    assert banner.state.used_tokens == 42
    assert banner.state.total_tokens == 100
