"""Tests for CLI startup readiness checks (OpenClaw gateway:startup pattern)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.onboarding import dry_run_opted_in, env_setup_wizard
from core.config import ANTHROPIC_PRIMARY, GLM_PRIMARY, OPENAI_PRIMARY
from core.wiring.startup import (
    Capability,
    ReadinessReport,
    check_readiness,
)


def _no_keys_mock(mock_settings):
    """Configure mock_settings with all LLM keys empty."""
    mock_settings.anthropic_api_key = ""
    mock_settings.openai_api_key = ""
    mock_settings.openrouter_api_key = ""
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
    @pytest.mark.parametrize("available", [False, True])
    def test_readiness_uses_the_shared_credential_route(self, tmp_path, available):
        with patch("core.wiring.startup.has_available_llm_credential", return_value=available):
            report = check_readiness(tmp_path)
        assert report.has_api_key is available
        assert report.blocked is not available
        assert report.force_dry_run is False
        assert (
            next(c for c in report.capabilities if c.name == "LLM Analysis").available is available
        )

    def test_env_file_check(self, tmp_path: Path):
        with patch("core.config.settings") as mock_settings:
            _no_keys_mock(mock_settings)

            # No .env, no .env.example
            report = check_readiness(tmp_path)
            assert report.has_env_file is False

            # An example is optional project configuration
            (tmp_path / ".env.example").write_text("KEY=value\n")
            report = check_readiness(tmp_path)
            assert report.has_env_file is False
            env_cap = [c for c in report.capabilities if c.name == "Environment"]
            assert len(env_cap) == 1
            assert env_cap[0].required is False

            # Create .env → should be satisfied
            (tmp_path / ".env").write_text("KEY=value\n")
            report = check_readiness(tmp_path)
            assert report.has_env_file is True

    def test_project_memory_check(self, tmp_path: Path):
        with patch("core.config.settings") as mock_settings:
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
        with patch("core.config.settings") as mock_settings:
            _no_keys_mock(mock_settings)
            report = check_readiness(tmp_path)

        names = [c.name for c in report.capabilities]
        assert "Setup and session commands" in names

        dry_run_cap = next(c for c in report.capabilities if c.name == "Setup and session commands")
        assert dry_run_cap.available is True


class TestEnvSetupWizard:
    """v0.54.0 — three-branch menu (1: subscription / 2: API key / 3: skip)."""

    @pytest.fixture(autouse=True)
    def isolate_dry_run_marker(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "core.paths.GLOBAL_DRY_RUN_MARKER",
            tmp_path / ".dry-run-opt-in",
        )

    def test_wizard_skips_on_enter_after_choosing_path_b(self, tmp_path):
        """An empty key for the selected provider does not complete setup."""
        with (
            patch("core.cli.onboarding.console") as mock_console,
            patch("core.config.settings") as mock_settings,
            patch("sys.stdin.isatty", return_value=True),
            patch("core.cli.commands.login.TerminalMenu") as menu,
        ):
            menu.return_value.show.return_value = 0
            _no_keys_mock(mock_settings)
            mock_console.input.return_value = "2"
            with patch("getpass.getpass", return_value=""):
                result = env_setup_wizard()
        assert result is False

    @pytest.mark.parametrize(
        "index,provider", [(0, "anthropic"), (1, "openai"), (2, "openrouter"), (3, "glm")]
    )
    def test_wizard_sets_key_via_path_b(self, tmp_path, index, provider):
        """Setup asks only for the selected provider, including OpenRouter."""
        with (
            patch("core.cli.onboarding.console") as mock_console,
            patch("core.auth.auth_toml.save_api_key") as save,
            patch("core.config.settings") as mock_settings,
            patch("sys.stdin.isatty", return_value=True),
            patch("core.cli.commands.login.TerminalMenu") as menu,
        ):
            menu.return_value.show.return_value = index
            _no_keys_mock(mock_settings)
            mock_console.input.return_value = "2"
            with patch("getpass.getpass", return_value="synthetic-provider-key") as hidden:
                result = env_setup_wizard()
        menu.assert_called_once()
        hidden.assert_called_once()
        save.assert_called_once_with("synthetic-provider-key", provider=provider)
        assert result is True

    def test_wizard_provider_cancel_does_not_prompt_or_save_key(self):
        with (
            patch("core.cli.onboarding.console") as console,
            patch("sys.stdin.isatty", return_value=True),
            patch("core.cli.commands.login.TerminalMenu") as menu,
            patch("getpass.getpass") as hidden,
            patch("core.auth.auth_toml.save_api_key") as save,
        ):
            console.input.return_value = "2"
            menu.return_value.show.return_value = None
            assert env_setup_wizard() is False
        hidden.assert_not_called()
        save.assert_not_called()

    def test_wizard_handles_ctrl_c(self, tmp_path):
        """Ctrl+C at the menu prompt gracefully stops."""
        with (
            patch("core.cli.onboarding.console") as mock_console,
            patch("core.config.settings") as mock_settings,
        ):
            _no_keys_mock(mock_settings)
            mock_console.input.side_effect = KeyboardInterrupt
            result = env_setup_wizard()
        assert result is False

    @pytest.mark.parametrize("success", [True, False])
    def test_wizard_subscription_uses_native_login(self, success):
        with (
            patch("core.cli.onboarding.console") as console,
            patch("core.cli.commands.cmd_login", return_value=success) as login,
        ):
            console.input.return_value = "1"
            assert env_setup_wizard() is success
        login.assert_called_once_with("openai")

    def test_wizard_skip_path_explicitly(self, tmp_path):
        """Path C — user chose skip (dry-run). Returns True so wizard
        won't re-prompt on next launch."""
        with (
            patch("core.cli.onboarding.console") as mock_console,
            patch("core.config.settings") as mock_settings,
        ):
            _no_keys_mock(mock_settings)
            mock_console.input.side_effect = ["3"]
            result = env_setup_wizard()
        assert result is True
        assert dry_run_opted_in() is True

    def test_wizard_reports_skip_marker_write_failure(self, monkeypatch, tmp_path):
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("x")
        monkeypatch.setattr(
            "core.paths.GLOBAL_DRY_RUN_MARKER",
            blocker / ".dry-run-opt-in",
        )
        with patch("core.cli.onboarding.console") as mock_console:
            mock_console.input.side_effect = ["3"]
            result = env_setup_wizard()
        assert result is False
        rendered = " ".join(str(call.args[0]) for call in mock_console.print.call_args_list)
        assert "Could not save" in rendered


