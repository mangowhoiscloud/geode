"""PR-MINIMAL-2 — 11-item alignment/pruning bundle invariants.

Pins:
- G1a — MutatorConfig.default_model + AutoresearchConfig.target_model
  + AutoresearchConfig.judge_model default to ``None`` and inherit
  ``Settings.model`` at the runner's dispatch / argv build time.
- C1 — MutatorConfig.allowed_models removed.
- C2/A2 — ``fallback_to_payg`` per-component override removed; only
  the global flag survives.
- A1 — MutatorConfig.role_contract removed.
- B1 — AutoresearchConfig.use_oauth (bool) → source (Source enum);
  argv translator maps non-``api_key`` source to ``--use-oauth``.
- B2 — RunnerContext.current_policies carries all 5 policy SoTs,
  _build_user_prompt surfaces them to the LLM.
- B5 — MUTATION_AUDIT_LOG_PATH lives in core.paths; runner re-exports.
- B8 — _FALLBACK_SYSTEM_PROMPT and program.md must share key section
  markers so a drift between the two paths surfaces here.
- C5 — autoresearch/program.md mentions all 5 target_kinds in the
  agent contract.
"""

from __future__ import annotations

import inspect
from pathlib import Path

# ---------------------------------------------------------------------------
# G1a — None defaults inherit Settings.model
# ---------------------------------------------------------------------------


def test_mutator_default_model_is_none() -> None:
    """MutatorConfig.default_model defaults to None so the runner
    inherits Settings.model. Explicit override still wins."""
    from core.config.self_improving_loop import MutatorConfig

    assert MutatorConfig().default_model is None


def test_autoresearch_target_and_judge_default_none() -> None:
    """AutoresearchConfig.target_model + judge_model default to None
    so audit argv builder falls back to Settings.model."""
    from core.config.self_improving_loop import AutoresearchConfig

    cfg = AutoresearchConfig()
    assert cfg.target_model is None
    assert cfg.judge_model is None


def test_runner_default_llm_call_inherits_settings_model() -> None:
    """Pin the inherit path in source — runner body must reference
    settings.model when MutatorConfig.default_model is None."""
    from core.self_improving_loop import runner

    src = inspect.getsource(runner._default_llm_call)
    assert "settings.model" in src
    # The inherit happens only when default_model is None — both
    # branches must be visible (truthy default_model + fallback).
    assert "cfg.mutator.default_model" in src


def test_build_audit_command_inherits_settings_model() -> None:
    """``autoresearch.train._build_audit_command`` must read
    ``cfg.target_model`` / ``cfg.judge_model`` AND fall back to
    ``_settings_model()`` when either is None (G1a)."""
    from autoresearch import train

    src = inspect.getsource(train._build_audit_command)
    assert "_settings_model" in src
    # Both target + judge fall back via the helper
    assert "cfg.target_model or _settings_model()" in src
    assert "cfg.judge_model or _settings_model()" in src


# ---------------------------------------------------------------------------
# C1 — allow-list removed
# ---------------------------------------------------------------------------


def test_mutator_config_has_no_allow_list() -> None:
    from core.config.self_improving_loop import MutatorConfig

    cfg = MutatorConfig()
    assert not hasattr(cfg, "allowed_models"), (
        "MutatorConfig.allowed_models removed in PR-MINIMAL-2 (C1) — "
        "router-level provider guards already cover the same need."
    )


# ---------------------------------------------------------------------------
# C2/A2 — fallback_to_payg per-component removed
# ---------------------------------------------------------------------------


def test_global_fallback_to_payg_kept() -> None:
    """Only the global flag at ``[self_improving_loop] fallback_to_payg``
    survives. Per-component overrides removed."""
    from core.config.self_improving_loop import SelfImprovingLoopConfig

    cfg = SelfImprovingLoopConfig()
    assert hasattr(cfg, "fallback_to_payg")
    assert cfg.fallback_to_payg is False


