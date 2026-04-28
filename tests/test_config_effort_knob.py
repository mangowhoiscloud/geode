"""Cycle B — durable picker persistence + PAYG store=False (v0.61.0).

Verifies:
  1. ``upsert_config_toml`` writes new files, updates existing keys,
     handles section boundaries.
  2. ``_apply_model`` from the picker persists effort + model to
     ``.geode/config.toml`` (durable layer), not just ``.env``.
  3. PAYG ``openai.py`` adapter sends ``store=False`` (parity with
     Codex Plus, R3-mini follow-up).
"""

from __future__ import annotations

import inspect
import tomllib
from pathlib import Path

from core.cli._helpers import upsert_config_toml


class TestUpsertConfigToml:
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
    def test_apply_model_writes_effort_to_config_toml(self, tmp_path: Path, monkeypatch) -> None:
        """After picker confirms an effort, .geode/config.toml must
        carry it so the next session re-loads from the durable layer."""
        monkeypatch.chdir(tmp_path)
        from core.cli.commands import MODEL_PROFILES, _apply_model
        from core.config import settings

        old_model = settings.model
        old_effort = getattr(settings, "agentic_effort", "high")
        try:
            settings.model = MODEL_PROFILES[0].id
            object.__setattr__(settings, "agentic_effort", "low")
            # Pick a different model AND a different effort so both branches fire
            target = MODEL_PROFILES[1]
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
    def test_store_false_in_openai_kwargs(self) -> None:
        """Source-pin: the PAYG adapter must send ``store=False`` so it
        matches Codex Plus and avoids server-side response retention."""
        from core.llm.providers import openai as openai_mod

        src = inspect.getsource(openai_mod)
        assert '"store": False' in src

    def test_codex_plus_still_uses_store_false(self) -> None:
        """Regression guard — extracting the shared replay walker
        in v0.60.0 must not have dropped Codex Plus's store=False."""
        from core.llm.providers import codex as codex_mod

        src = inspect.getsource(codex_mod)
        assert '"store": False' in src
