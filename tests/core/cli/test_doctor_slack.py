"""Tests for core.cli.doctor — Slack gateway diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.cli.doctor import (
    format_doctor_report,
    get_manifest_url,
    run_doctor_slack,
)


class TestCheckEnv:
    def test_token_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-1234567890")
        monkeypatch.setenv("SLACK_TEAM_ID", "T12345")
        from core.cli.doctor import _check_env

        results = _check_env()
        assert all(r["ok"] for r in results)

    def test_token_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_TEAM_ID", raising=False)
        # The resolver falls back to the global ~/.geode/.env — isolate it
        # from the real machine state (PR-SLACK-TRANSPORT).
        monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", tmp_path / "absent.env")
        from core.cli.doctor import _check_env

        results = _check_env()
        by_name = {r["name"]: r for r in results}
        assert not by_name["SLACK_BOT_TOKEN"]["ok"]
        assert "hint" in by_name["SLACK_BOT_TOKEN"]
        # SLACK_TEAM_ID is informational since the direct transport
        # never reads it (PR-SLACK-TRANSPORT).
        assert by_name["SLACK_TEAM_ID"]["ok"]


class TestCheckTokenValidity:
    def test_valid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")

        async def _fake_auth_test(self):
            return {"ok": True, "team": "test-ws", "user": "geode", "user_id": "U123"}

        monkeypatch.setattr(
            "core.messaging.slack_transport.SlackTransport.auth_test", _fake_auth_test
        )
        from core.cli.doctor import _check_token_validity

        result = _check_token_validity()
        assert result["ok"]
        assert "test-ws" in result["detail"]

    def test_invalid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-bad")

        async def _fake_auth_test(self):
            from core.messaging.slack_transport import SlackTransportError

            raise SlackTransportError("auth.test: invalid_auth")

        monkeypatch.setattr(
            "core.messaging.slack_transport.SlackTransport.auth_test", _fake_auth_test
        )
        from core.cli.doctor import _check_token_validity

        result = _check_token_validity()
        assert not result["ok"]
        assert "invalid_auth" in result["detail"]

    def test_no_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", tmp_path / "absent.env")
        from core.cli.doctor import _check_token_validity

        result = _check_token_validity()
        assert not result["ok"]


class TestCheckBindings:
    @pytest.fixture(autouse=True)
    def _isolate_global_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Keep binding diagnostics independent of the operator's config."""
        monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", tmp_path / "absent-global.toml")

    def test_valid_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        geode_dir = tmp_path / ".geode"
        geode_dir.mkdir()
        config = geode_dir / "config.toml"
        config.write_text("""
[gateway.bindings]
[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0ALUA25DKK"
auto_respond = true
require_mention = true
""")
        from core.cli.doctor import _check_bindings

        results = _check_bindings()
        assert any(r["ok"] and "C0ALUA25DKK" in r.get("detail", "") for r in results)

    def test_placeholder_channel_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        geode_dir = tmp_path / ".geode"
        geode_dir.mkdir()
        config = geode_dir / "config.toml"
        config.write_text("""
[gateway.bindings]
[[gateway.bindings.rules]]
channel = "slack"
channel_id = "C0XXXXXXXXX"
""")
        from core.cli.doctor import _check_bindings

        results = _check_bindings()
        binding_results = [r for r in results if r["name"].startswith("binding:")]
        assert not binding_results[0]["ok"]

    def test_missing_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        from core.cli.doctor import _check_bindings

        results = _check_bindings()
        assert not results[0]["ok"]
        assert "hint" in results[0]


class TestRunDoctorSlack:
    def test_all_fail_gracefully(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_TEAM_ID", raising=False)
        # Machine isolation: without this the resolvers fall back to the
        # REAL ~/.geode/.env and the doctor makes live auth.test calls.
        monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", tmp_path / "absent.env")
        monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", tmp_path / "absent.toml")
        monkeypatch.setattr("core.paths.PROJECT_CONFIG_TOML", tmp_path / "absent2.toml")

        report = run_doctor_slack()
        assert report["status"].startswith("DEGRADED")
        assert len(report["checks"]) >= 5

    def test_format_report(self) -> None:
        report = {
            "checks": [
                {"name": "test", "ok": True, "detail": "good"},
                {"name": "bad", "ok": False, "detail": "missing", "hint": "fix it"},
            ],
            "warnings": ["optional scope missing"],
            "status": "DEGRADED",
            "ok": False,
        }
        text = format_doctor_report(report)
        assert "PASS" in text
        assert "FAIL" in text
        assert "fix it" in text
        assert "DEGRADED" in text


class TestManifest:
    def test_manifest_url(self) -> None:
        url = get_manifest_url()
        assert url.startswith("https://api.slack.com/apps?new_app=1&manifest_json=")
        assert "GEODE" in url
