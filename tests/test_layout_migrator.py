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

    # v2→v3 archives runs/vault/projects under GEODE_HOME. The constants
    # were captured at core.paths import time bound to the *real*
    # ``~/.geode/``, so monkeypatching ``GEODE_HOME`` alone is not enough
    # — we also have to redirect the derived paths to ``tmp_path``.
    monkeypatch.setattr("core.paths.GLOBAL_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("core.paths.GLOBAL_VAULT_DIR", tmp_path / "vault")
    monkeypatch.setattr("core.paths.GLOBAL_PROJECTS_DIR", tmp_path / "projects")

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

    def test_full_chain_on_fresh_install(self, fake_geode_home: Path) -> None:
        """Pre-versioned install runs every step in one pass and ends at
        the current target marker."""
        from core.wiring.layout_migrator import (
            GEODE_LAYOUT_VERSION,
            ensure_layout_migrated,
            read_layout_version,
        )

        report = ensure_layout_migrated(force=True)
        step_names = [s.name for s in report.steps]
        assert any(n.startswith("v0→v1") for n in step_names)
        assert any(n.startswith("v1→v2") for n in step_names)
        assert any(n.startswith("v2→v3") for n in step_names)
        assert read_layout_version() == GEODE_LAYOUT_VERSION

    def test_constants_removed_from_paths(self, fake_geode_home: Path) -> None:
        """Sanity — the two vestigial constants must no longer exist on
        ``core.paths`` (P1 sloppiness cleanup)."""
        from core import paths

        assert not hasattr(paths, "PROJECT_EMBEDDING_CACHE")
        assert not hasattr(paths, "PROJECT_VECTORS_DIR")


# ---------------------------------------------------------------------------
# v2 → v3: TTL-based archival of runs/, vault/, projects/
# ---------------------------------------------------------------------------


class TestV2ToV3TTLArchival:
    """v2→v3 — children of `runs/`, `vault/{general,research}/`, and
    `projects/` older than the TTL are moved to a monthly bucket under
    `_archive/<YYYY-MM>/`. No writer changes; one-shot sweep gated by
    the version marker."""

    @staticmethod
    def _age_by_days(path: Path, days: float) -> None:
        """Set ``mtime`` (and ``atime``) on ``path`` to ``days`` ago."""
        import os
        import time as _time

        when = _time.time() - days * 86400.0
        os.utime(path, (when, when))

    def test_runs_old_files_archived_into_monthly_bucket(self, fake_geode_home: Path) -> None:
        runs_dir = fake_geode_home / "runs"
        runs_dir.mkdir(parents=True)
        old = runs_dir / "run-old.jsonl"
        old.write_text('{"trace": "old"}')
        self._age_by_days(old, days=90)
        fresh = runs_dir / "run-fresh.jsonl"
        fresh.write_text('{"trace": "fresh"}')

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        assert not old.exists()
        assert fresh.exists()
        archive = runs_dir / "_archive"
        buckets = list(archive.iterdir())
        assert len(buckets) == 1
        assert len(buckets[0].name) == 7 and buckets[0].name[4] == "-"  # YYYY-MM
        assert (buckets[0] / "run-old.jsonl").exists()

    def test_vault_general_and_research_both_archived(self, fake_geode_home: Path) -> None:
        general = fake_geode_home / "vault" / "general"
        research = fake_geode_home / "vault" / "research"
        general.mkdir(parents=True)
        research.mkdir(parents=True)
        old_g = general / "g-old.md"
        old_r = research / "r-old.md"
        old_g.write_text("g")
        old_r.write_text("r")
        self._age_by_days(old_g, days=60)
        self._age_by_days(old_r, days=60)

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        assert not old_g.exists()
        assert not old_r.exists()
        # Each scope keeps its own _archive bucket.
        assert any((general / "_archive").iterdir())
        assert any((research / "_archive").iterdir())

    def test_projects_stale_workspace_dir_archived(self, fake_geode_home: Path) -> None:
        projects = fake_geode_home / "projects"
        stale = projects / "encoded-cwd-stale"
        stale.mkdir(parents=True)
        (stale / "marker").write_text("x")
        self._age_by_days(stale, days=90)
        active = projects / "encoded-cwd-active"
        active.mkdir(parents=True)

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        assert not stale.exists()
        assert active.exists()
        archived_buckets = list((projects / "_archive").iterdir())
        assert len(archived_buckets) == 1
        assert (archived_buckets[0] / "encoded-cwd-stale").exists()

    def test_ttl_respected_default_30_days(self, fake_geode_home: Path) -> None:
        runs_dir = fake_geode_home / "runs"
        runs_dir.mkdir(parents=True)
        just_inside = runs_dir / "29-days-old"
        just_inside.write_text("a")
        self._age_by_days(just_inside, days=29)
        just_outside = runs_dir / "31-days-old"
        just_outside.write_text("b")
        self._age_by_days(just_outside, days=31)

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        assert just_inside.exists(), "29-day-old file must NOT be archived"
        assert not just_outside.exists(), "31-day-old file must be archived"

    def test_env_var_overrides_ttl(
        self, fake_geode_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEODE_ARCHIVE_TTL_DAYS", "5")
        runs_dir = fake_geode_home / "runs"
        runs_dir.mkdir(parents=True)
        seven_day = runs_dir / "7-day"
        seven_day.write_text("c")
        self._age_by_days(seven_day, days=7)

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        assert not seven_day.exists(), "7-day-old file must be archived when TTL=5"

    def test_bad_env_var_falls_back_to_default(
        self, fake_geode_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEODE_ARCHIVE_TTL_DAYS", "not-a-number")
        runs_dir = fake_geode_home / "runs"
        runs_dir.mkdir(parents=True)
        ten_day = runs_dir / "10-day"
        ten_day.write_text("d")
        self._age_by_days(ten_day, days=10)

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        # Fallback to 30-day default → 10-day file stays.
        assert ten_day.exists()

    def test_absent_directories_skip_cleanly(self, fake_geode_home: Path) -> None:
        """Fresh install with no runs/vault/projects → step records skips
        and emits no warnings besides the TTL banner."""
        from core.wiring.layout_migrator import ensure_layout_migrated

        report = ensure_layout_migrated(force=True)
        step = next(s for s in report.steps if s.name.startswith("v2→v3"))
        assert step.moved == []
        assert len(step.skipped) >= 4  # runs, vault/general, vault/research, projects

    def test_archive_root_is_not_self_archived(self, fake_geode_home: Path) -> None:
        """The migration must not eat its own ``_archive`` directory even
        if its mtime drifts past the TTL."""
        runs_dir = fake_geode_home / "runs"
        runs_dir.mkdir(parents=True)
        archive = runs_dir / "_archive"
        archive.mkdir()
        self._age_by_days(archive, days=365)

        from core.wiring.layout_migrator import ensure_layout_migrated

        ensure_layout_migrated(force=True)

        assert archive.exists()
        assert archive.is_dir()
        # Nothing nested into itself.
        assert not (archive / "_archive").exists()

    def test_v2_to_v3_idempotent_on_rerun(self, fake_geode_home: Path) -> None:
        """A second `force=True` run after archival completes must not
        re-archive (marker is at v3, no work)."""
        runs_dir = fake_geode_home / "runs"
        runs_dir.mkdir(parents=True)
        old = runs_dir / "x"
        old.write_text("x")
        self._age_by_days(old, days=90)

        from core.wiring.layout_migrator import ensure_layout_migrated

        first = ensure_layout_migrated(force=True)
        second = ensure_layout_migrated(force=True)

        v3_first = [s for s in first.steps if s.name.startswith("v2→v3")]
        v3_second = [s for s in second.steps if s.name.startswith("v2→v3")]
        assert len(v3_first[0].moved) == 1
        assert second.no_op is True
        assert v3_second == []


class TestV3ToV4MessagesBackfill:
    """v4 — backfill ``messages.json`` of every existing session into the
    SQLite ``messages`` table introduced in PR #1151."""

    def _make_session(
        self,
        fake_geode_home: Path,
        project: str,
        session_id: str,
        messages: list[dict[str, str]] | str,
    ) -> Path:
        sessions_dir = fake_geode_home / "projects" / project / "sessions"
        session_dir = sessions_dir / session_id
        session_dir.mkdir(parents=True)
        msg_file = session_dir / "messages.json"
        if isinstance(messages, str):
            msg_file.write_text(messages, encoding="utf-8")  # corrupt
        else:
            import json as _json

            msg_file.write_text(_json.dumps(messages), encoding="utf-8")
        return sessions_dir / "sessions.db"

    def test_v3_to_v4_backfills_pre_phase_1a_session(self, fake_geode_home: Path) -> None:
        from core.memory.session_manager import SessionManager
        from core.wiring.layout_migrator import ensure_layout_migrated

        # Pre-PR #1151 session: only messages.json exists, DB has nothing.
        db_path = self._make_session(
            fake_geode_home,
            "alpha",
            "sess-1",
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "ok"},
            ],
        )

        report = ensure_layout_migrated(force=True)

        v4 = [s for s in report.steps if s.name.startswith("v3→v4")]
        assert v4, "v3→v4 step must run"

        mgr = SessionManager(db_path=db_path)
        try:
            assert mgr.count_messages("sess-1") == 2
        finally:
            mgr.close()

    def test_v3_to_v4_skips_corrupt_messages_json(self, fake_geode_home: Path) -> None:
        """A single corrupt session must NOT block the rest of the migration."""
        from core.memory.session_manager import SessionManager
        from core.wiring.layout_migrator import ensure_layout_migrated

        # One good session, one corrupt — both under the same project.
        db_path = self._make_session(
            fake_geode_home,
            "alpha",
            "good",
            [{"role": "user", "content": "ok"}],
        )
        self._make_session(
            fake_geode_home,
            "alpha",
            "bad",
            "{not valid json",
        )

        report = ensure_layout_migrated(force=True)

        v4 = [s for s in report.steps if s.name.startswith("v3→v4")]
        assert v4
        assert any("corrupt" in w for w in v4[0].warnings)

        mgr = SessionManager(db_path=db_path)
        try:
            assert mgr.count_messages("good") == 1
            assert mgr.count_messages("bad") == 0
        finally:
            mgr.close()

    def test_v3_to_v4_idempotent(self, fake_geode_home: Path) -> None:
        """Re-running the migration on an already-migrated session is a no-op
        (UNIQUE(session_id, seq) makes upsert_messages safe)."""
        from core.memory.session_manager import SessionManager
        from core.wiring.layout_migrator import ensure_layout_migrated

        db_path = self._make_session(
            fake_geode_home,
            "alpha",
            "idem",
            [{"role": "user", "content": "x"}],
        )

        ensure_layout_migrated(force=True)
        ensure_layout_migrated(force=True)  # second run

        mgr = SessionManager(db_path=db_path)
        try:
            assert mgr.count_messages("idem") == 1
        finally:
            mgr.close()

    def test_v3_to_v4_no_op_on_fresh_install(self, fake_geode_home: Path) -> None:
        """No projects/ dir → step records ``skipped`` reason, no error."""
        from core.wiring.layout_migrator import ensure_layout_migrated

        report = ensure_layout_migrated(force=True)
        v4 = [s for s in report.steps if s.name.startswith("v3→v4")]
        assert v4
        assert any("projects/ dir absent" in s for s in v4[0].skipped)
