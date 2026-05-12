"""Tests for ``core.wiring.layout_migrator`` — version-aware ~/.geode/ migration.

Mirrors the integration patterns Hermes uses for ``hermes_state._init_schema``
(``hermes_state.py:550-678``): idempotency, version-gating, atomic marker
write, lossless moves. We exercise the public entry point
:func:`ensure_layout_migrated` against an isolated ``tmp_path`` instead of
``~/.geode`` so tests are sandboxed and parallel-safe.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_geode_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``GEODE_HOME`` (and all derived paths) to a tmp dir.

    For v1→v2 migration, also redirect ``get_project_root`` so the
    migration step's "current workspace" lands inside the same tmp_path
    instead of the actual repo (which would archive real files).
    """
    monkeypatch.setattr("core.paths.GEODE_HOME", tmp_path)
    monkeypatch.setattr("core.wiring.layout_migrator.GEODE_HOME", tmp_path)
    monkeypatch.setattr(
        "core.wiring.layout_migrator.LAYOUT_VERSION_FILE",
        tmp_path / ".layout-version",
    )

    # Project root → a workspace inside tmp_path. v1→v2 migration archives
    # things under {workspace}/.geode/_archive so we want the workspace to
    # be sandboxed too.
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("core.paths.get_project_root", lambda: workspace)

    # Reset the once-per-process guard so each test starts fresh.
    from core.wiring.layout_migrator import reset_migration_guard

    reset_migration_guard()
    yield tmp_path
    reset_migration_guard()


class TestVersionMarker:
    """`.layout-version` dotfile read/write — Hermes ``schema_version``
    table analog."""

    def test_absent_marker_returns_zero(self, fake_geode_home: Path) -> None:
        from core.wiring.layout_migrator import read_layout_version

        assert read_layout_version() == 0

    def test_write_then_read_round_trip(self, fake_geode_home: Path) -> None:
        from core.wiring.layout_migrator import read_layout_version, write_layout_version

        write_layout_version(7)
        assert read_layout_version() == 7
        # Atomic write — no leftover .tmp
        assert not (fake_geode_home / ".layout-version.tmp").exists()

    def test_corrupt_marker_treated_as_zero(self, fake_geode_home: Path) -> None:
        """Hermes idempotency rule — never crash bootstrap on a bad marker."""
        from core.wiring.layout_migrator import read_layout_version

        (fake_geode_home / ".layout-version").write_text("not-a-number")
        assert read_layout_version() == 0


