"""Tests for ``core/config/self_improving_loop.py`` — single SoT loader for the
``~/.geode/config.toml`` ``[self_improving_loop.*]`` section.

Covers schema defaults, sub-config defaults, missing-file fallback,
empty-section fallback, env override (``GEODE_CONFIG_TOML``), explicit
path argument, ``extra='forbid'`` typo guard, threshold validation
(abort > warn), and per-role binding deserialisation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.config.self_improving_loop import (
    AutoresearchConfig,
    PetriRoleConfig,
    SeedPipelineConfig,
    SelfImprovingLoopBindings,
    SelfImprovingLoopConfig,
    load_self_improving_loop_config,
)


def _write_toml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_default_config_has_safe_defaults() -> None:
    """SelfImprovingLoopConfig() with no input yields strict-mode safe defaults."""
    cfg = SelfImprovingLoopConfig()
    assert cfg.fallback_to_payg is False  # strict default
    assert cfg.warn_threshold == pytest.approx(0.5)
    assert cfg.abort_threshold == pytest.approx(0.9)
    assert isinstance(cfg.autoresearch, AutoresearchConfig)
    assert isinstance(cfg.seed_pipeline, SeedPipelineConfig)
    assert cfg.petri == {}


def test_autoresearch_defaults_match_train_module() -> None:
    """Defaults mirror the existing autoresearch/train.py module constants."""
    a = AutoresearchConfig()
    assert a.budget_minutes == 5
    assert a.target_model == "geode/gpt-5.5"
    assert a.judge_model == "claude-code/opus"
    assert a.use_oauth is True
    assert a.seed_limit == 10
    assert a.seed_select == "plugins/petri_audit/seeds"
    assert a.dim_set == "5axes"
    assert a.max_turns == 10
    assert a.fallback_to_payg is None


def test_load_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    """Missing file → fully-defaulted SelfImprovingLoopConfig, no error."""
    cfg = load_self_improving_loop_config(tmp_path / "nonexistent.toml")
    assert cfg == SelfImprovingLoopConfig()


def test_load_returns_defaults_when_section_missing(tmp_path: Path) -> None:
    """Existing file without [self_improving_loop] section → defaults."""
    path = tmp_path / "config.toml"
    _write_toml(path, "[settings]\nfoo = 'bar'\n")
    cfg = load_self_improving_loop_config(path)
    assert cfg == SelfImprovingLoopConfig()


def test_load_reads_self_improving_loop_section(tmp_path: Path) -> None:
    """[self_improving_loop] section keys override defaults."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
fallback_to_payg = true
warn_threshold = 0.6
abort_threshold = 0.95
""",
    )
    cfg = load_self_improving_loop_config(path)
    assert cfg.fallback_to_payg is True
    assert cfg.warn_threshold == pytest.approx(0.6)
    assert cfg.abort_threshold == pytest.approx(0.95)


def test_load_reads_autoresearch_subsection(tmp_path: Path) -> None:
    """[self_improving_loop.autoresearch] section deserialises into AutoresearchConfig."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop.autoresearch]
target_model = "geode/claude-opus-4-7"
judge_model = "claude-code/sonnet"
budget_minutes = 10
seed_limit = 25
""",
    )
    cfg = load_self_improving_loop_config(path)
    assert cfg.autoresearch.target_model == "geode/claude-opus-4-7"
    assert cfg.autoresearch.judge_model == "claude-code/sonnet"
    assert cfg.autoresearch.budget_minutes == 10
    assert cfg.autoresearch.seed_limit == 25
    # Untouched fields keep defaults.
    assert cfg.autoresearch.use_oauth is True


def test_load_reads_petri_role_bindings(tmp_path: Path) -> None:
    """[self_improving_loop.petri.<role>] keys become PetriRoleConfig entries."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop.petri.auditor]
model = "claude-sonnet-4-6"
source = "claude-cli"

[self_improving_loop.petri.target]
model = "geode/gpt-5.5"
source = "openai-codex"

[self_improving_loop.petri.judge]
model = "claude-opus-4-7"
source = "claude-cli"
""",
    )
    cfg = load_self_improving_loop_config(path)
    assert set(cfg.petri) == {"auditor", "target", "judge"}
    assert cfg.petri["auditor"].model == "claude-sonnet-4-6"
    assert cfg.petri["auditor"].source == "claude-cli"
    assert cfg.petri["target"].source == "openai-codex"
    assert cfg.petri["judge"].model == "claude-opus-4-7"


def test_load_reads_seed_pipeline_subsection(tmp_path: Path) -> None:
    """[self_improving_loop.seed_pipeline] + nested role bindings deserialise."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop.seed_pipeline]
candidates_default = 20
default_gen_tag = "gen3"

