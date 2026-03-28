"""Tests for SkillRegistry (ADR-007 Phase 2)."""

from __future__ import annotations

from pathlib import Path

from core.llm.skill_registry import SkillDefinition, SkillRegistry, _parse_frontmatter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_SKILL_MD = """\
---
name: test-mechanics
node: analyst
type: game_mechanics
priority: 50
version: "1.0"
role: system
enabled: true
---
# Test Skill

Focus on core gameplay loop quality.
"""

DISABLED_SKILL_MD = """\
---
name: disabled-skill
node: analyst
type: game_mechanics
priority: 50
version: "1.0"
role: system
enabled: false
---
# Disabled Skill

This should be excluded.
"""

WILDCARD_SKILL_MD = """\
---
name: wildcard-skill
node: analyst
type: "*"
priority: 10
version: "0.5"
role: system
enabled: true
---
# Wildcard Skill

Applies to all analyst types.
"""

NO_FRONTMATTER_MD = """\
# Just Markdown

No YAML frontmatter here.
"""

INCOMPLETE_FRONTMATTER_MD = """\
---
name: partial-skill
node: evaluator
---
# Partial Skill

Only name and node specified; others should use defaults.
"""


# ---------------------------------------------------------------------------
# Frontmatter Parser Tests
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_valid_frontmatter(self) -> None:
        result = _parse_frontmatter(VALID_SKILL_MD)
        assert result is not None
        meta, body = result
        assert meta["name"] == "test-mechanics"
        assert meta["node"] == "analyst"
        assert meta["type"] == "game_mechanics"
        assert meta["priority"] == "50"
        assert meta["version"] == "1.0"  # quotes stripped
        assert meta["role"] == "system"
        assert meta["enabled"] == "true"
        assert "# Test Skill" in body

    def test_no_frontmatter_returns_none(self) -> None:
        result = _parse_frontmatter(NO_FRONTMATTER_MD)
        assert result is None

    def test_incomplete_frontmatter_parsed(self) -> None:
        result = _parse_frontmatter(INCOMPLETE_FRONTMATTER_MD)
        assert result is not None
        meta, body = result
        assert meta["name"] == "partial-skill"
        assert meta["node"] == "evaluator"
        assert "type" not in meta  # not specified
        assert "# Partial Skill" in body


# ---------------------------------------------------------------------------
# SkillDefinition Parsing Tests
# ---------------------------------------------------------------------------


class TestParseSkillFile:
    def test_parse_skill_file_valid(self, tmp_path: Path) -> None:
        """Valid .md file parses correctly into SkillDefinition."""
        md_file = tmp_path / "test-mechanics.md"
        md_file.write_text(VALID_SKILL_MD, encoding="utf-8")

        skill = SkillRegistry._parse_skill_file(md_file)

        assert skill is not None
        assert skill.name == "test-mechanics"
        assert skill.node == "analyst"
        assert skill.type == "game_mechanics"
        assert skill.priority == 50
        assert skill.version == "1.0"
        assert skill.role == "system"
        assert skill.enabled is True
        assert "Focus on core gameplay loop quality." in skill.prompt_body
        assert skill.source_path == md_file

    def test_parse_skill_file_no_frontmatter(self, tmp_path: Path) -> None:
        """File without frontmatter returns None."""
        md_file = tmp_path / "no-front.md"
        md_file.write_text(NO_FRONTMATTER_MD, encoding="utf-8")

        skill = SkillRegistry._parse_skill_file(md_file)
        assert skill is None

    def test_parse_skill_file_incomplete_frontmatter(self, tmp_path: Path) -> None:
        """Incomplete frontmatter uses default values."""
        md_file = tmp_path / "partial.md"
        md_file.write_text(INCOMPLETE_FRONTMATTER_MD, encoding="utf-8")

        skill = SkillRegistry._parse_skill_file(md_file)

        assert skill is not None
        assert skill.name == "partial-skill"
        assert skill.node == "evaluator"
        assert skill.type == "*"  # default
        assert skill.priority == 100  # default
        assert skill.version == "0.1"  # default
        assert skill.role == "system"  # default
        assert skill.enabled is True  # default


