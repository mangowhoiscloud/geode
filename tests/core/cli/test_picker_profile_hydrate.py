"""Guard: /model picker hydrates auth profiles in the thin CLI (v0.99.176).

The interactive picker runs in the thin CLI process, which never runs the
wiring bootstrap — so the profile store is empty and ``model_available()``
returns False for EVERY model. The picker then treats Enter on any entry as
a blocked-Enter and reports ``Cancelled``, so no switch ever lands even
though the daemon is authenticated. ``_ensure_profiles_hydrated`` loads
``~/.geode/auth.toml`` before availability is evaluated.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from core.cli.commands import model as model_mod


def test_ensure_profiles_hydrated_calls_ensure_profile_store(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "core.wiring.container.ensure_profile_store",
        lambda: calls.append("hit"),
    )
    model_mod._ensure_profiles_hydrated()
    assert calls == ["hit"]


def test_ensure_profiles_hydrated_is_resilient(monkeypatch) -> None:
    """A hydration failure must not crash the picker."""

    def _boom() -> None:
        raise RuntimeError("auth.toml unreadable")

    monkeypatch.setattr("core.wiring.container.ensure_profile_store", _boom)
    model_mod._ensure_profiles_hydrated()  # must not raise


@pytest.mark.parametrize("role", ["primary", "reflection"])
def test_standalone_picker_hydrates_before_availability(monkeypatch, role) -> None:
    from core.cli.commands._state import ModelProfile, role_by_name

    calls = []
    monkeypatch.setattr(model_mod, "_ensure_profiles_hydrated", lambda: calls.append("hydrate"))
    monkeypatch.setattr(
        model_mod, "_picker_profiles", lambda *a: [ModelProfile("gpt-6-sol", "openai", "test", "$")]
    )

    def available(*args, **kwargs):
        assert calls[0] == "hydrate"
        calls.append("available")
        return True

    monkeypatch.setattr(model_mod, "model_available", available)
    monkeypatch.setattr(model_mod, "model_unavailable_reason", lambda *a, **kw: None)
    monkeypatch.setattr(
        "core.cli.effort_picker.pick_model_and_effort",
        lambda *a, **kw: SimpleNamespace(cancelled=True, model_id="gpt-6-sol", role=role),
    )
    if role == "primary":
        model_mod._interactive_model_picker()
    else:
        model_mod._interactive_model_picker_for_role(role_by_name(role))
    assert "available" in calls
