"""v0.53.0 + v0.90.0 — fail-fast governance.

v0.53.0 stubbed cross-provider auto-swap and made BillingError carry
plan context. v0.90.0 finished the job by removing the dormant
``_try_model_escalation`` / ``_try_cross_provider_escalation`` methods
entirely; the agentic loop now surfaces a ``model_action_required``
diagnostic so the user picks the next model via ``/model``.

Pre-v0.53.0 behaviour (incident sources): when a provider's chain
exhausted (billing/quota), GEODE silently swapped to the next
provider in ``CROSS_PROVIDER_FALLBACK`` (e.g. GLM → OpenAI). The
user paid metered $$$ on the new provider without consent, and the
LLM identity drifted (different reasoning style + cost). User
direction (2026-04-27): "API/구독 quota 초과 시 친절한 안내 + 시스템
중지가 안정적".

Four contracts pinned here:

1. ``CROSS_PROVIDER_FALLBACK`` is empty for every provider, and the
   loop has no escalation methods. v0.90.0 removed the residual
   ``_try_model_escalation`` / ``_try_cross_provider_escalation``
   methods so no caller can re-introduce auto-swap.

2. ``BillingError`` carries plan context (provider / plan_id /
   plan_display_name / upgrade_url / resets_in_seconds) so the
   user-facing message can render a plan-aware panel.

3. The agentic loop on ``BillingError`` calls ``_emit_quota_panel``
   which fires ``quota_exhausted`` IPC event when plan context
   present, falling back to legacy ``billing_error`` only when
   structured fields absent.

4. ``quota_exhausted`` event is allowlisted + handled by the
   thin-client renderer.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock

import core.agent.loop as _loop_mod
import core.agent.loop._model_switching as _switching_mod
import core.llm.provider_dispatch as _provider_dispatch_mod
from core.config._settings import Settings
from core.llm.errors import BillingError

import core.llm.adapters as _adapters_mod

# ---------------------------------------------------------------------------
# Contract 1 — cross-provider failover removed
# ---------------------------------------------------------------------------


def test_cross_provider_fallback_symbol_removed() -> None:
    """v0.99.19 — the empty-dict ``CROSS_PROVIDER_FALLBACK`` shim is
    deleted, not merely empty. Pre-fix GLM → OpenAI / OpenAI → Anthropic
    was wired here, masking quota issues with cost surprise; v0.53.0
    stubbed it to an empty dict; v0.99.19 removes the symbol entirely so
    no caller can re-introduce the silent swap by patching values in."""
    assert not hasattr(_adapters_mod, "CROSS_PROVIDER_FALLBACK"), (
        "CROSS_PROVIDER_FALLBACK resurfaced — silent provider swap is "
        "globally forbidden. Quota exhaustion fires ``quota_exhausted`` "
        "and the user picks the next model via /model."
    )


def test_provider_dispatch_has_no_cross_provider_dispatcher() -> None:
    """Router calls must not have a shared cross-provider fallback entry point."""
    assert not hasattr(_provider_dispatch_mod, "_cross_provider_dispatch")


def test_settings_class_has_no_cross_provider_failover_field() -> None:
    """The opt-in cross-provider failover setting was deleted, not hidden."""
    assert "llm_cross_provider_failover" not in Settings.model_fields
    assert "llm_cross_provider_order" not in Settings.model_fields
    assert not hasattr(Settings, "llm_cross_provider_failover")


def test_loop_has_no_escalation_methods() -> None:
    """v0.90.0 — escalation methods on AgenticLoop are gone entirely.

    Pre-v0.53.0 these auto-swapped models on quota/auth errors. v0.53.0
    stubbed them to ``return False``. v0.90.0 removed them so no caller
    can silently re-introduce auto-swap by patching the method back.
    """
    assert not hasattr(_loop_mod.AgenticLoop, "_try_model_escalation")
    assert not hasattr(_loop_mod.AgenticLoop, "_try_cross_provider_escalation")
    assert not hasattr(_loop_mod.AgenticLoop, "_persist_escalated_model")


def test_model_switching_module_has_no_escalation_helpers() -> None:
    """The underlying module-level helpers were removed too — only the
    user-initiated ``update_model_async`` / drift sync paths and the
    diagnostics-only ``fallback_chain_suggestions`` remain."""
    assert not hasattr(_switching_mod, "try_model_escalation")
    assert not hasattr(_switching_mod, "try_cross_provider_escalation")
    assert not hasattr(_switching_mod, "persist_escalated_model")
    # Sanity — the surviving helpers are still here.
    assert hasattr(_switching_mod, "update_model_async")
    assert hasattr(_switching_mod, "sync_model_from_settings_async")
    assert hasattr(_switching_mod, "fallback_chain_suggestions")


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
