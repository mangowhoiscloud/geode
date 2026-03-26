"""Tests for Tier 0.5 User Profile system.

Covers:
- FileBasedUserProfile: CRUD operations, merge, dedup, rotation
- UserProfilePort: Protocol conformance
- Profile tools: ProfileShow, ProfileUpdate, ProfilePreference, ProfileLearn
- ContextAssembler integration: Tier 0.5 injection
"""

from __future__ import annotations

import json

from core.memory.user_profile import MAX_LEARNED_PATTERNS, FileBasedUserProfile

# ---------------------------------------------------------------------------
# FileBasedUserProfile — Core Adapter
# ---------------------------------------------------------------------------


class TestFileBasedUserProfile:
    def test_ensure_structure_creates_files(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        created = profile.ensure_structure()
        assert created is True
        assert (tmp_path / "profile" / "profile.md").exists()
        assert (tmp_path / "profile" / "preferences.json").exists()
        assert (tmp_path / "profile" / "learned.md").exists()

    def test_ensure_structure_idempotent(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.ensure_structure()
        assert profile.ensure_structure() is False  # already exists

    def test_exists_false_when_empty(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "empty")
        assert profile.exists() is False

    def test_exists_true_after_create(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.ensure_structure()
        assert profile.exists() is True

    def test_save_and_load_profile(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.save_profile(
            {
                "role": "AI Engineer",
                "expertise": "ML, NLP",
                "name": "Tester",
                "bio": "A test user.",
            }
        )
        loaded = profile.load_profile()
        assert loaded["role"] == "AI Engineer"
        assert loaded["expertise"] == "ML, NLP"
        assert loaded["name"] == "Tester"
        assert "A test user." in loaded.get("bio", "")

    def test_save_profile_creates_dir(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "new" / "profile")
        assert profile.save_profile({"role": "Tester"}) is True
        assert (tmp_path / "new" / "profile" / "profile.md").exists()

    def test_load_empty_returns_empty_dict(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "empty")
        loaded = profile.load_profile()
        assert loaded == {}


class TestPreferences:
    def test_set_and_get_preference(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.set_preference("language", "ko")
        assert profile.get_preference("language") == "ko"

    def test_get_preference_default(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        assert profile.get_preference("nonexistent", "default") == "default"

    def test_preference_persistence(self, tmp_path):
        gdir = tmp_path / "profile"
        p1 = FileBasedUserProfile(global_dir=gdir)
        p1.set_preference("output_format", "verbose")

        # New instance reads from disk
        p2 = FileBasedUserProfile(global_dir=gdir)
        assert p2.get_preference("output_format") == "verbose"

    def test_project_override_preference(self, tmp_path):
        gdir = tmp_path / "global"
        pdir = tmp_path / "project"
        gdir.mkdir(parents=True)
        pdir.mkdir(parents=True)

        # Set global
        g = FileBasedUserProfile(global_dir=gdir)
        g.set_preference("language", "en")

        # Set project-local override
        (pdir / "preferences.json").write_text(json.dumps({"language": "ko"}), encoding="utf-8")

        # Project-local should win
        combined = FileBasedUserProfile(global_dir=gdir, project_dir=pdir)
        assert combined.get_preference("language") == "ko"


class TestLearnedPatterns:
    def test_add_and_get_patterns(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.add_learned_pattern("User prefers dark fantasy", "domain")
        patterns = profile.get_learned_patterns()
        assert len(patterns) == 1
        assert "dark fantasy" in patterns[0]

    def test_dedup_prevents_duplicate(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        assert profile.add_learned_pattern("Pattern A", "general") is True
        assert profile.add_learned_pattern("Pattern A", "general") is False  # dedup
        assert len(profile.get_learned_patterns()) == 1

    def test_newest_first_ordering(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.add_learned_pattern("First pattern", "general")
        profile.add_learned_pattern("Second pattern", "general")
        patterns = profile.get_learned_patterns()
        assert "Second" in patterns[0]
        assert "First" in patterns[1]

    def test_category_filter(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.add_learned_pattern("Domain insight", "domain")
        profile.add_learned_pattern("Workflow pattern", "workflow")
        domain_only = profile.get_learned_patterns(category="domain")
        assert len(domain_only) == 1
        assert "Domain" in domain_only[0]

    def test_rotation_max_entries(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        for i in range(MAX_LEARNED_PATTERNS + 10):
            profile.add_learned_pattern(f"Pattern {i}", "general")
        patterns = profile.get_learned_patterns()
        assert len(patterns) <= MAX_LEARNED_PATTERNS


class TestProjectOverride:
    def test_project_profile_overrides_global(self, tmp_path):
        gdir = tmp_path / "global"
        pdir = tmp_path / "project"

        # Create global profile
        g = FileBasedUserProfile(global_dir=gdir)
        g.save_profile({"role": "Global Role", "expertise": "Global Exp"})

        # Create project-local profile
        pdir.mkdir(parents=True)
        (pdir / "profile.md").write_text(
            "---\nrole: Project Role\n---\n\nProject bio.",
            encoding="utf-8",
        )

        combined = FileBasedUserProfile(global_dir=gdir, project_dir=pdir)
        loaded = combined.load_profile()
        assert loaded["role"] == "Project Role"  # project overrides
        assert loaded["expertise"] == "Global Exp"  # global preserved

    def test_project_learned_patterns_merge(self, tmp_path):
        gdir = tmp_path / "global"
        pdir = tmp_path / "project"

        g = FileBasedUserProfile(global_dir=gdir)
        g.add_learned_pattern("Global pattern", "general")

        pdir.mkdir(parents=True)
        (pdir / "learned.md").write_text(
            "# Learned Patterns\n\n- [2026-03-16] [domain] Project pattern\n",
            encoding="utf-8",
        )

        combined = FileBasedUserProfile(global_dir=gdir, project_dir=pdir)
        loaded = combined.load_profile()
        patterns = loaded.get("learned_patterns", [])
        assert len(patterns) == 2


class TestContextSummary:
    def test_context_summary_with_profile(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.save_profile({"role": "AI Engineer", "expertise": "ML"})
        profile.set_preference("language", "ko")
        summary = profile.get_context_summary()
        assert "AI Engineer" in summary
        assert "ML" in summary
        assert "ko" in summary

    def test_context_summary_empty(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "empty")
        assert profile.get_context_summary() == ""


# ---------------------------------------------------------------------------
# Profile Tools
# ---------------------------------------------------------------------------


class TestProfileShowTool:
    def test_show_no_profile(self):
        from core.tools.profile_tools import ProfileShowTool, set_user_profile

        set_user_profile(None)
        tool = ProfileShowTool()
        result = tool.execute()
        assert "error" in result

    def test_show_with_profile(self, tmp_path):
        from core.tools.profile_tools import ProfileShowTool, set_user_profile

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.ensure_structure()
        set_user_profile(profile)
        tool = ProfileShowTool()
        result = tool.execute()
        assert "result" in result
        assert result["result"]["exists"] is True


class TestProfileUpdateTool:
    def test_update_fields(self, tmp_path):
        from core.tools.profile_tools import ProfileUpdateTool, set_user_profile

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        set_user_profile(profile)
        tool = ProfileUpdateTool()
        result = tool.execute(role="Data Scientist", expertise="Statistics")
        assert result["result"]["updated"] is True

        # Verify persistence
        loaded = profile.load_profile()
        assert loaded["role"] == "Data Scientist"


class TestProfilePreferenceTool:
    def test_set_and_get(self, tmp_path):
        from core.tools.profile_tools import ProfilePreferenceTool, set_user_profile

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        set_user_profile(profile)
        tool = ProfilePreferenceTool()

        # Set
        result = tool.execute(key="language", value="ko")
        assert result["result"]["action"] == "set"
        assert result["result"]["success"] is True

        # Get
        result = tool.execute(key="language")
        assert result["result"]["action"] == "get"
        assert result["result"]["value"] == "ko"


class TestProfileLearnTool:
    def test_learn_pattern(self, tmp_path):
        from core.tools.profile_tools import ProfileLearnTool, set_user_profile

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        set_user_profile(profile)
        tool = ProfileLearnTool()
        result = tool.execute(pattern="User prefers dry-run first", category="workflow")
        assert result["result"]["saved"] is True
        assert result["result"]["category"] == "workflow"

    def test_learn_dedup(self, tmp_path):
        from core.tools.profile_tools import ProfileLearnTool, set_user_profile

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        set_user_profile(profile)
        tool = ProfileLearnTool()
        tool.execute(pattern="Same pattern")
        result = tool.execute(pattern="Same pattern")
        assert result["result"]["saved"] is False
        assert result["result"]["deduplicated"] is True


# ---------------------------------------------------------------------------
# Career Identity (career.toml)
# ---------------------------------------------------------------------------


class TestCareerIdentity:
    def test_load_career_empty_when_no_file(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "noprofile")
        assert profile.load_career() == {}

    def test_load_career_valid_toml(self, tmp_path):
        gdir = tmp_path / "profile"
        gdir.mkdir(parents=True)
        (gdir / "career.toml").write_text(
            '[identity]\ntitle = "AI Engineer"\nskills = ["Python", "ML"]\n',
            encoding="utf-8",
        )
        profile = FileBasedUserProfile(global_dir=gdir)
        career = profile.load_career()
        assert career["identity"]["title"] == "AI Engineer"
        assert "Python" in career["identity"]["skills"]

    def test_load_career_invalid_toml(self, tmp_path):
        gdir = tmp_path / "profile"
        gdir.mkdir(parents=True)
        (gdir / "career.toml").write_text("invalid [[ toml", encoding="utf-8")
        profile = FileBasedUserProfile(global_dir=gdir)
        assert profile.load_career() == {}

    def test_load_career_empty_file(self, tmp_path):
        gdir = tmp_path / "profile"
        gdir.mkdir(parents=True)
        (gdir / "career.toml").write_text("", encoding="utf-8")
        profile = FileBasedUserProfile(global_dir=gdir)
        assert profile.load_career() == {}

    def test_ensure_structure_creates_career_toml(self, tmp_path):
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.ensure_structure()
        assert (tmp_path / "profile" / "career.toml").exists()
        content = (tmp_path / "profile" / "career.toml").read_text()
        assert "[identity]" in content
        assert "title" in content

    def test_context_summary_includes_career(self, tmp_path):
        gdir = tmp_path / "profile"
        gdir.mkdir(parents=True)
        (gdir / "career.toml").write_text(
            '[identity]\ntitle = "Senior AI Engineer"\nskills = ["Python", "LangGraph"]\n',
            encoding="utf-8",
        )
        profile = FileBasedUserProfile(global_dir=gdir)
        profile.save_profile({"role": "Engineer"})
        summary = profile.get_context_summary()
        assert "Senior AI Engineer" in summary
        assert "Python" in summary

    def test_context_summary_no_career(self, tmp_path):
        """Career fields absent should not appear in summary."""
        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.save_profile({"role": "Tester"})
        summary = profile.get_context_summary()
        assert "Title:" not in summary
        assert "Skills:" not in summary

    def test_career_not_overwritten_by_ensure_structure(self, tmp_path):
        gdir = tmp_path / "profile"
        gdir.mkdir(parents=True)
        custom = '[identity]\ntitle = "Custom"\n'
        (gdir / "career.toml").write_text(custom, encoding="utf-8")
        # ensure_structure won't overwrite profile.md since it exists check is on profile.md
        # But career.toml should also not be overwritten
        (gdir / "profile.md").write_text("---\nrole: X\n---\n", encoding="utf-8")
        profile = FileBasedUserProfile(global_dir=gdir)
        profile.ensure_structure()  # returns False (already exists)
        assert (gdir / "career.toml").read_text() == custom


class TestProfileShowToolWithCareer:
    def test_show_includes_career(self, tmp_path):
        from core.tools.profile_tools import ProfileShowTool, set_user_profile

        gdir = tmp_path / "profile"
        gdir.mkdir(parents=True)
        (gdir / "career.toml").write_text(
            '[identity]\ntitle = "ML Engineer"\n',
            encoding="utf-8",
        )
        profile = FileBasedUserProfile(global_dir=gdir)
        profile.ensure_structure()
        set_user_profile(profile)
        tool = ProfileShowTool()
        result = tool.execute()
        assert "career" in result["result"]
        assert result["result"]["career"]["identity"]["title"] == "ML Engineer"


# ---------------------------------------------------------------------------
# UserProfilePort Protocol Conformance
# ---------------------------------------------------------------------------


class TestUserProfilePortConformance:
    def test_file_based_implements_protocol(self, tmp_path):
        from core.memory.port import UserProfilePort

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        assert isinstance(profile, UserProfilePort)


# ---------------------------------------------------------------------------
# ContextAssembler Integration
# ---------------------------------------------------------------------------


class TestContextAssemblerUserProfile:
    def test_assemble_includes_user_profile(self, tmp_path):
        from core.memory.context import ContextAssembler

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        profile.save_profile({"role": "AI Engineer", "expertise": "ML"})
        profile.set_preference("language", "ko")

        assembler = ContextAssembler(user_profile=profile)
        ctx = assembler.assemble("sess-1", "test")
        assert ctx.get("_user_profile_loaded") is True
        assert "AI Engineer" in ctx.get("_user_profile_summary", "")

    def test_assemble_without_user_profile(self):
        from core.memory.context import ContextAssembler

        assembler = ContextAssembler()
        ctx = assembler.assemble("sess-1", "test")
        # No user_profile key expected
        assert "_user_profile_loaded" not in ctx

    def test_assemble_user_profile_not_exists(self, tmp_path):
        from core.memory.context import ContextAssembler

        profile = FileBasedUserProfile(global_dir=tmp_path / "nonexistent")
        assembler = ContextAssembler(user_profile=profile)
        ctx = assembler.assemble("sess-1", "test")
        assert ctx.get("_user_profile_loaded") is False
