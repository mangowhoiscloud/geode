"""Tests for core.paths.ensure_directories — lazy directory creation."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.paths import ensure_directories


@pytest.fixture()
def clean_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Patch all GEODE path constants to use tmp_path."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)

    geode_home = home / ".geode"

    monkeypatch.setattr("core.paths.GEODE_HOME", geode_home)
    monkeypatch.setattr("core.paths.GLOBAL_RUNS_DIR", geode_home / "runs")
    monkeypatch.setattr("core.paths.GLOBAL_VAULT_DIR", geode_home / "vault")
    monkeypatch.setattr("core.paths.GLOBAL_MODELS_DIR", geode_home / "models")
    monkeypatch.setattr("core.paths.GLOBAL_USAGE_DIR", geode_home / "usage")
    monkeypatch.setattr("core.paths.GLOBAL_MCP_DIR", geode_home / "mcp")
    monkeypatch.setattr("core.paths.GLOBAL_SCHEDULER_DIR", geode_home / "scheduler")
    monkeypatch.setattr("core.paths.GLOBAL_PROJECTS_DIR", geode_home / "projects")
    monkeypatch.setattr("core.paths.GLOBAL_USER_PROFILE_DIR", geode_home / "user_profile")

    proj_geode = Path(".geode")
    monkeypatch.setattr("core.paths.PROJECT_GEODE_DIR", proj_geode)
    monkeypatch.setattr("core.paths.PROJECT_MEMORY_DIR", proj_geode / "memory")
    monkeypatch.setattr("core.paths.PROJECT_RULES_DIR", proj_geode / "rules")
    monkeypatch.setattr("core.paths.PROJECT_SKILLS_DIR", proj_geode / "skills")
    monkeypatch.setattr("core.paths.PROJECT_REPORTS_DIR", proj_geode / "reports")
    monkeypatch.setattr("core.paths.PROJECT_SCHEDULER_LOG_DIR", proj_geode / "scheduler_logs")

    # Patch get_project_data_dir to return a temp-based path
    proj_data = geode_home / "projects" / "test-project"
    monkeypatch.setattr("core.paths.get_project_data_dir", lambda *_a, **_kw: proj_data)

    return tmp_path


class TestEnsureDirectories:
    def test_creates_global_dirs(self, clean_dirs: Path) -> None:
        ensure_directories()

        home = clean_dirs / "home" / ".geode"
        assert home.is_dir()
        assert (home / "runs").is_dir()
        assert (home / "vault").is_dir()
        assert (home / "models").is_dir()
        assert (home / "usage").is_dir()
        assert (home / "mcp").is_dir()
        assert (home / "scheduler").is_dir()
        assert (home / "projects").is_dir()
        assert not (home / "identity").exists()  # career.toml lives in user_profile/
        assert (home / "user_profile").is_dir()

    def test_does_not_scaffold_project_inputs(self, clean_dirs: Path) -> None:
        ensure_directories()
        assert list((clean_dirs / "project").iterdir()) == []

    def test_creates_project_user_dirs(self, clean_dirs: Path) -> None:
        ensure_directories()

        proj_data = clean_dirs / "home" / ".geode" / "projects" / "test-project"
        assert proj_data.is_dir()
        assert (proj_data / "journal").is_dir()
        assert (proj_data / "sessions").is_dir()
        assert not (proj_data / "snapshots").exists()  # nothing writes snapshots
        assert (proj_data / "result_cache").is_dir()

    def test_idempotent(self, clean_dirs: Path) -> None:
        ensure_directories()
        ensure_directories()  # no error on second call

        home = clean_dirs / "home" / ".geode"
        assert home.is_dir()

    @pytest.mark.parametrize("existing", [None, "node_modules\n", "# user-owned\n.geode/\n"])
    def test_project_gitignore_is_not_created_or_modified(self, clean_dirs, existing):
        gitignore = clean_dirs / "project" / ".gitignore"
        if existing is not None:
            gitignore.write_text(existing)
        ensure_directories()
        if existing is None:
            assert not gitignore.exists()
        else:
            assert gitignore.read_text() == existing
