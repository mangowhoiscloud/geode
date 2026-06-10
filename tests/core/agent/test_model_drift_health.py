"""Bug class B3 — model drift sync was the silent-revert load-bearer.

Historical context (kept for the post-mortem trail): the v0.52.1
incident saw a stale ``settings.model`` overwrite a freshly registered
``loop.model`` because the drift sync ran on every turn and trusted
``settings.model`` over the operator's most-recent choice. The original
fix here was a *health-check guard* (consult ``ProfileRotator.resolve``
before allowing the drift to proceed).

PR-DRIFT-CUT (2026-05-24) cut the entire drift surface — the root
cause was that drift sync existed at all in a daemon process whose
``settings`` snapshot can never be authoritative. These tests now pin
the no-op contract: ``_sync_model_from_settings_async()`` always
returns ``False`` and never invokes ``update_model_async``.

We retain the test file (rather than delete it) because the
regressions it prevents are still real — they will surface the day
anyone tries to revive auto-revert under the old name. The new tests
that pin the *positive* contract (drift sync is dead) live in
``tests/test_drift_fallback_cut.py``.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import core.agent.loop as _loop_mod
from core.agent.loop import _model_switching

# ---------------------------------------------------------------------------
# Contract 1 — _sync_model_from_settings consults rotator before update_model
# ---------------------------------------------------------------------------


def test_sync_calls_health_check_before_update() -> None:
    """PR-DRIFT-CUT (2026-05-24) — drift sync entry point is a no-op.

    Pre-PR this test asserted that ``_settings_model_target`` consulted
    ``_drift_target_is_healthy`` *before* invoking ``update_model_async``.
    The drift surface is now cut entirely, so the test pins the
    stronger invariant: the function source must NOT call
    ``update_model_async`` at all (it must be a permanent no-op so a
    future revival has to use a new entry-point name).
    """
    src = inspect.getsource(_model_switching._settings_model_target) + inspect.getsource(
        _model_switching.sync_model_from_settings_async
    )
    assert "update_model_async" not in src, (
        "PR-DRIFT-CUT contract: ``sync_model_from_settings_async`` must "
        "NEVER invoke ``update_model_async``. Reviving auto-revert under "
        "this name re-introduces the v0.99.52 incident."
    )


def test_sync_returns_false_when_drift_disabled() -> None:
    """N6-followup: ``disable_settings_drift=True`` short-circuits sync.

    The petri_audit runner constructs ``AgenticLoop`` with this flag so a
    user-pinned ``--target`` is sticky for the audit's lifetime. If the
    short-circuit ever regresses, every audit silently routes back to
    ``settings.model`` between rounds — that exact failure was the v2
    "target metrics 0회" mystery (docs/audits/2026-05-10-petri-2a-v2.md
    § C4 follow-up).
    """
    stub = MagicMock()
    stub.model = "claude-opus-4-7"
    stub.update_model_async = AsyncMock()
    stub._disable_settings_drift = True
    stub._sync_model_from_settings_async = (
        _loop_mod.AgenticLoop._sync_model_from_settings_async.__get__(stub)
    )

    # settings.model intentionally divergent — would normally trigger drift.
    fake_settings = MagicMock(model="gpt-5.5")
    with patch("core.config.settings", fake_settings):
        changed = asyncio.run(stub._sync_model_from_settings_async())

    assert changed is False
    stub.update_model_async.assert_not_called()


def test_drift_target_is_healthy_uses_rotator() -> None:
    """The health helper must consult ProfileRotator.resolve, not invent
    its own definition of health (which would diverge from the actual
    selection used by the next LLM call)."""
    src = inspect.getsource(_loop_mod.AgenticLoop._drift_target_is_healthy)
    assert "rotator.resolve" in src, (
        "Health check must use ProfileRotator.resolve so the answer matches "
        "what the next LLM call would actually pick"
    )
    assert "_resolve_provider" in src, (
        "Must resolve target_model → provider via _resolve_provider, "
        "otherwise we'd query the wrong rotator pool"
    )


# ---------------------------------------------------------------------------
# Contract 2 — refuse drift when rotator returns None, accept when healthy
# ---------------------------------------------------------------------------


def _make_loop_stub(loop_model: str = "glm-5.1") -> MagicMock:
    """Build a stub bound to AgenticLoop._sync_model_from_settings + helper."""
    stub = MagicMock()
    stub.model = loop_model
    stub.update_model_async = AsyncMock()
    # MagicMock auto-creates a truthy attribute on first access — that
    # would make ``getattr(loop, "_disable_settings_drift", False)``
    # accidentally return a truthy mock and short-circuit the drift sync
    # in *every* test. Pin to False so existing contracts run as before.
    stub._disable_settings_drift = False
    # Bind the real methods to the stub so we exercise the patched logic.
    stub._sync_model_from_settings_async = (
        _loop_mod.AgenticLoop._sync_model_from_settings_async.__get__(stub)
    )
    stub._drift_target_is_healthy = _loop_mod.AgenticLoop._drift_target_is_healthy.__get__(stub)
    return stub


def test_drift_refused_when_rotator_returns_none(monkeypatch) -> None:
    """End-to-end: settings.model='glm-4.7-flash', loop.model='glm-5.1'.
    Rotator.resolve('glm') → None (no profile). Drift must be refused;
    update_model must NOT be called."""
    stub = _make_loop_stub("glm-5.1")

    fake_rotator = MagicMock()
    fake_rotator.resolve.return_value = None  # no eligible profile

    monkeypatch.setattr("core.wiring.container.get_profile_rotator", lambda: fake_rotator)
    monkeypatch.setattr("core.agent.loop._resolve_provider", lambda m: "glm")

    fake_settings = MagicMock(model="glm-4.7-flash")
    with patch("core.config.settings", fake_settings):
        changed = asyncio.run(stub._sync_model_from_settings_async())

    assert changed is False
    stub.update_model_async.assert_not_called()


def test_drift_is_noop_even_when_rotator_returns_profile(monkeypatch) -> None:
    """PR-DRIFT-CUT (2026-05-24) — even a healthy rotator + settings
    divergence must NOT trigger an auto-swap.

    Pre-PR this asserted that a valid profile combined with
    ``settings.model`` divergence drove ``update_model_async``. With
    drift sync removed, the rotator state is irrelevant — the loop
    waits for an explicit ``/model`` from the operator.
    """
    stub = _make_loop_stub("glm-5.1")

    fake_rotator = MagicMock()
    fake_rotator.resolve.return_value = MagicMock(name="profile")

    monkeypatch.setattr("core.wiring.container.get_profile_rotator", lambda: fake_rotator)
    monkeypatch.setattr("core.agent.loop._resolve_provider", lambda m: "glm")

    fake_settings = MagicMock(model="glm-4.7-flash")
    with patch("core.config.settings", fake_settings):
        changed = asyncio.run(stub._sync_model_from_settings_async())

    assert changed is False
    stub.update_model_async.assert_not_awaited()


def test_drift_is_noop_when_rotator_not_initialised(monkeypatch) -> None:
    """Early-bootstrap state was previously the lone exception that let
    drift sync proceed even without a rotator. Post PR-DRIFT-CUT there
    are no exceptions — drift never proceeds.
    """
    stub = _make_loop_stub("glm-5.1")

    monkeypatch.setattr("core.wiring.container.get_profile_rotator", lambda: None)
    monkeypatch.setattr("core.agent.loop._resolve_provider", lambda m: "glm")

    fake_settings = MagicMock(model="glm-4.7-flash")
    with patch("core.config.settings", fake_settings):
        changed = asyncio.run(stub._sync_model_from_settings_async())

    assert changed is False
    stub.update_model_async.assert_not_awaited()


def test_drift_no_op_when_models_match(monkeypatch) -> None:
    """settings.model == loop.model → no-op, no rotator call."""
    stub = _make_loop_stub("glm-5.1")
    fake_rotator = MagicMock()

    monkeypatch.setattr("core.wiring.container.get_profile_rotator", lambda: fake_rotator)

    fake_settings = MagicMock(model="glm-5.1")
    with patch("core.config.settings", fake_settings):
        changed = asyncio.run(stub._sync_model_from_settings_async())

    assert changed is False
    fake_rotator.resolve.assert_not_called()
    stub.update_model_async.assert_not_called()
