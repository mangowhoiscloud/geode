"""Picker → adapter resolution glue tests + config.toml SoT tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import plugins.seed_generation.picker as picker_mod
import pytest
from core.llm.adapters.registry import _reset_for_test, bootstrap_builtins
from plugins.seed_generation.picker import (
    RoleBinding,
    binding_to_adapter_source,
    load_user_overrides,
    resolve_binding_to_adapter,
)


@pytest.fixture(autouse=True)
def _registry_with_builtins():
    _reset_for_test()
    bootstrap_builtins()
    yield
    _reset_for_test()


@pytest.fixture(autouse=True)
def _reset_legacy_warned():
    """Force the one-time legacy-warning flag back to False per test."""
    picker_mod._LEGACY_OVERRIDE_WARNED = False
    yield
    picker_mod._LEGACY_OVERRIDE_WARNED = False


# ── binding_to_adapter_source ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("picker_source", "expected"),
    [
        ("api_key", "payg"),
        ("payg", "payg"),
        ("claude-cli", "adapter"),
        ("openai-codex", "subscription"),
        ("subscription", "subscription"),
        ("adapter", "adapter"),
    ],
)
def test_binding_to_adapter_source_known(picker_source: str, expected: str) -> None:
    assert binding_to_adapter_source(picker_source) == expected


def test_binding_to_adapter_source_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown picker source"):
        binding_to_adapter_source("nonexistent")


# ── resolve_binding_to_adapter end-to-end ─────────────────────────────────


def test_resolve_binding_claude_cli_returns_claude_cli_adapter() -> None:
    b = RoleBinding(
        role="generator", model="claude-sonnet-4-6", provider="anthropic", source="claude-cli"
    )
    adapter = resolve_binding_to_adapter(b)
    assert adapter.name == "claude-cli"  # type: ignore[attr-defined]


def test_resolve_binding_api_key_returns_payg_adapter() -> None:
    b = RoleBinding(
        role="critic", model="claude-sonnet-4-6", provider="anthropic", source="api_key"
    )
    adapter = resolve_binding_to_adapter(b)
    assert adapter.name == "anthropic-payg"  # type: ignore[attr-defined]


def test_resolve_binding_openai_codex_returns_codex_oauth_adapter() -> None:
    b = RoleBinding(role="evolver", model="gpt-5.5", provider="openai", source="openai-codex")
    adapter = resolve_binding_to_adapter(b)
    assert adapter.name == "codex-oauth"  # type: ignore[attr-defined]


def test_resolve_binding_new_adapter_name_passthrough() -> None:
    """A binding with adapter-native source (``adapter`` / ``subscription``) resolves directly."""
    b = RoleBinding(role="pilot", model="claude-sonnet-4-6", provider="anthropic", source="adapter")
    adapter = resolve_binding_to_adapter(b)
    assert adapter.name == "claude-cli"  # type: ignore[attr-defined]


# ── Config SoT — config.toml [seed_generation.role.*] precedence ──────────


def test_config_toml_wins_over_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When config.toml has [seed_generation.role.*], legacy file is NOT read."""
    config = tmp_path / "config.toml"
    config.write_text(
        textwrap.dedent(
            """
            [seed_generation.role.generator]
            source = "payg"

            [seed_generation.role.pilot]
            source = "adapter"
            model = "claude-haiku-4-5"
            """
        ),
        encoding="utf-8",
    )
    legacy = tmp_path / "seed_generation.toml"
    legacy.write_text(
        textwrap.dedent(
            """
            [generator]
            source = "should_not_be_read"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(picker_mod, "GLOBAL_CONFIG_TOML", config)
    monkeypatch.setattr(picker_mod, "GLOBAL_SEED_PIPELINE_TOML", legacy)

    overrides = load_user_overrides()
    assert overrides == {
        "generator": {"source": "payg"},
        "pilot": {"source": "adapter", "model": "claude-haiku-4-5"},
    }


def test_legacy_file_fallback_when_config_toml_lacks_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """Falls back to legacy seed_generation.toml + logs a one-time warning."""
    config = tmp_path / "config.toml"
    config.write_text(
        textwrap.dedent(
            """
            [other_section]
            value = "irrelevant"
            """
        ),
        encoding="utf-8",
    )
    legacy = tmp_path / "seed_generation.toml"
    legacy.write_text(
        textwrap.dedent(
            """
            [generator]
            source = "api_key"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(picker_mod, "GLOBAL_CONFIG_TOML", config)
    monkeypatch.setattr(picker_mod, "GLOBAL_SEED_PIPELINE_TOML", legacy)

    with caplog.at_level("WARNING"):
        overrides = load_user_overrides()
    assert overrides == {"generator": {"source": "api_key"}}
    assert any("legacy" in r.getMessage() for r in caplog.records)


def test_legacy_warning_only_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    config = tmp_path / "config.toml"
    config.write_text("# empty\n", encoding="utf-8")
    legacy = tmp_path / "seed_generation.toml"
    legacy.write_text('[generator]\nsource = "api_key"\n', encoding="utf-8")
    monkeypatch.setattr(picker_mod, "GLOBAL_CONFIG_TOML", config)
    monkeypatch.setattr(picker_mod, "GLOBAL_SEED_PIPELINE_TOML", legacy)

    with caplog.at_level("WARNING"):
        load_user_overrides()
        load_user_overrides()
        legacy_warnings = [r for r in caplog.records if "legacy" in r.getMessage()]
    assert len(legacy_warnings) == 1


def test_both_files_missing_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker_mod, "GLOBAL_CONFIG_TOML", tmp_path / "noconfig.toml")
    monkeypatch.setattr(picker_mod, "GLOBAL_SEED_PIPELINE_TOML", tmp_path / "nolegacy.toml")
    assert load_user_overrides() == {}


def test_explicit_path_bypasses_sot_resolution(tmp_path: Path) -> None:
    """``load_user_overrides(path=...)`` reads the explicit file directly (legacy shape)."""
    target = tmp_path / "custom.toml"
    target.write_text('[generator]\nsource = "adapter"\n', encoding="utf-8")
    assert load_user_overrides(path=target) == {"generator": {"source": "adapter"}}


def test_malformed_config_toml_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """An unparseable config.toml does not crash the picker — fall through."""
    config = tmp_path / "config.toml"
    config.write_text("not = valid = toml\n", encoding="utf-8")
    monkeypatch.setattr(picker_mod, "GLOBAL_CONFIG_TOML", config)
    monkeypatch.setattr(picker_mod, "GLOBAL_SEED_PIPELINE_TOML", tmp_path / "nolegacy.toml")
    with caplog.at_level("WARNING"):
        result = load_user_overrides()
    assert result == {}
    assert any("not valid TOML" in r.getMessage() for r in caplog.records)
