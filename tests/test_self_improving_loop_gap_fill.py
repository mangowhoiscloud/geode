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
# G-A — MutatorConfig manifest + runner.py uses call_with_retry, not anthropic SDK
# ---------------------------------------------------------------------------


def test_mutator_config_exists_with_default_model() -> None:
    from core.config.self_improving_loop import MutatorConfig

    cfg = MutatorConfig()
    assert cfg.default_model == "claude-opus-4-7"
    assert "claude-opus-4-7" in cfg.allowed_models
    assert cfg.source in ("auto", "api_key", "claude-cli", "openai-codex")
    assert cfg.max_tokens >= 128


def test_self_improving_loop_config_carries_mutator_section() -> None:
    from core.config.self_improving_loop import (
        MutatorConfig,
        SelfImprovingLoopConfig,
    )

    root = SelfImprovingLoopConfig()
    assert isinstance(root.mutator, MutatorConfig)
    assert root.mutator.default_model == "claude-opus-4-7"


def test_runner_default_llm_call_routes_through_call_with_retry() -> None:
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
        "through core.llm.router.call_with_retry so it shares the "
        "credential rotator with every other provider-aware caller."
    )
    assert "call_with_retry" in body, (
        "runner._default_llm_call must dispatch through core.llm.router.call_with_retry"
    )
    assert 'model="claude-opus-4-7"' not in body, (
        "model id must come from MutatorConfig, not a literal in the body."
    )


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


def test_program_md_example_log_matches_config_defaults() -> None:
    """Pin the example log block in ``autoresearch/program.md`` to the
    ``AutoresearchConfig`` defaults so an operator who edits the config
    default and forgets to refresh the doc gets a CI hit, not silent
    documentation drift."""
    from core.config.self_improving_loop import AutoresearchConfig

    cfg = AutoresearchConfig()
    repo_root = Path(__file__).resolve().parent.parent
    program_md = repo_root / "autoresearch" / "program.md"
    text = program_md.read_text(encoding="utf-8")
    assert f"target_model:             {cfg.target_model}" in text, (
        "program.md example log target_model has drifted from AutoresearchConfig "
        f"default ({cfg.target_model!r}). Update the example block (lines ~180) "
        "to keep the doc honest."
    )
    assert f"judge_model:              {cfg.judge_model}" in text, (
        "program.md example log judge_model has drifted from AutoresearchConfig "
        f"default ({cfg.judge_model!r})."
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