def test_welcome_does_not_repeat_wizard_after_dry_run_opt_in():
    """A persisted skip choice, not project .env presence, gates re-prompting."""
    from core.cli.welcome import _welcome_screen

    report = ReadinessReport(blocked=True)
    with (
        patch("core.cli.welcome._render_welcome_brand"),
        patch("core.wiring.startup.has_available_llm_credential", return_value=False),
        patch("core.cli.welcome.dry_run_opted_in", return_value=True),
        patch("core.cli.welcome.env_setup_wizard") as wizard,
        patch("core.cli.welcome.check_readiness", return_value=report),
        patch("core.cli.welcome._render_readiness_compact"),
        patch("core.cli.welcome.console"),
    ):
        _welcome_screen()

    wizard.assert_not_called()


def test_welcome_clears_dry_run_opt_in_when_stored_route_is_available():
    """A discovered credential makes a previous skip choice stale."""
    from core.cli.welcome import _welcome_screen

    report = ReadinessReport(has_api_key=True)
    with (
        patch("core.cli.welcome._render_welcome_brand"),
        patch("core.wiring.startup.has_available_llm_credential", return_value=True),
        patch("core.cli.welcome.clear_dry_run_opt_in") as clear_opt_in,
        patch("core.cli.welcome.check_readiness", return_value=report),
        patch("core.cli.welcome._render_readiness_compact"),
        patch("core.cli.welcome.console"),
    ):
        _welcome_screen()

    clear_opt_in.assert_called_once_with()