# ---------------------------------------------------------------------------
# Discovery Tests
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_discover_from_directory(self, tmp_path: Path) -> None:
        """Creates temp dir with .md files, discovers them."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        (skills_dir / "skill-a.md").write_text(VALID_SKILL_MD, encoding="utf-8")
        (skills_dir / "skill-b.md").write_text(WILDCARD_SKILL_MD, encoding="utf-8")

        registry = SkillRegistry(extra_dirs=[skills_dir])
        skills = registry.discover()

        # At least 2 from our temp dir (bundled dir may or may not exist)
        names = [s.name for s in skills]
        assert "test-mechanics" in names
        assert "wildcard-skill" in names

    def test_disabled_skill_excluded(self, tmp_path: Path) -> None:
        """Skill with enabled: false is not included in discovery results."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        (skills_dir / "disabled.md").write_text(DISABLED_SKILL_MD, encoding="utf-8")
        (skills_dir / "enabled.md").write_text(VALID_SKILL_MD, encoding="utf-8")

        registry = SkillRegistry(extra_dirs=[skills_dir])
        skills = registry.discover()

        names = [s.name for s in skills]
        assert "disabled-skill" not in names
        assert "test-mechanics" in names


# ---------------------------------------------------------------------------
# Filtering Tests
# ---------------------------------------------------------------------------


class TestGetSkills:
    def test_get_skills_by_node_and_type(self) -> None:
        """Filters correctly by node and role_type."""
        registry = SkillRegistry()
        registry._skills = [
            SkillDefinition(
                name="a",
                node="analyst",
                type="game_mechanics",
                priority=50,
                version="1.0",
                role="system",
                enabled=True,
                prompt_body="body a",
                source_path=Path("/fake/a.md"),
            ),
            SkillDefinition(
                name="b",
                node="analyst",
                type="player_experience",
                priority=50,
                version="1.0",
                role="system",
                enabled=True,
                prompt_body="body b",
                source_path=Path("/fake/b.md"),
            ),
            SkillDefinition(
                name="c",
                node="evaluator",
                type="game_mechanics",
                priority=50,
                version="1.0",
                role="system",
                enabled=True,
                prompt_body="body c",
                source_path=Path("/fake/c.md"),
            ),
        ]

        result = registry.get_skills(node="analyst", role_type="game_mechanics")
        assert len(result) == 1
        assert result[0].name == "a"

    def test_get_skills_wildcard_type(self) -> None:
        """Skill with type='*' matches all role_types for its node."""
        registry = SkillRegistry()
        registry._skills = [
            SkillDefinition(
                name="wildcard",
                node="analyst",
                type="*",
                priority=10,
                version="1.0",
                role="system",
                enabled=True,
                prompt_body="wildcard body",
                source_path=Path("/fake/wild.md"),
            ),
        ]

        result_gm = registry.get_skills(node="analyst", role_type="game_mechanics")
        result_pe = registry.get_skills(node="analyst", role_type="player_experience")
        result_ev = registry.get_skills(node="evaluator", role_type="game_mechanics")

        assert len(result_gm) == 1
        assert result_gm[0].name == "wildcard"
        assert len(result_pe) == 1
        assert len(result_ev) == 0  # wrong node

    def test_priority_ordering(self) -> None:
        """Lower priority number = higher priority = first in list."""
        registry = SkillRegistry()
        registry._skills = [
            SkillDefinition(
                name="low-prio",
                node="analyst",
                type="game_mechanics",
                priority=100,
                version="1.0",
                role="system",
                enabled=True,
                prompt_body="low priority",
                source_path=Path("/fake/low.md"),
            ),
            SkillDefinition(
                name="high-prio",
                node="analyst",
                type="game_mechanics",
                priority=10,
                version="1.0",
                role="system",
                enabled=True,
                prompt_body="high priority",
                source_path=Path("/fake/high.md"),
            ),
        ]

        result = registry.get_skills(node="analyst", role_type="game_mechanics")
        # get_skills returns in insertion order; the assembler sorts by priority.
        # But let's verify both are returned.
        assert len(result) == 2
        # Sort by priority to verify ordering behaviour expected by assembler
        sorted_result = sorted(result, key=lambda s: s.priority)
        assert sorted_result[0].name == "high-prio"
        assert sorted_result[1].name == "low-prio"


class TestSkillDirs:
    def test_5_priority_dirs(self, tmp_path: Path) -> None:
        """Bundled, user global, project local, project flat, extra dirs."""
        extra = tmp_path / "extra-skills"
        extra.mkdir()

        registry = SkillRegistry(extra_dirs=[extra])
        dirs = registry._resolve_skill_dirs()

        # Should have at least 5 dirs: bundled, user, project .geode/, project flat, extra
        assert len(dirs) >= 5
        assert extra in dirs
        # Bundled dir should end with "skills"
        assert dirs[0].name == "skills"
        # User global dir
        assert dirs[1] == Path.home() / ".geode" / "skills"
        # Project local (CWD/.geode/skills)
        assert dirs[2] == Path.cwd() / ".geode" / "skills"
