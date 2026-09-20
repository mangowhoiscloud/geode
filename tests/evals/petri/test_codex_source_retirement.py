"""The optional direct Inspect adapter must reject retirement before auth I/O."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import Mock

import pytest
from core.llm.errors import ModelSourceUnavailableError


@pytest.mark.parametrize("model", ["gpt-5.4", "gpt-5.4-mini", "gpt-5.2", "gpt-5.3-codex"])
@pytest.mark.parametrize("positional", [True, False])
def test_direct_codex_provider_rejects_before_token_resolution(
    monkeypatch: pytest.MonkeyPatch, model: str, positional: bool
) -> None:
    from evals.petri import codex_provider

    # Only registration and constructor admission are under test. No optional
    # dependency installation, SDK client construction, or credential lookup.
    captured: list[type] = []

    def modelapi(*, name: str):
        assert name == "openai-codex"

        def register(cls: type) -> type:
            captured.append(cls)
            return cls

        return register

    class _StockOpenAIAPI:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pytest.fail("Retirement must fail before the stock client constructor")

    model_module = ModuleType("inspect_ai.model")
    model_module.modelapi = modelapi
    provider_module = ModuleType("inspect_ai.model._providers.openai")
    provider_module.OpenAIAPI = _StockOpenAIAPI
    util_module = ModuleType("inspect_ai.model._providers.util")
    util_module.environment_prerequisite_error = Mock()
    monkeypatch.setitem(sys.modules, "inspect_ai.model", model_module)
    monkeypatch.setitem(sys.modules, "inspect_ai.model._providers.openai", provider_module)
    monkeypatch.setitem(sys.modules, "inspect_ai.model._providers.util", util_module)
    token = Mock(side_effect=AssertionError("must not read credentials"))
    monkeypatch.setattr("core.llm.providers.codex.resolve_codex_token", token)

    codex_provider.register()
    with pytest.raises(ModelSourceUnavailableError, match="subscription"):
        if positional:
            captured[0](model)
        else:
            captured[0](model_name=model)
    token.assert_not_called()
