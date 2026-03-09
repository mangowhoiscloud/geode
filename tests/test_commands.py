"""Tests for CLI command dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from geode.cli.commands import (
    COMMAND_MAP,
    MODEL_PROFILES,
    _apply_model,
    _mask_key,
    _upsert_env,
    cmd_batch,
    cmd_key,
    cmd_model,
    cmd_schedule,
    cmd_trigger,
    resolve_action,
)


class TestCommandMap:
    def test_quit_commands(self):
        assert resolve_action("/quit") == "quit"
        assert resolve_action("/exit") == "quit"
        assert resolve_action("/q") == "quit"

    def test_help(self):
        assert resolve_action("/help") == "help"

    def test_list(self):
        assert resolve_action("/list") == "list"

    def test_verbose(self):
        assert resolve_action("/verbose") == "verbose"

    def test_analyze(self):
        assert resolve_action("/analyze") == "analyze"
        assert resolve_action("/a") == "analyze"

    def test_run(self):
        assert resolve_action("/run") == "run"
        assert resolve_action("/r") == "run"

    def test_search(self):
        assert resolve_action("/search") == "search"
        assert resolve_action("/s") == "search"

    def test_key(self):
        assert resolve_action("/key") == "key"

    def test_model(self):
        assert resolve_action("/model") == "model"

    def test_unknown_command(self):
        assert resolve_action("/nonexistent") is None

    def test_all_commands_have_actions(self):
        """Every command in COMMAND_MAP should resolve to a non-None action."""
        for cmd in COMMAND_MAP:
            assert resolve_action(cmd) is not None


class TestMaskKey:
    def test_normal_key(self):
        result = _mask_key("sk-ant-api03-abcdef1234567890xyz")
        assert result.startswith("sk-ant-api")
        assert result.endswith("0xyz")
        assert "..." in result

    def test_short_key(self):
        assert _mask_key("short") == "***"

    def test_empty_key(self):
        assert _mask_key("") == "***"


class TestUpsertEnv:
    def test_create_new_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _upsert_env("MY_KEY", "my_value")

        content = (tmp_path / ".env").read_text()
        assert "MY_KEY=my_value" in content

    def test_update_existing(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("MY_KEY=old\nOTHER=keep\n")

        _upsert_env("MY_KEY", "new")
        content = (tmp_path / ".env").read_text()
        assert "MY_KEY=new" in content
        assert "OTHER=keep" in content
        assert "old" not in content

    def test_append_when_not_found(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("EXISTING=yes\n")

        _upsert_env("NEW_VAR", "hello")
        content = (tmp_path / ".env").read_text()
        assert "EXISTING=yes" in content
        assert "NEW_VAR=hello" in content


class TestCmdKey:
    def test_show_status_no_args(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = cmd_key("")
        assert result is False

    def test_set_anthropic(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.anthropic_api_key
        try:
            result = cmd_key("sk-ant-test-key-12345678")
            assert result is True
            assert settings.anthropic_api_key == "sk-ant-test-key-12345678"
            content = (tmp_path / ".env").read_text()
            assert "ANTHROPIC_API_KEY=sk-ant-test-key-12345678" in content
        finally:
            settings.anthropic_api_key = old

    def test_set_openai(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.openai_api_key
        try:
            result = cmd_key("openai sk-openai-test-key-999")
            assert result is True
            assert settings.openai_api_key == "sk-openai-test-key-999"
            content = (tmp_path / ".env").read_text()
            assert "OPENAI_API_KEY=sk-openai-test-key-999" in content
        finally:
            settings.openai_api_key = old

    def test_openai_no_value(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = cmd_key("openai")
        assert result is False


class TestCmdModel:
    def test_interactive_picker_select(self, tmp_path: Path, monkeypatch):
        """Arrow-key picker: user selects index 2 (Haiku)."""
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.model
        try:
            with patch("geode.cli.commands.TerminalMenu") as MockMenu:
                MockMenu.return_value.show.return_value = 2  # Haiku
                cmd_model("")
            assert settings.model == MODEL_PROFILES[2].id
        finally:
            settings.model = old

    def test_interactive_picker_cancel(self, tmp_path: Path, monkeypatch):
        """Arrow-key picker: user presses q/Esc → cancel."""
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.model
        with patch("geode.cli.commands.TerminalMenu") as MockMenu:
            MockMenu.return_value.show.return_value = None
            cmd_model("")
        assert settings.model == old

    def test_select_by_number(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.model
        try:
            cmd_model("2")
            assert settings.model == MODEL_PROFILES[1].id
            content = (tmp_path / ".env").read_text()
            assert f"GEODE_MODEL={MODEL_PROFILES[1].id}" in content
        finally:
            settings.model = old

    def test_select_by_name(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.model
        try:
            # Ensure starting model differs from target
            settings.model = "claude-opus-4-6"
            cmd_model("gpt-5.4")
            assert settings.model == "gpt-5.4"
            content = (tmp_path / ".env").read_text()
            assert "GEODE_MODEL=gpt-5.4" in content
        finally:
            settings.model = old

    def test_select_by_partial_name(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.model
        try:
            cmd_model("haiku")
            assert settings.model == "claude-haiku-4-5-20251001"
        finally:
            settings.model = old

    def test_invalid_number(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.model
        cmd_model("99")
        assert settings.model == old

    def test_unknown_name(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.model
        cmd_model("nonexistent-model-xyz")
        assert settings.model == old

    def test_same_model_noop(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.model
        cmd_model(old)
        assert settings.model == old


class TestApplyModel:
    def test_apply_new_model(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        old = settings.model
        try:
            _apply_model(MODEL_PROFILES[3])  # GPT-5.4
            assert settings.model == "gpt-5.4"
        finally:
            settings.model = old

    def test_apply_same_model(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from geode.config import settings

        # Should not write .env when model unchanged
        _apply_model(next(p for p in MODEL_PROFILES if p.id == settings.model))


class TestCmdBatch:
    def test_batch_command_registered(self):
        assert resolve_action("/batch") == "batch"
        assert resolve_action("/b") == "batch"

    def test_batch_no_args(self):
        result = cmd_batch("")
        assert result == []

    def test_batch_space_separated(self):
        calls = []

        def mock_run(ip_name, dry_run=False, verbose=False):
            calls.append(ip_name)
            return {"ip_name": ip_name}

        result = cmd_batch("Balatro Hades Celeste", run_fn=mock_run, dry_run=True)
        assert len(result) == 3
        assert calls == ["Balatro", "Hades", "Celeste"]

    def test_batch_comma_separated(self):
        calls = []

        def mock_run(ip_name, dry_run=False, verbose=False):
            calls.append(ip_name)
            return {"ip_name": ip_name}

        result = cmd_batch("Balatro, Hades, Celeste", run_fn=mock_run)
        assert len(result) == 3
        assert calls == ["Balatro", "Hades", "Celeste"]

    def test_batch_no_run_fn(self):
        result = cmd_batch("Balatro Hades")
        assert result == [None, None]


class TestCmdSchedule:
    def test_schedule_command_registered(self):
        assert resolve_action("/schedule") == "schedule"
        assert resolve_action("/sched") == "schedule"

    def test_schedule_list(self):
        """Should not raise."""
        cmd_schedule("")
        cmd_schedule("list")

    def test_schedule_enable_unknown(self):
        """Should not raise for unknown template."""
        cmd_schedule("enable nonexistent_template")

    def test_schedule_run_unknown(self):
        """Should not raise for unknown template."""
        cmd_schedule("run nonexistent_template")


class TestCmdTrigger:
    def test_trigger_command_registered(self):
        assert resolve_action("/trigger") == "trigger"

    def test_trigger_list(self):
        """Should not raise."""
        cmd_trigger("")
        cmd_trigger("list")

    def test_trigger_fire(self):
        """Should not raise."""
        cmd_trigger("fire test_event")
