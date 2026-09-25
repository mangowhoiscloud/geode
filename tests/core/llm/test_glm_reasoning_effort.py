"""Model-specific GLM reasoning controls, grounded in the current API contract."""

from __future__ import annotations

import pytest
from core.llm.errors import LLMRequestValidationError
from core.llm.providers.glm import build_glm_reasoning_extra_body


class TestGlmReasoningGate:
    def test_unset_sends_nothing(self, monkeypatch):
        from core.config import settings

        monkeypatch.setattr(settings, "glm_reasoning_effort", "", raising=False)
        assert build_glm_reasoning_extra_body("glm-5.2") is None

    def test_set_valid_builds_extra_body(self, monkeypatch):
        from core.config import settings

        monkeypatch.setattr(settings, "glm_reasoning_effort", "high", raising=False)
        xb = build_glm_reasoning_extra_body("glm-5.2")
        assert xb == {"reasoning_effort": "high", "thinking": {"type": "enabled"}}

    def test_none_disables_thinking(self, monkeypatch):
        from core.config import settings

        monkeypatch.setattr(settings, "glm_reasoning_effort", "none", raising=False)
        xb = build_glm_reasoning_extra_body("glm-5.2")
        assert xb == {"reasoning_effort": "none", "thinking": {"type": "disabled"}}

    def test_older_models_do_not_get_graded_effort(self, monkeypatch):
        # The documented graded control begins with GLM-5.2.
        from core.config import settings

        monkeypatch.setattr(settings, "glm_reasoning_effort", "max", raising=False)
        assert build_glm_reasoning_extra_body("glm-5.1") is None
        assert build_glm_reasoning_extra_body("glm-5-turbo") is None
        assert build_glm_reasoning_extra_body("glm-5.2") is not None

    def test_invalid_value_rejected(self, monkeypatch):
        from core.config import settings

        monkeypatch.setattr(settings, "glm_reasoning_effort", "turbo", raising=False)
        with pytest.raises(LLMRequestValidationError, match="does not support effort 'turbo'"):
            build_glm_reasoning_extra_body("glm-5.2")

    def test_case_and_whitespace_rejected(self, monkeypatch):
        from core.config import settings

        monkeypatch.setattr(settings, "glm_reasoning_effort", "  HIGH  ", raising=False)
        with pytest.raises(LLMRequestValidationError, match="does not support effort '  HIGH  '"):
            build_glm_reasoning_extra_body("glm-5.2")


def test_glm_default_is_5_3():
    """The shipped model default follows the September 24 contract."""
    from core.config import GLM_PRIMARY

    assert GLM_PRIMARY == "glm-5.3"


def test_glm_5_3_leads_picker_without_retiring_active_older_models():
    from core.cli.commands._state import get_model_profiles

    rows = [row for row in get_model_profiles(openai_source="payg") if row.provider == "glm"]
    assert rows[0].id == "glm-5.3"
    assert rows[0].label == "GLM-5.3"
    assert {"glm-5.2", "glm-5.1"} <= {row.id for row in rows}
