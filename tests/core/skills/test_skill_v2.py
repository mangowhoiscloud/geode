"""Tests for Skill System v2 — Progressive Disclosure, multi-scope, dynamic context."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.skills.skills import SkillDefinition, SkillLoader, SkillRegistry


@pytest.fixture()
def tmp_skills(tmp_path: Path) -> Path:
    """Create a temporary skills directory with test SKILL.md files."""
    # Skill 1: standard invocable skill
    s1 = tmp_path / "researcher" / "SKILL.md"
    s1.parent.mkdir()
    s1.write_text(
        "---\n"
        "name: researcher\n"
        'description: 조사 스킬. "조사해", "research" 키워드로 트리거.\n'
        "tools: web_search, memory_save\n"
        "---\n"
        "# Researcher\nDo research on $ARGUMENTS\n"
    )

    # Skill 2: background knowledge (user-invocable: false)
    s2 = tmp_path / "bg-knowledge" / "SKILL.md"
    s2.parent.mkdir()
    s2.write_text(
        "---\n"
        "name: bg-knowledge\n"
        "description: Background skill.\n"
        "user-invocable: false\n"
        "---\n"
        "# Background\nThis is background knowledge.\n"
    )

    # Skill 3: forked skill
    s3 = tmp_path / "heavy-analysis" / "SKILL.md"
    s3.parent.mkdir()
    s3.write_text(
        "---\n"
        "name: heavy-analysis\n"
        'description: Heavy analysis. "분석해" 키워드로 트리거.\n'
        "context: fork\n"
        'argument-hint: "[topic]"\n'
        "---\n"
        "# Heavy Analysis\nAnalyze $ARGUMENTS in depth.\n"
        "Current date: !`date +%Y-%m-%d`\n"
    )

    return tmp_path


class TestSkillDefinitionV2:
    """Test new SkillDefinition fields."""

    def test_default_user_invocable(self) -> None:
        s = SkillDefinition(name="test")
        assert s.user_invocable is True

    def test_default_context_fork(self) -> None:
        s = SkillDefinition(name="test")
        assert s.context_fork is False

    def test_lazy_body_loading(self, tmp_skills: Path) -> None:
        loader = SkillLoader(skills_dir=tmp_skills, lazy=True)
        skills = loader.load_all()
        researcher = next(s for s in skills if s.name == "researcher")
        assert researcher.body == ""  # lazy — not loaded yet
        assert researcher.source_path is not None

        body = researcher.load_body()
        assert "Do research" in body
        assert researcher.body != ""  # now loaded

    def test_eager_body_loading(self, tmp_skills: Path) -> None:
        loader = SkillLoader(skills_dir=tmp_skills, lazy=False)
        skills = loader.load_all()
        researcher = next(s for s in skills if s.name == "researcher")
        assert "Do research" in researcher.body  # loaded immediately

    def test_bundled_deep_research_uses_runtime_orchestration_tools(self) -> None:
        repo_root = Path(__file__).parents[3]
        skill = SkillLoader(lazy=False).load_file(
            repo_root / ".geode/skills/deep-researcher/SKILL.md"
        )

        assert skill.tools == [
            "update_plan",
            "create_goal",
            "get_goal",
            "update_goal",
            "delegate_task",
            "spawn_agent",
            "list_agents",
            "wait_agent",
            "send_message",
            "followup_task",
            "interrupt_agent",
            "general_web_search",
            "web_fetch",
            "llms_txt_index",
        ]
        assert "independent" in skill.body
        assert "contradiction" in skill.body
        assert "instead of creating a competing checklist" in skill.body
        assert "only when the user explicitly requests" in skill.body
        assert "remain depth one" in skill.body
        assert "memory_save" not in skill.body

    def test_bundled_geo_uses_bounded_evidence_frontier(self) -> None:
        repo_root = Path(__file__).parents[3]
        skill = SkillLoader(lazy=False).load_file(repo_root / ".geode/skills/geo/SKILL.md")

        assert "delegate_task" in skill.tools
        assert "spawn_agent" in skill.tools
        assert "read_document" in skill.tools
        assert "read_file" not in skill.tools
        assert "at most three finite branches" in skill.body
        assert "hidden chain-of-thought" in skill.body
        assert "not_measured" in skill.body
        assert "parent AgenticLoop" in skill.body
        assert "deterministically" in skill.body
        assert "parent's active model and credential source" in skill.body
        assert "never rename or transcode" in skill.body
        assert "geode.trajectory@1" in skill.body
        assert "withheld-private" in skill.body
        assert "--allow-replay-incomplete" in skill.body

        scaffold = (repo_root / ".agents/skills/geo/SKILL.md").read_text()
        assert "at most three independent read-only branches" in scaffold
        assert "generic Tree-of-Thought/MCTS engine" in scaffold
        assert "Inspect `.eval`" in scaffold
        assert "geode-eval-artifacts" in scaffold


class TestProgressiveDisclosure:
    """Test 3-tier loading behavior."""

    def test_context_block_metadata_only(self, tmp_skills: Path) -> None:
        """Tier 1: context block should contain metadata, not body."""
        reg = SkillRegistry()
        SkillLoader(skills_dir=tmp_skills, lazy=True).load_all(registry=reg)

        ctx = reg.get_context_block()
        assert "researcher" in ctx
        assert "heavy-analysis" in ctx
        # Body content should NOT be in context block
        assert "Do research on" not in ctx
        assert "Analyze" not in ctx

    def test_context_block_fork_tag(self, tmp_skills: Path) -> None:
        """Forked skills should be tagged in XML context block."""
        reg = SkillRegistry()
        SkillLoader(skills_dir=tmp_skills, lazy=True).load_all(registry=reg)
        ctx = reg.get_context_block()
        assert "<available_skills>" in ctx
        assert 'name="heavy-analysis"' in ctx
        assert 'context="fork"' in ctx

    def test_context_block_background_tag(self, tmp_skills: Path) -> None:
        """Background skills should be tagged in XML context block."""
        reg = SkillRegistry()
        SkillLoader(skills_dir=tmp_skills, lazy=True).load_all(registry=reg)
        ctx = reg.get_context_block()
        assert 'name="bg-knowledge"' in ctx
        assert 'user_invocable="false"' in ctx


class TestUserInvocable:
    """Test user-invocable control."""

    def test_list_skills_hides_background(self, tmp_skills: Path) -> None:
        reg = SkillRegistry()
        SkillLoader(skills_dir=tmp_skills).load_all(registry=reg)
        names = reg.list_skills()
        assert "researcher" in names
        assert "heavy-analysis" in names
        assert "bg-knowledge" not in names  # hidden

    def test_list_all_includes_background(self, tmp_skills: Path) -> None:
        reg = SkillRegistry()
        SkillLoader(skills_dir=tmp_skills).load_all(registry=reg)
        names = reg.list_all()
        assert "bg-knowledge" in names

    def test_frontmatter_parsing(self, tmp_skills: Path) -> None:
        loader = SkillLoader(skills_dir=tmp_skills)
        skills = loader.load_all()
        bg = next(s for s in skills if s.name == "bg-knowledge")
        assert bg.user_invocable is False

        heavy = next(s for s in skills if s.name == "heavy-analysis")
        assert heavy.context_fork is True
        assert heavy.argument_hint == "[topic]"


class TestDynamicContext:
    """Test !`cmd` preprocessing and $ARGUMENTS substitution."""

    def test_arguments_substitution(self, tmp_skills: Path) -> None:
        loader = SkillLoader(skills_dir=tmp_skills, lazy=False)
        skills = loader.load_all()
        researcher = next(s for s in skills if s.name == "researcher")
        rendered = researcher.render(arguments="AI trends 2026")
        assert "AI trends 2026" in rendered
        assert "$ARGUMENTS" not in rendered

    def test_positional_arguments(self) -> None:
        skill = SkillDefinition(
            name="test",
            body="Hello $0, welcome to $1",
        )
        rendered = skill.render(arguments="Alice Wonderland")
        assert "Hello Alice" in rendered
        assert "welcome to Wonderland" in rendered

    def test_dynamic_cmd_execution(self, tmp_skills: Path) -> None:
        """!`cmd` should be replaced with command output."""
        loader = SkillLoader(skills_dir=tmp_skills, lazy=False)
        skills = loader.load_all()
        heavy = next(s for s in skills if s.name == "heavy-analysis")
        rendered = heavy.render(arguments="quantum computing")
        # !`date +%Y-%m-%d` should be replaced with actual date
        assert "!`" not in rendered
        assert "quantum computing" in rendered
        # Date should look like YYYY-MM-DD
        import re

        assert re.search(r"\d{4}-\d{2}-\d{2}", rendered)

    def test_no_arguments_passthrough(self) -> None:
        skill = SkillDefinition(name="test", body="Static content only")
        rendered = skill.render()
        assert rendered == "Static content only"

    def test_empty_arguments_erase_placeholder(self) -> None:
        skill = SkillDefinition(name="test", body="Target: $ARGUMENTS")
        assert skill.render() == "Target: "


class TestMultiScopeDiscovery:
    """Test multi-directory skill discovery."""

    def test_later_scope_overrides(self, tmp_path: Path) -> None:
        """Higher-priority scope should override lower-priority."""
        # Scope 1 (low priority)
        d1 = tmp_path / "scope1"
        s1 = d1 / "my-skill" / "SKILL.md"
        s1.parent.mkdir(parents=True)
        s1.write_text("---\nname: my-skill\ndescription: v1\n---\nBody v1\n")

        # Scope 2 (high priority — extra_dirs)
        d2 = tmp_path / "scope2"
        s2 = d2 / "my-skill" / "SKILL.md"
        s2.parent.mkdir(parents=True)
        s2.write_text("---\nname: my-skill\ndescription: v2\n---\nBody v2\n")

        loader = SkillLoader(skills_dir=d1, extra_dirs=[d2])
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].description == "v2"  # higher scope wins

    def test_multiple_scopes_merge(self, tmp_path: Path) -> None:
        """Skills from different scopes should merge (not only latest scope)."""
        d1 = tmp_path / "scope1"
        s1 = d1 / "skill-a" / "SKILL.md"
        s1.parent.mkdir(parents=True)
        s1.write_text("---\nname: skill-a\ndescription: A\n---\n")

        d2 = tmp_path / "scope2"
        s2 = d2 / "skill-b" / "SKILL.md"
        s2.parent.mkdir(parents=True)
        s2.write_text("---\nname: skill-b\ndescription: B\n---\n")

        loader = SkillLoader(skills_dir=d1, extra_dirs=[d2])
        skills = loader.load_all()
        names = {s.name for s in skills}
        assert names == {"skill-a", "skill-b"}


class TestTriggerFrontmatter:
    """The ``triggers:`` frontmatter key (TEMPLATE.md schema) is honored by the loader."""

    def _load_with(self, skills_root: Path, frontmatter: str):
        skill_md = skills_root / "sample" / "SKILL.md"
        skill_md.parent.mkdir(parents=True)
        skill_md.write_text(f"---\n{frontmatter}\n---\n# Sample\nBody.\n")
        return SkillLoader(skills_dir=skills_root).load_file(skill_md)

    def test_comma_string_triggers(self, tmp_path: Path) -> None:
        loaded = self._load_with(
            tmp_path, "name: sample\ndescription: d\ntriggers: alpha, beta, 감마"
        )
        assert loaded.triggers == ["alpha", "beta", "감마"]

    def test_inline_list_triggers(self, tmp_path: Path) -> None:
        loaded = self._load_with(tmp_path, "name: sample\ndescription: d\ntriggers: [alpha, beta]")
        assert loaded.triggers == ["alpha", "beta"]

    def test_frontmatter_unions_with_description_pattern(self, tmp_path: Path) -> None:
        loaded = self._load_with(
            tmp_path,
            'name: sample\ndescription: 조사 스킬. "조사해", "research" 키워드로 트리거.\n'
            "triggers: alpha",
        )
        assert loaded.triggers[0] == "alpha"
        assert "조사해" in loaded.triggers

    def test_context_block_emits_triggers_and_use_skill_usage(self, tmp_path: Path) -> None:
        loaded = self._load_with(tmp_path, "name: sample\ndescription: d\ntriggers: alpha, beta")
        registry = SkillRegistry()
        registry.register(loaded)
        block = registry.get_context_block()
        assert 'triggers="alpha, beta"' in block
        assert "use_skill" in block
