"""SkillLoader tier discovery + visibility parsing (PR-SKILL-UNIFY).

``discover_tiered`` tags each winning SKILL.md with its tier label, and
``load_file`` now parses the ``visibility`` frontmatter field it previously
dropped (always-"public") — both consumed by ``geode skill list``.
"""

from __future__ import annotations

from pathlib import Path

from core.skills.skills import SkillLoader


def _write(dir_: Path, name: str, *, visibility: str = "public") -> None:
    d = dir_ / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} desc\nvisibility: {visibility}\n---\n# {name}",
        encoding="utf-8",
    )


def test_load_file_parses_visibility(tmp_path: Path) -> None:
    _write(tmp_path, "secret", visibility="unlisted")
    skill = SkillLoader().load_file(tmp_path / "secret" / "SKILL.md")
    assert skill.visibility == "unlisted"  # previously always "public"


def test_discover_tiered_labels_and_override(tmp_path: Path, monkeypatch) -> None:
    builtin, personal, project = tmp_path / "b", tmp_path / "p", tmp_path / "j"
    _write(builtin, "only-builtin")
    _write(builtin, "shared")
    _write(project, "shared")  # later tier overrides
    _write(personal, "only-personal")
    monkeypatch.setattr(
        SkillLoader, "_resolve_skill_dirs", lambda self: [builtin, personal, project]
    )

    tiered = {p.parent.name: tier for p, tier in SkillLoader().discover_tiered()}
    assert tiered["only-builtin"] == "builtin"
    assert tiered["only-personal"] == "personal"
    assert tiered["shared"] == "project"  # project wins over builtin (later override)
