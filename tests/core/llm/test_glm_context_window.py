"""GAP-X1 — GLM context window verified against z.ai docs (2026-05-12).

Pre-fix: ``MODEL_CONTEXT_WINDOW`` rounded all five GLM models to a flat
``200_000`` token guard.  The 2026-04-26 comment claimed "200K standard
across 5.x family" but the upstream z.ai docs + openrouter listings give
the precise value as **202_752 tokens** for every model in the
``_GLM_THINKING_MODELS`` whitelist that GEODE registers.

Difference vs prior config: +2_752 tokens.  Effect: the post-call 200K
guard tripped ~2.7K tokens early; conservative but inaccurate. Cost /
fail-fast paths now reflect the upstream contract.

Sources (verified 2026-05-12):
- z.ai docs ``glm-5.1`` / ``glm-4.7`` — "Context: 200K"
- openrouter ``z-ai/glm-5`` — "Context: 203K"
- openrouter ``z-ai/glm-5-turbo`` / ``z-ai/glm-4.7-flash`` — 202_752
"""

from __future__ import annotations

import pytest
from core.llm.token_tracker import MODEL_CONTEXT_WINDOW


@pytest.mark.parametrize(
    "model",
    ["glm-5.2", "glm-5.1", "glm-5", "glm-5-turbo", "glm-4.7", "glm-4.7-flash"],
)
def test_glm_model_context_window_is_202752(model: str) -> None:
    """GAP-X1: every registered GLM model exposes z.ai's exact 202_752
    token limit (not the 200_000 round-down).

    glm-5.2 supports up to 1M via the ``glm-5.2[1m]`` DevPack form, but the
    plain id GEODE calls over the PAYG OpenAI-compatible endpoint uses the
    family window — see docs/research/glm-5.2-model-spec.md §4.
    """
    assert MODEL_CONTEXT_WINDOW[model] == 202_752, (
        f"GAP-X1 regression: {model} context window drifted "
        f"({MODEL_CONTEXT_WINDOW[model]} ≠ 202_752 per z.ai docs)"
    )


def test_all_glm_models_share_same_window() -> None:
    """If a future model joins the GLM family with a different window
    (e.g. a 1M-context variant), this assertion will fail and prompt an
    explicit override rather than silent inheritance.
    """
    glm_models = [k for k in MODEL_CONTEXT_WINDOW if k.startswith("glm-")]
    assert len(glm_models) == 6, f"Unexpected GLM model count: {glm_models}"
    windows = {MODEL_CONTEXT_WINDOW[m] for m in glm_models}
    assert windows == {202_752}, (
        f"GLM family no longer shares a single window — verify each new "
        f"entry against z.ai docs before merging: {windows}"
    )


# --- GLM-5.2 support (2026-06-23, docs.z.ai/guides/overview/pricing) --------


def test_glm_5_2_pricing_registered() -> None:
    """glm-5.2 priced with the official input/output rates — without this the
    model bills at $0.00 (Unknown model fallback). cached_per_mtok is omitted
    to match the GLM family (the GLM chat path doesn't surface cached_tokens
    yet — see spec §4), so cache_read derives to 0.0."""
    from core.llm.token_tracker import MODEL_PRICING

    price = MODEL_PRICING["glm-5.2"]
    assert price.input == pytest.approx(1.40 / 1_000_000)
    assert price.output == pytest.approx(4.40 / 1_000_000)
    assert price.cache_read == 0.0  # family-consistent (no cached_per_mtok)


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
