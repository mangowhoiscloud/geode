"""GAP-17 — OpenAI HTML ``data:text/html`` URL guard.

``core.agent.system_prompt._build_model_card`` prepends a provider-gated
guard that tells OpenAI/Codex models not to emit the address-bar shape in
the first place.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# system_prompt guard — provider-gated injection
# ---------------------------------------------------------------------------


_GUARD_NEEDLE = "data:text/html"


@pytest.mark.parametrize("openai_model", ["gpt-5.5", "gpt-5.4-mini"])
def test_guard_present_for_openai(monkeypatch: pytest.MonkeyPatch, openai_model: str) -> None:
    """OpenAI models must receive the data-URL ban in their model card."""
    from core.agent.system_prompt import _build_model_card

    _build_model_card.cache_clear()
    card = _build_model_card(openai_model)
    assert _GUARD_NEEDLE in card, f"Missing GAP-17 guard for {openai_model}"
    assert "address bar" in card.lower()


def test_guard_present_for_codex() -> None:
    """Codex shares the OpenAI tendency — guard should apply via provider
    routing (Codex resolves to ``openai`` or ``codex`` depending on config).
    """
    from core.agent.system_prompt import _build_model_card

    _build_model_card.cache_clear()
    # Codex model id from CODEX_PRIMARY
    card = _build_model_card("gpt-5.3-codex")
    # Codex routes through OpenAI provider in _resolve_provider; check the
    # guard fires.  If the resolver renames codex models later this test
    # still asserts the address-bar phrase is present for any OpenAI-family
    # model card.
    assert _GUARD_NEEDLE in card


@pytest.mark.parametrize(
    "non_openai_model",
    ["claude-opus-4-7", "claude-sonnet-4-6", "glm-5.1", "glm-4.7"],
)
def test_guard_absent_for_non_openai(non_openai_model: str) -> None:
    """Anthropic / GLM do not exhibit the data-URL drift — guard must not
    bleed into their cards (cache pressure + irrelevant instructions).
    """
    from core.agent.system_prompt import _build_model_card

    _build_model_card.cache_clear()
    card = _build_model_card(non_openai_model)
    assert _GUARD_NEEDLE not in card, f"GAP-17 guard leaked into {non_openai_model} model card"
