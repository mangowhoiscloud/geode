from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from scripts.probes.probe_effort_surface import (
    _acomplete_with_runtime_retry,
    visible_effort_surface,
)


def test_visible_effort_surface_matches_picker() -> None:
    surface = visible_effort_surface()

    assert len(surface) == 61
    assert len(surface) == len(set(surface))
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
