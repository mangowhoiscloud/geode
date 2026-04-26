"""Bug class B3 — model drift sync must check target health.

The v0.52.1 incident: User completed `/login oauth openai` (Codex Plus
registered). Same session immediately started a new prompt. Settings
store still pointed at the old `glm-4.7-flash`. Loop started with
`glm-5.1`, detected drift, **silently overwrote loop's choice with
`glm-4.7-flash`** even though GLM had no quota left. Result: 5×4 retry
storm on a model the user did not pick and which had no available
profile.

Invariant: ``_sync_model_from_settings()`` must consult
``ProfileRotator.resolve(target_provider)`` and **refuse** the drift
when the rotator returns None (no eligible profile for the target).
The loop's currently-chosen model is preserved instead.

Pattern source: OpenClaw ``evaluate_eligibility`` + ``_LAST_VERDICTS``
cached health view (referenced in `core/auth/rotation.py`,
`core/auth/profiles.py:176`).
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import core.agent.loop as _loop_mod

# ---------------------------------------------------------------------------
# Contract 1 — _sync_model_from_settings consults rotator before update_model
# ---------------------------------------------------------------------------


def test_sync_calls_health_check_before_update() -> None:
    """Source-level: the drift branch must call ``_drift_target_is_healthy``
    before ``self.update_model`` so an unhealthy drift target cannot
    silently overwrite the loop's choice."""
    src = inspect.getsource(_loop_mod.AgenticLoop._sync_model_from_settings)
    health_pos = src.find("_drift_target_is_healthy")
    update_pos = src.find("self.update_model")
    assert health_pos >= 0, (
        "_sync_model_from_settings must call _drift_target_is_healthy. "
        "Without the check the v0.51-incident regression returns: stale "
        "settings.model overwrites loop.model when target is unhealthy."
    )
    assert update_pos >= 0
    assert health_pos < update_pos, (
        "Health check must come BEFORE update_model — otherwise we swap "
        "the adapter and only then discover there's no profile to use."
    )


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
    stub.update_model = MagicMock()
    # Bind the real methods to the stub so we exercise the patched logic.
    stub._sync_model_from_settings = _loop_mod.AgenticLoop._sync_model_from_settings.__get__(stub)
    stub._drift_target_is_healthy = _loop_mod.AgenticLoop._drift_target_is_healthy.__get__(stub)
    return stub


def test_drift_refused_when_rotator_returns_none(monkeypatch) -> None:
    """End-to-end: settings.model='glm-4.7-flash', loop.model='glm-5.1'.
    Rotator.resolve('glm') → None (no profile). Drift must be refused;
    update_model must NOT be called."""
    stub = _make_loop_stub("glm-5.1")

    fake_rotator = MagicMock()
    fake_rotator.resolve.return_value = None  # no eligible profile

    monkeypatch.setattr("core.lifecycle.container.get_profile_rotator", lambda: fake_rotator)
    monkeypatch.setattr("core.agent.loop._resolve_provider", lambda m: "glm")

    fake_settings = MagicMock(model="glm-4.7-flash")
    with patch("core.config.settings", fake_settings):
        changed = stub._sync_model_from_settings()

    assert changed is False
    stub.update_model.assert_not_called()


def test_drift_accepted_when_rotator_returns_profile(monkeypatch) -> None:
    """Same setup but rotator returns a valid profile → drift proceeds."""
    stub = _make_loop_stub("glm-5.1")

    fake_rotator = MagicMock()
    fake_rotator.resolve.return_value = MagicMock(name="profile")

    monkeypatch.setattr("core.lifecycle.container.get_profile_rotator", lambda: fake_rotator)
    monkeypatch.setattr("core.agent.loop._resolve_provider", lambda m: "glm")

    fake_settings = MagicMock(model="glm-4.7-flash")
    with patch("core.config.settings", fake_settings):
        changed = stub._sync_model_from_settings()

    assert changed is True
    stub.update_model.assert_called_once_with("glm-4.7-flash")


def test_drift_accepted_when_rotator_not_initialised(monkeypatch) -> None:
    """Early bootstrap: rotator singleton is None. Drift must NOT be blocked
    (would prevent legitimate model switches before bootstrap completes).
    """
    stub = _make_loop_stub("glm-5.1")

    monkeypatch.setattr("core.lifecycle.container.get_profile_rotator", lambda: None)
    monkeypatch.setattr("core.agent.loop._resolve_provider", lambda m: "glm")

    fake_settings = MagicMock(model="glm-4.7-flash")
    with patch("core.config.settings", fake_settings):
        changed = stub._sync_model_from_settings()

    assert changed is True
    stub.update_model.assert_called_once()


def test_drift_no_op_when_models_match(monkeypatch) -> None:
    """settings.model == loop.model → no-op, no rotator call."""
    stub = _make_loop_stub("glm-5.1")
    fake_rotator = MagicMock()

    monkeypatch.setattr("core.lifecycle.container.get_profile_rotator", lambda: fake_rotator)

    fake_settings = MagicMock(model="glm-5.1")
    with patch("core.config.settings", fake_settings):
        changed = stub._sync_model_from_settings()

    assert changed is False
    fake_rotator.resolve.assert_not_called()
    stub.update_model.assert_not_called()
