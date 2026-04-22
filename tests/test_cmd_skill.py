"""Tests for geode skill CLI (core/cli/cmd_skill.py)."""

from __future__ import annotations

from pathlib import Path

from core.cli.cmd_skill import app
from typer.testing import CliRunner

runner = CliRunner()


class TestSkillList:
    def test_list_returns_success(self, tmp_path: Path, monkeypatch: object):
        result = runner.invoke(app, ["list"])
        # Should not crash — may have 0 or more skills
        assert result.exit_code == 0

    def test_list_all_includes_unlisted(self, tmp_path: Path):
        result = runner.invoke(app, ["list", "--all"])
        assert result.exit_code == 0


class TestSkillCreate:
    def test_create_public(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".geode" / "skills").mkdir(parents=True)
        result = runner.invoke(app, ["create", "test-skill", "--desc", "A test skill"])
        assert result.exit_code == 0
        assert "Created skill" in result.output
        skill_md = tmp_path / ".geode" / "skills" / "test-skill" / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "visibility: public" in content

    def test_create_private(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        personal = tmp_path / "personal_skills"
        monkeypatch.setattr("core.cli.cmd_skill._PERSONAL_SKILLS", personal)
        result = runner.invoke(app, ["create", "secret-skill", "--private", "--desc", "Private"])
        assert result.exit_code == 0
        assert "private" in result.output
        assert (personal / "secret-skill" / "SKILL.md").exists()

    def test_create_duplicate_fails(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skill_dir = tmp_path / ".geode" / "skills" / "existing"
        skill_dir.mkdir(parents=True)
        result = runner.invoke(app, ["create", "existing"])
        assert result.exit_code == 1


class TestSkillShow:
    def test_show_existing(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skill_dir = tmp_path / ".geode" / "skills" / "demo"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: demo\ndescription: Demo skill\nvisibility: public\n---\n\n# Demo\nHello",
        )
        result = runner.invoke(app, ["show", "demo"])
        assert result.exit_code == 0
        assert "demo" in result.output
        assert "public" in result.output

    def test_show_not_found(self):
        result = runner.invoke(app, ["show", "nonexistent-skill-xyz"])
        assert result.exit_code == 1


class TestSkillRemove:
    def test_remove_existing(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skill_dir = tmp_path / ".geode" / "skills" / "to-delete"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: to-delete\n---\n")
        result = runner.invoke(app, ["remove", "to-delete"])
        assert result.exit_code == 0
        assert not skill_dir.exists()

    def test_remove_not_found(self):
        result = runner.invoke(app, ["remove", "nonexistent-xyz"])
        assert result.exit_code == 1