class TestEnsureLayoutMigrated:
    """Public entry point — bootstrap call site."""

    def test_no_op_when_already_at_target(self, fake_geode_home: Path) -> None:
        from core.wiring.layout_migrator import (
            GEODE_LAYOUT_VERSION,
            ensure_layout_migrated,
            write_layout_version,
        )

        write_layout_version(GEODE_LAYOUT_VERSION)
        report = ensure_layout_migrated(force=True)
        assert report.no_op is True
        assert report.steps == []

    def test_disable_env_var_skips_migration(
        self, fake_geode_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.wiring.layout_migrator import (
            DISABLE_ENV_VAR,
            ensure_layout_migrated,
        )

        monkeypatch.setenv(DISABLE_ENV_VAR, "1")
        report = ensure_layout_migrated(force=True)
        assert report.disabled is True
        # Marker file must NOT be created when migration is disabled.
        assert not (fake_geode_home / ".layout-version").exists()

    def test_idempotent_within_process(self, fake_geode_home: Path) -> None:
        """Second call in the same process returns a no-op report (mirrors
        ``autoMigrateStateDirChecked`` + Hermes ``_bootstrap_applied``)."""
        from core.wiring.layout_migrator import ensure_layout_migrated

        first = ensure_layout_migrated()
        second = ensure_layout_migrated()
        assert first.no_op is False or first.steps  # something happened OR fresh+empty
        assert second.no_op is True

    def test_fresh_install_writes_marker_at_target(self, fake_geode_home: Path) -> None:
        from core.wiring.layout_migrator import (
            GEODE_LAYOUT_VERSION,
            ensure_layout_migrated,
            read_layout_version,
        )

        report = ensure_layout_migrated(force=True)
        assert report.from_version == 0
        assert report.to_version == GEODE_LAYOUT_VERSION
        assert read_layout_version() == GEODE_LAYOUT_VERSION


class TestV0ToV1PathReconciliation:
    """v0→v1 — three documented path mismatches in legacy ``~/.geode/``."""

    def test_serve_log_relocated(self, fake_geode_home: Path) -> None:
        legacy = fake_geode_home / "serve.log"
        legacy.write_text("legacy serve content")

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        assert not legacy.exists()
        new_path = fake_geode_home / "logs" / "serve.log"
        assert new_path.exists()
        assert new_path.read_text() == "legacy serve content"

    def test_approve_history_renamed(self, fake_geode_home: Path) -> None:
        """paths.py-side typo (``approve_history.json``) reconciled with
        the actual writer's name (``approval_history.jsonl``)."""
        legacy = fake_geode_home / "approve_history.json"
        legacy.write_text("{}")

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        assert not legacy.exists()
        assert (fake_geode_home / "approval_history.jsonl").exists()

    def test_mcp_registry_cache_relocated(self, fake_geode_home: Path) -> None:
        legacy = fake_geode_home / "mcp-registry-cache.json"
        legacy.write_text('{"servers": []}')

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        assert not legacy.exists()
        new_path = fake_geode_home / "mcp" / "registry-cache.json"
        assert new_path.exists()
        assert new_path.read_text() == '{"servers": []}'

    def test_conflict_left_for_manual_review(self, fake_geode_home: Path) -> None:
        """When both legacy and destination exist, leave both in place +
        emit a warning. Never overwrite user data."""
        legacy = fake_geode_home / "serve.log"
        new = fake_geode_home / "logs" / "serve.log"
        new.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("old")
        new.write_text("new")

        from core.wiring.layout_migrator import ensure_layout_migrated

        report = ensure_layout_migrated(force=True)

        assert legacy.exists()
        assert new.exists()
        assert new.read_text() == "new"  # untouched
        # Warning surfaced in the step report
        step = next(s for s in report.steps if s.name.startswith("v0→v1"))
        assert any("manual review" in w for w in step.warnings)

    def test_missing_legacy_files_skip_silently(self, fake_geode_home: Path) -> None:
        """Fresh install with no legacy files — should run cleanly + record skips."""
        from core.wiring.layout_migrator import ensure_layout_migrated

        report = ensure_layout_migrated(force=True)
        step = next(s for s in report.steps if s.name.startswith("v0→v1"))
        # All three sources are absent → three skipped entries
        assert len(step.skipped) == 3
        assert step.moved == []
        assert step.warnings == []


class TestV1ToV2VestigialArchival:
    """v1→v2 — archive `.geode/embedding-cache/` and `.geode/vectors/`
    (no writer since 2026-04-05) under `.geode/_archive/` for safe review."""

    def _workspace(self, fake_geode_home: Path) -> Path:
        """Return the sandbox workspace that the fixture patched
        `get_project_root` to return."""
        return fake_geode_home / "workspace"

    def test_archives_populated_embedding_cache(self, fake_geode_home: Path) -> None:
        workspace = self._workspace(fake_geode_home)
        src = workspace / ".geode" / "embedding-cache"
        src.mkdir(parents=True)
        (src / "old-cache.bin").write_bytes(b"junk")

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        # Source moved
        assert not src.exists()
        # Archive contains exactly one timestamped dir whose name starts with
        # the original directory name (`embedding-cache-<UTC>`).
        archive = workspace / ".geode" / "_archive"
        moved = list(archive.iterdir())
        assert len(moved) == 1
        assert moved[0].name.startswith("embedding-cache-")
        assert (moved[0] / "old-cache.bin").exists()

    def test_archives_populated_vectors(self, fake_geode_home: Path) -> None:
        workspace = self._workspace(fake_geode_home)
        src = workspace / ".geode" / "vectors"
        src.mkdir(parents=True)
        (src / "index.faiss").write_bytes(b"stub")

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        assert not src.exists()
        archive = workspace / ".geode" / "_archive"
        moved = list(archive.iterdir())
        assert any(d.name.startswith("vectors-") for d in moved)

    def test_archives_both_when_both_present(self, fake_geode_home: Path) -> None:
        workspace = self._workspace(fake_geode_home)
        (workspace / ".geode" / "embedding-cache").mkdir(parents=True)
        (workspace / ".geode" / "embedding-cache" / "a").write_text("x")
        (workspace / ".geode" / "vectors").mkdir(parents=True)
        (workspace / ".geode" / "vectors" / "b").write_text("y")

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        archive = workspace / ".geode" / "_archive"
        names = sorted(d.name.split("-")[0] for d in archive.iterdir())
        assert names == ["embedding", "vectors"]

    def test_empty_dir_is_rmdir_not_archived(self, fake_geode_home: Path) -> None:
        """Empty vestigial dir gets `rmdir`'d — no archive entry."""
        workspace = self._workspace(fake_geode_home)
        src = workspace / ".geode" / "embedding-cache"
        src.mkdir(parents=True)

        from core.wiring.layout_migrator import ensure_layout_migrated

        report = ensure_layout_migrated(force=True)

        assert not src.exists()
        assert not (workspace / ".geode" / "_archive").exists()
        step = next(s for s in report.steps if s.name.startswith("v1→v2"))
        moved_destinations = [dst for _, dst in step.moved]
        assert any("empty" in d for d in moved_destinations)

    def test_absent_dirs_skip_silently(self, fake_geode_home: Path) -> None:
        """Fresh install with no vestigial dirs — both candidates skipped."""
        workspace = self._workspace(fake_geode_home)
        (workspace / ".geode").mkdir(parents=True)

        from core.wiring.layout_migrator import ensure_layout_migrated

        report = ensure_layout_migrated(force=True)
        step = next(s for s in report.steps if s.name.startswith("v1→v2"))
        assert step.moved == []
        assert step.warnings == []
        assert len(step.skipped) == 2

    def test_no_geode_dir_short_circuits(self, fake_geode_home: Path) -> None:
        """If the workspace has no .geode/ at all, the step skips entirely."""
        # Workspace exists but no .geode/ in it
        from core.wiring.layout_migrator import ensure_layout_migrated

        report = ensure_layout_migrated(force=True)
        step = next(s for s in report.steps if s.name.startswith("v1→v2"))
        assert step.moved == []
        # Single skipped entry — the .geode/ short-circuit
        assert any(".geode/" in s for s in step.skipped)

    def test_full_v0_to_v2_chain_on_fresh_install(self, fake_geode_home: Path) -> None:
        """Pre-versioned install runs both v0→v1 and v1→v2 in one pass and
        ends at the target marker."""
        from core.wiring.layout_migrator import (
            GEODE_LAYOUT_VERSION,
            ensure_layout_migrated,
            read_layout_version,
        )

        report = ensure_layout_migrated(force=True)
        step_names = [s.name for s in report.steps]
        assert any(n.startswith("v0→v1") for n in step_names)
        assert any(n.startswith("v1→v2") for n in step_names)
        assert read_layout_version() == GEODE_LAYOUT_VERSION == 2

    def test_constants_removed_from_paths(self, fake_geode_home: Path) -> None:
        """Sanity — the two vestigial constants must no longer exist on
        ``core.paths`` (P1 sloppiness cleanup)."""
        from core import paths

        assert not hasattr(paths, "PROJECT_EMBEDDING_CACHE")
        assert not hasattr(paths, "PROJECT_VECTORS_DIR")
