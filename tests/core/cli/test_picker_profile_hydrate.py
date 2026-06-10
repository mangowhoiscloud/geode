"""Guard: /model picker hydrates auth profiles in the thin CLI (v0.99.176).

The interactive picker runs in the thin CLI process, which never runs the
wiring bootstrap — so the profile store is empty and ``model_available()``
returns False for EVERY model. The picker then treats Enter on any entry as
a blocked-Enter and reports ``Cancelled``, so no switch ever lands even
though the daemon is authenticated. ``_ensure_profiles_hydrated`` loads
``~/.geode/auth.toml`` before availability is evaluated.
"""

from __future__ import annotations

import inspect

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


def test_interactive_picker_hydrates_before_availability() -> None:
    source = inspect.getsource(model_mod._interactive_model_picker)
    # hydrate must come before the model_available evaluation
    assert "_ensure_profiles_hydrated()" in source
    assert source.index("_ensure_profiles_hydrated()") < source.index("model_available(")


def test_role_picker_hydrates_before_availability() -> None:
    source = inspect.getsource(model_mod._interactive_model_picker_for_role)
    assert "_ensure_profiles_hydrated()" in source
    assert source.index("_ensure_profiles_hydrated()") < source.index("model_available(")
