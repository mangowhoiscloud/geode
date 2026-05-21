"""PR-1 gap fill — manifest / config wiring invariants.

Pre-PR-1 the self-improving loop had five hardcoded selection points
that fell outside the paperclip-style abstraction every other GEODE
component already used:

  G-A  core/self_improving_loop/runner.py    — anthropic.Anthropic()
                                                + model="claude-opus-4-7"
  G-B  autoresearch/train.py                 — TARGET_MODEL/JUDGE_MODEL
                                                module constants (now
                                                already config-wired
                                                via PR-δ1, this file
                                                pins the invariant)
  G-C  autoresearch/program.md ↔ train.py    — example log block has
                                                hardcoded model ids;
                                                we pin that they agree
                                                with the config default
  G-D  core/hooks/llm_extract_learning.py    — model="glm-4.7-flash"
                                                literal
  G-E  settings.model default drift          — was 4-6, routing.toml
                                                says 4-7

Each contract below is a grep-checkable invariant so a regression
shows up here, not in a runtime traceback.
"""

from __future__ import annotations

import inspect
from pathlib import Path

# ---------------------------------------------------------------------------
# G-A — MutatorConfig manifest + runner.py uses call_with_failover, not anthropic SDK
# ---------------------------------------------------------------------------


def test_mutator_config_exists_with_default_model() -> None:
    """PR-MINIMAL-2 (2026-05-21) — MutatorConfig defaults:
    - ``default_model`` flipped to ``None`` (G1a inherit Settings.model)
    - ``allowed_models`` field removed (C1)
    - ``role_contract`` field removed (A1)
    - ``fallback_to_payg`` per-component override removed (C2)
    """
    from core.config.self_improving_loop import MutatorConfig

    cfg = MutatorConfig()
    assert cfg.default_model is None  # G1a inherit
    assert cfg.source in ("auto", "api_key", "claude-cli", "openai-codex")
    assert cfg.max_tokens >= 128
    # Removed fields must not exist
    assert not hasattr(cfg, "allowed_models")
    assert not hasattr(cfg, "role_contract")
    assert not hasattr(cfg, "fallback_to_payg")


def test_self_improving_loop_config_carries_mutator_section() -> None:
    """PR-MINIMAL-2 — MutatorConfig section still present, but its
    ``default_model`` now inherits ``Settings.model`` when ``None``."""
    from core.config.self_improving_loop import (
        MutatorConfig,
        SelfImprovingLoopConfig,
    )

    root = SelfImprovingLoopConfig()
    assert isinstance(root.mutator, MutatorConfig)
    assert root.mutator.default_model is None  # G1a inherit


def test_runner_default_llm_call_routes_through_call_with_failover() -> None:
    """Anti-deception — the runner must not instantiate the anthropic SDK
    directly; it must dispatch through the router so the credential /
    provider rotator applies."""
    from core.self_improving_loop import runner

    src = inspect.getsource(runner._default_llm_call)
    # Strip docstring (between first triple-quote pair) so we only grep
    # the function body — the docstring legitimately mentions the
    # pre-fix anti-pattern in its rationale.
    import re

    body = re.sub(r'""".*?"""', "", src, count=1, flags=re.DOTALL)
    assert "client = anthropic.Anthropic()" not in body, (
        "runner._default_llm_call body must NOT instantiate "
        "anthropic.Anthropic() directly — PR-1 G-A routes the mutator "
        "through core.llm.router.call_with_failover so it shares the "
        "credential rotator with every other provider-aware caller."
    )
    assert "call_with_failover" in body, (
        "runner._default_llm_call must dispatch through core.llm.router.call_with_failover"
    )
    assert 'model="claude-opus-4-7"' not in body, (
        "model id must come from MutatorConfig, not a literal in the body."
    )


def test_runner_default_llm_call_import_resolves() -> None:
    """Codex MCP catch — the prior draft imported a router symbol
    (``call_with_retry``) that does not exist on main, so the mutator
    default path would have crashed at import time. Pin the contract:
    every symbol the runner imports must resolve."""
    from core.llm.router import call_with_failover  # noqa: F401
    from core.self_improving_loop.runner import _default_llm_call

    assert callable(_default_llm_call)


def test_runner_default_llm_call_consumes_source() -> None:
    """PR-MINIMAL-2 (2026-05-21) — narrowed invariant: only
    ``source`` survives as a runner-consumed field. ``role_contract``
    was removed in A1 (was logged only, never injected into the LLM
    prompt — silent knob). The dispatch telemetry log keeps the
    source for downstream observers."""
    from core.self_improving_loop import runner

    src = inspect.getsource(runner._default_llm_call)
    assert "cfg.mutator.source" in src, (
        "_default_llm_call must read MutatorConfig.source — otherwise "
        "the field is a silent declarative knob (Codex MCP anti-pattern)."
    )
    # role_contract removed — A1 (PR-MINIMAL-2)
    assert "role_contract" not in src, (
        "role_contract was removed; the runner must NOT reference it."
    )
    # Telemetry surface stays — every dispatch logs (model, provider, source).
    assert "mutator dispatch:" in src, (
        "_default_llm_call must emit a telemetry log row with the "
        "MutatorConfig context so Petri / Inspect viewers can group runs."
    )


