"""Cycle B — durable picker persistence + PAYG store=False (v0.61.0).

Verifies:
  1. ``upsert_config_toml`` writes new files, updates existing keys,
     handles section boundaries.
  2. ``_apply_model`` from the picker persists effort + model to
     ``.geode/config.toml`` (durable layer), not just ``.env``.
  3. PAYG ``openai.py`` adapter sends ``store=False`` (parity with
     Codex, R3-mini follow-up).
"""

from __future__ import annotations

import inspect
import tomllib
from io import StringIO
from pathlib import Path

import pytest
from core.config.env_io import upsert_config_toml


class TestUpsertConfigToml:
    @pytest.mark.parametrize("value", ['model"quoted', "model\\path", "model\nline\ttab"])
    @pytest.mark.parametrize("existing", [False, True])
    def test_string_value_round_trips(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, existing: bool
    ) -> None:
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".geode" / "config.toml"
        if existing:
            config_path.parent.mkdir()
            config_path.write_text('[llm]\nprimary_model = "old"\n')

        upsert_config_toml("llm", "primary_model", value)

        assert tomllib.loads(config_path.read_text()) == {"llm": {"primary_model": value}}

    def test_creates_file_with_section(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        upsert_config_toml("agentic", "effort", "max")
        config_path = tmp_path / ".geode" / "config.toml"
        assert config_path.exists()
        loaded = tomllib.loads(config_path.read_text())
        assert loaded == {"agentic": {"effort": "max"}}

    def test_updates_existing_key(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".geode" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text('[agentic]\neffort = "low"\n')
        upsert_config_toml("agentic", "effort", "high")
        loaded = tomllib.loads(config_path.read_text())
        assert loaded["agentic"]["effort"] == "high"

    def test_inserts_into_existing_section_with_other_keys(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".geode" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text('[agentic]\ntime_budget = 600\n\n[llm]\nprimary_model = "x"\n')
        upsert_config_toml("agentic", "effort", "max")
        loaded = tomllib.loads(config_path.read_text())
        assert loaded["agentic"]["effort"] == "max"
        assert loaded["agentic"]["time_budget"] == 600
        assert loaded["llm"]["primary_model"] == "x"

    def test_uncomments_existing_commented_key(self, tmp_path: Path, monkeypatch) -> None:
        """Default config.toml ships with ``# effort = "high"`` — picker
        choice should overwrite the comment, not duplicate the key."""
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".geode" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text('[agentic]\n# effort = "high"\n')
        upsert_config_toml("agentic", "effort", "xhigh")
        loaded = tomllib.loads(config_path.read_text())
        assert loaded["agentic"]["effort"] == "xhigh"
        # Key appears exactly once
        text = config_path.read_text()
        assert text.count("effort =") == 1

    def test_appends_section_when_missing(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / ".geode" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text('[llm]\nprimary_model = "claude-opus-4-7"\n')
        upsert_config_toml("agentic", "effort", "high")
        loaded = tomllib.loads(config_path.read_text())
        assert loaded["agentic"]["effort"] == "high"
        assert loaded["llm"]["primary_model"] == "claude-opus-4-7"


class TestPickerPersistence:
    @pytest.mark.parametrize("scope", ["global", "project"])
    def test_redirected_global_path_round_trips_through_picker_and_reload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str
    ) -> None:
        import core.config as cfg
        from core import paths
        from core.cli import commands
        from core.cli.commands import model as model_mod
        from core.cli.commands._state import ModelProfile
        from core.config import explain, toml_edit
        from core.config._settings import Settings
        from rich.console import Console

        monkeypatch.chdir(tmp_path)
        default_global = tmp_path / "default-global.toml"
        default_global.write_text('[llm]\nprimary_model = "untouched-default"\n')
        redirected = tmp_path / "redirected.toml"
        redirected.write_text('[llm]\nprimary_model = "redirected-before"\n')
        project = tmp_path / ".geode" / "config.toml"
        monkeypatch.setattr(paths, "GLOBAL_CONFIG_TOML", default_global)
        monkeypatch.setattr(toml_edit, "GLOBAL_CONFIG_TOML", default_global)
        monkeypatch.setattr(cfg, "GLOBAL_CONFIG_PATH", default_global)
        monkeypatch.setattr(cfg, "PROJECT_CONFIG_PATH", project)
        monkeypatch.setattr(explain, "PROJECT_CONFIG_PATH", project)
        monkeypatch.setattr(explain, "GLOBAL_ENV_FILE", tmp_path / "absent-global.env")
        monkeypatch.setattr(explain, "PROJECT_ENV_FILE", tmp_path / "absent-project.env")
        monkeypatch.setenv("GEODE_CONFIG_TOML", f"  {redirected}  ")
        monkeypatch.delenv("GEODE_MODEL", raising=False)
        monkeypatch.setitem(Settings.model_config, "env_file", None)
        monkeypatch.delitem(cfg.__dict__, "settings", raising=False)
        monkeypatch.setattr(cfg, "_settings_instance", Settings(model="old-runtime"))
        monkeypatch.setattr(cfg, "reload_routing_constants", lambda: None)
        monkeypatch.setattr(commands, "_check_provider_key", lambda _profile: None)
        monkeypatch.setattr(commands, "get_conversation_context", lambda: None)
        monkeypatch.setattr(commands, "remove_env", lambda _name: False)
        output = StringIO()
        monkeypatch.setattr(commands, "console", Console(file=output, width=500))
        target = ModelProfile(
            id="claude-opus-4-8", provider="anthropic", label="Opus 4.8", cost="$$$"
        )

        assert cfg.settings.model == "old-runtime"
        model_mod._apply_model(target, scope=scope)

        destination = redirected if scope == "global" else project
        assert tomllib.loads(destination.read_text())["llm"]["primary_model"] == target.id
        assert tomllib.loads(default_global.read_text())["llm"]["primary_model"] == (
            "untouched-default"
        )
        assert model_mod._read_toml_value("llm", "primary_model") == (
            target.id if scope == "global" else "redirected-before"
        )
        assert str(destination.relative_to(tmp_path)) in output.getvalue()
        assert str(default_global) not in output.getvalue()

        object.__setattr__(cfg.settings, "model", "stale-runtime")
        cfg.reload_settings_from_disk()
        assert cfg.settings.model == target.id
        report = explain.explain_field("model")
        assert report.winner is not None
        assert report.winner.layer == f"{scope} config.toml"
        assert report.winner.value == target.id
        assert Path(report.winner.source) == destination
        global_layer = next(layer for layer in report.layers if layer.layer == "global config.toml")
        assert Path(global_layer.source) == redirected

    def test_apply_model_writes_effort_to_config_toml(self, tmp_path: Path, monkeypatch) -> None:
        """After picker confirms an effort, .geode/config.toml must
        carry it so the next session re-loads from the durable layer."""
        monkeypatch.chdir(tmp_path)
        from core.cli.commands import _apply_model, get_model_profiles
        from core.config import settings

        model_profiles = get_model_profiles()
        old_model = settings.model
        old_effort = getattr(settings, "agentic_effort", "high")
        try:
            settings.model = model_profiles[0].id
            object.__setattr__(settings, "agentic_effort", "low")
            # Pick a different model AND a different effort so both branches fire
            target = model_profiles[1]
            _apply_model(target, effort="max")
            config_path = tmp_path / ".geode" / "config.toml"
            assert config_path.exists()
            loaded = tomllib.loads(config_path.read_text())
            assert loaded["agentic"]["effort"] == "max"
            assert loaded["llm"]["primary_model"] == target.id
        finally:
            settings.model = old_model
            object.__setattr__(settings, "agentic_effort", old_effort)


class TestPaygStoreFalse:
    def test_codex_plus_still_uses_store_false(self) -> None:
        """Regression guard — Codex subscription backend mandates
        ``store=False``; the kwargs builder for the OAuth adapter must
        keep it.

        PR-LEGACY-PROVIDER-REMOVAL (2026-05-28) — pin migrated from the
        deleted ``core.llm.providers.codex.CodexAgenticAdapter.agentic_call``
        to ``core.llm.adapters.codex_oauth._build_codex_call_kwargs`` (the
        single shared builder used by ``CodexOAuthAdapter.acomplete`` and
        ``.astream``).

        The companion PAYG ``store=False`` pin was retired: the new PAYG
        adapter (``core.llm.adapters.openai_payg.OpenAIPaygAdapter``)
        uses the Chat Completions API which has no ``store`` field, so
        the invariant does not apply on that path."""
        from core.llm.adapters import codex_oauth as codex_oauth_mod

        src = inspect.getsource(codex_oauth_mod)
        assert '"store": False' in src