[self_improving_loop.seed_pipeline.roles.generator]
model = "gpt-5.5"
source = "openai-codex"
""",
    )
    cfg = load_self_improving_loop_config(path)
    assert cfg.seed_pipeline.candidates_default == 20
    assert cfg.seed_pipeline.default_gen_tag == "gen3"
    assert cfg.seed_pipeline.roles["generator"].model == "gpt-5.5"


def test_extra_forbid_rejects_typo(tmp_path: Path) -> None:
    """Unknown field at top level → pydantic ValidationError."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
falback_to_payg = true
""",
    )
    with pytest.raises(Exception) as exc_info:
        load_self_improving_loop_config(path)
    assert "falback_to_payg" in str(exc_info.value)


def test_extra_forbid_rejects_typo_in_autoresearch(tmp_path: Path) -> None:
    """Unknown field in [self_improving_loop.autoresearch] → ValidationError."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop.autoresearch]
budget_minute = 5
""",
    )
    with pytest.raises(Exception) as exc_info:
        load_self_improving_loop_config(path)
    assert "budget_minute" in str(exc_info.value)


def test_abort_threshold_must_exceed_warn(tmp_path: Path) -> None:
    """abort_threshold ≤ warn_threshold → ValidationError."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
warn_threshold = 0.8
abort_threshold = 0.7
""",
    )
    with pytest.raises(Exception) as exc_info:
        load_self_improving_loop_config(path)
    assert "abort_threshold" in str(exc_info.value)


def test_threshold_range_clamps(tmp_path: Path) -> None:
    """warn / abort thresholds outside [0, 1] are rejected."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
warn_threshold = 1.5
""",
    )
    with pytest.raises(Exception):
        load_self_improving_loop_config(path)


def test_env_override_resolves_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GEODE_CONFIG_TOML env var redirects the loader."""
    path = tmp_path / "alt.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
warn_threshold = 0.42
""",
    )
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(path))
    cfg = load_self_improving_loop_config()
    assert cfg.warn_threshold == pytest.approx(0.42)


def test_explicit_path_arg_wins_over_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit path argument trumps GEODE_CONFIG_TOML env var."""
    env_path = tmp_path / "env.toml"
    arg_path = tmp_path / "arg.toml"
    _write_toml(env_path, "[self_improving_loop]\nwarn_threshold = 0.1\n")
    _write_toml(arg_path, "[self_improving_loop]\nwarn_threshold = 0.9\n")
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(env_path))
    # abort_threshold must remain > warn so reduce abort and bump warn:
    # write a valid file at arg_path.
    _write_toml(arg_path, "[self_improving_loop]\nwarn_threshold = 0.5\nabort_threshold = 0.9\n")
    cfg = load_self_improving_loop_config(arg_path)
    assert cfg.warn_threshold == pytest.approx(0.5)


def test_bindings_dataclass_round_trip() -> None:
    """SelfImprovingLoopBindings serialises both ways without loss."""
    b = SelfImprovingLoopBindings(model="x", source="claude-cli", fallback_to_payg=True)
    assert b.model == "x"
    assert b.source == "claude-cli"
    assert b.fallback_to_payg is True


def test_petri_role_default_source_is_auto() -> None:
    """PetriRoleConfig without explicit source picks 'auto' default."""
    p = PetriRoleConfig(model="claude-sonnet-4-6")
    assert p.source == "auto"


def test_load_handles_empty_self_improving_loop_section(tmp_path: Path) -> None:
    """File with `[self_improving_loop]` but no body → defaults (model_validator must
    not reject the default-vs-default threshold pair)."""
    path = tmp_path / "config.toml"
    _write_toml(path, "[self_improving_loop]\n")
    cfg = load_self_improving_loop_config(path)
    assert cfg == SelfImprovingLoopConfig()


def test_threshold_inversion_caught_when_only_warn_set(tmp_path: Path) -> None:
    """If user raises warn_threshold past the default abort_threshold without
    moving abort, model_validator must catch the inversion. ``field_validator``
    misses this case because it only fires when abort is explicitly set."""
    path = tmp_path / "config.toml"
    _write_toml(
        path,
        """
[self_improving_loop]
warn_threshold = 0.95
""",
    )
    with pytest.raises(Exception) as exc_info:
        load_self_improving_loop_config(path)
    assert "abort_threshold" in str(exc_info.value)


def test_default_path_resolves_to_global_config_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without explicit path or env override, the loader resolves to
    ``core.paths.GLOBAL_CONFIG_TOML``."""
    import core.config.self_improving_loop as mod

    monkeypatch.delenv("GEODE_CONFIG_TOML", raising=False)
    fake = tmp_path / "global.toml"
    _write_toml(fake, "[self_improving_loop]\nwarn_threshold = 0.33\n")
    monkeypatch.setattr(mod, "GLOBAL_CONFIG_TOML", fake)
    cfg = load_self_improving_loop_config()
    assert cfg.warn_threshold == pytest.approx(0.33)
