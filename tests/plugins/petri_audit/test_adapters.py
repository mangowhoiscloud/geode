"""Unit tests for the Petri adapter registry + per-adapter facades (P1-C)."""

from __future__ import annotations

import pytest
from plugins.petri_audit.adapters import (
    get_adapter_metadata,
    get_adapter_spec,
    is_adapter_available,
    load_adapter_module,
    register_adapter,
)
from plugins.petri_audit.manifest import AUTO_SOURCE, clear_manifest_cache, load_manifest


@pytest.fixture(autouse=True)
def _clear_caches():
    clear_manifest_cache()
    yield
    clear_manifest_cache()


def _concrete_bindings() -> list[tuple[str, str]]:
    """Return every (family, source) pair from the default manifest, skipping
    the 'auto' sentinel which is not a concrete adapter."""
    manifest = load_manifest()
    pairs: list[tuple[str, str]] = []
    for family, source_spec in manifest.sources.items():
        for source in source_spec.allowed:
            if source != AUTO_SOURCE:
                pairs.append((family, source))
    return pairs


# ── load_adapter_module ────────────────────────────────────────────────────


@pytest.mark.parametrize("family,source", _concrete_bindings())
def test_every_manifest_binding_imports(family: str, source: str):
    """Every (family, source) declared by manifest resolves to an importable
    Python module — guards against typos in the manifest module path."""
    module = load_adapter_module(family, source)
    assert module is not None


@pytest.mark.parametrize("family,source", _concrete_bindings())
def test_module_exposes_inspect_prefix(family: str, source: str):
    """Adapter modules export ``INSPECT_PREFIX`` matching the manifest entry."""
    module = load_adapter_module(family, source)
    spec = get_adapter_spec(family, source)
    assert getattr(module, "INSPECT_PREFIX", None) == spec.inspect_prefix


# ── register_adapter ───────────────────────────────────────────────────────


@pytest.mark.parametrize("family,source", _concrete_bindings())
def test_module_exposes_register(family: str, source: str):
    """Every adapter module exposes a callable ``register`` (may be a no-op)."""
    module = load_adapter_module(family, source)
    register_fn = getattr(module, "register", None)
    assert callable(register_fn)


def test_register_adapter_invokes_module_register(monkeypatch):
    """``register_adapter`` calls the adapter module's ``register()``."""
    calls = []
    module = load_adapter_module("anthropic", "api_key")

    def _fake_register() -> None:
        calls.append(("anthropic", "api_key"))

    monkeypatch.setattr(module, "register", _fake_register)
    register_adapter("anthropic", "api_key")
    assert calls == [("anthropic", "api_key")]


def test_register_adapter_no_op_when_module_has_no_register(monkeypatch):
    """No ``register`` attribute → silently skip (no AttributeError)."""
    module = load_adapter_module("anthropic", "api_key")
    monkeypatch.delattr(module, "register", raising=False)
    register_adapter("anthropic", "api_key")  # no raise


# ── is_adapter_available ───────────────────────────────────────────────────


def test_is_available_http_anthropic_reads_env(monkeypatch):
    """http_anthropic.is_available reflects ``ANTHROPIC_API_KEY`` presence."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert is_adapter_available("anthropic", "api_key") is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert is_adapter_available("anthropic", "api_key") is True


def test_is_available_http_openai_reads_env(monkeypatch):
    """http_openai.is_available reflects ``OPENAI_API_KEY`` presence."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert is_adapter_available("openai", "api_key") is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    assert is_adapter_available("openai", "api_key") is True


def test_is_available_http_zhipuai_reads_env(monkeypatch):
    """http_zhipuai.is_available reflects ``ZHIPUAI_API_KEY`` presence."""
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)
    assert is_adapter_available("zhipuai", "api_key") is False
    monkeypatch.setenv("ZHIPUAI_API_KEY", "glm-test")
    assert is_adapter_available("zhipuai", "api_key") is True


def test_is_available_swallows_probe_exception(monkeypatch):
    """A probe that raises collapses to False (no propagation)."""
    module = load_adapter_module("anthropic", "api_key")

    def _boom() -> bool:
        raise RuntimeError("probe boom")

    monkeypatch.setattr(module, "is_available", _boom)
    assert is_adapter_available("anthropic", "api_key") is False


def test_is_available_falls_back_to_env_vars_when_no_probe(monkeypatch):
    """No ``is_available`` attribute → check manifest auth_env_vars."""
    module = load_adapter_module("anthropic", "api_key")
    monkeypatch.delattr(module, "is_available", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert is_adapter_available("anthropic", "api_key") is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert is_adapter_available("anthropic", "api_key") is True


# ── get_adapter_metadata ───────────────────────────────────────────────────


def test_metadata_stock_provider_returns_none():
    """Stock providers (no OAuth) — no metadata function → None."""
    assert get_adapter_metadata("anthropic", "api_key") is None
    assert get_adapter_metadata("openai", "api_key") is None
    assert get_adapter_metadata("zhipuai", "api_key") is None


def test_metadata_swallows_exception(monkeypatch):
    """A metadata function that raises returns None."""
    module = load_adapter_module("anthropic", "claude-cli")

    def _boom() -> dict:
        raise RuntimeError("metadata boom")

    monkeypatch.setattr(module, "metadata", _boom)
    assert get_adapter_metadata("anthropic", "claude-cli") is None


def test_metadata_rejects_non_dict(monkeypatch):
    """Non-dict return values collapse to None."""
    module = load_adapter_module("anthropic", "claude-cli")
    monkeypatch.setattr(module, "metadata", lambda: ["not", "a", "dict"])
    assert get_adapter_metadata("anthropic", "claude-cli") is None


# ── Unknown bindings ───────────────────────────────────────────────────────


def test_load_unknown_family_raises_keyerror():
    # ``get_adapter`` falls through to "No adapter for family=…" when the
    # family has no entry in ``manifest.adapters`` (empty dict). The exact
    # message is the manifest's; we just verify the failure mode.
    with pytest.raises(KeyError, match="No adapter for family=nonexistent"):
        load_adapter_module("nonexistent", "api_key")


def test_load_auto_source_raises_valueerror():
    with pytest.raises(ValueError, match="Cannot resolve adapter for 'auto'"):
        load_adapter_module("anthropic", AUTO_SOURCE)
