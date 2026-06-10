"""Tests for core.cli.doctor — Slack gateway diagnostics."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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

    def test_token_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_TEAM_ID", raising=False)
        from core.cli.doctor import _check_env

        results = _check_env()
        assert not any(r["ok"] for r in results)
        assert any("hint" in r for r in results)


class TestCheckTokenValidity:
    def test_valid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")

        mock_resp = type(
            "R",
            (),
            {
                "json": lambda self: {
                    "ok": True,
                    "team": "test-ws",
                    "user": "geode",
                    "user_id": "U123",
                },
            },
        )()

        with patch("httpx.get", return_value=mock_resp):
            from core.cli.doctor import _check_token_validity

            result = _check_token_validity()
            assert result["ok"]
            assert "test-ws" in result["detail"]

    def test_invalid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-bad")

        mock_resp = type(
            "R",
            (),
            {
                "json": lambda self: {"ok": False, "error": "invalid_auth"},
            },
        )()

        with patch("httpx.get", return_value=mock_resp):
            from core.cli.doctor import _check_token_validity

            result = _check_token_validity()
            assert not result["ok"]
            assert "invalid_auth" in result["detail"]

    def test_no_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        from core.cli.doctor import _check_token_validity

        result = _check_token_validity()
        assert not result["ok"]


class TestCheckBindings:
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
