"""Tests for GAP 2: Model Policy (model-policy.toml governance)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from core.config import ModelPolicy, is_model_allowed, load_model_policy


class TestModelPolicy:
    """ModelPolicy dataclass behavior."""

    def test_empty_policy_allows_all(self) -> None:
        policy = ModelPolicy()
        assert is_model_allowed("claude-opus-4-6", policy)
        assert is_model_allowed("gpt-5.4", policy)
        assert is_model_allowed("any-model", policy)

    def test_allowlist_blocks_unlisted(self) -> None:
        policy = ModelPolicy(allowlist=["claude-opus-4-6", "gpt-5.4"])
        assert is_model_allowed("claude-opus-4-6", policy)
        assert is_model_allowed("gpt-5.4", policy)
        assert not is_model_allowed("claude-haiku-4-5-20251001", policy)
        assert not is_model_allowed("unknown", policy)

    def test_denylist_blocks_listed(self) -> None:
        policy = ModelPolicy(denylist=["claude-haiku-4-5-20251001"])
        assert is_model_allowed("claude-opus-4-6", policy)
        assert not is_model_allowed("claude-haiku-4-5-20251001", policy)

    def test_allowlist_takes_precedence_over_denylist(self) -> None:
        """When both are set, allowlist wins."""
        policy = ModelPolicy(
            allowlist=["claude-opus-4-6"],
            denylist=["claude-opus-4-6"],
        )
        # allowlist says yes → allowed
        assert is_model_allowed("claude-opus-4-6", policy)
        # Not in allowlist → blocked (denylist ignored)
        assert not is_model_allowed("gpt-5.4", policy)

    def test_default_model_field(self) -> None:
        policy = ModelPolicy(default_model="claude-sonnet-4-6")
        assert policy.default_model == "claude-sonnet-4-6"


class TestLoadModelPolicy:
    """Loading from TOML file."""

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        policy = load_model_policy(tmp_path / "nonexistent.toml")
        assert policy.allowlist == []
        assert policy.denylist == []
        assert policy.default_model == ""

    def test_load_allowlist(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "policy.toml"
        toml_file.write_text(
            textwrap.dedent("""\
            [policy]
            allowlist = ["claude-opus-4-6", "claude-sonnet-4-6"]
            default_model = "claude-sonnet-4-6"
            """)
        )
        policy = load_model_policy(toml_file)
        assert policy.allowlist == ["claude-opus-4-6", "claude-sonnet-4-6"]
        assert policy.default_model == "claude-sonnet-4-6"

    def test_load_denylist(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "policy.toml"
        toml_file.write_text(
            textwrap.dedent("""\
            [policy]
            denylist = ["claude-haiku-4-5-20251001"]
            """)
        )
        policy = load_model_policy(toml_file)
        assert policy.denylist == ["claude-haiku-4-5-20251001"]
        assert policy.allowlist == []

    def test_malformed_toml_returns_empty(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "bad.toml"
        toml_file.write_text("{{invalid toml}}")
        policy = load_model_policy(toml_file)
        assert policy.allowlist == []

    def test_empty_section_returns_empty(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "empty.toml"
        toml_file.write_text("[other]\nkey = 1\n")
        policy = load_model_policy(toml_file)
        assert policy.allowlist == []


class TestIsModelAllowedDefault:
    """is_model_allowed() without explicit policy (loads from disk)."""

    def test_no_file_allows_all(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Without a policy file, all models are allowed."""
        import core.config as cfg

        monkeypatch.setattr(cfg, "MODEL_POLICY_PATH", tmp_path / "nope.toml")
        assert is_model_allowed("any-model")


def test_required_model_policy_missing_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="required model policy is missing"):
        load_model_policy(tmp_path / "missing.toml", required=True)


@pytest.mark.parametrize(
    "content",
    [
        "{{invalid toml}}",
        "[other]\nallowlist = []\n",
        'policy = "not a table"\n',
        '[policy]\nallowlist = "gpt-5.6-sol"\n',
        "[policy]\ndenylist = [1]\n",
        '[policy]\nallowlist = [""]\n',
        "[policy]\ndefault_model = false\n",
        '[policy]\nallowist = ["gpt-5.6-sol"]\n',
    ],
)
def test_required_model_policy_malformed_fails_closed(tmp_path: Path, content: str) -> None:
    path = tmp_path / "policy.toml"
    path.write_text(content)
    with pytest.raises(ValueError, match="required model policy is malformed"):
        load_model_policy(path, required=True)


def test_required_policy_path_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="must be absolute"):
        load_model_policy(Path("policy.toml"), required=True)


def test_model_policy_path_settings_reject_relative_and_keep_empty_default() -> None:
    from core.config import Settings
    from pydantic import ValidationError

    assert Settings(_env_file=None).model_policy_path == ""
    with pytest.raises(ValidationError, match="model_policy_path must be absolute or empty"):
        Settings(_env_file=None, model_policy_path="policy.toml")


def test_toml_model_policy_path_loads_from_another_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.config as cfg

    policy_path = tmp_path / "policy.toml"
    policy_path.write_text('[policy]\nallowlist = ["gpt-5.6-sol"]\n')
    global_config = tmp_path / "config.toml"
    global_config.write_text(f'[llm]\nmodel_policy_path = "{policy_path}"\n')
    elsewhere = tmp_path / "child"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    values = cfg._load_toml_config(
        global_path=global_config, project_path=elsewhere / "config.toml"
    )
    settings = cfg.Settings(_env_file=None, **values)
    monkeypatch.setattr(cfg, "_settings_instance", settings)

    assert settings.model_policy_path == str(policy_path)
    assert is_model_allowed("gpt-5.6-sol")
    assert not is_model_allowed("gpt-5.5")
    policy_path.unlink()
    with pytest.raises(ValueError, match="required model policy is missing"):
        is_model_allowed("gpt-5.6-sol")
