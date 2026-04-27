"""v0.53.0 — fail-fast governance: cross-provider escalation REMOVED,
quota exhaustion surfaces a plan-aware panel + stops the loop.

Pre-v0.53.0 behaviour (incident sources): when a provider's chain
exhausted (billing/quota), GEODE silently swapped to the next
provider in ``CROSS_PROVIDER_FALLBACK`` (e.g. GLM → OpenAI). The
user paid metered $$$ on the new provider without consent, and the
LLM identity drifted (different reasoning style + cost). User
direction (2026-04-27): "API/구독 quota 초과 시 친절한 안내 + 시스템
중지가 안정적".

Three contracts pinned here:

1. ``CROSS_PROVIDER_FALLBACK`` is empty for every provider — no
   silent swap path remains. ``_try_cross_provider_escalation``
   returns False unconditionally. ``_try_model_escalation``
   exhausts the same-provider chain and returns False (no
   provider hop).

2. ``BillingError`` carries plan context (provider / plan_id /
   plan_display_name / upgrade_url / resets_in_seconds) so the
   user-facing message can render a plan-aware panel.

3. The agentic loop on ``BillingError`` calls ``_emit_quota_panel``
   which fires ``quota_exhausted`` IPC event when plan context
   present, falling back to legacy ``billing_error`` only when
   structured fields absent.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock

import core.agent.loop as _loop_mod
import core.llm.adapters as _adapters_mod
from core.llm.errors import BillingError

# ---------------------------------------------------------------------------
# Contract 1 — cross-provider failover removed
# ---------------------------------------------------------------------------


def test_cross_provider_fallback_map_is_empty_for_all_providers() -> None:
    """v0.53.0 invariant: no provider may auto-swap to another. Pre-fix
    GLM → OpenAI / OpenAI → Anthropic was wired here, masking quota
    issues with cost surprise."""
    for provider, fallbacks in _adapters_mod.CROSS_PROVIDER_FALLBACK.items():
        assert fallbacks == [], (
            f"{provider} still has cross-provider fallbacks {fallbacks} — "
            "v0.53.0 governance redesign requires empty list. Silent "
            "provider swap creates cost surprise + behavior drift."
        )


def test_try_cross_provider_escalation_returns_false() -> None:
    """The escalation method must be a no-op returning False so callers
    that previously relied on auto-recovery now propagate the original
    error to the user."""
    src = inspect.getsource(_loop_mod.AgenticLoop._try_cross_provider_escalation)
    assert "return False" in src, (
        "_try_cross_provider_escalation must early-return False — auto-swap is removed in v0.53.0"
    )
    assert "v0.53.0" in src, (
        "method body must document the removal so future readers don't "
        "re-introduce the cross-provider swap"
    )


def test_try_model_escalation_does_not_call_cross_provider() -> None:
    """Inside the same-provider escalation path, the cross-provider
    fallback loop must be removed. Pre-fix: ``for fallback_provider,
    fallback_model in fallbacks`` ran after the same-provider chain
    exhausted."""
    src = inspect.getsource(_loop_mod.AgenticLoop._try_model_escalation)
    # The CROSS_PROVIDER_FALLBACK iteration is gone.
    assert "for fallback_provider, fallback_model in fallbacks" not in src, (
        "cross-provider for-loop still present in _try_model_escalation"
    )
    # Surfacing-to-user log is present.
    assert "surfacing to user" in src or "v0.53.0" in src, (
        "method must log that exhaustion now surfaces to user instead of auto-swapping providers"
    )


# ---------------------------------------------------------------------------
# Contract 2 — BillingError carries plan context + user_message()
# ---------------------------------------------------------------------------


def test_billing_error_default_plain_message() -> None:
    """Back-compat: a plain BillingError(msg) still works (no plan ctx)."""
    exc = BillingError("Insufficient balance")
    assert str(exc) == "Insufficient balance"
    assert exc.provider == ""
    assert exc.plan_id == ""
    msg = exc.user_message()
    assert "Insufficient balance" in msg
    assert "Options:" in msg


def test_billing_error_carries_plan_context() -> None:
    """v0.53.0: structured fields are addressable."""
    exc = BillingError(
        "GLM Coding Plan quota exhausted",
        provider="glm-coding",
        plan_id="glm-coding-lite",
        plan_display_name="GLM Coding Lite",
        upgrade_url="https://z.ai/subscribe",
        resets_in_seconds=8000,  # 2h13m
    )
    assert exc.provider == "glm-coding"
    assert exc.plan_id == "glm-coding-lite"
    assert exc.plan_display_name == "GLM Coding Lite"
    assert exc.upgrade_url == "https://z.ai/subscribe"
    assert exc.resets_in_seconds == 8000


def test_billing_error_user_message_renders_panel() -> None:
    """The user-facing message contains header + reset time + 3 options
    + upgrade URL when all fields populated."""
    exc = BillingError(
        "Insufficient balance",
        provider="glm",
        plan_display_name="GLM Coding Lite",
        upgrade_url="https://z.ai/subscribe",
        resets_in_seconds=3600,
    )
    msg = exc.user_message()
    assert "GLM Coding Lite quota exhausted" in msg
    assert "Insufficient balance" in msg
    assert "Resets in: 1h 0m" in msg
    assert "Options:" in msg
    assert "1. Wait for quota reset" in msg
    assert "/login set-key glm" in msg
    assert "/model" in msg
    assert "https://z.ai/subscribe" in msg


def test_billing_error_user_message_omits_reset_when_zero() -> None:
    """resets_in_seconds=0 ⇒ the reset line is omitted (avoid "Resets in: 0m")."""
    exc = BillingError("balance", provider="openai")
    msg = exc.user_message()
    assert "Resets in" not in msg


# ---------------------------------------------------------------------------
# Contract 3 — _emit_quota_panel routes to quota_exhausted vs billing_error
# ---------------------------------------------------------------------------


def _make_loop_stub() -> Any:
    """Minimal stub binding _emit_quota_panel onto a MagicMock."""
    stub = MagicMock()
    stub._emit_quota_panel = _loop_mod.AgenticLoop._emit_quota_panel.__get__(stub)
    return stub


def test_emit_quota_panel_uses_structured_event_when_provider_present(
    monkeypatch,
) -> None:
    """When BillingError carries a provider, the new structured
    ``emit_quota_exhausted`` IPC event fires (multi-line panel)."""
    captured: dict[str, Any] = {}

    def fake_quota(**kwargs: Any) -> None:
        captured.update(kwargs)
        captured["_event"] = "quota_exhausted"

    def fake_billing(message: str) -> None:
        captured["_event"] = "billing_error"
        captured["message"] = message

    monkeypatch.setattr("core.ui.agentic_ui.emit_quota_exhausted", fake_quota)
    monkeypatch.setattr("core.ui.agentic_ui.emit_billing_error", fake_billing)

    stub = _make_loop_stub()
    stub._emit_quota_panel(
        BillingError(
            "out",
            provider="glm",
            plan_id="glm-coding-lite",
            plan_display_name="GLM Coding Lite",
        )
    )

    assert captured["_event"] == "quota_exhausted", (
        "structured event must fire when Plan context is present — "
        "pre-v0.53.0 used the single-line billing_error"
    )
    assert captured["provider"] == "glm"
    assert captured["plan_id"] == "glm-coding-lite"
    assert captured["plan_display_name"] == "GLM Coding Lite"


def test_emit_quota_panel_falls_back_to_billing_error_without_provider(
    monkeypatch,
) -> None:
    """Legacy path: BillingError without Plan context still works
    (e.g. a caller that pre-dates v0.53.0)."""
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "core.ui.agentic_ui.emit_quota_exhausted",
        lambda **kw: captured.setdefault("_event", "quota_exhausted"),
    )
    monkeypatch.setattr(
        "core.ui.agentic_ui.emit_billing_error",
        lambda msg: captured.update({"_event": "billing_error", "message": msg}),
    )

    stub = _make_loop_stub()
    stub._emit_quota_panel(BillingError("plain"))

    assert captured["_event"] == "billing_error"
    assert captured["message"] == "plain"


# ---------------------------------------------------------------------------
# Contract 4 — quota_exhausted in IPC allowlist + handler exists
# ---------------------------------------------------------------------------


def test_quota_exhausted_in_ipc_allowlist() -> None:
    """The new event type must be on the thin-client allowlist or it'd
    be silently dropped (v0.52 phase 6 invariant)."""
    import core.cli.ipc_client as _ipc_mod

    src = inspect.getsource(_ipc_mod)
    assert '"quota_exhausted"' in src, (
        "quota_exhausted missing from KNOWN_EVENT_TYPES allowlist — "
        "thin client will silently drop the panel event"
    )


def test_event_renderer_has_quota_exhausted_handler() -> None:
    """The thin-client event renderer must implement the handler so
    the event isn't a no-op."""
    from core.ui.event_renderer import EventRenderer

    assert hasattr(EventRenderer, "_handle_quota_exhausted"), (
        "EventRenderer must implement _handle_quota_exhausted — without "
        "it the dispatch (`getattr(self, f'_handle_{etype}')`) returns "
        "None and the panel is silently dropped"
    )
