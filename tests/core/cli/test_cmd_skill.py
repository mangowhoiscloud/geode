"""Tests for geode skill CLI (core/cli/commands/skill.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.commands.skill import app
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
        monkeypatch.setattr("core.cli.commands.skill._PERSONAL_SKILLS", personal)
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


class TestSkillListTiers:
    """PR-SKILL-UNIFY — `geode skill list`/`show` must see the SAME tiers the
    runtime SkillLoader does, including the bundled/builtin tier the old 2-tier
    iterdir scan omitted."""

    def _bundled(self, tmp_path: Path, monkeypatch) -> None:
        import core.skills.skills as sk

        d = tmp_path / "builtin" / "bundled-demo"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            "---\nname: bundled-demo\ndescription: shipped\nvisibility: public\n---\n# Body\nhi",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            sk.SkillLoader, "_resolve_skill_dirs", lambda self: [tmp_path / "builtin"]
        )

    def test_list_surfaces_builtin_tier(self, tmp_path: Path, monkeypatch):
        self._bundled(tmp_path, monkeypatch)
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "bundled-demo" in result.output
        assert "builtin" in result.output  # tier column

    def test_show_finds_builtin_tier(self, tmp_path: Path, monkeypatch):
        self._bundled(tmp_path, monkeypatch)
        result = runner.invoke(app, ["show", "bundled-demo"])
        assert result.exit_code == 0
        assert "bundled-demo" in result.output and "Body" in result.output

    def test_show_matches_frontmatter_name_when_dir_differs(self, tmp_path: Path, monkeypatch):
        """`list` prints the frontmatter name, so `show <that name>` must resolve
        even when the skill dir differs (Codex MEDIUM)."""
        import core.skills.skills as sk

        d = tmp_path / "builtin" / "dir-name"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            "---\nname: declared-name\ndescription: x\n---\n# Body\nhi", encoding="utf-8"
        )
        monkeypatch.setattr(
            sk.SkillLoader, "_resolve_skill_dirs", lambda self: [tmp_path / "builtin"]
        )
        assert runner.invoke(app, ["show", "declared-name"]).exit_code == 0
        assert runner.invoke(app, ["show", "dir-name"]).exit_code == 0


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


@pytest.mark.parametrize("command", ["create", "remove"])
@pytest.mark.parametrize("name", ["", ".", "..", "../outside", "nested/name", "nested\\name"])
def test_skill_rejects_nonlocal_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, name: str
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".geode" / "skills").mkdir(parents=True)
    if command == "remove":
        (tmp_path / ".geode" / "skills" / name).mkdir(parents=True, exist_ok=True)
    with patch("shutil.rmtree") as remove, patch.object(Path, "mkdir") as mkdir:
        result = runner.invoke(app, [command, "--", name])
    assert result.exit_code != 0
    remove.assert_not_called()
    mkdir.assert_not_called()


@pytest.mark.parametrize("command", ["create", "remove"])
def test_skill_rejects_absolute_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "outside"
    if command == "remove":
        outside.mkdir()
    with patch("shutil.rmtree") as remove, patch.object(Path, "mkdir") as mkdir:
        result = runner.invoke(app, [command, str(outside)])
    assert result.exit_code != 0
    remove.assert_not_called()
    mkdir.assert_not_called()


@pytest.mark.parametrize("command", ["create", "remove"])
def test_skill_rejects_symlinked_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".geode").symlink_to(outside, target_is_directory=True)
    (outside / "skills" / "demo").mkdir(parents=True)
    with patch("shutil.rmtree") as remove, patch.object(Path, "mkdir") as mkdir:
        result = runner.invoke(app, [command, "new" if command == "create" else "demo"])
    assert result.exit_code != 0
    remove.assert_not_called()
    mkdir.assert_not_called()


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("command", ["create", "remove"])
@pytest.mark.parametrize("case_alias", [False, True])
def test_skill_never_mutates_bundled_tier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    private: bool,
    case_alias: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    bundled = tmp_path / ".geode" / "skills"
    (bundled / "demo").mkdir(parents=True)
    monkeypatch.setattr("core.skills.skills._PACKAGE_ROOT", tmp_path)
    selected = bundled.with_name("SKILLS") if case_alias else bundled
    if case_alias and not selected.exists():
        pytest.skip("Filesystem does not provide case-insensitive aliases")
    monkeypatch.setattr("core.cli.commands.skill._PROJECT_SKILLS", selected)
    if private:
        monkeypatch.setattr("core.cli.commands.skill._PROJECT_SKILLS", tmp_path / "project")
        monkeypatch.setattr("core.cli.commands.skill._PERSONAL_SKILLS", selected)
    args = [command, "new" if command == "create" else "demo"]
    if command == "create" and private:
        args.append("--private")
    with patch("shutil.rmtree") as remove, patch.object(Path, "mkdir") as mkdir:
        result = runner.invoke(app, args)
    assert result.exit_code != 0
    remove.assert_not_called()
    mkdir.assert_not_called()


def test_private_skill_does_not_modify_project_gitignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    ignore = tmp_path / ".gitignore"
    ignore.write_text("existing-rule\n")
    personal = tmp_path / "personal" / "skills"
    monkeypatch.setattr("core.cli.commands.skill._PERSONAL_SKILLS", personal)
    assert runner.invoke(app, ["create", "private-demo", "--private"]).exit_code == 0
    assert ignore.read_text() == "existing-rule\n"
    assert (personal / "private-demo" / "SKILL.md").is_file()


def test_remove_preserves_personal_override_until_project_skill_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / ".geode" / "skills" / "demo"
    personal = tmp_path / "personal" / "demo"
    project.mkdir(parents=True)
    personal.mkdir(parents=True)
    monkeypatch.setattr("core.cli.commands.skill._PERSONAL_SKILLS", personal.parent)
    assert runner.invoke(app, ["remove", "demo"]).exit_code == 0
    assert not project.exists()
    assert personal.exists()
    assert runner.invoke(app, ["remove", "demo"]).exit_code == 0
    assert not personal.exists()


def test_remove_rejects_symlinked_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evidence").write_text("preserve")
    skills = tmp_path / ".geode" / "skills"
    skills.mkdir(parents=True)
    (skills / "alias").symlink_to(outside, target_is_directory=True)
    with patch("shutil.rmtree") as remove:
        assert runner.invoke(app, ["remove", "alias"]).exit_code != 0
    remove.assert_not_called()
    assert (outside / "evidence").read_text() == "preserve"
