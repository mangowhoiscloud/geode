"""Tests for Config Cascade -- TOML-based config overlay."""

import textwrap

from core.config import (
    DEFAULT_CONFIG_TOML,
    Settings,
    _apply_toml_overlay,
    _flatten_toml,
    _load_toml_config,
)


class TestFlattenToml:
    def test_flat_dict(self):
        result = _flatten_toml({"key": "value"})
        assert result == {"key": "value"}

    def test_nested_dict(self):
        result = _flatten_toml({"llm": {"primary_model": "gpt-5.4"}})
        assert result == {"llm.primary_model": "gpt-5.4"}

    def test_deeply_nested(self):
        result = _flatten_toml({"a": {"b": {"c": 42}}})
        assert result == {"a.b.c": 42}

    def test_mixed(self):
        result = _flatten_toml(
            {
                "llm": {"primary_model": "x"},
                "output": {"verbose": True},
                "top": "level",
            }
        )
        assert result["llm.primary_model"] == "x"
        assert result["output.verbose"] is True
        assert result["top"] == "level"

    def test_empty_dict(self):
        assert _flatten_toml({}) == {}


class TestLoadTomlConfig:
    def test_global_config_loaded(self, tmp_path):
        """Global config.toml values are loaded."""
        global_toml = tmp_path / "global" / "config.toml"
        global_toml.parent.mkdir(parents=True)
        global_toml.write_text(
            textwrap.dedent("""\
                [llm]
                primary_model = "gpt-5.4"
            """),
            encoding="utf-8",
        )
        result = _load_toml_config(
            global_path=global_toml,
            project_path=tmp_path / "nonexistent" / "config.toml",
        )
        assert result["model"] == "gpt-5.4"

    def test_project_overrides_global(self, tmp_path):
        """Project config.toml overrides global."""
        global_toml = tmp_path / "global" / "config.toml"
        global_toml.parent.mkdir(parents=True)
        global_toml.write_text(
            textwrap.dedent("""\
                [llm]
                primary_model = "gpt-5.4"
                [output]
                verbose = false
            """),
            encoding="utf-8",
        )
        project_toml = tmp_path / "project" / "config.toml"
        project_toml.parent.mkdir(parents=True)
        project_toml.write_text(
            textwrap.dedent("""\
                [llm]
                primary_model = "claude-opus-4-6"
            """),
            encoding="utf-8",
        )
        result = _load_toml_config(
            global_path=global_toml,
            project_path=project_toml,
        )
        assert result["model"] == "claude-opus-4-6"
        # verbose from global should remain
        assert result["verbose"] is False

    def test_missing_toml_graceful(self, tmp_path):
        """Missing TOML files produce empty result (no crash)."""
        result = _load_toml_config(
            global_path=tmp_path / "no_such.toml",
            project_path=tmp_path / "also_no.toml",
        )
        assert result == {}

    def test_malformed_toml_warning(self, tmp_path):
        """Malformed TOML file logs warning and continues."""
        bad_toml = tmp_path / "bad.toml"
        bad_toml.write_text("this is not [valid toml", encoding="utf-8")
        result = _load_toml_config(
            global_path=bad_toml,
            project_path=tmp_path / "nonexistent.toml",
        )
        assert result == {}

    def test_unknown_keys_ignored(self, tmp_path):
        """TOML keys not in _TOML_TO_SETTINGS are silently ignored."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            textwrap.dedent("""\
                [unknown_section]
                unknown_key = "value"
            """),
            encoding="utf-8",
        )
        result = _load_toml_config(
            global_path=toml_file,
            project_path=tmp_path / "nonexistent.toml",
        )
        assert result == {}


class TestApplyTomlOverlay:
    def test_overlay_sets_unset_field(self, tmp_path, monkeypatch):
        """TOML value is applied when env var is not set."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            textwrap.dedent("""\
                [pipeline]
                confidence_threshold = 0.85
            """),
            encoding="utf-8",
        )
        # Ensure env var is NOT set
        monkeypatch.delenv("GEODE_CONFIDENCE_THRESHOLD", raising=False)

        s = Settings()
        assert s.confidence_threshold == 0.7  # code default

        # Patch _load_toml_config to use our temp file
        monkeypatch.setattr(
            "core.config._load_toml_config",
            lambda **_kw: _load_toml_config(
                global_path=toml_file,
                project_path=tmp_path / "nonexistent.toml",
            ),
        )
        _apply_toml_overlay(s)
        assert s.confidence_threshold == 0.85

    def test_env_overrides_toml(self, tmp_path, monkeypatch):
        """Environment variable takes precedence over TOML."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text(
            textwrap.dedent("""\
                [pipeline]
                max_iterations = 99
            """),
            encoding="utf-8",
        )
        # Set env var (should take precedence)
        monkeypatch.setenv("GEODE_MAX_ITERATIONS", "10")

        s = Settings()
        monkeypatch.setattr(
            "core.config._load_toml_config",
            lambda **_kw: _load_toml_config(
                global_path=toml_file,
                project_path=tmp_path / "nonexistent.toml",
            ),
        )
        _apply_toml_overlay(s)
        # env wins: max_iterations stays at env value, not TOML's 99
        assert s.max_iterations != 99

    def test_no_toml_no_change(self, tmp_path, monkeypatch):
        """Without TOML files, Settings stays at defaults."""
        monkeypatch.setattr(
            "core.config._load_toml_config",
            lambda **_kw: {},
        )
        s = Settings()
        original_model = s.model
        _apply_toml_overlay(s)
        assert s.model == original_model


class TestDefaultConfigToml:
    def test_template_is_valid_toml(self):
        """DEFAULT_CONFIG_TOML can be parsed without error."""
        import tomllib

        # Should not raise
        tomllib.loads(DEFAULT_CONFIG_TOML)

    def test_template_has_sections(self):
        """Template contains expected commented sections."""
        assert "[llm]" in DEFAULT_CONFIG_TOML
        assert "[output]" in DEFAULT_CONFIG_TOML
        assert "[pipeline]" in DEFAULT_CONFIG_TOML


class TestFullCascade:
    """Integration test: 4-level override order."""

    def test_cascade_order(self, tmp_path, monkeypatch):
        """CLI > env > project TOML > global TOML > default.

        We test: global sets model, project overrides it,
        env would override project (if set).
        """
        global_toml = tmp_path / "global.toml"
        global_toml.write_text(
            textwrap.dedent("""\
                [llm]
                primary_model = "global-model"
                [output]
                verbose = true
            """),
            encoding="utf-8",
        )
        project_toml = tmp_path / "project.toml"
        project_toml.write_text(
            textwrap.dedent("""\
                [llm]
                primary_model = "project-model"
            """),
            encoding="utf-8",
        )

        # No env vars set
        monkeypatch.delenv("GEODE_MODEL", raising=False)
        monkeypatch.delenv("GEODE_VERBOSE", raising=False)

        result = _load_toml_config(
            global_path=global_toml,
            project_path=project_toml,
        )

        # Project overrides global for model
        assert result["model"] == "project-model"
        # Global verbose survives (not overridden by project)
        assert result["verbose"] is True
