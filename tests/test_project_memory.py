"""Tests for ProjectMemory — markdown-based persistent memory."""

from __future__ import annotations

from pathlib import Path

from core.memory.project import MAX_INSIGHTS, MAX_MEMORY_LINES, ProjectMemory


class TestProjectMemoryExists:
    def test_exists_false_when_no_file(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        assert mem.exists() is False

    def test_exists_true_after_ensure(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        assert mem.exists() is True

    def test_memory_file_path(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        assert mem.memory_file == tmp_path / ".claude" / "MEMORY.md"

    def test_rules_dir_path(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        assert mem.rules_dir == tmp_path / ".claude" / "rules"


class TestEnsureStructure:
    def test_creates_memory_file(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        created = mem.ensure_structure()
        assert created is True
        assert mem.memory_file.exists()

    def test_creates_rules_dir(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        assert mem.rules_dir.exists()
        assert mem.rules_dir.is_dir()

    def test_creates_sample_rule(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        anime_rule = mem.rules_dir / "anime-ip.md"
        assert anime_rule.exists()

    def test_idempotent(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        assert mem.ensure_structure() is True
        assert mem.ensure_structure() is False  # Already exists


class TestLoadMemory:
    def test_load_empty_when_no_file(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        assert mem.load_memory() == ""

    def test_load_default_content(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        content = mem.load_memory()
        assert "GEODE Project Memory" in content
        assert "프로젝트 개요" in content

    def test_load_respects_max_lines(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        # Write a very long file
        long_content = "\n".join(f"line {i}" for i in range(500))
        mem.memory_file.write_text(long_content, encoding="utf-8")

        loaded = mem.load_memory()
        lines = loaded.split("\n")
        assert len(lines) == MAX_MEMORY_LINES

    def test_load_custom_max_lines(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        long_content = "\n".join(f"line {i}" for i in range(50))
        mem.memory_file.write_text(long_content, encoding="utf-8")

        loaded = mem.load_memory(max_lines=10)
        lines = loaded.split("\n")
        assert len(lines) == 10


class TestLoadRules:
    def test_empty_when_no_dir(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        assert mem.load_rules() == []

    def test_load_all_rules(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        rules = mem.load_rules()
        assert len(rules) >= 1
        assert rules[0]["name"] == "anime-ip"

    def test_rule_has_paths(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        rules = mem.load_rules()
        anime = rules[0]
        assert len(anime["paths"]) > 0
        assert any("anime" in p for p in anime["paths"])

    def test_rule_has_content(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        rules = mem.load_rules()
        assert "애니메이션 IP 분석 규칙" in rules[0]["content"]

    def test_filter_by_context(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        # "anime" matches the sample rule paths
        matched = mem.load_rules("anime")
        assert len(matched) >= 1

        # "nonexistent" shouldn't match
        no_match = mem.load_rules("nonexistent_xyz_999")
        assert len(no_match) == 0

    def test_wildcard_loads_all(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        rules = mem.load_rules("*")
        assert len(rules) >= 1

    def test_rule_without_frontmatter(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()
        # Write a rule without YAML frontmatter
        plain_rule = mem.rules_dir / "plain.md"
        plain_rule.write_text("# Plain Rule\nNo frontmatter here.\n", encoding="utf-8")

        rules = mem.load_rules()
        names = [r["name"] for r in rules]
        assert "plain" in names


class TestAddInsight:
    def test_add_insight(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()

        result = mem.add_insight("Berserk shows high soulslike affinity")
        assert result is True

        content = mem.memory_file.read_text(encoding="utf-8")
        assert "Berserk shows high soulslike affinity" in content

    def test_add_insight_no_file(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        assert mem.add_insight("test") is False

    def test_multiple_insights(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()

        mem.add_insight("First insight")
        mem.add_insight("Second insight")

        content = mem.memory_file.read_text(encoding="utf-8")
        assert "First insight" in content
        assert "Second insight" in content

    def test_add_insight_dedup_same_ip_same_day(self, tmp_path: Path):
        """Same IP + same date → second call returns False (dedup)."""
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()

        assert mem.add_insight("[TestDedup] tier=S, score=0.85") is True
        assert mem.add_insight("[TestDedup] tier=S, score=0.90") is False

        content = mem.memory_file.read_text(encoding="utf-8")
        assert content.count("TestDedup") == 1

    def test_add_insight_different_ip_same_day(self, tmp_path: Path):
        """Different IPs on the same day → both succeed."""
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()

        assert mem.add_insight("[Berserk] tier=S, score=0.85") is True
        assert mem.add_insight("[Cowboy Bebop] tier=A, score=0.70") is True

        content = mem.memory_file.read_text(encoding="utf-8")
        assert "Berserk" in content
        assert "Cowboy Bebop" in content

    def test_add_insight_rotation_max_50(self, tmp_path: Path):
        """51st insertion drops oldest entry (rotation)."""
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()

        # Insert MAX_INSIGHTS + 1 entries (each with unique IP to avoid dedup)
        for i in range(MAX_INSIGHTS + 1):
            result = mem.add_insight(f"[IP_{i}] tier=B, score=0.{i:02d}")
            assert result is True

        content = mem.memory_file.read_text(encoding="utf-8")
        insight_lines = [ln for ln in content.split("\n") if ln.startswith("- ") and "tier=" in ln]
        assert len(insight_lines) == MAX_INSIGHTS

        # Oldest (IP_0) should be dropped, newest (IP_50) should be present
        assert "IP_0" not in content
        assert f"IP_{MAX_INSIGHTS}" in content

    def test_add_insight_newest_first(self, tmp_path: Path):
        """New insight appears at the top of the section (newest-first)."""
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()

        mem.add_insight("[Alpha] tier=A, score=0.80")
        mem.add_insight("[Beta] tier=B, score=0.60")

        content = mem.memory_file.read_text(encoding="utf-8")
        alpha_idx = content.index("Alpha")
        beta_idx = content.index("Beta")
        # Beta (added second) should appear before Alpha (newest-first)
        assert beta_idx < alpha_idx

    def test_add_insight_no_ip_bracket_no_dedup(self, tmp_path: Path):
        """Insights without [IP] brackets don't trigger dedup."""
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()

        assert mem.add_insight("General insight one") is True
        assert mem.add_insight("General insight two") is True

        content = mem.memory_file.read_text(encoding="utf-8")
        assert "General insight one" in content
        assert "General insight two" in content


class TestGetContextForIP:
    def test_get_context(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()

        ctx = mem.get_context_for_ip("cowboy bebop")
        assert "memory" in ctx
        assert "rules" in ctx
        assert isinstance(ctx["memory"], str)
        assert isinstance(ctx["rules"], list)

    def test_context_has_matching_rules(self, tmp_path: Path):
        mem = ProjectMemory(tmp_path)
        mem.ensure_structure()

        # "cowboy" matches the sample rule paths pattern "*cowboy*"
        ctx = mem.get_context_for_ip("cowboy")
        assert len(ctx["rules"]) >= 1