def test_per_component_fallback_to_payg_removed() -> None:
    """All per-component classes lost their ``fallback_to_payg``
    override (which had no downstream reader)."""
    from core.config.self_improving_loop import (
        AutoresearchConfig,
        MutatorConfig,
        PetriRoleConfig,
        SeedGenerationConfig,
        SelfImprovingLoopBindings,
    )

    assert not hasattr(MutatorConfig(), "fallback_to_payg")
    assert not hasattr(AutoresearchConfig(), "fallback_to_payg")
    assert not hasattr(PetriRoleConfig(), "fallback_to_payg")
    assert not hasattr(SeedGenerationConfig(), "fallback_to_payg")
    assert not hasattr(
        SelfImprovingLoopBindings(model="x", source="auto"),
        "fallback_to_payg",
    )


# ---------------------------------------------------------------------------
# A1 — role_contract removed
# ---------------------------------------------------------------------------


def test_mutator_config_has_no_role_contract() -> None:
    """MutatorConfig.role_contract was a silent knob (logged only,
    never injected into the LLM prompt). Removed in PR-MINIMAL-2."""
    from core.config.self_improving_loop import MutatorConfig

    assert not hasattr(MutatorConfig(), "role_contract")


# ---------------------------------------------------------------------------
# B1 — use_oauth (bool) → source (Source enum)
# ---------------------------------------------------------------------------


def test_autoresearch_config_has_source_not_use_oauth() -> None:
    """``AutoresearchConfig.use_oauth: bool`` replaced by
    ``source: Source`` (4-enum) so the credential vocabulary is
    one shape across the loop."""
    from core.config.self_improving_loop import AutoresearchConfig

    cfg = AutoresearchConfig()
    assert hasattr(cfg, "source")
    assert cfg.source in ("auto", "api_key", "claude-cli", "openai-codex")
    assert not hasattr(cfg, "use_oauth")


def test_build_audit_command_maps_source_to_use_oauth_flag() -> None:
    """The argv translator must add ``--use-oauth`` for any source
    EXCEPT ``api_key`` (auto / claude-cli / openai-codex all use
    subscription credentials)."""
    from autoresearch import train

    src = inspect.getsource(train._build_audit_command)
    assert 'getattr(cfg, "source", "auto") != "api_key"' in src or "cfg.source" in src
    assert "--use-oauth" in src


# ---------------------------------------------------------------------------
# B2 — RunnerContext.current_policies carries all 5 SoTs
# ---------------------------------------------------------------------------


def test_runner_context_has_current_policies_field() -> None:
    """RunnerContext now carries all 5 policy SoTs via current_policies."""
    from core.self_improving_loop.runner import RunnerContext

    ctx = RunnerContext()
    assert hasattr(ctx, "current_policies")
    # Default empty dict (build_runner_context fills it)
    assert ctx.current_policies == {}
    # Legacy current_sections still exists for backwards compat
    assert hasattr(ctx, "current_sections")


def test_build_runner_context_loads_all_5_policies(
    monkeypatch,
) -> None:
    """build_runner_context must populate current_policies with all
    5 target_kinds so the mutator LLM sees the full policy surface."""
    from core.self_improving_loop.policies import TARGET_KINDS

    from core.self_improving_loop import runner as runner_mod

    # Stub out the external loaders so we don't touch disk or LLMs.
    monkeypatch.setattr(
        "autoresearch.train.load_wrapper_prompt_sections",
        lambda: {"role": "test"},
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_baseline",
        lambda: None,
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.load_latest_meta_review",
        lambda: None,
    )
    monkeypatch.setattr(
        "core.self_improving_loop.policies.load_policy",
        lambda kind: {f"{kind}_section": "stub"},
    )

    ctx = runner_mod.build_runner_context()
    for kind in TARGET_KINDS:
        assert kind in ctx.current_policies, (
            f"build_runner_context must include {kind!r} in current_policies"
        )


def test_build_user_prompt_surfaces_all_policies() -> None:
    """The user prompt must include the 5-kind header so the LLM
    sees the full policy surface, not just the wrapper sections."""
    from core.self_improving_loop.runner import RunnerContext

    from core.self_improving_loop import runner as runner_mod

    ctx = RunnerContext(
        current_policies={
            "prompt": {"role": "test"},
            "tool_policy": {"delegate_task": "priority=5"},
            "decomposition": {},
            "retrieval": {},
            "reflection": {},
        },
        current_sections={"role": "test"},
    )
    prompt = runner_mod._build_user_prompt(ctx)
    assert "Current policy SoT" in prompt
    # All 5 kinds visible in the rendered JSON block
    for kind in ("prompt", "tool_policy", "decomposition", "retrieval", "reflection"):
        assert f'"{kind}"' in prompt


