"""Tests for Context Hub features: career-identity, /context, /apply."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Feature 1: career-identity — load_career + career summary
# ---------------------------------------------------------------------------


class TestLoadCareer:
    """FileBasedUserProfile.load_career() loads ~/.geode/identity/career.toml."""

    def test_load_career_missing_file(self, tmp_path: Path) -> None:
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        # Patch Path.home to return tmp_path so career.toml won't exist
        with patch("core.memory.user_profile.Path.home", return_value=tmp_path):
            result = profile.load_career()
        assert result == {}

    def test_load_career_valid_toml(self, tmp_path: Path) -> None:
        from core.memory.user_profile import FileBasedUserProfile

        identity_dir = tmp_path / ".geode" / "identity"
        identity_dir.mkdir(parents=True)
        career_toml = identity_dir / "career.toml"
        career_toml.write_text(
            '[identity]\ntitle = "AI Engineer"\nexperience = "5y"\n'
            'skills = ["Python", "LangGraph"]\n\n'
            '[goals]\nseeking = "remote AI roles"\n',
            encoding="utf-8",
        )

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        with patch("core.memory.user_profile.Path.home", return_value=tmp_path):
            result = profile.load_career()

        assert result["identity"]["title"] == "AI Engineer"
        assert result["identity"]["experience"] == "5y"
        assert result["identity"]["skills"] == ["Python", "LangGraph"]
        assert result["goals"]["seeking"] == "remote AI roles"

    def test_load_career_invalid_toml(self, tmp_path: Path) -> None:
        from core.memory.user_profile import FileBasedUserProfile

        identity_dir = tmp_path / ".geode" / "identity"
        identity_dir.mkdir(parents=True)
        career_toml = identity_dir / "career.toml"
        career_toml.write_text("not valid toml {{{}}", encoding="utf-8")

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        with patch("core.memory.user_profile.Path.home", return_value=tmp_path):
            result = profile.load_career()
        assert result == {}

    def test_get_career_summary(self, tmp_path: Path) -> None:
        from core.memory.user_profile import FileBasedUserProfile

        identity_dir = tmp_path / ".geode" / "identity"
        identity_dir.mkdir(parents=True)
        (identity_dir / "career.toml").write_text(
            '[identity]\ntitle = "Senior AI Engineer"\nexperience = "5y"\n'
            'skills = ["Python", "LangGraph", "MLOps"]\n\n'
            '[goals]\nseeking = "remote AI roles"\n',
            encoding="utf-8",
        )

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        with patch("core.memory.user_profile.Path.home", return_value=tmp_path):
            summary = profile.get_career_summary()

        assert "Senior AI Engineer" in summary
        assert "5y" in summary
        assert "Python" in summary
        assert "remote AI roles" in summary

    def test_get_career_summary_empty(self, tmp_path: Path) -> None:
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        with patch("core.memory.user_profile.Path.home", return_value=tmp_path):
            summary = profile.get_career_summary()
        assert summary == ""


# ---------------------------------------------------------------------------
# Feature 1b: career context in system prompt
# ---------------------------------------------------------------------------


class TestCareerSystemPrompt:
    """_build_career_context() injects career data."""

    def test_build_career_context_with_data(self, tmp_path: Path) -> None:
        from core.cli.system_prompt import _build_career_context

        identity_dir = tmp_path / ".geode" / "identity"
        identity_dir.mkdir(parents=True)
        (identity_dir / "career.toml").write_text(
            '[identity]\ntitle = "ML Engineer"\nexperience = "3y"\n'
            'skills = ["Python"]\n\n[goals]\nseeking = "startup"\n',
            encoding="utf-8",
        )

        with patch("core.memory.user_profile.Path.home", return_value=tmp_path):
            result = _build_career_context()

        assert "## User Career" in result
        assert "ML Engineer" in result

    def test_build_career_context_no_data(self, tmp_path: Path) -> None:
        from core.cli.system_prompt import _build_career_context

        with patch("core.memory.user_profile.Path.home", return_value=tmp_path):
            result = _build_career_context()
        assert result == ""


# ---------------------------------------------------------------------------
# Feature 2: /context command
# ---------------------------------------------------------------------------


class TestCmdContext:
    """cmd_context displays context tier summaries."""

    def test_context_default(self) -> None:
        """Calling cmd_context with no args should not raise."""
        from core.cli.commands import cmd_context

        # Just ensure it runs without error (console output is side-effect)
        cmd_context("")

    def test_context_career_no_data(self, tmp_path: Path) -> None:
        from core.cli.commands import cmd_context

        with patch("core.memory.user_profile.Path.home", return_value=tmp_path):
            cmd_context("career")  # should not raise

    def test_context_profile(self) -> None:
        from core.cli.commands import cmd_context

        cmd_context("profile")  # should not raise


# ---------------------------------------------------------------------------
# Feature 2: /context and /apply in COMMAND_MAP
# ---------------------------------------------------------------------------


class TestCommandMapRegistration:
    """Verify new commands are registered."""

    def test_context_in_command_map(self) -> None:
        from core.cli.commands import COMMAND_MAP

        assert "/context" in COMMAND_MAP
        assert COMMAND_MAP["/context"] == "context"
        assert "/ctx" in COMMAND_MAP
        assert COMMAND_MAP["/ctx"] == "context"

    def test_apply_in_command_map(self) -> None:
        from core.cli.commands import COMMAND_MAP

        assert "/apply" in COMMAND_MAP
        assert COMMAND_MAP["/apply"] == "apply"


# ---------------------------------------------------------------------------
# Feature 3: ApplicationTracker CRUD
# ---------------------------------------------------------------------------


class TestApplicationTracker:
    """ApplicationTracker CRUD operations on tracker.json."""

    def test_list_empty(self, tmp_path: Path) -> None:
        from core.memory.vault import ApplicationTracker

        tracker = ApplicationTracker(vault_dir=tmp_path)
        assert tracker.list() == []

    def test_add_and_list(self, tmp_path: Path) -> None:
        from core.memory.vault import ApplicationEntry, ApplicationTracker

        tracker = ApplicationTracker(vault_dir=tmp_path)
        tracker.add(ApplicationEntry(company="Anthropic", position="AI Engineer"))
        tracker.add(ApplicationEntry(company="OpenAI", position="ML Researcher"))

        entries = tracker.list()
        assert len(entries) == 2
        assert entries[0].company == "Anthropic"
        assert entries[0].position == "AI Engineer"
        assert entries[0].status == "draft"
        assert entries[1].company == "OpenAI"

    def test_update_status(self, tmp_path: Path) -> None:
        from core.memory.vault import ApplicationEntry, ApplicationTracker

        tracker = ApplicationTracker(vault_dir=tmp_path)
        tracker.add(ApplicationEntry(company="Anthropic", position="AI Engineer"))

        assert tracker.update_status("Anthropic", "applied") is True
        entries = tracker.list()
        assert entries[0].status == "applied"

    def test_update_status_case_insensitive(self, tmp_path: Path) -> None:
        from core.memory.vault import ApplicationEntry, ApplicationTracker

        tracker = ApplicationTracker(vault_dir=tmp_path)
        tracker.add(ApplicationEntry(company="Anthropic", position="AI Engineer"))

        assert tracker.update_status("anthropic", "interview") is True
        entries = tracker.list()
        assert entries[0].status == "interview"

    def test_update_status_not_found(self, tmp_path: Path) -> None:
        from core.memory.vault import ApplicationTracker

        tracker = ApplicationTracker(vault_dir=tmp_path)
        assert tracker.update_status("NonExistent", "applied") is False

    def test_remove(self, tmp_path: Path) -> None:
        from core.memory.vault import ApplicationEntry, ApplicationTracker

        tracker = ApplicationTracker(vault_dir=tmp_path)
        tracker.add(ApplicationEntry(company="Anthropic", position="AI Engineer"))
        tracker.add(ApplicationEntry(company="OpenAI", position="ML Researcher"))

        assert tracker.remove("Anthropic") is True
        entries = tracker.list()
        assert len(entries) == 1
        assert entries[0].company == "OpenAI"

    def test_remove_not_found(self, tmp_path: Path) -> None:
        from core.memory.vault import ApplicationTracker

        tracker = ApplicationTracker(vault_dir=tmp_path)
        assert tracker.remove("NonExistent") is False

    def test_persistence(self, tmp_path: Path) -> None:
        """Verify data survives across tracker instances."""
        from core.memory.vault import ApplicationEntry, ApplicationTracker

        tracker1 = ApplicationTracker(vault_dir=tmp_path)
        tracker1.add(ApplicationEntry(company="Anthropic", position="AI Engineer"))

        # New instance should see the same data
        tracker2 = ApplicationTracker(vault_dir=tmp_path)
        entries = tracker2.list()
        assert len(entries) == 1
        assert entries[0].company == "Anthropic"

    def test_tracker_json_format(self, tmp_path: Path) -> None:
        """Verify the JSON file is valid and well-structured."""
        from core.memory.vault import ApplicationEntry, ApplicationTracker

        tracker = ApplicationTracker(vault_dir=tmp_path)
        tracker.add(ApplicationEntry(company="Anthropic", position="Engineer", url="https://example.com"))

        json_path = tmp_path / "applications" / "tracker.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert data[0]["company"] == "Anthropic"
        assert data[0]["url"] == "https://example.com"


# ---------------------------------------------------------------------------
# Feature 3b: /apply command
# ---------------------------------------------------------------------------


class TestCmdApply:
    """cmd_apply dispatches ApplicationTracker operations."""

    def test_apply_list_empty(self) -> None:
        """Calling /apply with no tracked applications should not raise."""
        from core.cli.commands import cmd_apply
        from core.memory.vault import ApplicationTracker

        with patch.object(ApplicationTracker, "list", return_value=[]):
            cmd_apply("")

    def test_apply_add(self, tmp_path: Path) -> None:
        from core.cli.commands import cmd_apply
        from core.memory.vault import ApplicationTracker

        with patch.object(ApplicationTracker, "__init__", return_value=None), \
             patch.object(ApplicationTracker, "add") as mock_add:
            # Need _path for __init__ bypass
            cmd_apply("add Anthropic AI Engineer")
            mock_add.assert_called_once()
            entry = mock_add.call_args[0][0]
            assert entry.company == "Anthropic"
            assert entry.position == "AI Engineer"

    def test_apply_status_update(self) -> None:
        from core.cli.commands import cmd_apply
        from core.memory.vault import ApplicationTracker

        with patch.object(ApplicationTracker, "__init__", return_value=None), \
             patch.object(ApplicationTracker, "update_status", return_value=True):
            cmd_apply("status Anthropic interview")

    def test_apply_remove(self) -> None:
        from core.cli.commands import cmd_apply
        from core.memory.vault import ApplicationTracker

        with patch.object(ApplicationTracker, "__init__", return_value=None), \
             patch.object(ApplicationTracker, "remove", return_value=True):
            cmd_apply("remove Anthropic")


# ---------------------------------------------------------------------------
# Feature 1b: ContextAssembler career injection
# ---------------------------------------------------------------------------


class TestContextAssemblerCareer:
    """ContextAssembler injects career summary when available."""

    def test_career_injected_into_context(self, tmp_path: Path) -> None:
        from core.memory.context import ContextAssembler
        from core.memory.user_profile import FileBasedUserProfile

        identity_dir = tmp_path / ".geode" / "identity"
        identity_dir.mkdir(parents=True)
        (identity_dir / "career.toml").write_text(
            '[identity]\ntitle = "AI Engineer"\nskills = ["Python"]\n'
            '[goals]\nseeking = "startup"\n',
            encoding="utf-8",
        )

        profile = FileBasedUserProfile(global_dir=tmp_path / "profile")
        # Create minimal profile so exists() returns True
        (tmp_path / "profile").mkdir(parents=True, exist_ok=True)
        (tmp_path / "profile" / "profile.md").write_text(
            "---\nrole: dev\n---\n", encoding="utf-8"
        )

        assembler = ContextAssembler(user_profile=profile)

        with patch("core.memory.user_profile.Path.home", return_value=tmp_path):
            ctx = assembler.assemble("test-session", "test-ip")

        assert "_career_summary" in ctx
        assert "AI Engineer" in ctx["_career_summary"]
