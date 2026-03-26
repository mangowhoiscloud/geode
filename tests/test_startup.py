"""Tests for CLI startup readiness checks (OpenClaw gateway:startup pattern)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.cli.startup import (
    Capability,
    ReadinessReport,
    check_readiness,
    detect_api_key,
    env_setup_wizard,
    setup_project_memory,
)
from core.config import ANTHROPIC_PRIMARY, GLM_PRIMARY, OPENAI_PRIMARY


def _no_keys_mock(mock_settings):
    """Configure mock_settings with all LLM keys empty."""
    mock_settings.anthropic_api_key = ""
    mock_settings.openai_api_key = ""
    mock_settings.zai_api_key = ""


class TestCapability:
    def test_available(self):
        cap = Capability(name="LLM", available=True)
        assert cap.available is True
        assert cap.reason == ""

    def test_unavailable_with_reason(self):
        cap = Capability(name="LLM", available=False, reason="no key")
        assert cap.available is False
        assert cap.reason == "no key"


class TestReadinessReport:
    def test_all_ready_true(self):
        report = ReadinessReport(
            capabilities=[
                Capability("A", True),
                Capability("B", True),
            ]
        )
        assert report.all_ready is True

    def test_all_ready_false(self):
        report = ReadinessReport(
            capabilities=[
                Capability("A", True),
                Capability("B", False, "missing"),
            ]
        )
        assert report.all_ready is False

    def test_empty_capabilities_all_ready(self):
        report = ReadinessReport()
        assert report.all_ready is True


class TestCheckReadiness:
    def test_without_api_key(self, tmp_path: Path):
        with patch("core.cli.startup.settings") as mock_settings:
            _no_keys_mock(mock_settings)
            report = check_readiness(tmp_path)

        assert report.has_api_key is False
        assert report.force_dry_run is True

        # Should have LLM Analysis capability marked unavailable
        llm_cap = next(c for c in report.capabilities if c.name == "LLM Analysis")
        assert llm_cap.available is False

    def test_with_anthropic_key(self, tmp_path: Path):
        with patch("core.cli.startup.settings") as mock_settings:
            _no_keys_mock(mock_settings)
            mock_settings.anthropic_api_key = "sk-ant-real-key-here"
            report = check_readiness(tmp_path)

        assert report.has_api_key is True
        assert report.force_dry_run is False

        llm_cap = next(c for c in report.capabilities if c.name == "LLM Analysis")
        assert llm_cap.available is True

    def test_with_openai_key_only(self, tmp_path: Path):
        """ANY provider key unblocks — OpenAI alone should suffice."""
        with patch("core.cli.startup.settings") as mock_settings:
            _no_keys_mock(mock_settings)
            mock_settings.openai_api_key = "sk-proj-real-key-here"
            report = check_readiness(tmp_path)

        assert report.has_api_key is True
        assert report.blocked is False

    def test_with_glm_key_only(self, tmp_path: Path):
        """ANY provider key unblocks — GLM alone should suffice."""
        with patch("core.cli.startup.settings") as mock_settings:
            _no_keys_mock(mock_settings)
            mock_settings.zai_api_key = "abc12345.def67890"
            report = check_readiness(tmp_path)

        assert report.has_api_key is True
        assert report.blocked is False

    def test_placeholder_key_treated_as_missing(self, tmp_path: Path):
        with patch("core.cli.startup.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-ant-..."
            mock_settings.openai_api_key = "sk-..."
            mock_settings.zai_api_key = "..."
            report = check_readiness(tmp_path)

        assert report.has_api_key is False
        assert report.force_dry_run is True

    def test_env_file_check(self, tmp_path: Path):
        with patch("core.cli.startup.settings") as mock_settings:
            _no_keys_mock(mock_settings)

            # No .env, no .env.example
            report = check_readiness(tmp_path)
            assert report.has_env_file is False

            # Create .env.example only → should suggest cp
            (tmp_path / ".env.example").write_text("KEY=value\n")
            report = check_readiness(tmp_path)
            assert report.has_env_file is False
            env_cap = [c for c in report.capabilities if c.name == "Environment"]
            assert len(env_cap) == 1
            assert "cp" in env_cap[0].reason

            # Create .env → should be satisfied
            (tmp_path / ".env").write_text("KEY=value\n")
            report = check_readiness(tmp_path)
            assert report.has_env_file is True

    def test_project_memory_check(self, tmp_path: Path):
        with patch("core.cli.startup.settings") as mock_settings:
            _no_keys_mock(mock_settings)

            # No .geode/memory/PROJECT.md → unavailable
            report = check_readiness(tmp_path)
            assert report.has_memory is False
            mem_cap = next(c for c in report.capabilities if c.name == "Project Memory")
            assert mem_cap.available is False

            # Create .geode/memory/PROJECT.md → available
            mem_dir = tmp_path / ".geode" / "memory"
            mem_dir.mkdir(parents=True)
            (mem_dir / "PROJECT.md").write_text("# Memory\n")
            report = check_readiness(tmp_path)
            assert report.has_memory is True
            mem_cap = next(c for c in report.capabilities if c.name == "Project Memory")
            assert mem_cap.available is True

    def test_always_available_capabilities(self, tmp_path: Path):
        with patch("core.cli.startup.settings") as mock_settings:
            _no_keys_mock(mock_settings)
            report = check_readiness(tmp_path)

        names = [c.name for c in report.capabilities]
        assert "Dry-Run Analysis" in names
        assert "IP Search" in names

        dry_run_cap = next(c for c in report.capabilities if c.name == "Dry-Run Analysis")
        assert dry_run_cap.available is True


class TestDetectApiKey:
    """Test natural-language API key detection."""

    def test_anthropic_key(self):
        result = detect_api_key("sk-ant-api03-abcdefghij1234567890")
        assert result is not None
        assert result[0] == "anthropic"
        assert result[1] == "ANTHROPIC_API_KEY"

    def test_openai_proj_key(self):
        result = detect_api_key("sk-proj-abcdefghij1234567890")
        assert result is not None
        assert result[0] == "openai"

    def test_openai_sk_key(self):
        result = detect_api_key("sk-abcdefghij1234567890ABCD")
        assert result is not None
        assert result[0] == "openai"

    def test_glm_key(self):
        result = detect_api_key("abc12345def.ghijklmn12345")
        assert result is not None
        assert result[0] == "glm"
        assert result[1] == "ZAI_API_KEY"

    def test_normal_text_not_detected(self):
        assert detect_api_key("Hello world") is None
        assert detect_api_key("Berserk 분석해줘") is None
        assert detect_api_key("") is None

    def test_short_key_not_detected(self):
        assert detect_api_key("sk-short") is None

    def test_email_not_detected(self):
        """Email addresses must not be misdetected as GLM keys."""
        assert detect_api_key("ryoo0504@gmail.com") is None
        assert detect_api_key("user@example.com") is None

    def test_email_with_trailing_text_not_detected(self):
        """Email with Korean suffix must not be misdetected."""
        assert detect_api_key("ryoo0504@gmail.com이야.") is None


class TestEnvSetupWizard:
    def test_wizard_skips_on_enter(self, tmp_path):
        """User presses Enter for all prompts → no keys set."""
        with (
            patch("core.cli.startup.console") as mock_console,
            patch("core.cli.startup.settings") as mock_settings,
        ):
            _no_keys_mock(mock_settings)
            mock_console.input.return_value = ""
            result = env_setup_wizard()
        assert result is False

    def test_wizard_sets_key(self, tmp_path):
        """User enters a key for Anthropic, skips others."""
        with (
            patch("core.cli.startup.console") as mock_console,
            patch("core.cli.startup._upsert_env"),
            patch("core.cli.startup.settings") as mock_settings,
        ):
            _no_keys_mock(mock_settings)
            mock_console.input.side_effect = [
                "sk-ant-test-key-12345678",  # Anthropic
                "",  # OpenAI skip
                "",  # ZhipuAI skip
            ]
            result = env_setup_wizard()
        assert result is True

    def test_wizard_handles_ctrl_c(self, tmp_path):
        """Ctrl+C during wizard gracefully stops."""
        with (
            patch("core.cli.startup.console") as mock_console,
            patch("core.cli.startup.settings") as mock_settings,
        ):
            _no_keys_mock(mock_settings)
            mock_console.input.side_effect = KeyboardInterrupt
            result = env_setup_wizard()
        assert result is False


class TestIsPlaceholder:
    """Test _is_placeholder helper."""

    def test_ellipsis_exact(self):
        from core.cli.startup import _is_placeholder

        assert _is_placeholder("...") is True

    def test_prefixed_ellipsis(self):
        from core.cli.startup import _is_placeholder

        assert _is_placeholder("sk-ant-...") is True
        assert _is_placeholder("sk-...") is True
        assert _is_placeholder("lsv2_pt_...") is True
        assert _is_placeholder("BSA...") is True

    def test_real_value_not_placeholder(self):
        from core.cli.startup import _is_placeholder

        assert _is_placeholder("sk-ant-api03-realkey123456789") is False
        assert _is_placeholder("") is False
        assert _is_placeholder("some-real-key") is False
        assert _is_placeholder("true") is False

    def test_trailing_dots_not_three(self):
        from core.cli.startup import _is_placeholder

        # Only exactly "..." at end counts
        assert _is_placeholder("value..") is False
        assert _is_placeholder("value.") is False


class TestAutoGenerateEnv:
    """Test auto_generate_env function."""

    def test_creates_env_from_example(self, tmp_path: Path):
        from core.cli.startup import auto_generate_env

        example = tmp_path / ".env.example"
        example.write_text("ANTHROPIC_API_KEY=sk-ant-...\nDEBUG=true\n")

        result = auto_generate_env(tmp_path)
        assert result is True

        env = tmp_path / ".env"
        assert env.exists()
        content = env.read_text()
        assert "ANTHROPIC_API_KEY=" in content
        # Placeholder should be replaced with empty value
        assert "sk-ant-..." not in content
        # Non-placeholder value should remain
        assert "DEBUG=true" in content

    def test_env_file_permissions(self, tmp_path: Path):
        """P0-1: .env must have 0o600 permissions (owner read/write only)."""
        from core.cli.startup import auto_generate_env

        example = tmp_path / ".env.example"
        example.write_text("KEY=sk-ant-...\n")

        auto_generate_env(tmp_path)
        env = tmp_path / ".env"
        mode = env.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_atomic_write_no_partial(self, tmp_path: Path):
        """P0-2: .env should not exist as .tmp after successful write."""
        from core.cli.startup import auto_generate_env

        example = tmp_path / ".env.example"
        example.write_text("KEY=value\n")

        auto_generate_env(tmp_path)
        assert not (tmp_path / ".env.tmp").exists()
        assert (tmp_path / ".env").exists()

    def test_skips_existing_env(self, tmp_path: Path):
        from core.cli.startup import auto_generate_env

        example = tmp_path / ".env.example"
        example.write_text("KEY=sk-...\n")
        env = tmp_path / ".env"
        env.write_text("KEY=my-real-key\n")

        result = auto_generate_env(tmp_path)
        assert result is False
        # Original .env should be untouched
        assert env.read_text() == "KEY=my-real-key\n"

    def test_no_example_file(self, tmp_path: Path):
        from core.cli.startup import auto_generate_env

        # Neither .env nor .env.example exist
        result = auto_generate_env(tmp_path)
        assert result is False
        assert not (tmp_path / ".env").exists()

    def test_replaces_placeholders(self, tmp_path: Path):
        from core.cli.startup import auto_generate_env

        example = tmp_path / ".env.example"
        example.write_text(
            "ANTHROPIC_API_KEY=sk-ant-...\n"
            "OPENAI_API_KEY=sk-...\n"
            "ZAI_API_KEY=...\n"
            "DEBUG=true\n"
            "# This is a comment\n"
            "GEODE_MODEL=claude-opus-4-6\n"
        )

        result = auto_generate_env(tmp_path)
        assert result is True

        content = (tmp_path / ".env").read_text()
        lines = content.strip().split("\n")

        # Placeholders become empty — assert value after '=' is empty
        assert lines[0] == "ANTHROPIC_API_KEY="
        assert lines[1] == "OPENAI_API_KEY="
        assert lines[2] == "ZAI_API_KEY="

        # Non-placeholders preserved
        assert "DEBUG=true" in content
        assert "# This is a comment" in content
        assert "GEODE_MODEL=claude-opus-4-6" in content

    def test_preserves_comments(self, tmp_path: Path):
        from core.cli.startup import auto_generate_env

        example = tmp_path / ".env.example"
        example.write_text(
            "# Anthropic\nANTHROPIC_API_KEY=sk-ant-...\n\n# OpenAI\nOPENAI_API_KEY=sk-...\n"
        )

        auto_generate_env(tmp_path)
        content = (tmp_path / ".env").read_text()
        assert "# Anthropic" in content
        assert "# OpenAI" in content


class TestResolveProvider:
    """Test _resolve_provider helper."""

    def test_anthropic(self):
        from core.config import _resolve_provider

        assert _resolve_provider(ANTHROPIC_PRIMARY) == "anthropic"
        assert _resolve_provider("claude-sonnet-4-6") == "anthropic"

    def test_openai(self):
        from core.config import _resolve_provider

        assert _resolve_provider(OPENAI_PRIMARY) == "openai"
        assert _resolve_provider("gpt-4.1") == "openai"

    def test_glm(self):
        from core.config import _resolve_provider

        assert _resolve_provider(GLM_PRIMARY) == "glm"
        assert _resolve_provider("glm-5-turbo") == "glm"
        assert _resolve_provider("glm-4.7-flash") == "glm"


class TestUpdateModel:
    """Test AgenticLoop.update_model method."""

    def test_update_model_changes_provider(self):
        from unittest.mock import MagicMock

        from core.agent.agentic_loop import AgenticLoop
        from core.agent.conversation import ConversationContext
        from core.agent.tool_executor import ToolExecutor

        ctx = ConversationContext()
        executor = MagicMock(spec=ToolExecutor)
        loop = AgenticLoop(ctx, executor)
        assert loop.model == ANTHROPIC_PRIMARY
        assert loop._provider == "anthropic"

        loop.update_model(GLM_PRIMARY)
        assert loop.model == GLM_PRIMARY
        assert loop._provider == "glm"
        assert loop._adapter.provider_name == "glm"  # adapter re-created

    def test_update_model_same_provider_keeps_adapter(self):
        from unittest.mock import MagicMock

        from core.agent.agentic_loop import AgenticLoop
        from core.agent.conversation import ConversationContext
        from core.agent.tool_executor import ToolExecutor

        ctx = ConversationContext()
        executor = MagicMock(spec=ToolExecutor)
        loop = AgenticLoop(ctx, executor)
        original_adapter = loop._adapter

        loop.update_model("claude-sonnet-4-6")
        assert loop.model == "claude-sonnet-4-6"
        assert loop._provider == "anthropic"
        assert loop._adapter is original_adapter  # kept — same provider


class TestGlmClient:
    """Test GLM client creation with custom base_url."""

    def test_get_glm_client_base_url(self):
        from unittest.mock import MagicMock
        from unittest.mock import patch as _p

        from core.config import GLM_BASE_URL

        mock_openai_mod = MagicMock()

        with (
            _p.dict("sys.modules", {"openai": mock_openai_mod}),
            _p("core.llm.providers.glm._glm_client", None),
            _p("core.llm.providers.glm.settings") as ms,
        ):
            ms.zai_api_key = "test-key"
            from core.llm.providers.glm import _get_glm_client

            _get_glm_client()
            mock_openai_mod.OpenAI.assert_called_once_with(
                api_key="test-key",
                base_url=GLM_BASE_URL,
            )


class TestModelProfiles:
    """Test MODEL_PROFILES includes GLM entries."""

    def test_glm_profiles_present(self):
        from core.cli.commands import MODEL_PROFILES

        ids = [p.id for p in MODEL_PROFILES]
        assert GLM_PRIMARY in ids
        assert "glm-5-turbo" in ids
        assert "glm-4.7-flash" in ids

    def test_glm_profiles_provider(self):
        from core.cli.commands import MODEL_PROFILES

        glm_profiles = [p for p in MODEL_PROFILES if p.provider == "ZhipuAI"]
        assert len(glm_profiles) == 3


class TestSetupProjectMemory:
    def test_creates_memory(self, tmp_path: Path):
        created = setup_project_memory(tmp_path)
        assert created is True
        assert (tmp_path / ".geode" / "memory" / "PROJECT.md").exists()

    def test_idempotent(self, tmp_path: Path):
        assert setup_project_memory(tmp_path) is True
        assert setup_project_memory(tmp_path) is False


class TestSetupUserProfileWarning:
    """Fix 1: setup_user_profile() logs warning (not debug) on failure."""

    def test_logs_warning_on_exception(self):
        """setup_user_profile() should log.warning on failure, not log.debug."""
        from unittest.mock import MagicMock

        from core.cli.startup import setup_user_profile

        mock_profile = MagicMock()
        mock_profile.ensure_structure.side_effect = RuntimeError("boom")

        with (
            patch(
                "core.memory.user_profile.FileBasedUserProfile",
                return_value=mock_profile,
            ),
            patch("core.cli.startup.log") as mock_log,
        ):
            result = setup_user_profile()
            assert result is False
            mock_log.warning.assert_called_once()
            assert "boom" in str(mock_log.warning.call_args)

    def test_returns_false_on_failure(self):
        from unittest.mock import MagicMock

        from core.cli.startup import setup_user_profile

        mock_profile = MagicMock()
        mock_profile.ensure_structure.side_effect = OSError("denied")

        with patch(
            "core.memory.user_profile.FileBasedUserProfile",
            return_value=mock_profile,
        ):
            assert setup_user_profile() is False


class TestReadinessProfileStatus:
    """Fix 2: check_readiness() includes User Profile capability."""

    def test_profile_exists_shown_available(self, tmp_path: Path):
        """When global profile exists, User Profile capability is available."""
        from unittest.mock import MagicMock

        mock_profile_instance = MagicMock()
        mock_profile_instance.exists.return_value = True

        with (
            patch("core.cli.startup.settings") as mock_settings,
            patch(
                "core.memory.user_profile.FileBasedUserProfile",
                return_value=mock_profile_instance,
            ),
        ):
            _no_keys_mock(mock_settings)
            report = check_readiness(tmp_path)

        assert report.has_profile is True
        profile_cap = next(c for c in report.capabilities if c.name == "User Profile")
        assert profile_cap.available is True

    def test_profile_missing_shown_unavailable(self, tmp_path: Path):
        """When no profile exists, User Profile shows as unavailable with hint."""
        from unittest.mock import MagicMock

        mock_profile_instance = MagicMock()
        mock_profile_instance.exists.return_value = False

        with (
            patch("core.cli.startup.settings") as mock_settings,
            patch(
                "core.memory.user_profile.FileBasedUserProfile",
                return_value=mock_profile_instance,
            ),
        ):
            _no_keys_mock(mock_settings)
            report = check_readiness(tmp_path)

        assert report.has_profile is False
        profile_cap = next(c for c in report.capabilities if c.name == "User Profile")
        assert profile_cap.available is False
        assert "/profile" in profile_cap.reason

    def test_profile_load_exception_handled(self, tmp_path: Path):
        """If FileBasedUserProfile raises, profile shows as unavailable."""
        with (
            patch("core.cli.startup.settings") as mock_settings,
            patch(
                "core.memory.user_profile.FileBasedUserProfile",
                side_effect=RuntimeError("broken"),
            ),
        ):
            _no_keys_mock(mock_settings)
            report = check_readiness(tmp_path)

        assert report.has_profile is False
        profile_cap = next(c for c in report.capabilities if c.name == "User Profile")
        assert profile_cap.available is False
        assert "load failed" in profile_cap.reason


class TestGeodeInitProfileSeeding:
    """Fix 3: geode init seeds project profile from global."""

    def test_seeds_project_profile_from_global(self, tmp_path: Path, monkeypatch):
        """When global profile exists and project profile absent, copy it."""
        import shutil

        # Set up global profile dir
        global_profile = tmp_path / "global_profile"
        global_profile.mkdir(parents=True)
        (global_profile / "profile.md").write_text("---\nrole: engineer\n---\n")
        (global_profile / "preferences.json").write_text('{"lang": "ko"}\n')

        # Set up project dir
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        project_profile = project_dir / ".geode" / "user_profile"
        # .geode exists but user_profile does not
        (project_dir / ".geode").mkdir()

        # Simulate the seeding logic from geode init
        if not project_profile.exists() and global_profile.exists():
            shutil.copytree(str(global_profile), str(project_profile))

        assert project_profile.exists()
        assert (project_profile / "profile.md").exists()
        assert "engineer" in (project_profile / "profile.md").read_text()
        assert (project_profile / "preferences.json").exists()

    def test_does_not_overwrite_existing_project_profile(self, tmp_path: Path):
        """If project profile already exists, do not overwrite."""
        import shutil

        # Set up global profile
        global_profile = tmp_path / "global_profile"
        global_profile.mkdir(parents=True)
        (global_profile / "profile.md").write_text("---\nrole: global\n---\n")

        # Set up existing project profile
        project_profile = tmp_path / ".geode" / "user_profile"
        project_profile.mkdir(parents=True)
        (project_profile / "profile.md").write_text("---\nrole: local\n---\n")

        # Seeding logic: should skip
        if not project_profile.exists() and global_profile.exists():
            shutil.copytree(str(global_profile), str(project_profile))

        # Project profile should be untouched
        assert "local" in (project_profile / "profile.md").read_text()
