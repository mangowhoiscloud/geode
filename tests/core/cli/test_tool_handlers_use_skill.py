"""use_skill handler — model-side skill body loading (Progressive Disclosure Tier 2).

The system prompt carries only ``<available_skills>`` metadata; this handler is
the runtime LLM's only path to a skill's full body. Pinned here so the tool
never regresses into a CLI-only surface again.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.cli.tool_handlers.single_tool import _build_use_skill_handler
from core.skills.skills import SkillLoader, SkillRegistry


def _write_demo_skill(skills_root: Path) -> None:
    demo_md = skills_root / "demo-skill" / "SKILL.md"
    demo_md.parent.mkdir(parents=True)
    demo_md.write_text(
        "---\n"
        "name: demo-skill\n"
        "description: Demo skill.\n"
        "triggers: demo, sample\n"
        "---\n"
        "# Demo\nDo the demo on $ARGUMENTS.\n",
        encoding="utf-8",
    )


@pytest.fixture()
def demo_registry(tmp_path: Path) -> SkillRegistry:
    _write_demo_skill(tmp_path)
    registry = SkillRegistry()
    SkillLoader(skills_dir=tmp_path).load_all(registry=registry)
    return registry


def test_use_skill_renders_body_with_arguments(demo_registry: SkillRegistry) -> None:
    handler = _build_use_skill_handler(demo_registry)["use_skill"]
    result = handler(name="demo-skill", arguments="X")
    assert result["result"]["name"] == "demo-skill"
    assert "Do the demo on X." in result["result"]["instructions"]


def test_use_skill_unknown_name_lists_available(demo_registry: SkillRegistry) -> None:
    handler = _build_use_skill_handler(demo_registry)["use_skill"]
    result = handler(name="nope")
    assert result["error_type"] == "not_found"
    assert "demo-skill" in result["hint"]


def test_use_skill_without_registry_falls_back_to_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker path: handlers built without daemon wiring still resolve skills."""
    import core.skills.skills as skills_mod

    _write_demo_skill(tmp_path)
    real_loader = skills_mod.SkillLoader
    monkeypatch.setattr(skills_mod, "SkillLoader", lambda: real_loader(skills_dir=tmp_path))
    handler = _build_use_skill_handler(None)["use_skill"]
    result = handler(name="demo-skill")
    assert "Do the demo on" in result["result"]["instructions"]
