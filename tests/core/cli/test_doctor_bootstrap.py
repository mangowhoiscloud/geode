"""Tests for the bootstrap doctor (`geode doctor` default target).

v0.54.0 — diagnostic surface that verifies the first-run state for an
absolute beginner: Python version, ``geode`` on PATH, ``~/.geode/.env``,
Codex CLI OAuth, ProfileStore, serve daemon socket, ``~/.local/bin``
on PATH.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.cli.doctor_bootstrap import (
    BootstrapReport,
    CheckResult,
    _check_codex_oauth,
    _check_desktop_computer_use,
    _check_env_file,
    _check_geode_on_path,
    _check_local_bin_on_path,
    _check_profile_store,
    _check_python_version,
    _check_serve_socket,
    format_bootstrap_report,
    run_bootstrap_doctor,
)


class TestCheckPythonVersion:
    def test_passes_on_312(self):
        result = _check_python_version()
        assert result.ok is (sys.version_info[:2] >= (3, 12))


class TestCheckGeodeOnPath:
    def test_present(self):
        with patch("core.cli.doctor_bootstrap.shutil.which", return_value="/usr/local/bin/geode"):
            result = _check_geode_on_path()
        assert result.ok is True
        assert "/usr/local/bin/geode" in result.detail

    def test_absent(self):
        with patch("core.cli.doctor_bootstrap.shutil.which", return_value=None):
            result = _check_geode_on_path()
        assert result.ok is False
        assert "uv tool install" in result.fix


class TestCheckEnvFile:
    def test_present(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("ANTHROPIC_API_KEY=sk-ant-test")
        with patch("core.paths.GLOBAL_ENV_FILE", env_path):
            result = _check_env_file()
        assert result.ok is True

    def test_absent(self, tmp_path):
        # PR-CLEANUP-D2 — patch the core.paths anchor, not Path.expanduser.
        env_path = tmp_path / "missing" / ".env"
        with patch("core.paths.GLOBAL_ENV_FILE", env_path):
            result = _check_env_file()
        assert result.ok is False
        assert "geode setup" in result.fix


class TestCheckCodexOAuth:
    def test_no_credentials(self):
        with patch("core.auth.codex_cli_oauth.read_codex_cli_credentials", return_value=None):
            result = _check_codex_oauth()
        assert result.ok is False
        assert "Optional" in result.fix

    def test_valid_credentials(self):
        # Far-future expiry
        creds = {"access_token": "tok", "expires_at": 9999999999.0, "account_id": "acct-x"}
        with patch(
            "core.auth.codex_cli_oauth.read_codex_cli_credentials",
            return_value=creds,
        ):
            result = _check_codex_oauth()
        assert result.ok is True
        assert "acct-x" in result.detail

    def test_expired_token(self):
        creds = {"access_token": "tok", "expires_at": 1.0, "account_id": "acct-x"}
        with patch(
            "core.auth.codex_cli_oauth.read_codex_cli_credentials",
            return_value=creds,
        ):
            result = _check_codex_oauth()
        assert result.ok is False
        assert "expired" in result.detail
        assert "codex auth login" in result.fix

    def test_probe_failure_doesnt_crash(self):
        with patch(
            "core.auth.codex_cli_oauth.read_codex_cli_credentials",
            side_effect=OSError("boom"),
        ):
            result = _check_codex_oauth()
        assert result.ok is False


class TestCheckProfileStore:
    def test_no_profiles(self):
        from unittest.mock import MagicMock

        empty_store = MagicMock()
        empty_store.list_all.return_value = []
        with patch("core.wiring.container.ensure_profile_store", return_value=empty_store):
            result = _check_profile_store()
        assert result.ok is False
        assert "geode setup" in result.fix

    def test_with_profile(self):
        from unittest.mock import MagicMock

        profile = MagicMock(provider="openai-codex", key="tok-abc")
        store = MagicMock()
        store.list_all.return_value = [profile]
        with patch("core.wiring.container.ensure_profile_store", return_value=store):
            result = _check_profile_store()
        assert result.ok is True
        assert "openai-codex" in result.detail


class TestCheckServeSocket:
    def test_socket_absent(self, tmp_path):
        # PR-CLEANUP-D2 — the socket path is the core.paths anchor now;
        # patch the anchor, not Path.expanduser.
        sock_path = tmp_path / "missing.sock"
        with patch("core.paths.CLI_SOCKET_PATH", sock_path):
            result = _check_serve_socket()
        assert result.ok is False
        assert "geode serve" in result.fix


class TestCheckLocalBinOnPath:
    def test_present(self):
        local_bin = str(Path("~/.local/bin").expanduser())
        with patch.dict("os.environ", {"PATH": f"/usr/bin:{local_bin}:/sbin"}):
            result = _check_local_bin_on_path()
        assert result.ok is True

    def test_absent(self):
        with patch.dict("os.environ", {"PATH": "/usr/bin:/sbin"}, clear=True):
            result = _check_local_bin_on_path()
        assert result.ok is False
        assert "PATH" in result.fix


class TestCheckDesktopComputerUse:
    def test_disabled_config_passes(self):
        fake_settings = type("Settings", (), {"computer_use_enabled": False})()
        with patch("core.config.settings", fake_settings):
            result = _check_desktop_computer_use()
        assert result.ok is True
        assert "disabled" in result.detail

    def test_missing_host_dependency_fails(self):
        fake_settings = type("Settings", (), {"computer_use_enabled": True})()

        def fake_find_spec(name: str):
            if name == "pyautogui":
                return None
            return object()

        with (
            patch("core.config.settings", fake_settings),
            patch("core.tools.computer_use.computer_use_env", return_value="host"),
            patch("core.tools.computer_use.computer_use_driver", return_value="python"),
            patch("core.cli.doctor_bootstrap.find_spec", side_effect=fake_find_spec),
        ):
            result = _check_desktop_computer_use()
        assert result.ok is False
        assert "pyautogui" in result.detail
        assert "uv sync --extra desktop" in result.fix

    def test_macos_ax_untrusted_fails_after_dependencies_present(self):
        fake_settings = type("Settings", (), {"computer_use_enabled": True})()

        with (
            patch("core.config.settings", fake_settings),
            patch("core.tools.computer_use.computer_use_env", return_value="host"),
            patch("core.tools.computer_use.computer_use_driver", return_value="python"),
            patch("core.cli.doctor_bootstrap.find_spec", return_value=object()),
            patch("core.cli.doctor_bootstrap.platform.system", return_value="Darwin"),
            patch.dict(
                "sys.modules",
                {"ApplicationServices": SimpleNamespace(AXIsProcessTrusted=lambda: False)},
            ),
        ):
            result = _check_desktop_computer_use()
        assert result.ok is False
        assert "Accessibility" in result.detail
        assert "Grant Accessibility" in result.fix

    def test_required_helper_missing_fails_with_build_command(self):
        fake_settings = type("Settings", (), {"computer_use_enabled": True})()

        with (
            patch("core.config.settings", fake_settings),
            patch("core.tools.computer_use.computer_use_env", return_value="host"),
            patch("core.tools.computer_use.computer_use_driver", return_value="helper"),
            patch("core.tools.computer_use.computer_use_helper_path", return_value=None),
        ):
            result = _check_desktop_computer_use()
        assert result.ok is False
        assert "Helper is not installed" in result.detail
        assert "build_computer_helper.sh" in result.fix

    def test_helper_untrusted_reports_helper_app_permission(self, tmp_path):
        fake_settings = type("Settings", (), {"computer_use_enabled": True})()
        helper_path = tmp_path / "GEODE Computer Use Helper.app" / "Contents" / "MacOS" / "helper"

        with (
            patch("core.config.settings", fake_settings),
            patch("core.tools.computer_use.computer_use_env", return_value="host"),
            patch("core.tools.computer_use.computer_use_driver", return_value="helper"),
            patch(
                "core.tools.computer_use.computer_use_helper_path",
                return_value=helper_path,
            ),
            patch(
                "core.tools.computer_use.computer_use_helper_status",
                return_value={
                    "result": "success",
                    "ax_trusted": False,
                    "screenshot_ok": True,
                },
            ),
            patch("core.cli.doctor_bootstrap.platform.system", return_value="Darwin"),
        ):
            result = _check_desktop_computer_use()
        assert result.ok is False
        assert "GEODE Computer Use Helper is installed" in result.detail
        assert "GEODE Computer Use Helper.app" in result.fix


class TestRunAndFormat:
    def test_run_returns_aggregated_report(self):
        report = run_bootstrap_doctor()
        assert isinstance(report, BootstrapReport)
        assert len(report.checks) >= 6

    def test_format_renders_markers_and_fixes(self):
        report = BootstrapReport(
            checks=[
                CheckResult(name="ok-check", ok=True, detail="present"),
                CheckResult(name="bad-check", ok=False, detail="missing", fix="run setup"),
            ]
        )
        rendered = format_bootstrap_report(report)
        assert "ok-check" in rendered
        assert "bad-check" in rendered
        assert "run setup" in rendered
        assert "1 check(s) need attention" in rendered

    def test_all_ok_summary(self):
        report = BootstrapReport(
            checks=[CheckResult(name="x", ok=True, detail="")],
        )
        rendered = format_bootstrap_report(report)
        assert "All checks passed" in rendered
