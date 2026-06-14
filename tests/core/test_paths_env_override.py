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


def test_state_root_unset_splits_tracked_in_repo_from_runtime_home(
    monkeypatch: pytest.MonkeyPatch, reload_paths: None
) -> None:
    """DEFAULT (no GEODE_STATE_ROOT): tracked SoT is in-repo, runtime is ~/.geode.

    PR-STATE-SOT-RUNTIME-SPLIT — the persistent default splits by lifecycle so a
    worktree/clone never scatters runtime scratch into git, nor vanishes the
    tracked ledger/policies.
    """
    monkeypatch.delenv("GEODE_STATE_ROOT", raising=False)
    importlib.reload(paths)
    # Tracked SoT colocated with its package, in-repo.
    assert paths.SELF_IMPROVING_SOT_DIR.parts[-3:] == ("core", "self_improving", "state")
    assert paths.MUTATION_AUDIT_LOG_PATH.is_relative_to(paths.SELF_IMPROVING_SOT_DIR)
    # Runtime baseline OUT of the repo, under ~/.geode.
    assert paths.RUNTIME_ROOT == paths.GEODE_HOME / "self-improving"
    assert paths.BASELINE_JSON_PATH.is_relative_to(paths.GEODE_HOME)
    assert not paths.BASELINE_JSON_PATH.is_relative_to(paths.SELF_IMPROVING_SOT_DIR)


def test_state_root_set_colocates_tracked_and_runtime_for_worker_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reload_paths: None
) -> None:
    """ISOLATION (GEODE_STATE_ROOT set): tracked SoT AND runtime collapse to
    ``$GEODE_STATE_ROOT/autoresearch`` so a campaign worker's reads/writes land in
    its own seeded tree — restoring the pre-split single-knob isolation that
    ``campaign._seed_isolated_state_root`` (``<root>/autoresearch/{policies,
    baseline.json}``) depends on. Regression guard: a fixed in-repo SoT would make
    concurrent workers race + pollute the git-tracked mutations.jsonl, and read
    baseline.json from the wrong place.
    """
    worker_root = tmp_path / "w0"
    monkeypatch.setenv("GEODE_STATE_ROOT", str(worker_root))
    importlib.reload(paths)
    iso = worker_root / "autoresearch"
    # Tracked + runtime co-locate under the worker root's autoresearch/ subdir
    # (the literal must match campaign._seed_isolated_state_root's layout).
    assert iso == paths.SELF_IMPROVING_SOT_DIR
    assert iso == paths.RUNTIME_ROOT
    assert iso / "mutations.jsonl" == paths.MUTATION_AUDIT_LOG_PATH
    assert iso / "baseline.json" == paths.BASELINE_JSON_PATH
    assert iso / "policies" == paths.AUTORESEARCH_POLICIES_DIR
    # STATE_ROOT stays the RAW env root (back-compat contract).
    assert worker_root == paths.STATE_ROOT


def test_seed_pools_always_repo_pinned_even_under_state_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reload_paths: None
) -> None:
    """Seed pools are git-tracked campaign INPUT (operator decision D-3): ALWAYS
    in-repo, never under ``GEODE_STATE_ROOT`` — so an isolated worker still reads
    the real tracked pools, not an empty seeded tree."""
    monkeypatch.setenv("GEODE_STATE_ROOT", str(tmp_path / "w0"))
    importlib.reload(paths)
    assert paths.SEED_POOLS_DIR.parts[-4:] == ("core", "self_improving", "state", "seed_pools")
    assert not paths.SEED_POOLS_DIR.is_relative_to(tmp_path)
