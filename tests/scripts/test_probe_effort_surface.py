from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from scripts.probes.probe_effort_surface import (
    _acomplete_with_runtime_retry,
    visible_effort_surface,
)


@pytest.mark.parametrize("source,expected_count", [("subscription", 51), ("payg", 66)])
def test_visible_effort_surface_matches_picker(
    monkeypatch: pytest.MonkeyPatch, source: str, expected_count: int
) -> None:
    from core.cli.commands._state import get_model_profiles
    from core.cli.effort_picker import supported_efforts

    monkeypatch.setattr("core.cli.commands._state._selected_openai_source", lambda: source)
    surface = visible_effort_surface()

    assert len(surface) == expected_count
    assert len(surface) == len(set(surface))
    assert surface == tuple(
        (profile.id, profile.provider, effort)
        for profile in get_model_profiles(openai_source=source)
        for effort in supported_efforts(profile.id, profile.provider)
    )
    retired_subscription_ids = {"gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"}
    surface_models = {model for model, _, _ in surface}
    if source == "subscription":
        assert retired_subscription_ids.isdisjoint(surface_models)
    else:
        assert retired_subscription_ids <= surface_models
    assert ("gpt-6-astra", "openai", "low") in surface
    assert ("gpt-6-astra", "openai", "max") in surface
    assert ("gpt-5.6-sol", "openai", "max") in surface
    assert ("claude-fable-5", "anthropic", "xhigh") in surface


def test_visible_effort_surface_honors_explicit_model_order() -> None:
    surface = visible_effort_surface(("gpt-5.6-luna", "gpt-5.6-sol"))

    assert len(surface) == 12
    assert [model for model, _, _ in surface[:6]] == ["gpt-5.6-luna"] * 6
    assert [model for model, _, _ in surface[6:]] == ["gpt-5.6-sol"] * 6


def test_measurement_retries_pre_response_transient_once() -> None:
    class FlakyAdapter:
        calls = 0

        async def acomplete(self, request: object) -> object:
            del request
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("servers are currently overloaded")
            return SimpleNamespace(text="EFFORT_OK")

    adapter = FlakyAdapter()
    history: list[dict[str, object]] = []
    with patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock):
        result = asyncio.run(
            _acomplete_with_runtime_retry(
                adapter,
                SimpleNamespace(model="gpt-5.6-sol"),
                timeout_s=1,
                retry_history=history,
            )
        )

    assert result.text == "EFFORT_OK"
    assert adapter.calls == 2
    assert history[0]["error_category"] == "unknown"
