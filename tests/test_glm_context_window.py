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
    ["glm-5.1", "glm-5", "glm-5-turbo", "glm-4.7", "glm-4.7-flash"],
)
def test_glm_model_context_window_is_202752(model: str) -> None:
    """GAP-X1: every registered GLM model exposes z.ai's exact 202_752
    token limit (not the 200_000 round-down).
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
    assert len(glm_models) == 5, f"Unexpected GLM model count: {glm_models}"
    windows = {MODEL_CONTEXT_WINDOW[m] for m in glm_models}
    assert windows == {202_752}, (
        f"GLM family no longer shares a single window — verify each new "
        f"entry against z.ai docs before merging: {windows}"
    )
