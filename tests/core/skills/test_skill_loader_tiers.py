"""SkillLoader tier discovery + visibility parsing (PR-SKILL-UNIFY).

``discover_tiered`` tags each winning SKILL.md with its tier label, and
``load_file`` now parses the ``visibility`` frontmatter field it previously
dropped (always-"public") — both consumed by ``geode skill list``.
"""

from __future__ import annotations

from pathlib import Path

from core.extensions import ExtensionPolicy, ExtensionState
from core.skills.skills import SkillLoader, SkillRegistry


def _write(
    dir_: Path,
    name: str,
    *,
    visibility: str = "public",
    body: str | None = None,
) -> None:
    d = dir_ / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} desc\nvisibility: {visibility}\n---\n"
        f"{body or f'# {name}'}",
        encoding="utf-8",
    )


def _policy(name: str, *, capabilities: list[str] | None = None) -> ExtensionPolicy:
    return ExtensionPolicy.from_mapping(
        {
            "version": 1,
            "extensions": {
                f"skill:{name}": {
                    "enabled": True,
                    "trusted": True,
                    "execution": "trusted",
                    "capabilities": capabilities or [],
                }
            },
        }
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


def test_project_skill_requires_operator_policy_before_registration(
    tmp_path: Path, monkeypatch
) -> None:
    builtin, personal, project = tmp_path / "b", tmp_path / "p", tmp_path / "j"
    _write(project, "third-party")
    monkeypatch.setattr(
        SkillLoader, "_resolve_skill_dirs", lambda self: [builtin, personal, project]
    )
    registry = SkillRegistry()

    loaded = SkillLoader(extension_policy=ExtensionPolicy.empty()).load_all(registry)

    assert loaded == []
    assert "third-party" not in registry
    assert registry.extension_decisions[0].state is ExtensionState.REJECTED


def test_authorized_project_skill_loads_with_exact_capability_grant(
    tmp_path: Path, monkeypatch
) -> None:
    builtin, personal, project = tmp_path / "b", tmp_path / "p", tmp_path / "j"
    _write(project, "dynamic", body="# Dynamic\nCurrent branch: !`git branch --show-current`")
    monkeypatch.setattr(
        SkillLoader, "_resolve_skill_dirs", lambda self: [builtin, personal, project]
    )
    registry = SkillRegistry()

    loaded = SkillLoader(extension_policy=_policy("dynamic", capabilities=["shell"])).load_all(
        registry
    )

    assert [skill.name for skill in loaded] == ["dynamic"]
    assert registry.get("dynamic") is not None
    decision = registry.extension_decisions[0]
    assert decision.state is ExtensionState.GRANTED
    assert decision.granted_capabilities == ("shell",)


def test_dynamic_project_skill_without_shell_grant_is_rejected(tmp_path: Path, monkeypatch) -> None:
    builtin, personal, project = tmp_path / "b", tmp_path / "p", tmp_path / "j"
    _write(project, "dynamic", body="# Dynamic\n!`echo should-not-run`")
    monkeypatch.setattr(
        SkillLoader, "_resolve_skill_dirs", lambda self: [builtin, personal, project]
    )

    registry = SkillRegistry()
    loaded = SkillLoader(extension_policy=_policy("dynamic")).load_all(registry)

    assert loaded == []
    assert registry.extension_decisions[0].reason == "missing capability grants: shell"
