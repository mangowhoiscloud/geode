"""PR-MEMORY-LIFECYCLE — ``geode memory-lifecycle`` CLI invariants.

Registered on the main Typer app; dry-run by default (no file moves, no
proposal writes); ``--apply`` moves archived entries.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.cli import app
from typer.testing import CliRunner


class _FakeSessionManager:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def list_context_artifacts(self, *, kinds=None, limit=20, session_id=None):
        return []

    def close(self) -> None:
        pass


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fixture project with one resolved memory entry + its guard test."""
    memory_dir = tmp_path / ".geode" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "resolved.md").write_text(
        "---\n"
        "name: resolved\n"
        "description: cron double fire\n"
        "resolution:\n"
        '  pr: "#2400"\n'
        "  guard_test: tests/test_guard.py::test_cron_dedup\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_guard.py").write_text("def test_cron_dedup():\n    pass\n", "utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("core.memory.session_manager.SessionManager", _FakeSessionManager)
    return tmp_path


def test_command_registered_on_app():
    registered = [c.name for c in app.registered_commands]
    assert "memory-lifecycle" in registered


def test_dry_run_default_moves_nothing(project: Path):
    result = CliRunner().invoke(app, ["memory-lifecycle"])
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output
    assert "archived" in result.output
    # Dry-run: the entry stays active, nothing archived, no proposals dir.
    assert (project / ".geode" / "memory" / "resolved.md").exists()
    assert not (project / ".geode" / "memory" / "_archive").exists()
    assert not (project / ".geode" / "memory" / "_proposals").exists()


def test_apply_moves_resolved_entry_to_archive(project: Path, monkeypatch: pytest.MonkeyPatch):
    # Keep the test hermetic: real bootstrap wires the project event database;
    # a bare HookSystem is enough for the emit path.
    from core.hooks import HookSystem

    monkeypatch.setattr(
        "core.wiring.bootstrap.build_hooks",
        lambda **_kwargs: (HookSystem(), None, None),
    )
    result = CliRunner().invoke(app, ["memory-lifecycle", "--apply"])
    assert result.exit_code == 0, result.output
    assert (project / ".geode" / "memory" / "_archive" / "resolved.md").exists()
    assert not (project / ".geode" / "memory" / "resolved.md").exists()
