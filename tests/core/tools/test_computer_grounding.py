"""Retired visual grounding cannot select a hidden model or credential route."""

from __future__ import annotations

import asyncio
from unittest.mock import Mock, patch

import pytest
from core.tools import computer_grounding as cg
from core.tools.base import ToolContext


@pytest.mark.parametrize(
    "provider,source",
    [("", ""), ("glm", "payg"), ("glm", "subscription"), ("openai", "subscription")],
)
def test_automatic_grounding_is_unavailable_without_opening_a_client(
    provider: str, source: str
) -> None:
    client = Mock(side_effect=AssertionError("must not open a provider client"))
    context = ToolContext(provider=provider, source=source) if provider else None
    with (
        patch("openai.AsyncOpenAI", client),
        pytest.raises(cg.VisualGroundingUnavailableError) as raised,
    ):
        asyncio.run(cg.locate_with_active_provider("B64", "submit", tool_context=context))
    assert raised.value.provider == provider
    assert raised.value.source == source
    assert "implicit GLM fallback is disabled" in str(raised.value)
    client.assert_not_called()
