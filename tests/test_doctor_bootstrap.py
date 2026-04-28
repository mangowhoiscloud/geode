"""Tests for the bootstrap doctor (`geode doctor` default target).

v0.54.0 — diagnostic surface that verifies the first-run state for an
absolute beginner: Python version, ``geode`` on PATH, ``~/.geode/.env``,
Codex CLI OAuth, ProfileStore, serve daemon socket, ``~/.local/bin``
on PATH.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from core.cli.doctor_bootstrap import (
    BootstrapReport,
    CheckResult,
    _check_codex_oauth,
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
        with patch("pathlib.Path.expanduser", return_value=env_path):
            result = _check_env_file()
        assert result.ok is True

    def test_absent(self, tmp_path):
        env_path = tmp_path / "missing" / ".env"
        with patch("pathlib.Path.expanduser", return_value=env_path):
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
        with patch("core.lifecycle.container.ensure_profile_store", return_value=empty_store):
            result = _check_profile_store()
        assert result.ok is False
        assert "geode setup" in result.fix

    def test_with_profile(self):
        from unittest.mock import MagicMock

        profile = MagicMock(provider="openai-codex", key="tok-abc")
        store = MagicMock()
        store.list_all.return_value = [profile]
        with patch("core.lifecycle.container.ensure_profile_store", return_value=store):
            result = _check_profile_store()
        assert result.ok is True
        assert "openai-codex" in result.detail


class TestCheckServeSocket:
    def test_socket_absent(self, tmp_path):
        sock_path = tmp_path / "missing.sock"
        with patch("pathlib.Path.expanduser", return_value=sock_path):
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
