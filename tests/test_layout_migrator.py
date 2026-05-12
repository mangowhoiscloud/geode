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
    """Redirect ``GEODE_HOME`` (and all derived paths) to a tmp dir."""
    # Both the constant and the live reference in layout_migrator/paths must
    # point at tmp_path so reads + writes land in the sandbox.
    monkeypatch.setattr("core.paths.GEODE_HOME", tmp_path)
    monkeypatch.setattr("core.wiring.layout_migrator.GEODE_HOME", tmp_path)
    monkeypatch.setattr(
        "core.wiring.layout_migrator.LAYOUT_VERSION_FILE",
        tmp_path / ".layout-version",
    )

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
