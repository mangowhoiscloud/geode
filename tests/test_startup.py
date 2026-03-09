"""Tests for CLI startup readiness checks (OpenClaw gateway:startup pattern)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from geode.cli.startup import (
    Capability,
    ReadinessReport,
    check_readiness,
    setup_project_memory,
)


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
        with patch("geode.cli.startup.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            report = check_readiness(tmp_path)

        assert report.has_api_key is False
        assert report.force_dry_run is True

        # Should have LLM Analysis capability marked unavailable
        llm_cap = next(c for c in report.capabilities if c.name == "LLM Analysis")
        assert llm_cap.available is False

    def test_with_api_key(self, tmp_path: Path):
        with patch("geode.cli.startup.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-ant-real-key-here"
            report = check_readiness(tmp_path)

        assert report.has_api_key is True
        assert report.force_dry_run is False

        llm_cap = next(c for c in report.capabilities if c.name == "LLM Analysis")
        assert llm_cap.available is True

    def test_placeholder_key_treated_as_missing(self, tmp_path: Path):
        with patch("geode.cli.startup.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-ant-..."
            report = check_readiness(tmp_path)

        assert report.has_api_key is False
        assert report.force_dry_run is True

    def test_env_file_check(self, tmp_path: Path):
        with patch("geode.cli.startup.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""

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
        with patch("geode.cli.startup.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""

            # No .claude/MEMORY.md → unavailable
            report = check_readiness(tmp_path)
            assert report.has_memory is False
            mem_cap = next(c for c in report.capabilities if c.name == "Project Memory")
            assert mem_cap.available is False

            # Create .claude/MEMORY.md → available
            claude_dir = tmp_path / ".claude"
            claude_dir.mkdir()
            (claude_dir / "MEMORY.md").write_text("# Memory\n")
            report = check_readiness(tmp_path)
            assert report.has_memory is True
            mem_cap = next(c for c in report.capabilities if c.name == "Project Memory")
            assert mem_cap.available is True

    def test_always_available_capabilities(self, tmp_path: Path):
        with patch("geode.cli.startup.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            report = check_readiness(tmp_path)

        names = [c.name for c in report.capabilities]
        assert "Dry-Run Analysis" in names
        assert "IP Search" in names

        dry_run_cap = next(c for c in report.capabilities if c.name == "Dry-Run Analysis")
        assert dry_run_cap.available is True


class TestSetupProjectMemory:
    def test_creates_memory(self, tmp_path: Path):
        created = setup_project_memory(tmp_path)
        assert created is True
        assert (tmp_path / ".claude" / "MEMORY.md").exists()

    def test_idempotent(self, tmp_path: Path):
        assert setup_project_memory(tmp_path) is True
        assert setup_project_memory(tmp_path) is False
