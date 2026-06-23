"""GLM-5.2 reasoning_effort / thinking control gate (PR-GLM-5.2-FINALIZE).

``build_glm_reasoning_extra_body`` gates the GLM-5.2 reasoning params behind
``settings.glm_reasoning_effort`` (default empty = send nothing → server
default, no regression). The param shape is doc-grounded (official z.ai
chat-completion API ref) but live-unverified (GLM balance 0).
"""

from __future__ import annotations

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

    def test_only_glm_5_2(self, monkeypatch):
        # reasoning_effort is GLM-5.2-only — older GLM ids never get the param.
        from core.config import settings

        monkeypatch.setattr(settings, "glm_reasoning_effort", "max", raising=False)
        assert build_glm_reasoning_extra_body("glm-5.1") is None
        assert build_glm_reasoning_extra_body("glm-5-turbo") is None
        assert build_glm_reasoning_extra_body("glm-5.2") is not None

    def test_invalid_value_dropped_with_warning(self, monkeypatch, caplog):
        import logging

        from core.config import settings

        monkeypatch.setattr(settings, "glm_reasoning_effort", "turbo", raising=False)
        with caplog.at_level(logging.WARNING, logger="core.llm.providers.glm"):
            assert build_glm_reasoning_extra_body("glm-5.2") is None
        assert any("not a valid z.ai value" in r.getMessage() for r in caplog.records)

    def test_case_and_whitespace_normalized(self, monkeypatch):
        from core.config import settings

        monkeypatch.setattr(settings, "glm_reasoning_effort", "  HIGH  ", raising=False)
        xb = build_glm_reasoning_extra_body("glm-5.2")
        assert xb is not None
        assert xb["reasoning_effort"] == "high"


def test_glm_default_is_5_2():
    """GLM default flipped to the flagship glm-5.2."""
    from core.config import GLM_PRIMARY

    assert GLM_PRIMARY == "glm-5.2"


def test_glm_5_2_is_default_picker_entry():
    """The /model picker's GLM default entry is glm-5.2 (labelled GLM-5.2),
    with glm-5.1 still explicitly selectable."""
    from core.cli.commands._state import get_model_index

    idx = get_model_index()
    assert "glm-5.2" in idx
    assert "glm-5.1" in idx
    assert idx["glm-5.2"].label == "GLM-5.2"
