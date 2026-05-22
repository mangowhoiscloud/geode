"""OL-G — Config drift invariants (G-B / G-D / G-E pin tests).

PR-1 G-B/G-D/G-E (2026-05-21) closed three config drift surfaces:

- **G-B**: Petri role models → ``[self_improving_loop.petri.<role>]``
  config knob. PR-CSP-12 (2026-05-22) consolidated to single-SoT
  semantics — the legacy ``TARGET_MODEL`` / ``JUDGE_MODEL`` module
  constants and ``AutoresearchConfig.target_model`` /
  ``judge_model`` fields are deprecated no-ops; the real SoT is the
  ``[self_improving_loop.petri.<role>].model`` section consulted by
  ``autoresearch.train._petri_role_model`` and
  ``plugins.petri_audit.registry.get_binding``.
- **G-D**: ``core/hooks/llm_extract_learning.py`` 의 ``"glm-4.7-flash"``
  literal → ``settings.learning_extract_model`` config-overridable.
- **G-E**: ``settings.model`` (was ``claude-opus-4-6``) vs
  ``routing.toml`` (was ``claude-opus-4-7``) drift → aligned to
  ``claude-opus-4-7``.

The drift fixes are already in develop. This test module **pins** them
so a future refactor cannot silently re-introduce the drift. Each test
fails immediately if someone reverts the corresponding fix.

Pattern: every test name carries the ``G-X`` tag so a CI failure can
be traced back to which drift slice regressed.
"""

from __future__ import annotations

from pathlib import Path


def test_g_b_autoresearch_petri_role_is_canonical_sot() -> None:
    """Petri role models resolve through ``[self_improving_loop.petri.<role>]``.

    Single-SoT (2026-05-22, PR-CSP-12) — ``AutoresearchConfig.target_model``
    and ``judge_model`` survive as **deprecated no-op slots** for
    back-compat config load (so an old config.toml doesn't break parse),
    but the canonical SoT is the petri-role section. The fields must
    accept any string round-trip, but runtime resolution does NOT
    consult them — that path runs through ``_petri_role_model``.
    """
    from core.config.self_improving_loop import (
        AutoresearchConfig,
        SelfImprovingLoopConfig,
    )

    cfg = AutoresearchConfig()
    # Deprecated fields survive on AutoresearchConfig — default None
    # signals "not set" (back-compat: an old config.toml carrying
    # these keys won't fail to parse).
    assert getattr(cfg, "target_model", "MISSING") is None, (
        "G-B regressed: target_model deprecated slot removed before back-compat window"
    )
    assert getattr(cfg, "judge_model", "MISSING") is None, (
        "G-B regressed: judge_model deprecated slot removed before back-compat window"
    )
    # The petri section lives on the top-level config — it's the
    # real SoT for per-role model selection.
    loop_cfg = SelfImprovingLoopConfig()
    assert hasattr(loop_cfg, "petri"), (
        "G-B regressed: SelfImprovingLoopConfig.petri role-config section missing"
    )


def test_g_b_autoresearch_resolves_role_model_through_helper() -> None:
    """``autoresearch.train`` resolves per-role models via the helper —
    no surviving module-constant SoT.

    Single-SoT (2026-05-22) — the legacy ``TARGET_MODEL`` /
    ``JUDGE_MODEL`` constants were removed because they shadowed the
    petri-role config section (operator-facing SoT). The remaining
    surface is ``_petri_role_model(role)`` which consults the manifest
    + ``[self_improving_loop.petri.<role>]`` overrides.
    """
    from autoresearch import train

    assert callable(getattr(train, "_petri_role_model", None)), (
        "G-B regressed: _petri_role_model helper removed — role resolution path broken"
    )
    assert not hasattr(train, "TARGET_MODEL"), (
        "G-B regressed: TARGET_MODEL re-introduced — must stay removed (single-SoT)"
    )
    assert not hasattr(train, "JUDGE_MODEL"), (
        "G-B regressed: JUDGE_MODEL re-introduced — must stay removed (single-SoT)"
    )
    assert callable(getattr(train, "_get_autoresearch_config", None)), (
        "G-B regressed: _get_autoresearch_config loader missing"
    )


def test_g_d_learning_extract_model_is_config_overridable() -> None:
    """The ``core.hooks.llm_extract_learning`` budget-model picker must
    resolve via ``settings.learning_extract_model``, NOT a hardcoded
    string literal. PR-1 G-D moved the literal out so an operator can
    flip via ``GEODE_LEARNING_EXTRACT_MODEL=...`` env or
    ``[llm] learning_extract_model`` config.
    """
    from core.config import settings
    from core.hooks import llm_extract_learning

    # 1. Settings field exists.
    assert hasattr(settings, "learning_extract_model"), (
        "G-D regressed: settings.learning_extract_model field missing"
    )
    # 2. Default is a non-empty string (some GLM-family model).
    assert isinstance(settings.learning_extract_model, str)
    assert settings.learning_extract_model, "G-D regressed: empty default"
    # 3. The hook source code references the settings field — grep the
    # module file for ``settings.learning_extract_model`` so a future
    # refactor that hardcodes the model again fails this test.
    source = Path(llm_extract_learning.__file__).read_text(encoding="utf-8")
    assert "settings.learning_extract_model" in source, (
        "G-D regressed: hook no longer reads settings.learning_extract_model"
    )


def test_g_e_settings_model_default_matches_routing_toml_anthropic() -> None:
    """The two SoTs for "primary anthropic model" — ``Settings.model``
    field default and ``routing.toml [model.defaults] anthropic`` — MUST
    match. Pre-PR-1 G-E they drifted (4-6 vs 4-7), so the router used a
    different model than ``/model`` reported. We compare the *class-level
    default*, not the runtime ``settings.model`` (which env vars
    legitimately override per operator preference — that's not drift).
    """
    import tomllib
    from pathlib import Path as PathT

    from core.config._settings import Settings

    settings_default = Settings.model_fields["model"].default
    routing_toml = PathT(__file__).resolve().parents[1] / "core" / "config" / "routing.toml"
    data = tomllib.loads(routing_toml.read_text(encoding="utf-8"))
    model_defaults = data.get("model", {}).get("defaults", {})
    anthropic_canon = model_defaults.get("anthropic")
    assert anthropic_canon, "G-E regressed: routing.toml missing [model.defaults] anthropic"
    assert settings_default == anthropic_canon, (
        f"G-E regressed: Settings.model default ({settings_default!r}) ≠ "
        f"routing.toml [model.defaults].anthropic ({anthropic_canon!r})"
    )


def test_g_e_settings_model_default_uses_current_4_7_family() -> None:
    """Belt-and-suspenders: pin the *generation* (claude-opus-4-7) of the
    field default so a future routing.toml edit that silently rolls to
    claude-opus-4-8 also updates ``_settings.py``. If we ever do an
    intentional bump, this test changes alongside the model literal.

    Compares the class-level default (env-immune) — see sibling test for
    the routing.toml↔Settings parity assertion.
    """
    from core.config._settings import Settings

    settings_default = Settings.model_fields["model"].default
    assert settings_default.startswith("claude-opus-4-7"), (
        f"G-E watcher: Settings.model default is {settings_default!r} — "
        "expected claude-opus-4-7 family. If this is an intentional bump, "
        "update this test together with routing.toml + _settings.py."
    )