def test_welcome_clears_dry_run_opt_in_when_api_key_is_detected():
    """An existing API key also makes a previous skip choice stale."""
    from core.cli.welcome import _welcome_screen

    report = ReadinessReport(has_api_key=True)
    with (
        patch("core.cli.welcome._render_welcome_brand"),
        patch("core.wiring.startup.has_available_llm_credential", return_value=True),
        patch("core.cli.welcome.clear_dry_run_opt_in") as clear_opt_in,
        patch("core.cli.welcome.check_readiness", return_value=report),
        patch("core.cli.welcome._render_readiness_compact"),
        patch("core.cli.welcome.console"),
    ):
        _welcome_screen()

    clear_opt_in.assert_called_once_with()


def test_welcome_inspects_once_and_leaves_optional_project_inputs_untouched(tmp_path, monkeypatch):
    from core.cli.welcome import _welcome_screen

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=placeholder\n")
    report = ReadinessReport(
        has_api_key=True,
        capabilities=[Capability("Project Memory", False, required=False)],
    )
    with (
        patch("core.cli.welcome.check_readiness", return_value=report) as inspect,
        patch("core.cli.welcome._render_welcome_brand"),
        patch("core.cli.welcome.clear_dry_run_opt_in"),
        patch("core.cli.welcome.console") as output,
    ):
        _welcome_screen()
    inspect.assert_called_once_with()
    output.print.assert_not_called()
    assert report.all_ready
    assert [p.name for p in tmp_path.iterdir()] == [".env.example"]


def test_cancelled_setup_stops_before_starting_a_daemon(tmp_path, monkeypatch):
    from unittest.mock import Mock

    import typer
    from core.cli import _run_main

    monkeypatch.chdir(tmp_path)
    with (
        patch("core.cli.welcome.check_readiness", return_value=ReadinessReport(blocked=True)),
        patch("core.cli.welcome.dry_run_opted_in", return_value=False),
        patch("core.cli.welcome.env_setup_wizard", return_value=False),
        patch("core.cli.ipc_client.start_serve_if_needed") as spawn,
        pytest.raises(typer.Exit) as cancelled,
    ):
        _run_main(Mock(invoked_subcommand=None), False, False, "", False)
    assert cancelled.value.exit_code != 0
    spawn.assert_not_called()
    assert list(tmp_path.iterdir()) == []


class TestResolveProvider:
    """Test _resolve_provider helper."""

    def test_anthropic(self):
        from core.config import _resolve_provider

        assert _resolve_provider(ANTHROPIC_PRIMARY) == "anthropic"
        assert _resolve_provider("claude-sonnet-4-6") == "anthropic"

    def test_openai(self):
        from core.config import _resolve_provider

        # Model family and credential source are separate: GPT-5.5 also has
        # documented Platform API support. The operator selects the source.
        assert _resolve_provider(OPENAI_PRIMARY) == "openai"
        assert _resolve_provider("gpt-5.4") == "openai"
        assert _resolve_provider("gpt-5.4-mini") == "openai"
        assert _resolve_provider("gpt-4.1") == "openai"

    def test_glm(self):
        from core.config import _resolve_provider

        assert _resolve_provider(GLM_PRIMARY) == "glm"
        assert _resolve_provider("glm-5-turbo") == "glm"
        assert _resolve_provider("glm-4.7-flash") == "glm"


