"""Unit tests for plugins.petri_audit.registry (P1-E)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from plugins.petri_audit.manifest import clear_manifest_cache
from plugins.petri_audit.registry import (
    FamilyInferenceError,
    PetriBinding,
    get_binding,
    infer_family,
)

from plugins.petri_audit import credential_source as cs


@pytest.fixture(autouse=True)
def _isolate_self_improving_loop_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-δ2 — pin the self-improving-loop config loader to a non-existent tmp path so
    a developer / CI host with real ``[self_improving_loop.petri.*]`` does not bleed
    into ``read_role_override`` results."""
    monkeypatch.setenv(
        "GEODE_CONFIG_TOML", str(tmp_path / "self_improving_loop_isolation_sentinel.toml")
    )
    # Same isolation for the legacy petri.toml path, in case any test
    # touches save_role_override indirectly.
    monkeypatch.setenv("GEODE_PETRI_TOML", str(tmp_path / "petri.toml"))


@pytest.fixture(autouse=True)
def _clear_state() -> Iterator[None]:
    clear_manifest_cache()
    cs.clear_suppressions()
    yield
    cs.clear_suppressions()
    clear_manifest_cache()


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPUAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cs, "_settings_source", lambda family: None)


@pytest.fixture(autouse=True)
def _stub_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.petri_audit.adapters import claude_cli_backend, openai_codex_oauth

    monkeypatch.setattr(claude_cli_backend, "is_available", lambda: False)
    monkeypatch.setattr(openai_codex_oauth, "is_available", lambda: False)


# ── infer_family ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-4-6", "anthropic"),
        ("claude-opus-4-7", "anthropic"),
        ("claude-haiku-4-5", "anthropic"),
        ("gpt-5.5", "openai"),
        ("gpt-5.4-mini", "openai"),
        ("o3", "openai"),
        ("o4-mini", "openai"),
        ("glm-4-6", "zhipuai"),
        ("anthropic/claude-sonnet-4-6", "anthropic"),
        ("openai/gpt-5.5", "openai"),
        ("openai-api/gpt-5.5", "openai"),
    ],
)
def test_infer_family(model: str, expected: str) -> None:
    assert infer_family(model) == expected


def test_infer_family_unknown_raises() -> None:
    with pytest.raises(FamilyInferenceError, match="cannot infer family"):
        infer_family("mystery-model-7")


def test_infer_family_empty_raises() -> None:
    with pytest.raises(FamilyInferenceError, match="empty model"):
        infer_family("")


# ── get_binding — happy path ───────────────────────────────────────────────


def test_get_binding_auditor_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    binding = get_binding("auditor")
    assert isinstance(binding, PetriBinding)
    assert binding.role == "auditor"
    assert binding.model == "claude-sonnet-4-6"
    assert binding.source == "api_key"
    assert binding.family == "anthropic"
    assert binding.adapter_module == "plugins.petri_audit.adapters.http_anthropic"
    assert binding.inspect_prefix == "anthropic"
    assert binding.inspect_id == "anthropic/claude-sonnet-4-6"


def test_get_binding_judge_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    binding = get_binding("judge")
    assert binding.role == "judge"
    assert binding.model == "claude-sonnet-4-6"
    assert binding.inspect_id == "anthropic/claude-sonnet-4-6"


def test_get_binding_target_uses_geode_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Target role always routes through GeodeModelAPI regardless of family."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    binding = get_binding("target")
    assert binding.role == "target"
    assert binding.model == "claude-haiku-4-5"
    # Family adapter still recorded — shows underlying source in picker.
    assert binding.family == "anthropic"
    assert binding.adapter_module == "plugins.petri_audit.adapters.http_anthropic"
    # But the inspect id uses 'geode' prefix unconditionally.
    assert binding.inspect_prefix == "geode"
    assert binding.inspect_id == "geode/claude-haiku-4-5"


# ── get_binding — overrides ────────────────────────────────────────────────


def test_get_binding_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    binding = get_binding("auditor", model="claude-opus-4-7")
    assert binding.model == "claude-opus-4-7"
    assert binding.inspect_id == "anthropic/claude-opus-4-7"


def test_get_binding_source_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit source override survives even when env var is set."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from plugins.petri_audit.adapters import claude_cli_backend

    monkeypatch.setattr(claude_cli_backend, "is_available", lambda: True)
    binding = get_binding("auditor", source="claude-cli")
    assert binding.source == "claude-cli"
    assert binding.inspect_prefix == "claude-code"


def test_get_binding_model_not_in_allowed_raises() -> None:
    """auditor.allowed_models excludes GLM family — manifest enforced."""
    with pytest.raises(ValueError, match="not in allowed_models"):
        get_binding("auditor", model="glm-4-6")


def test_get_binding_judge_rejects_gpt54_mini() -> None:
    """judge.allowed_models = [opus, sonnet, gpt-5.5] — gpt-5.4-mini not in."""
    with pytest.raises(ValueError, match="not in allowed_models"):
        get_binding("judge", model="gpt-5.4-mini")


def test_get_binding_unknown_role_raises() -> None:
    with pytest.raises(KeyError, match="Unknown petri role"):
        get_binding("imposter")


# ── get_binding — credential resolution ───────────────────────────────────


def test_get_binding_no_credential_raises() -> None:
    """No env var → resolve_credential_source raises."""
    with pytest.raises(cs.CredentialResolutionError):
        get_binding("auditor")


def test_get_binding_oauth_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """When both claude-cli and api_key are available, manifest order wins."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from plugins.petri_audit.adapters import claude_cli_backend

    monkeypatch.setattr(claude_cli_backend, "is_available", lambda: True)
    binding = get_binding("auditor")
    assert binding.source == "claude-cli"
    assert binding.inspect_prefix == "claude-code"
    assert binding.inspect_id == "claude-code/claude-sonnet-4-6"


def test_get_binding_target_with_openai_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Target with a GPT model still routes through 'geode/' prefix."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    binding = get_binding("target", model="gpt-5.4-mini")
    assert binding.family == "openai"
    assert binding.adapter_module == "plugins.petri_audit.adapters.http_openai"
    assert binding.inspect_prefix == "geode"
    assert binding.inspect_id == "geode/gpt-5.4-mini"


def test_get_binding_target_with_glm_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZHIPUAI_API_KEY", "glm-test")
    binding = get_binding("target", model="glm-4-6")
    assert binding.family == "zhipuai"
    assert binding.inspect_prefix == "geode"
    assert binding.inspect_id == "geode/glm-4-6"


# ── PetriBinding immutability ──────────────────────────────────────────────


def test_petri_binding_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    binding = get_binding("auditor")
    with pytest.raises(Exception):  # FrozenInstanceError
        binding.model = "other"  # type: ignore[misc]
