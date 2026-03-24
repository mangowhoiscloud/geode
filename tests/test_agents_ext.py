"""Tests for L5 Agent extensibility (AgentDefinition, AgentRegistry, SubagentLoader)."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.config import ANTHROPIC_SECONDARY
from core.skills.agents import (
    AgentDefinition,
    AgentRegistry,
    SubagentLoader,
    _parse_yaml_frontmatter,
)


class TestAgentDefinition:
    def test_create_minimal(self):
        agent = AgentDefinition(name="test", role="Tester", system_prompt="Do testing.")
        assert agent.name == "test"
        assert agent.role == "Tester"
        assert agent.tools == []
        assert agent.model == ANTHROPIC_SECONDARY

    def test_create_with_all_fields(self):
        agent = AgentDefinition(
            name="custom",
            role="Custom Agent",
            system_prompt="Custom prompt.",
            tools=["web_search", "trend_analysis"],
            model="claude-opus-4-20250514",
        )
        assert agent.tools == ["web_search", "trend_analysis"]
        assert agent.model == "claude-opus-4-20250514"

    def test_to_system_message(self):
        agent = AgentDefinition(name="a", role="Analyst", system_prompt="Analyze things.")
        msg = agent.to_system_message()
        assert "You are a Analyst" in msg
        assert "Analyze things." in msg


class TestAgentRegistry:
    def test_register_and_get(self):
        registry = AgentRegistry()
        agent = AgentDefinition(name="test_agent", role="Tester", system_prompt="Test.")
        registry.register(agent)
        assert registry.get("test_agent") is agent

    def test_get_nonexistent(self):
        registry = AgentRegistry()
        assert registry.get("nope") is None

    def test_duplicate_registration_raises(self):
        registry = AgentRegistry()
        agent = AgentDefinition(name="dup", role="R", system_prompt="P")
        registry.register(agent)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(agent)

    def test_list_agents(self):
        registry = AgentRegistry()
        registry.register(AgentDefinition(name="a", role="R", system_prompt="P"))
        registry.register(AgentDefinition(name="b", role="R", system_prompt="P"))
        assert sorted(registry.list_agents()) == ["a", "b"]

    def test_unregister(self):
        registry = AgentRegistry()
        registry.register(AgentDefinition(name="rem", role="R", system_prompt="P"))
        registry.unregister("rem")
        assert "rem" not in registry

    def test_unregister_nonexistent_raises(self):
        registry = AgentRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.unregister("ghost")

    def test_load_defaults(self):
        registry = AgentRegistry()
        registry.load_defaults()
        assert len(registry) == 3
        assert "research_assistant" in registry
        assert "data_analyst" in registry
        assert "web_researcher" in registry

    def test_len_and_contains(self):
        registry = AgentRegistry()
        assert len(registry) == 0
        registry.register(AgentDefinition(name="x", role="R", system_prompt="P"))
        assert len(registry) == 1
        assert "x" in registry
        assert "y" not in registry


class TestYamlFrontmatter:
    def test_parse_valid_frontmatter(self):
        text = "---\nname: test\nrole: Tester\ntools: [a, b]\n---\nBody text here."
        meta, body = _parse_yaml_frontmatter(text)
        assert meta["name"] == "test"
        assert meta["role"] == "Tester"
        assert meta["tools"] == ["a", "b"]
        assert body == "Body text here."

    def test_no_frontmatter(self):
        text = "Just plain markdown content."
        meta, body = _parse_yaml_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_quoted_values(self):
        text = "---\nname: \"my_agent\"\nrole: 'Specialist'\n---\nPrompt."
        meta, body = _parse_yaml_frontmatter(text)
        assert meta["name"] == "my_agent"
        assert meta["role"] == "Specialist"


class TestSubagentLoader:
    def test_discover_empty_dir(self, tmp_path: Path):
        loader = SubagentLoader(agents_dir=tmp_path)
        assert loader.discover() == []

    def test_discover_nonexistent_dir(self, tmp_path: Path):
        loader = SubagentLoader(agents_dir=tmp_path / "nonexistent")
        assert loader.discover() == []

    def test_load_file(self, tmp_path: Path):
        md = (
            "---\nname: loader_test\nrole: Test Role\n"
            "tools: [search]\nmodel: gpt-4\n---\nYou are a test agent."
        )
        path = tmp_path / "test_agent.md"
        path.write_text(md)

        loader = SubagentLoader(agents_dir=tmp_path)
        agent = loader.load_file(path)
        assert agent.name == "loader_test"
        assert agent.role == "Test Role"
        assert agent.tools == ["search"]
        assert agent.model == "gpt-4"
        assert "test agent" in agent.system_prompt

    def test_load_file_missing_role_raises(self, tmp_path: Path):
        md = "---\nname: no_role\n---\nBody."
        path = tmp_path / "bad.md"
        path.write_text(md)

        loader = SubagentLoader(agents_dir=tmp_path)
        with pytest.raises(ValueError, match="missing required 'role'"):
            loader.load_file(path)

    def test_load_file_not_found(self, tmp_path: Path):
        loader = SubagentLoader(agents_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            loader.load_file(tmp_path / "missing.md")

    def test_load_all_with_registry(self, tmp_path: Path):
        for i in range(2):
            md = f"---\nname: agent_{i}\nrole: Role {i}\n---\nPrompt {i}."
            (tmp_path / f"agent_{i}.md").write_text(md)

        registry = AgentRegistry()
        loader = SubagentLoader(agents_dir=tmp_path)
        agents = loader.load_all(registry=registry)
        assert len(agents) == 2
        assert len(registry) == 2

    def test_default_agents_dir(self):
        loader = SubagentLoader()
        assert loader.agents_dir == Path(".claude/agents")
