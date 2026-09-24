"""Per-model GLM context contracts; provider families do not share one limit."""

from __future__ import annotations

import pytest
from core.llm.token_tracker import MODEL_CONTEXT_WINDOW


@pytest.mark.parametrize(
    "model,window",
    [
        ("glm-5.2", 1_000_000),
        ("glm-5.3", 1_000_000),
        ("glm-5.3-flash", 1_000_000),
        ("glm-5.3-flashx", 1_000_000),
        ("glm-5.1", 200_000),
        ("glm-5", 200_000),
        ("glm-4.7", 200_000),
        ("glm-4.7-flash", 200_000),
    ],
)
def test_glm_context_is_model_specific(model: str, window: int) -> None:
    assert MODEL_CONTEXT_WINDOW[model] == window


def test_unknown_glm_model_does_not_inherit_latest_context() -> None:
    from core.llm.model_catalog import context_window_for

    assert context_window_for("glm-unpublished", default=12345) == 12345


# --- GLM-5.2 support (2026-06-23, docs.z.ai/guides/overview/pricing) --------


def test_glm_5_2_pricing_registered() -> None:
    """glm-5.2 priced with the official input/cached/output rates. The cached
    rate is honoured since PR-CACHE-COST-ACCOUNTING wired GLM cached-token
    surfacing (translate_chat_response) + inclusive-input cost math."""
    from core.llm.token_tracker import MODEL_PRICING

    price = MODEL_PRICING["glm-5.2"]
    assert price.input == pytest.approx(1.40 / 1_000_000)
    assert price.output == pytest.approx(4.40 / 1_000_000)
    assert price.cache_read == pytest.approx(0.26 / 1_000_000)


def test_glm_5_2_in_model_picker() -> None:
    """glm-5.2 is selectable via the interactive /model picker."""
    from core.cli.commands._state import get_model_index

    idx = get_model_index()
    assert "glm-5.2" in idx
    assert idx["glm-5.2"].provider == "glm"


def test_glm_5_2_effort_classification_always_on() -> None:
    """glm-5.2 classified always-on (no effort knob surfaced) — the GLM
    adapter does not send thinking/reasoning_effort, so a toggle would be a
    picker-vs-adapter disconnect (see spec §4)."""
    from core.cli.effort_picker import supported_efforts

    assert supported_efforts("glm-5.2", "glm") == ()


def test_glm_5_2_routes_to_glm_provider() -> None:
    """Prefix routing (`glm-` → glm) accepts the new id with no allowlist edit."""
    from core.llm.model_guidance import FAMILY_GLM, resolve_family

    assert resolve_family("glm-5.2") == FAMILY_GLM
