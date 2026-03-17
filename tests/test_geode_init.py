"""Tests for `geode init` subcommand."""

from unittest.mock import patch

from core.cli import app
from typer.testing import CliRunner

runner = CliRunner()

# The init command does lazy imports: `from core.memory.user_profile import FileBasedUserProfile`
# We must patch at the source module, not at core.cli.
_PATCH_USER_PROFILE = "core.memory.user_profile.FileBasedUserProfile"


def _mock_user_profile():
    """Create a patch context that mocks FileBasedUserProfile."""
    return patch(_PATCH_USER_PROFILE)


class TestGeodeInit:
    def test_creates_geode_directories(self, tmp_path, monkeypatch):
        """init creates .geode/ subdirectories."""
        monkeypatch.chdir(tmp_path)
        with _mock_user_profile() as mock_cls:
            mock_cls.return_value.ensure_structure.return_value = False
            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        for subdir in ["snapshots", "reports", "result_cache", "models", "sessions"]:
            assert (tmp_path / ".geode" / subdir).is_dir()

    def test_creates_config_toml(self, tmp_path, monkeypatch):
        """init creates .geode/config.toml with template content."""
        monkeypatch.chdir(tmp_path)
        with _mock_user_profile() as mock_cls:
            mock_cls.return_value.ensure_structure.return_value = False
            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        config_path = tmp_path / ".geode" / "config.toml"
        assert config_path.exists()
        content = config_path.read_text(encoding="utf-8")
        assert "[llm]" in content
        assert "[pipeline]" in content

    def test_does_not_overwrite_existing_config(self, tmp_path, monkeypatch):
        """init preserves existing config.toml without --force."""
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".geode" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("# custom config\n", encoding="utf-8")

        with _mock_user_profile() as mock_cls:
            mock_cls.return_value.ensure_structure.return_value = False
            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert config_path.read_text(encoding="utf-8") == "# custom config\n"

    def test_force_overwrites_config(self, tmp_path, monkeypatch):
        """init --force overwrites existing config.toml."""
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".geode" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("# old config\n", encoding="utf-8")

        with _mock_user_profile() as mock_cls:
            mock_cls.return_value.ensure_structure.return_value = False
            result = runner.invoke(app, ["init", "--force"])

        assert result.exit_code == 0, result.output
        content = config_path.read_text(encoding="utf-8")
        assert "[llm]" in content  # template content, not "# old config"

    def test_idempotent_run(self, tmp_path, monkeypatch):
        """Running init twice does not error."""
        monkeypatch.chdir(tmp_path)
        with _mock_user_profile() as mock_cls:
            mock_cls.return_value.ensure_structure.return_value = False
            result1 = runner.invoke(app, ["init"])
            result2 = runner.invoke(app, ["init"])

        assert result1.exit_code == 0, result1.output
        assert result2.exit_code == 0, result2.output

    def test_gitignore_entry_added(self, tmp_path, monkeypatch):
        """.gitignore gets .geode/ entry."""
        monkeypatch.chdir(tmp_path)
        with _mock_user_profile() as mock_cls:
            mock_cls.return_value.ensure_structure.return_value = False
            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text(encoding="utf-8")
        assert ".geode/" in content

    def test_gitignore_no_duplicate(self, tmp_path, monkeypatch):
        """.gitignore does not add duplicate .geode/ entries."""
        monkeypatch.chdir(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".geode/\n", encoding="utf-8")

        with _mock_user_profile() as mock_cls:
            mock_cls.return_value.ensure_structure.return_value = False
            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        content = gitignore.read_text(encoding="utf-8")
        assert content.count(".geode/") == 1

    def test_success_message(self, tmp_path, monkeypatch):
        """init prints success message."""
        monkeypatch.chdir(tmp_path)
        with _mock_user_profile() as mock_cls:
            mock_cls.return_value.ensure_structure.return_value = False
            result = runner.invoke(app, ["init"])

        assert result.exit_code == 0, result.output
        assert "initialized" in result.output.lower() or "GEODE" in result.output
