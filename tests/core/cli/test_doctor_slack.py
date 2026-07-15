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
        monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test-1234567890")
        monkeypatch.setenv("SLACK_TEAM_ID", "T12345")
        from core.cli.doctor import _check_env

        results = _check_env()
        assert all(r["ok"] for r in results)

    def test_token_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_TEAM_ID", raising=False)
        # The resolver falls back to the global ~/.geode/.env — isolate it
        # from the real machine state (PR-SLACK-TRANSPORT).
        monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", tmp_path / "absent.env")
        from core.cli.doctor import _check_env

        results = _check_env()
        by_name = {r["name"]: r for r in results}
        assert not by_name["SLACK_BOT_TOKEN"]["ok"]
        assert "hint" in by_name["SLACK_BOT_TOKEN"]
        assert not by_name["SLACK_APP_TOKEN"]["ok"]
        assert "polling fallback" in by_name["SLACK_APP_TOKEN"]["detail"]
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


class TestCheckSocketMode:
    def test_valid_app_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")

        async def fake_open(self) -> str:
            return "wss://wss-primary.slack.com/link/?ticket=redacted"

        monkeypatch.setattr(
            "core.messaging.slack_transport.open_socket_mode_url",
            fake_open,
        )
        from core.cli.doctor import _check_socket_mode

        result = _check_socket_mode()
        assert result["ok"]
        assert "ticket redacted" in result["detail"]

    def test_missing_app_token(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
        monkeypatch.setattr("core.paths.GLOBAL_ENV_FILE", tmp_path / "absent.env")
        from core.cli.doctor import _check_socket_mode

        result = _check_socket_mode()
        assert not result["ok"]
        assert "polling fallback" in result["detail"]


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
        monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", tmp_path / "absent.toml")
        monkeypatch.setattr("core.paths.PROJECT_CONFIG_TOML", config)
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
        monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", tmp_path / "absent.toml")
        monkeypatch.setattr("core.paths.PROJECT_CONFIG_TOML", config)
        from core.cli.doctor import _check_bindings

        results = _check_bindings()
        binding_results = [r for r in results if r["name"].startswith("binding:")]
        assert not binding_results[0]["ok"]

    def test_missing_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", tmp_path / "absent.toml")
        monkeypatch.setattr("core.paths.PROJECT_CONFIG_TOML", tmp_path / "absent2.toml")
        from core.cli.doctor import _check_bindings

        results = _check_bindings()
        assert not results[0]["ok"]
        assert "hint" in results[0]


class TestCheckBindingAccess:
    def test_reports_membership_and_channel_link(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setenv("SLACK_TEAM_ID", "T123")
        monkeypatch.setattr(
            "core.wiring.adapters._load_gateway_config",
            lambda: (
                {"gateway": {"bindings": {"rules": [{"channel": "slack", "channel_id": "C123"}]}}},
                ["test"],
            ),
        )

        async def fake_channel_info(self, channel_id: str):
            return {"id": channel_id, "name": "general", "is_member": False}

        monkeypatch.setattr(
            "core.messaging.slack_transport.SlackTransport.channel_info",
            fake_channel_info,
        )
        from core.cli.doctor import _check_binding_access

        result = _check_binding_access()[0]
        assert not result["ok"]
        assert "https://app.slack.com/client/T123/C123" in result["detail"]
        assert "/invite @geode" in result["hint"]


class TestRunDoctorSlack:
    def test_all_fail_gracefully(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
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

    def test_manifest_enables_socket_mode_events(self) -> None:
        from core.cli.doctor import SLACK_APP_MANIFEST

        settings = SLACK_APP_MANIFEST["settings"]
        assert settings["socket_mode_enabled"] is True
        assert settings["event_subscriptions"]["bot_events"] == [
            "app_mention",
            "message.channels",
        ]
