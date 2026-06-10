"""PR-DRIFT-ANCHORS (2026-06-10) — single-SoT guards for former literal mirrors.

Two families used to drift:

1. ``_PROVIDER_NORMALIZATION`` — the legacy→registry provider map existed
   as FOUR independent copies (two full dict literals, two partial
   functions that only mapped the openai half, with a comment admitting
   they were not sync'd). Anchor:
   ``core.llm.adapters.registry.PROVIDER_REGISTRY_NORMALIZATION``.

2. Anthropic model-capability sets — adapter request shaping
   (``core/llm/providers/anthropic.py``) and the CLI effort picker
   (``core/cli/effort_picker.py``) each hardcoded the same model sets
   with a "Keep these in sync" comment. Anchor:
   ``core.llm.model_capabilities``.

These tests pin the anchor's content invariants AND that the consumers
alias the anchor objects (identity, not copies) — a re-introduced literal
copy fails the identity assertions.
"""

from __future__ import annotations

import inspect


class TestProviderNormalizationAnchor:
    def test_map_contents(self) -> None:
        from core.llm.adapters.registry import PROVIDER_REGISTRY_NORMALIZATION

        assert PROVIDER_REGISTRY_NORMALIZATION == {
            "openai-codex": "openai",
            "zhipuai": "glm",
        }

    def test_normalize_passthrough_and_mapping(self) -> None:
        from core.llm.adapters.registry import normalize_registry_provider

        assert normalize_registry_provider("openai-codex") == "openai"
        assert normalize_registry_provider("zhipuai") == "glm"
        assert normalize_registry_provider("anthropic") == "anthropic"
        assert normalize_registry_provider("glm") == "glm"

    def test_no_literal_copies_at_former_sites(self) -> None:
        """The four former copy sites must call the anchor, not re-declare
        the dict. Source-scan guard (same style as TestCacheContract)."""
        import core.agent.loop._model_switching as model_switching
        import core.agent.loop._reflection as reflection
        from core.agent.loop.agent_loop import AgenticLoop
        from core.self_improving.loop.mutate import runner

        for src in (
            inspect.getsource(AgenticLoop.__init__),
            inspect.getsource(model_switching._resolve_path_b_adapter),
            inspect.getsource(reflection),
            inspect.getsource(runner),
        ):
            assert "_PROVIDER_NORMALIZATION = {" not in src
            assert "_normalize_provider_for_registry" not in src
        assert "normalize_registry_provider" in inspect.getsource(AgenticLoop.__init__)


class TestModelCapabilityAnchor:
    def test_capability_subset_invariants(self) -> None:
        """xhigh ⊆ adaptive ⊆ context-mgmt — a model cannot accept the
        xhigh effort knob without being adaptive, and every adaptive
        model in the catalog is a 1M/compaction model."""
        from core.llm.model_capabilities import (
            ANTHROPIC_ADAPTIVE_MODELS,
            ANTHROPIC_CONTEXT_MGMT_MODELS,
            ANTHROPIC_XHIGH_MODELS,
        )

        assert ANTHROPIC_XHIGH_MODELS <= ANTHROPIC_ADAPTIVE_MODELS
        assert ANTHROPIC_ADAPTIVE_MODELS <= ANTHROPIC_CONTEXT_MGMT_MODELS

    def test_adapter_aliases_are_anchor_objects(self) -> None:
        """Identity, not equality — a re-introduced literal copy would be
        equal today and silently drift tomorrow."""
        from core.llm import model_capabilities as caps
        from core.llm.providers import anthropic as anthropic_provider

        assert anthropic_provider._CONTEXT_MGMT_MODELS is caps.ANTHROPIC_CONTEXT_MGMT_MODELS
        assert anthropic_provider._ADAPTIVE_MODELS is caps.ANTHROPIC_ADAPTIVE_MODELS
        assert anthropic_provider._XHIGH_EFFORT_MODELS is caps.ANTHROPIC_XHIGH_MODELS

    def test_effort_picker_aliases_are_anchor_objects(self) -> None:
        from core.cli import effort_picker
        from core.llm import model_capabilities as caps

        assert effort_picker._ANTHROPIC_ADAPTIVE_MODELS is caps.ANTHROPIC_ADAPTIVE_MODELS
        assert effort_picker._ANTHROPIC_XHIGH_MODELS is caps.ANTHROPIC_XHIGH_MODELS

    def test_picker_surfaces_match_adapter_acceptance(self) -> None:
        """End-to-end invariant the anchor exists to guarantee: the picker
        offers xhigh exactly for the models the adapter will accept it on."""
        from core.cli.effort_picker import supported_efforts
        from core.llm.model_capabilities import (
            ANTHROPIC_ADAPTIVE_MODELS,
            ANTHROPIC_XHIGH_MODELS,
        )

        for model in ANTHROPIC_ADAPTIVE_MODELS:
            efforts = supported_efforts(model, "anthropic")
            assert ("xhigh" in efforts) == (model in ANTHROPIC_XHIGH_MODELS)
