"""PR-PATH-MODERNIZE Phase 1 — ``GEODE_HOME`` / ``GEODE_STATE_ROOT`` env overrides.

Frontier convergence: every surveyed agent CLI resolves its home dir as
``env.get({APP}_HOME) ?? ~/.{app}`` (CODEX_HOME / HERMES_HOME / OPENCLAW_HOME /
PAPERCLIP_HOME / CRUMB_HOME). GEODE's ``GEODE_HOME`` was hardcoded; this pins
the override + ``~`` expansion, and that derived ``GLOBAL_*`` constants follow.

The module evaluates its path constants at import, so each case reloads
``core.paths`` under a patched env and reloads it back to the pristine state
afterwards so no other test sees a redirected tree.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from core import paths

# Path env vars these tests patch — snapshotted/restored by the fixture.
_PATCHED_ENV = ("GEODE_HOME", "GEODE_STATE_ROOT")


@pytest.fixture
def reload_paths() -> Iterator[None]:
    """Restore the path env vars to their pre-test values, THEN reload
    ``core.paths``, so the module's import-time constants return to pristine.

    This fixture's teardown runs BEFORE ``monkeypatch``'s (teardown is
    reverse-of-setup), so we must restore the env ourselves rather than rely on
    monkeypatch — otherwise the final reload re-reads the still-patched env and
    leaks a redirected ``GEODE_HOME`` into later tests (Codex review MAJOR)."""
    saved = {k: os.environ.get(k) for k in _PATCHED_ENV}
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(paths)


def test_geode_home_env_override_redirects_global_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reload_paths: None
) -> None:
    monkeypatch.setenv("GEODE_HOME", str(tmp_path / "alt_home"))
    importlib.reload(paths)
    assert tmp_path / "alt_home" == paths.GEODE_HOME
    # A derived GLOBAL_* constant follows the single override point.
    assert tmp_path / "alt_home" / "petri.toml" == paths.GLOBAL_PETRI_TOML
    assert tmp_path / "alt_home" / "projects" == paths.GLOBAL_PROJECTS_DIR


def test_geode_home_default_is_dot_geode(
    monkeypatch: pytest.MonkeyPatch, reload_paths: None
) -> None:
    monkeypatch.delenv("GEODE_HOME", raising=False)
    importlib.reload(paths)
    assert Path.home() / ".geode" == paths.GEODE_HOME


def test_geode_home_tilde_expands(monkeypatch: pytest.MonkeyPatch, reload_paths: None) -> None:
    monkeypatch.setenv("GEODE_HOME", "~/customgeode")
    importlib.reload(paths)
    assert Path.home() / "customgeode" == paths.GEODE_HOME
    assert "~" not in str(paths.GEODE_HOME)


def test_geode_state_root_env_override_and_tilde(
    monkeypatch: pytest.MonkeyPatch, reload_paths: None
) -> None:
    monkeypatch.setenv("GEODE_STATE_ROOT", "~/altstate")
    importlib.reload(paths)
    assert Path.home() / "altstate" == paths.STATE_ROOT
    assert "~" not in str(paths.STATE_ROOT)