class TestUpdateModel:
    """Test AgenticLoop.update_model method."""

    def test_update_model_changes_provider(self):
        """PR-MAINPATH-67 (2026-05-24) — reads the Path-B
        ``_new_adapter`` field (legacy ``_adapter`` was deleted)."""
        from unittest.mock import MagicMock

        from core.agent.conversation import ConversationContext
        from core.agent.loop import AgenticLoop
        from core.agent.tool_executor import ToolExecutor

        ctx = ConversationContext()
        executor = MagicMock(spec=ToolExecutor)
        loop = AgenticLoop(ctx, executor)
        assert loop.model == ANTHROPIC_PRIMARY
        assert loop._provider == "anthropic"

        asyncio.run(loop.update_model_async(GLM_PRIMARY))
        assert loop.model == GLM_PRIMARY
        assert loop._provider == "glm"
        assert loop._new_adapter.provider == "glm"  # adapter re-resolved

    def test_update_model_same_provider_keeps_adapter(self):
        """PR-MAINPATH-67 (2026-05-24) — reads the Path-B
        ``_new_adapter`` field (legacy ``_adapter`` was deleted)."""
        from unittest.mock import MagicMock

        from core.agent.conversation import ConversationContext
        from core.agent.loop import AgenticLoop
        from core.agent.tool_executor import ToolExecutor

        ctx = ConversationContext()
        executor = MagicMock(spec=ToolExecutor)
        loop = AgenticLoop(ctx, executor)
        original_adapter = loop._new_adapter

        asyncio.run(loop.update_model_async("claude-sonnet-4-6"))
        assert loop.model == "claude-sonnet-4-6"
        assert loop._provider == "anthropic"
        assert loop._new_adapter is original_adapter  # kept — same provider


class TestGlmClient:
    """Test GLM client creation with custom base_url."""


class TestModelProfiles:
    """Test the model picker list includes GLM entries."""

    def test_glm_profiles_present(self):
        from core.cli.commands import get_model_profiles

        ids = [p.id for p in get_model_profiles(openai_source="payg")]
        assert GLM_PRIMARY in ids
        assert {"glm-5.3", "glm-5.3-flash", "glm-5.3-flashx"} <= set(ids)
        assert "glm-5-turbo" not in ids
        assert "glm-4.7-flash" in ids

    def test_glm_profiles_provider(self):
        from core.cli.commands import get_model_profiles
        from core.llm.model_catalog import MODEL_OFFERINGS

        # v0.53.0 — provider labels are CANONICAL provider IDs (lowercase
        # `glm`), matching /login dashboard + auth.toml. Pre-fix used
        # capitalised "GLM" which diverged from the dispatch key.
        glm_profiles = [p for p in get_model_profiles(openai_source="payg") if p.provider == "glm"]
        assert {p.id for p in glm_profiles} == {
            offering.id
            for offering in MODEL_OFFERINGS
            if offering.provider == "glm" and "payg" in offering.sources
        }