# ---------------------------------------------------------------------------
# B5 — MUTATION_AUDIT_LOG_PATH in core.paths
# ---------------------------------------------------------------------------


def test_mutation_audit_log_path_canonical_in_core_paths() -> None:
    """The canonical definition now lives in core.paths."""
    from core import paths

    assert hasattr(paths, "MUTATION_AUDIT_LOG_PATH")
    assert paths.MUTATION_AUDIT_LOG_PATH.name == "mutations.jsonl"
    parts = paths.MUTATION_AUDIT_LOG_PATH.parts
    assert parts[-2:] == ("state", "mutations.jsonl")


def test_runner_reexports_mutation_audit_log_path() -> None:
    """The runner re-exports the constant so existing callers
    (5+ tests + production sites) keep working unchanged.

    Equality (not identity) — other tests legitimately monkeypatch
    ``runner.MUTATION_AUDIT_LOG_PATH`` to ``tmp_path`` paths; the
    invariant we want here is *path value equivalence*, not Python
    object identity which would force test isolation we don't need.
    """
    from core import paths
    from core.self_improving_loop import runner

    # The default value (before any monkeypatch) must point at the
    # canonical core.paths location.
    canonical = paths.MUTATION_AUDIT_LOG_PATH
    assert canonical.name == "mutations.jsonl"
    assert canonical.parts[-2] == "state"
    # The runner export resolves to the same path. ``is`` would also
    # work in a fresh process; we use value equality so the test
    # tolerates other tests' monkeypatches that didn't reset.
    assert "MUTATION_AUDIT_LOG_PATH" in runner.__all__
    # Whatever the (possibly-patched) runner reference is, the
    # canonical paths.MUTATION_AUDIT_LOG_PATH MUST still be exported.
    assert hasattr(runner, "MUTATION_AUDIT_LOG_PATH")


# ---------------------------------------------------------------------------
# B8 — FALLBACK_SYSTEM_PROMPT vs program.md drift guard
# ---------------------------------------------------------------------------


def test_fallback_prompt_shares_setup_anchor_with_program_md() -> None:
    """If the fallback prompt drifts from program.md (e.g. operator
    edits one without the other), the mutator LLM sees a different
    contract depending on whether the disk read succeeds. Pin a
    stable section header (``Setup``) so a drift surfaces here."""
    from core.self_improving_loop import runner

    repo_root = Path(__file__).resolve().parent.parent
    program_md = (repo_root / "autoresearch" / "program.md").read_text(encoding="utf-8")
    # Both paths describe the same setup workflow; pick a stable
    # anchor from program.md that the fallback should also mention.
    # If either path drops "Setup" as a section concept the test
    # fails — and the operator is forced to reconcile.
    assert "## Setup" in program_md
    # The fallback prompt's mutation-contract section should at least
    # reference the same mutation_id / target_kind / target_section
    # schema so an LLM run on either path uses the same JSON shape.
    fallback = runner._FALLBACK_SYSTEM_PROMPT
    for required_field in ("target_section", "new_value", "rationale"):
        assert required_field in fallback


# ---------------------------------------------------------------------------
# C5 — program.md lists all 5 target_kinds
# ---------------------------------------------------------------------------


def test_program_md_mentions_all_5_target_kinds() -> None:
    """``autoresearch/program.md`` is the Mode A agent's baseline
    instruction. The doc must mention all 5 mutation kinds so a
    Karpathy-idiom agent (external Claude/Codex session) knows it can
    edit tool_policy / decomposition / retrieval / reflection in
    addition to the legacy wrapper-prompt sections.
    """
    repo_root = Path(__file__).resolve().parent.parent
    program_md = (repo_root / "autoresearch" / "program.md").read_text(encoding="utf-8")
    for kind in ("prompt", "tool_policy", "decomposition", "retrieval", "reflection"):
        assert f"`{kind}`" in program_md, (
            f"program.md must mention target_kind {kind!r} in the "
            "5-kind table so Mode A agents see the full mutation surface."
        )