def test_mutator_default_model_inherits_settings() -> None:
    """PR-MINIMAL-2 G1a — when MutatorConfig.default_model is None
    (the new default), the runner falls back to Settings.model so
    operator's ``/model`` choice flows through automatically."""
    import inspect as _inspect

    from core.self_improving_loop import runner

    src = _inspect.getsource(runner._default_llm_call)
    # Inherit path: when cfg.mutator.default_model is None, use Settings.model
    assert "settings.model" in src, (
        "_default_llm_call must fall back to Settings.model when "
        "MutatorConfig.default_model is None (G1a inherit)."
    )


def test_runner_default_llm_call_guards_empty_text() -> None:
    """Codex MCP catch — non-None ``AgenticResponse`` with no text
    blocks was silently returning an empty string and letting
    ``parse_mutation`` raise a confusing JSON error. Pin the explicit
    guard."""
    from core.self_improving_loop import runner

    src = inspect.getsource(runner._default_llm_call)
    assert "returned empty text" in src, (
        "_default_llm_call must raise RuntimeError on empty text instead "
        "of letting parse_mutation surface the failure as a JSON error."
    )


def test_config_toml_maps_learning_extract_model() -> None:
    """Codex MCP catch — CHANGELOG claimed
    ``[llm] learning_extract_model`` works in ``config.toml`` but the
    parser table didn't carry the entry. Pin it explicitly."""
    from core.config import _TOML_TO_SETTINGS

    assert _TOML_TO_SETTINGS.get("llm.learning_extract_model") == "learning_extract_model"


def test_runner_reads_default_model_from_config() -> None:
    from core.self_improving_loop import runner

    src = inspect.getsource(runner._default_llm_call)
    assert "load_self_improving_loop_config" in src
    assert "cfg.mutator.default_model" in src or "mutator.default_model" in src


# ---------------------------------------------------------------------------
# G-B — train.py uses AutoresearchConfig (PR-δ1 was the wire-up; we keep it pinned)
# ---------------------------------------------------------------------------


def test_train_audit_command_uses_config_target_judge() -> None:
    from autoresearch import train

    src = inspect.getsource(train._build_audit_command)
    assert "cfg.target_model" in src
    assert "cfg.judge_model" in src
    assert '"--target",' in src and '"--judge",' in src


# ---------------------------------------------------------------------------
# G-C — program.md example log uses the config default model ids
# ---------------------------------------------------------------------------


def test_program_md_example_log_matches_train_module_constants() -> None:
    """Pin the example log block in ``autoresearch/program.md`` to the
    ``autoresearch.train`` module-constant defaults
    (``TARGET_MODEL`` / ``JUDGE_MODEL``) so an operator who edits the
    constant and forgets to refresh the doc gets a CI hit.

    PR-MINIMAL-2 (2026-05-21) — pre-PR this test compared against
    ``AutoresearchConfig`` defaults. With G1a those defaults are
    ``None`` (inherit ``Settings.model``), so the example log can no
    longer use the config dataclass as the truth source — the
    module constants in ``train.py`` ARE the SoT for the docs
    example, and the agent (per ``program.md``) can grep + edit them.
    """
    from autoresearch.train import JUDGE_MODEL, TARGET_MODEL

    repo_root = Path(__file__).resolve().parent.parent
    program_md = repo_root / "autoresearch" / "program.md"
    text = program_md.read_text(encoding="utf-8")
    assert f"target_model:             {TARGET_MODEL}" in text, (
        "program.md example log target_model has drifted from "
        f"autoresearch.train.TARGET_MODEL ({TARGET_MODEL!r}). Update "
        "the example block (lines ~180) to keep the doc honest."
    )
    assert f"judge_model:              {JUDGE_MODEL}" in text, (
        "program.md example log judge_model has drifted from "
        f"autoresearch.train.JUDGE_MODEL ({JUDGE_MODEL!r})."
    )


# ---------------------------------------------------------------------------
# G-D — learning-extract hook reads settings, not a literal
# ---------------------------------------------------------------------------


def test_settings_carries_learning_extract_model_field() -> None:
    from core.config._settings import Settings

    fields = Settings.model_fields
    assert "learning_extract_model" in fields
    field_info = fields["learning_extract_model"]
    assert field_info.default == "glm-4.7-flash"


def test_glm_flash_hook_reads_settings_learning_extract_model() -> None:
    from core.hooks import llm_extract_learning

    src = inspect.getsource(llm_extract_learning._call_glm_flash)
    assert 'model="glm-4.7-flash"' not in src, (
        "PR-1 G-D — the GLM hook must read settings.learning_extract_model instead of the literal."
    )
    assert "settings.learning_extract_model" in src


# ---------------------------------------------------------------------------
# G-E — settings.model default aligns with routing.toml [model.defaults] anthropic
# ---------------------------------------------------------------------------


def test_settings_model_default_matches_routing_anthropic_default() -> None:
    from core.config import ANTHROPIC_PRIMARY
    from core.config._settings import Settings

    fields = Settings.model_fields
    assert fields["model"].default == ANTHROPIC_PRIMARY, (
        "PR-1 G-E — settings.model default must match "
        "core.config.ANTHROPIC_PRIMARY (routing.toml [model.defaults] "
        f"anthropic). Currently: settings.model default = "
        f"{fields['model'].default!r}, ANTHROPIC_PRIMARY = {ANTHROPIC_PRIMARY!r}."
    )
    assert fields["router_model"].default == ANTHROPIC_PRIMARY, (
        "PR-1 G-E — settings.router_model default must match ANTHROPIC_PRIMARY for the same reason."
    )