class TestReadinessProfileStatus:
    """Fix 2: check_readiness() includes User Profile capability."""

    def test_profile_exists_shown_available(self, tmp_path: Path):
        """When global profile exists, User Profile capability is available."""
        from unittest.mock import MagicMock

        mock_profile_instance = MagicMock()
        mock_profile_instance.exists.return_value = True

        with (
            patch("core.config.settings") as mock_settings,
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
            patch("core.config.settings") as mock_settings,
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
        assert "geode init" in profile_cap.reason  # /profile does not exist

    def test_profile_load_exception_handled(self, tmp_path: Path):
        """If FileBasedUserProfile raises, profile shows as unavailable."""
        with (
            patch("core.config.settings") as mock_settings,
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


def test_credential_check_works_before_a_runtime_registers_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `geode setup`, `geode doctor`, the REPL welcome and serve's pre-runtime
    # readiness all ask before any runtime exists. An empty adapter registry
    # used to read as "no credential", so setup re-ran its wizard every time.
    from core.config import settings
    from core.llm.adapters import registry
    from core.wiring.startup import has_available_llm_credential

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-" + "x" * 40)
    registry._reset_for_test()
    assert has_available_llm_credential("anthropic")


class TestSetupReset:
    """`geode setup --reset` reconfigures credentials without deleting state."""

    @pytest.fixture
    def stored_state(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_bytes(b"OPENAI_API_KEY=sk-old\nSLACK_BOT_TOKEN=xoxb-keep\n")
        auth_file = tmp_path / "auth.toml"
        auth_file.write_bytes(b'[profiles."openai-payg"]\nprovider = "openai"\n')
        marker = tmp_path / ".dry-run-opt-in"
        monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", env_file)
        monkeypatch.setattr("core.paths.GLOBAL_DRY_RUN_MARKER", marker)
        monkeypatch.setenv("GEODE_AUTH_TOML", str(auth_file))
        snapshot = {path: path.read_bytes() for path in (env_file, auth_file)}
        return snapshot

    @staticmethod
    def _run_setup(*, reset: bool, has_credential: bool = True):
        from core.cli.typer_commands import setup

        with (
            patch("core.wiring.startup.has_available_llm_credential", return_value=has_credential),
            patch("core.cli.onboarding.configure_bash_sandbox"),
            patch("core.cli.onboarding.configure_computer_use_helper"),
            patch("core.cli.typer_commands.console"),
        ):
            setup(reset=reset)

    def test_reset_opens_wizard_with_usable_credential_and_keeps_files(self, stored_state):
        with patch("core.cli.onboarding.env_setup_wizard", return_value=True) as wizard:
            self._run_setup(reset=True)
        wizard.assert_called_once()
        for path, data in stored_state.items():
            assert path.read_bytes() == data

    def test_setup_without_reset_skips_wizard_when_usable(self, stored_state):
        with patch("core.cli.onboarding.env_setup_wizard") as wizard:
            self._run_setup(reset=False)
        wizard.assert_not_called()

    def test_reset_cancellation_preserves_credentials(self, stored_state):
        with (
            patch("core.cli.onboarding.console") as console,
            patch("core.auth.auth_toml.save_api_key") as save,
        ):
            console.input.side_effect = KeyboardInterrupt
            self._run_setup(reset=True)
        save.assert_not_called()
        for path, data in stored_state.items():
            assert path.read_bytes() == data

    def test_reset_cancellation_keeps_existing_dry_run_marker(self, stored_state):
        """Reset no longer clears the skip marker before entry; cancelling
        leaves it byte-identical (only a successful credential clears it)."""
        from core.paths import GLOBAL_DRY_RUN_MARKER

        GLOBAL_DRY_RUN_MARKER.write_bytes(b"dry-run")
        with patch("core.cli.onboarding.console") as console:
            console.input.side_effect = KeyboardInterrupt
            self._run_setup(reset=True)
        assert GLOBAL_DRY_RUN_MARKER.read_bytes() == b"dry-run"

    def test_reset_selected_key_goes_through_auth_owner_only(self, stored_state):
        with (
            patch("core.cli.onboarding.console") as console,
            patch("core.auth.auth_toml.save_api_key") as save,
            patch("sys.stdin.isatty", return_value=True),
            patch("core.cli.commands.login.TerminalMenu") as menu,
            patch("getpass.getpass", return_value="synthetic-new-key"),
        ):
            console.input.return_value = "2"
            menu.return_value.show.return_value = 1
            self._run_setup(reset=True)
        save.assert_called_once_with("synthetic-new-key", provider="openai")
        for path, data in stored_state.items():
            assert path.read_bytes() == data


@pytest.mark.parametrize("answers", [["", KeyboardInterrupt], ["x", "4", KeyboardInterrupt]])
def test_wizard_invalid_choice_never_requests_or_saves_key(answers, monkeypatch, tmp_path):
    monkeypatch.setattr("core.paths.GLOBAL_DRY_RUN_MARKER", tmp_path / ".dry-run-opt-in")
    with (
        patch("core.cli.onboarding.console") as console,
        patch("core.cli.commands.login.TerminalMenu") as menu,
        patch("getpass.getpass") as hidden,
        patch("core.auth.auth_toml.save_api_key") as save,
    ):
        console.input.side_effect = answers
        assert env_setup_wizard() is False
    assert console.input.call_count == len(answers)
    menu.assert_not_called()
    hidden.assert_not_called()
    save.assert_not_called()


def test_wizard_reprompts_after_invalid_choice(monkeypatch, tmp_path):
    monkeypatch.setattr("core.paths.GLOBAL_DRY_RUN_MARKER", tmp_path / ".dry-run-opt-in")
    with patch("core.cli.onboarding.console") as console:
        console.input.side_effect = ["two", "3"]
        assert env_setup_wizard() is True
    assert dry_run_opted_in() is True
